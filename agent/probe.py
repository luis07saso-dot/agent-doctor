"""P2 live probe: is another agent really answering on the Agent Chat Protocol right now?

Reusable interface (the human audit report will call this later):

    result: ProbeResult = await PROBER.probe(ctx, address)

- Sends ONE ChatMessage (PROBE_TEXT) to `address` in a fresh session that only the probe
  uses, then waits up to PROBE_TIMEOUT_S for the target's ChatAcknowledgement and first reply.
- status: "live" (it replied), "degraded" (acked, no reply in time), "unreachable" (nothing,
  or the message could not be sent), "skipped" (own address), "error" (our side: too many
  probes in flight, or an internal failure; not cached).
- ack_ms / reply_ms are measured separately from the moment the message was sent. They include
  mailbox polling on both sides (~1s each), so treat them as "what a caller would see".
- Results are cached for CACHE_TTL_S per address (failures too), and concurrent probes of the
  same address share one in-flight probe. So a target gets at most one probe message per
  CACHE_TTL_S from Doctor, however many people ask.

Routing (no reply loops): every message the target sends in a probe session (acks, replies,
late replies, session ends) is consumed by `owns()` + `on_chat()` / `on_ack()`, which the chat
handlers call BEFORE the user path. The probe never sends a second ChatMessage; only acks.
Probe sessions are remembered for LATE_TTL_S after they close, so late replies are swallowed too.

Needs concurrent message handling (Agent(handle_messages_concurrently=True)): the probe awaits
replies that arrive as ordinary messages. With uagents' default sequential queue, a handler
awaiting the probe would block the very reply it waits for.

Logs: one "PROBE {json}" line per probe and per consumed message. Target and session hashed,
no message bodies.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections import OrderedDict
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Callable, Literal

from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    ResourceContent,
    TextContent,
)
from uagents_core.models import Model

from agent import rubric

ProbeStatus = Literal["live", "degraded", "unreachable", "skipped", "error"]

PROBE_TEXT = "Hi! What can you do?"  # neutral, in-scope for any chat agent (see drafts)
PROBE_TIMEOUT_S = 14.0  # send -> first reply. User decision 2026-11-02 (was 12s). Chat paths
#                        stop waiting at service.REPLY_BUDGET_S and report "still checking".
SEND_TIMEOUT_S = 5  # resolving the endpoint + handing the envelope to it
CACHE_TTL_S = 600.0  # 10 min per target: also the anti-spam bound for third-party agents
CACHE_MAX = 512
LATE_TTL_S = 3600.0  # closed probe sessions: swallow late replies for this long
LATE_MAX = 2048
MAX_INFLIGHT = 8  # distinct targets probed at once
CHAT_PROTOCOL_DIGEST = f"proto:{rubric.CHAT_PROTOCOL_DIGEST}"


@dataclass(frozen=True)
class ProbeResult:
    address: str
    status: ProbeStatus
    ack_ms: int | None = None
    reply_ms: int | None = None
    checked_at: str = ""  # ISO 8601 UTC, when the probe message was sent
    cached: bool = False
    detail: str = ""  # reason code: ok | no_ack | no_reply | no_endpoint | send_failed |
    #                   timeout | self | busy | internal

    @property
    def live(self) -> bool:
        return self.status == "live"


class _Pending:
    __slots__ = ("address", "msg_id", "sent_at", "ack_ms", "reply_ms", "acked", "replied")

    def __init__(self, address: str, msg_id: str, sent_at: float) -> None:
        self.address = address
        self.msg_id = msg_id
        self.sent_at = sent_at
        self.ack_ms: int | None = None
        self.reply_ms: int | None = None
        self.acked = asyncio.Event()
        self.replied = asyncio.Event()


def _hash(value: str, n: int = 12) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:n]


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _session(ctx: Any) -> str:
    try:
        return str(ctx.session or "")
    except Exception:
        return ""


class Prober:
    def __init__(
        self,
        context_factory: Callable[[], Any] | None = None,
        *,
        timeout: float = PROBE_TIMEOUT_S,
        cache_ttl: float = CACHE_TTL_S,
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
    ) -> None:
        self._factory = context_factory
        self._timeout = timeout
        self._cache_ttl = cache_ttl
        self._clock = clock
        self._wall = wall
        self._self: set[str] = set()
        self._pending: dict[str, _Pending] = {}  # session -> probe in flight
        self._closed: OrderedDict[str, tuple[float, str]] = OrderedDict()  # session -> (exp, addr)
        self._cache: OrderedDict[str, tuple[float, ProbeResult]] = OrderedDict()
        self._inflight: dict[str, asyncio.Task] = {}

    def configure(self, context_factory: Callable[[], Any] | None, self_addresses=()) -> None:
        """Called from main: `context_factory` returns a context with a FRESH session
        (agent._build_context in uagents 0.26.1). Own addresses are never probed."""
        self._factory = context_factory
        self._self = {a for a in self_addresses if a}

    # ---------- public API ----------

    async def probe(self, ctx: Any, address: str) -> ProbeResult:
        """Probe one agent. Never raises. Waits at most ~timeout (send time counts)."""
        address = (address or "").strip().lower()
        now_wall = self._wall()
        if address in self._self:
            return ProbeResult(address, "skipped", checked_at=_iso(now_wall), detail="self")
        hit = self._cache_get(address)
        if hit is not None:
            return replace(hit, cached=True)
        task = self._inflight.get(address)
        if task is None:
            if len(self._inflight) >= MAX_INFLIGHT:
                return ProbeResult(address, "error", checked_at=_iso(now_wall), detail="busy")
            task = asyncio.ensure_future(self._run(ctx, address))
            self._inflight[address] = task
            task.add_done_callback(lambda _t, a=address: self._inflight.pop(a, None))
        try:
            # shield: a caller that gives up (its own timeout) doesn't cancel a shared probe.
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            raise
        except Exception:
            return ProbeResult(address, "error", checked_at=_iso(now_wall), detail="internal")

    def owns(self, sender: str, session: str) -> bool:
        """True if this message belongs to a probe session (open or recently closed) and comes
        from the probed agent. Such messages must never reach the user handler."""
        p = self._pending.get(session)
        if p is not None:
            return p.address == sender
        closed = self._closed.get(session)
        if closed is None:
            return False
        exp, addr = closed
        if self._clock() >= exp:
            self._closed.pop(session, None)
            return False
        return addr == sender

    async def on_chat(self, ctx: Any, sender: str, msg: ChatMessage) -> None:
        """Probe-session ChatMessage from the target (the caller already acked it)."""
        session = _session(ctx)
        p = self._pending.get(session)
        has_reply = any(
            (isinstance(c, TextContent) and c.text.strip()) or isinstance(c, ResourceContent)
            for c in msg.content
        )
        if p is None:
            self._log(ctx, "late_reply" if has_reply else "late_control", sender, session)
            return
        if has_reply and not p.replied.is_set():
            p.reply_ms = self._ms_since(p.sent_at)
            p.replied.set()
            self._log(ctx, "reply", sender, session, reply_ms=p.reply_ms)
        else:
            self._log(ctx, "extra" if has_reply else "control", sender, session)

    async def on_ack(self, ctx: Any, sender: str, msg: ChatAcknowledgement) -> None:
        session = _session(ctx)
        p = self._pending.get(session)
        if p is None:
            self._log(ctx, "late_ack", sender, session)
            return
        if not p.acked.is_set():
            p.ack_ms = self._ms_since(p.sent_at)
            p.acked.set()
            match = str(msg.acknowledged_msg_id) == p.msg_id
            self._log(ctx, "ack", sender, session, ack_ms=p.ack_ms, msg_id_match=match)

    # ---------- internals ----------

    async def _run(self, ctx: Any, address: str) -> ProbeResult:
        sctx = self._factory() if self._factory else ctx  # fresh session when possible
        session = _session(sctx)
        msg = ChatMessage(content=[TextContent(text=PROBE_TEXT)])
        started_wall = self._wall()
        p = _Pending(address, str(msg.msg_id), self._clock())
        self._pending[session] = p  # register before sending: acks can be fast
        try:
            return await self._send_and_wait(sctx, ctx, p, msg, session, started_wall)
        finally:
            self._pending.pop(session, None)
            self._remember_closed(session, address)

    async def _send_and_wait(self, sctx, ctx, p: _Pending, msg: ChatMessage, session: str,
                             started_wall: float) -> ProbeResult:
        address = p.address

        def done(status: ProbeStatus, detail: str, cache: bool = True) -> ProbeResult:
            r = ProbeResult(address, status, p.ack_ms, p.reply_ms, _iso(started_wall), False,
                            detail)
            if cache:
                self._cache_put(address, r)
            self._log(ctx, "result", address, session, status=status, detail=detail,
                      ack_ms=p.ack_ms, reply_ms=p.reply_ms)
            return r

        try:
            st = await asyncio.wait_for(
                sctx.send_raw(
                    destination=address,
                    message_schema_digest=Model.build_schema_digest(msg),
                    message_body=msg.model_dump_json(),
                    timeout=SEND_TIMEOUT_S,
                    protocol_digest=CHAT_PROTOCOL_DIGEST,
                ),
                SEND_TIMEOUT_S + 1,
            )
        except asyncio.TimeoutError:
            return done("unreachable", "send_failed")
        except Exception:
            return done("unreachable", "send_failed")
        status = str(getattr(getattr(st, "status", None), "value", getattr(st, "status", "")))
        if status == "failed":
            no_ep = "resolve" in str(getattr(st, "detail", "")).lower()
            return done("unreachable", "no_endpoint" if no_ep else "send_failed")

        remaining = self._timeout - (self._clock() - p.sent_at)
        if remaining > 0:
            try:
                await asyncio.wait_for(p.replied.wait(), remaining)
            except asyncio.TimeoutError:
                pass
        if p.replied.is_set():
            return done("live", "ok" if p.acked.is_set() else "no_ack")
        if p.acked.is_set():
            return done("degraded", "no_reply")
        return done("unreachable", "timeout")

    def _ms_since(self, t0: float) -> int:
        return max(0, int((self._clock() - t0) * 1000))

    def _remember_closed(self, session: str, address: str) -> None:
        if not session:
            return
        self._closed[session] = (self._clock() + LATE_TTL_S, address)
        self._closed.move_to_end(session)
        while len(self._closed) > LATE_MAX:
            self._closed.popitem(last=False)

    def _cache_get(self, address: str) -> ProbeResult | None:
        hit = self._cache.get(address)
        if hit is None:
            return None
        exp, r = hit
        if self._clock() >= exp:
            self._cache.pop(address, None)
            return None
        return r

    def _cache_put(self, address: str, r: ProbeResult) -> None:
        self._cache[address] = (self._clock() + self._cache_ttl, r)
        self._cache.move_to_end(address)
        while len(self._cache) > CACHE_MAX:
            self._cache.popitem(last=False)

    def _log(self, ctx: Any, event: str, address: str, session: str, **extra) -> None:
        rec = {"event": event, "target": _hash(address), "session": _hash(session, 8),
               **{k: v for k, v in extra.items() if v is not None}}
        try:
            ctx.logger.info("PROBE " + json.dumps(rec, separators=(",", ":"), sort_keys=True))
        except Exception:
            pass


PROBER = Prober()
