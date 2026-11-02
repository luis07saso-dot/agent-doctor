"""L5 service: text -> reply. Orchestrates router -> Agentverse lookup -> scorer -> report.

Never raises and never returns an empty reply. Outcome labels go to the request log:
ok | partial | not_found | invalid | api_down | timeout | help | need_target | bad_address |
off_scope | fallback | fix_guide | fix_guide_none (Q5: no audit in this chat, or no such
fix number), plus for Pre-Hire Check: prehire_<status> (live | degraded | unreachable |
unknown | not_found | invalid | error | pending) and prehire_need_target.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Iterable, Optional, Protocol

from agent import guides, router
from agent.agentverse import Lookup
from agent.extract import Target
from agent.report import PROFILE_URL, TOP_FIXES, clean, fit, format_report
from agent.scorer import UNRESPONSIVE_FLAG, score

HARD_TIMEOUT_S = 13.5  # client caps itself at 12s; this is the belt to its braces
# Every chat reply that waits on a live probe goes out by this many seconds after the request
# arrived (our p95 target is <15s; a slow reply risks our own "unresponsive" flag). The probe
# waits up to 14s (user decision 2026-11-02). Not done by then -> "still checking" reply; the
# probe keeps running and is cached, so asking again gives the verdict at once.
REPLY_BUDGET_S = 15.0
# Pre-Hire chat path: the check stops waiting at REPLY_BUDGET_S itself (deadline set in
# chat.py). This is only the belt, for a slow Agentverse lookup.
PREHIRE_HARD_TIMEOUT_S = REPLY_BUDGET_S + 2.0
# Q2: audit + live check of a flagged agent must still answer in one reply (user decision
# Q2-D2 = a). Counted from the start of the request; the probe gets what's left.
AUDIT_BUDGET_S = REPLY_BUDGET_S
MIN_PROBE_S = 1.0  # less than this left: don't wait, report the check as still running
LIVE_PENDING = "pending"  # format_report: probe started but not finished within the budget


class LookupClient(Protocol):
    async def lookup(self, address: str) -> Lookup: ...
    async def lookup_handle(self, handle: str) -> Lookup: ...


# Pre-Hire Check for one target -> (reply text, status). Injected by the chat handler, which
# owns the context the live probe needs. None = Pre-Hire wording is answered with an audit.
PreHireFn = Callable[[Target], Awaitable[tuple[str, str]]]
# Live probe of one address -> ProbeResult (agent/probe.py). Injected by the chat handler.
# Used only when Agentverse flags the audited agent "unresponsive" (user decision Q2-D1).
ProbeFn = Callable[[str], Awaitable[Any]]


@dataclass(frozen=True)
class Result:
    text: str
    outcome: str
    input_type: str  # address | handle | none
    targets: int = 0
    via_url: bool = False
    cached: bool = False
    live: str = ""  # Q2 live check: "" (not run) | pending | live | degraded | unreachable | ...


async def handle(text: str, client: LookupClient, self_handles: Iterable[str] = (),
                 self_addresses: Iterable[str] = (), prehire: Optional[PreHireFn] = None,
                 probe: Optional[ProbeFn] = None, chat_key: str = "") -> Result:
    """`chat_key` identifies one chat (hashed sender + session). An audit remembers its top
    fixes under it, so a later "how do I fix #2" in the same chat gets that fix's guide."""
    try:
        return await _handle(text, client, self_handles, self_addresses, prehire, probe, chat_key)
    except Exception:  # last line of defence: the caller still gets a reply
        return Result(router.FALLBACK, "fallback", "none")


