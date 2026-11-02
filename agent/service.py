"""L5 service: text -> reply. Orchestrates router -> Agentverse lookup -> scorer -> report.

Never raises and never returns an empty reply. Outcome labels go to the request log:
ok | partial | not_found | invalid | api_down | timeout | help | need_target | bad_address |
off_scope | fallback
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Iterable, Protocol

from agent import router
from agent.agentverse import Lookup
from agent.extract import Target
from agent.report import fit, format_report
from agent.scorer import score

HARD_TIMEOUT_S = 13.5  # client caps itself at 12s; this is the belt to its braces


class LookupClient(Protocol):
    async def lookup(self, address: str) -> Lookup: ...
    async def lookup_handle(self, handle: str) -> Lookup: ...


@dataclass(frozen=True)
class Result:
    text: str
    outcome: str
    input_type: str  # address | handle | none
    targets: int = 0
    via_url: bool = False
    cached: bool = False


async def handle(text: str, client: LookupClient, self_handles: Iterable[str] = (),
                 self_addresses: Iterable[str] = ()) -> Result:
    try:
        return await _handle(text, client, self_handles, self_addresses)
    except Exception:  # last line of defence: the caller still gets a reply
        return Result(router.FALLBACK, "fallback", "none")


async def _handle(text: str, client: LookupClient, self_handles: Iterable[str],
                  self_addresses: Iterable[str] = ()) -> Result:
    intent = router.classify(text, self_handles, self_addresses)
    if intent.kind != "audit":
        return Result(router.reply_for(intent.kind), intent.kind, "none")

    target: Target = intent.targets[0]
    n = len(intent.targets)
    footer = router.more_targets(n - 1) if n > 1 else ""

    def err(text: str, outcome: str) -> Result:
        return Result(text + footer, outcome, target.kind, n, target.from_url)

    try:
        lk = await asyncio.wait_for(_lookup(client, target), HARD_TIMEOUT_S)
    except asyncio.TimeoutError:
        return err(router.TIMEOUT, "timeout")

    # Profile fetch failed (not "not found"): any score would be a guess. Say so instead.
    if lk.outcome == "partial" and lk.profile_status in ("timeout", "api_down"):
        return err(router.TIMEOUT if lk.profile_status == "timeout" else router.API_DOWN,
                   lk.profile_status)

    if lk.outcome in ("ok", "partial"):
        body = fit(format_report(lk, score(lk)), footer)
        return Result(body, lk.outcome, target.kind, n, target.from_url, lk.cached)
    reply = {
        "not_found": router.not_found(target.label),
        "invalid": router.invalid(target.label),
        "api_down": router.API_DOWN,
        "timeout": router.TIMEOUT,
    }.get(lk.outcome, router.FALLBACK)
    outcome = lk.outcome if lk.outcome in ("not_found", "invalid", "api_down", "timeout") else "fallback"
    return err(reply, outcome)


async def _lookup(client: LookupClient, target: Target) -> Lookup:
    if target.kind == "address":
        return await client.lookup(target.value)
    return await client.lookup_handle(target.value)
