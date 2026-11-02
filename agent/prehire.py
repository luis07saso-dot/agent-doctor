"""P1 Pre-Hire Check: should my agent hire (call) agent X right now?

Agent-to-agent protocol "AgentDoctorPreHire" 0.1.0, published with its manifest:

    PreHireRequest{address, live_probe=True}  ->  PreHireResult{...}

`address` takes an agent address (agent1q...), an @handle / handle, or an Agentverse profile
URL. The result joins the static Agentverse data (Doctor's 0-100 profile score as
`trust_score`, rating, Chat Protocol, active, Agentverse "unresponsive" flag) with a live
Chat Protocol probe (agent/probe.py): `status` live | degraded | unreachable, ack_ms, reply_ms.

The models carry NO docstrings or field descriptions on purpose: they are part of the schema
digest, and clients copy these classes verbatim (examples/prehire_client.py). Any change to
the models changes PROTOCOL_DIGEST: bump PROTOCOL_VERSION and update the client snippet
(tests/test_prehire.py pins both).

Humans reach the same check in chat: "pre-hire check <address/@handle>", "is <agent> live?".
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Optional

from uagents import Context, Model, Protocol
from uagents_core.protocol import ProtocolSpecification

from agent import report
from agent.agentverse import is_address, normalize_handle
from agent.extract import Target, extract
from agent.probe import PROBER, Prober, ProbeResult, _iso
from agent.scorer import score

PROTOCOL_NAME = "AgentDoctorPreHire"
PROTOCOL_VERSION = "0.1.0"
# Pinned by tests: changing the models must be a deliberate, versioned change.
PROTOCOL_DIGEST = "proto:4d48d9b2f6b74dc064cbaf0d516fbc9cdb1ea0127151d92e1205471a200477d4"

CHECK_TIMEOUT_S = 28.0  # handle resolve (<=12s, usually <1s) + probe (14s) + slack
# Chat path only: the probe did not finish before the reply deadline. It keeps running and is
# cached for 10 min, so asking again answers at once. Protocol callers never get this status.
PENDING = "pending"
PER_SENDER_PER_MIN = 20  # protocol callers; cached answers are cheap, probes are bounded


class PreHireRequest(Model):
    address: str
    live_probe: bool = True


class PreHireResult(Model):
    query: str
    address: str = ""
    status: str  # live | degraded | unreachable | unknown | not_found | invalid | rate_limited | error | pending (chat only)
    live: bool = False
    detail: str = ""
    chat_protocol: Optional[bool] = None
    active: Optional[bool] = None
    unresponsive_flag: Optional[bool] = None
    rating: Optional[float] = None
    trust_score: Optional[int] = None
    ack_ms: Optional[int] = None
    reply_ms: Optional[int] = None
    checked_at: str = ""
    cached: bool = False
    profile_url: str = ""


prehire_protocol_spec = ProtocolSpecification(
    name=PROTOCOL_NAME,
    version=PROTOCOL_VERSION,
    interactions={PreHireRequest: {PreHireResult}},
)
prehire_proto = Protocol(spec=prehire_protocol_spec)


# ---------- the check (shared by the protocol handler and the chat path) ----------

def parse_query(text: str, self_handles=()) -> Target | None:
    """Address, @handle, bare handle, or profile URL -> Target. None if nothing usable."""
    text = (text or "").strip()
    if is_address(text.lower()):
        return Target("address", text.lower())
    ex = extract(text, ignore_handles=self_handles)
    if ex.targets:
        return ex.targets[0]
    if ex.bad_address or text.lower().startswith("agent1"):
        return None  # mistyped / truncated address, not a handle
    h = normalize_handle(text)
    return Target("handle", h) if h else None


async def run_check(ctx: Any, target: Target, client: Any, prober: Prober = PROBER,
                    live_probe: bool = True, query: str = "",
                    deadline: float | None = None) -> PreHireResult:
    """Never raises. Bounded by CHECK_TIMEOUT_S.
    `deadline` (time.monotonic(), chat path only): stop waiting for the live probe then and
    return status PENDING. The probe itself keeps running and its result is cached."""
    query = (query or target.label)[:200]
    try:
        return await asyncio.wait_for(
            _run_check(ctx, target, client, prober, live_probe, query, deadline),
            CHECK_TIMEOUT_S)
    except asyncio.TimeoutError:
        return PreHireResult(query=query, status="error", detail="timeout",
                             checked_at=_iso(time.time()))
    except Exception:
        return PreHireResult(query=query, status="error", detail="internal",
                             checked_at=_iso(time.time()))


async def _run_check(ctx, target: Target, client, prober: Prober, live_probe: bool,
                     query: str, deadline: float | None = None) -> PreHireResult:
    address = target.value if target.kind == "address" else None
    if address is None:
        outcome, address = await client.resolve_handle(target.value)
        if address is None:
            status = {"not_found": "not_found", "invalid": "invalid"}.get(outcome, "error")
            return PreHireResult(query=query, status=status, detail=str(outcome),
                                 checked_at=_iso(time.time()))

    if live_probe:
        lk, pr = await asyncio.gather(client.lookup(address),
                                      _probe_until(prober, ctx, address, deadline))
    else:
        lk, pr = await client.lookup(address), None
    return build_result(query, address, lk, pr)


async def _probe_until(prober: Prober, ctx: Any, address: str,
                       deadline: float | None) -> ProbeResult | str:
    """Probe result, or PENDING if `deadline` passes first. shield: the probe is shared and
    cached, so giving up on waiting must not cancel it."""
    if deadline is None:
        return await prober.probe(ctx, address)
    try:
        return await asyncio.wait_for(asyncio.shield(prober.probe(ctx, address)),
                                      max(0.05, deadline - time.monotonic()))  # 0.05: lets a cached result through
    except asyncio.TimeoutError:
        return PENDING


def build_result(query: str, address: str, lk: Any,
                 pr: ProbeResult | str | None) -> PreHireResult:
    fields: dict[str, Any] = {}
    static_ok = lk is not None and lk.outcome in ("ok", "partial") and lk.profile_status not in (
        "timeout", "api_down")
    if static_ok:
        sc = score(lk)
        prof = lk.profile or {}
        rating = prof.get("rating")
        fields = dict(
            chat_protocol=sc.check("chat_protocol").ok,
            active=not sc.down,
            unresponsive_flag=prof.get("unresponsive") if isinstance(
                prof.get("unresponsive"), bool) else None,
            rating=float(rating) if isinstance(rating, (int, float)) and not isinstance(
                rating, bool) else None,
            trust_score=sc.total,
        )
    static_note = "" if static_ok else f"profile {getattr(lk, 'outcome', 'unknown')}"

    if pr == PENDING:
        status, detail = PENDING, "still_running"
        pr = None
    elif pr is None:
        status, detail = "unknown", "live probe not requested"
    elif pr.status in ("live", "degraded", "unreachable"):
        status, detail = pr.status, pr.detail
    else:  # skipped (self) / error (busy, internal): no live verdict
        status, detail = "unknown", pr.detail
    if static_note:
        detail = f"{detail}; {static_note}" if detail else static_note
    return PreHireResult(
        query=query,
        address=address,
        status=status,
        live=status == "live",
        detail=detail,
        ack_ms=pr.ack_ms if pr else None,
        reply_ms=pr.reply_ms if pr else None,
        checked_at=pr.checked_at if pr else _iso(time.time()),
        cached=pr.cached if pr else False,
        profile_url=report.PROFILE_URL.format(address=address),
        **fields,
    )


# ---------- protocol handler ----------

class _RateLimiter:
    """Per-sender sliding window. Bounded memory."""

    def __init__(self, per_min: int = PER_SENDER_PER_MIN, clock=time.monotonic,
                 max_keys: int = 10_000) -> None:
        self._per_min, self._clock, self._max = per_min, clock, max_keys
        self._hits: dict[str, list[float]] = {}

    def allow(self, sender: str) -> bool:
        now = self._clock()
        hits = [t for t in self._hits.pop(sender, []) if t > now - 60.0]
        ok = len(hits) < self._per_min
        if ok:
            hits.append(now)
        self._hits[sender] = hits  # re-insert: dict order = recency
        while len(self._hits) > self._max:
            self._hits.pop(next(iter(self._hits)))
        return ok


LIMITER = _RateLimiter()


@prehire_proto.on_message(PreHireRequest)
async def on_prehire(ctx: Context, sender: str, msg: PreHireRequest) -> None:
    from agent import chat  # late import: chat owns the shared client + REQ log format

    started = time.monotonic()
    query = (msg.address or "")[:200]
    try:
        if not LIMITER.allow(sender):
            res = PreHireResult(query=query, status="rate_limited",
                                detail="max %d requests/min" % PER_SENDER_PER_MIN,
                                checked_at=_iso(time.time()))
        else:
            target = parse_query(query, chat.SELF_HANDLES)
            if target is None:
                res = PreHireResult(query=query, status="invalid",
                                    detail="send an agent address, @handle or profile URL",
                                    checked_at=_iso(time.time()))
            else:
                res = await run_check(ctx, target, chat.CLIENT, PROBER,
                                      bool(msg.live_probe), query)
    except Exception as e:
        ctx.logger.error(f"prehire handler failed: {type(e).__name__}")
        res = PreHireResult(query=query, status="error", detail="internal",
                            checked_at=_iso(time.time()))
    try:
        await ctx.send(sender, res)
    finally:
        chat.log_request(ctx, sender, "prehire_protocol", res.status, started,
                         cached=res.cached, probe=bool(msg.live_probe))


# ---------- chat text (humans) ----------

def format_text(r: PreHireResult, label: str) -> str:
    """Short verdict for the chat path. Copy: docs/drafts/phase-p-chat-copy.md."""
    who = report.clean(label, 70)
    if r.status == "not_found":
        return (f"I couldn't find {who} on Agentverse (mainnet). "
                "Check the address or handle and try again.")
    if r.status == "invalid":
        return (f"`{who}` isn't a valid agent address or handle. "
                "Addresses start with `agent1q`; handles look like `my-agent`.")
    if r.status == "error" and not r.address:
        return "Sorry, I couldn't run the check right now. Please try again in a minute."

    head = {
        PENDING: "CHECKING: no answer to my test message yet.",
        "live": "LIVE: it answered a test message just now.",
        "degraded": "DEGRADED: it acknowledged a test message but sent no answer in time.",
        "unreachable": "UNREACHABLE: no acknowledgement and no answer to a test message.",
    }.get(r.status, "UNKNOWN: I couldn't run the live test this time. Try again in a minute.")
    lines = [f"**Pre-Hire Check: {who}**", f"**{head}**"]

    if r.status in ("live", "degraded", "unreachable"):
        ack = f"{r.ack_ms / 1000:.1f}s" if r.ack_ms is not None else "none"
        rep = f"{r.reply_ms / 1000:.1f}s" if r.reply_ms is not None else "none"
        lines.append(f"Live test: ack {ack} · answer {rep}")
        if r.detail.startswith("no_endpoint"):
            lines.append("_No reachable endpoint is registered for this address._")
    elif r.status == PENDING:
        # No "@" in the follow-up: on ASI:One "@other" routes the message to the other agent.
        ask = who.lstrip("@") or "this agent"
        lines.append(f"_I'm still waiting for its answer (up to {report.PROBE_WAIT_S}s). "
                     f"Ask \"is {ask} live?\" again in a minute for the verdict._")

    if r.trust_score is not None:
        cp = "✅" if r.chat_protocol else "❌"
        act = "✅" if r.active else "❌"
        rating = f"{r.rating:g}/5" if r.rating is not None else "none"
        lines.append(f"Profile: {act} Active · {cp} Chat Protocol · Rating {rating} · "
                     f"Doctor score {r.trust_score}/100")
        if r.unresponsive_flag and r.status == "live":
            lines.append("_Agentverse flags it \"unresponsive\", but it answered our test just "
                         "now, so the flag looks out of date. It clears after its next "
                         "answered conversation._")
        elif r.unresponsive_flag:
            lines.append("_Agentverse also flags it \"unresponsive\"._")
    else:
        lines.append("_Agentverse profile data unavailable right now._")

    when = r.checked_at[11:16] + " UTC" if len(r.checked_at) >= 16 else "just now"
    if r.status != PENDING:
        lines += ["", f"_Checked {when} with one test message. "
                      "Results are cached for 10 minutes._"]
    if r.address:
        lines.append(f"Full profile audit: `audit {r.address}`")
    return report.fit("\n".join(lines))