async def _handle(text: str, client: LookupClient, self_handles: Iterable[str],
                  self_addresses: Iterable[str] = (), prehire: Optional[PreHireFn] = None,
                  probe: Optional[ProbeFn] = None, chat_key: str = "") -> Result:
    started = time.monotonic()
    has_audit = guides.LAST.get(chat_key) is not None
    intent = router.classify(text, self_handles, self_addresses, has_audit)
    if intent.kind == "fix_guide":
        return _fix_guide(intent.n, chat_key)
    if intent.kind not in ("audit", "prehire"):
        return Result(router.reply_for(intent.kind), intent.kind, "none")

    target: Target = intent.targets[0]
    n = len(intent.targets)
    footer = router.more_targets(n - 1) if n > 1 else ""

    def err(text: str, outcome: str) -> Result:
        return Result(text + footer, outcome, target.kind, n, target.from_url)

    if intent.kind == "prehire" and prehire is not None:
        try:
            body, status = await asyncio.wait_for(prehire(target), PREHIRE_HARD_TIMEOUT_S)
        except asyncio.TimeoutError:
            return err(router.TIMEOUT, "prehire_error")
        return Result(fit(body, footer), f"prehire_{status}", target.kind, n, target.from_url)

    try:
        lk = await asyncio.wait_for(_lookup(client, target), HARD_TIMEOUT_S)
    except asyncio.TimeoutError:
        return err(router.TIMEOUT, "timeout")

    # Profile fetch failed (not "not found"): any score would be a guess. Say so instead.
    if lk.outcome == "partial" and lk.profile_status in ("timeout", "api_down"):
        return err(router.TIMEOUT if lk.profile_status == "timeout" else router.API_DOWN,
                   lk.profile_status)

    if lk.outcome in ("ok", "partial"):
        sc = score(lk)
        live = None
        if probe is not None and lk.address and sc.check("responsive").detail == UNRESPONSIVE_FLAG:
            live = await _live_check(probe, lk.address, AUDIT_BUDGET_S - (time.monotonic() - started))
        body = format_report(lk, sc, live=live, footer=footer)
        name = clean((lk.profile or {}).get("name")) or clean(target.label)
        guides.LAST.put(chat_key, guides.Shown(name, lk.address or "", sc.fixes[:TOP_FIXES]))
        live_status = live if isinstance(live, str) else str(getattr(live, "status", "") or "")
        return Result(body, lk.outcome, target.kind, n, target.from_url, lk.cached, live_status)
    reply = {
        "not_found": router.not_found(target.label),
        "invalid": router.invalid(target.label),
        "api_down": router.API_DOWN,
        "timeout": router.TIMEOUT,
    }.get(lk.outcome, router.FALLBACK)
    outcome = lk.outcome if lk.outcome in ("not_found", "invalid", "api_down", "timeout") else "fallback"
    return err(reply, outcome)


def _fix_guide(n: int, chat_key: str) -> Result:
    """Q5: full guide for fix #n of this chat's last audit. No lookup, no I/O."""
    shown = guides.LAST.get(chat_key)
    if shown is None:
        return Result(router.NO_AUDIT_YET, "fix_guide_none", "none")
    if not 1 <= n <= len(shown.fixes):
        return Result(router.no_such_fix(n, len(shown.fixes), shown.name), "fix_guide_none", "none")
    tail = ""
    if shown.address:
        tail = f"\n\n[Open profile on Agentverse]({PROFILE_URL.format(address=shown.address)})"
    body = guides.full_guide(n, shown.fixes[n - 1], shown.name)
    return Result(fit(body, tail), "fix_guide", "none")


async def _lookup(client: LookupClient, target: Target) -> Lookup:
    if target.kind == "address":
        return await client.lookup(target.value)
    return await client.lookup_handle(target.value)


async def _live_check(probe: ProbeFn, address: str, remaining: float) -> Any:
    """Q2: probe a flagged agent within what's left of the reply budget. Returns the
    ProbeResult, or LIVE_PENDING if it isn't done in time. The probe keeps running (and is
    cached for 10 min), so a follow-up "is <agent> live?" answers instantly."""
    if remaining < MIN_PROBE_S:
        return LIVE_PENDING
    try:
        return await asyncio.wait_for(asyncio.shield(probe(address)), remaining)
    except asyncio.TimeoutError:
        return LIVE_PENDING
    except Exception:
        return None  # no live verdict: report falls back to the Q1 note
