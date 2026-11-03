"""L5 service: text -> reply. Orchestrates router -> Agentverse lookup -> scorer -> report.

Never raises and never returns an empty reply. Outcome labels go to the request log:
ok | partial | not_found | invalid | api_down | timeout | help | need_target | bad_address |
off_scope | fallback | fix_guide | fix_guide_none (Q5: no audit in this chat, or no such
fix number), explain | explain_none (Q10 "why this score?": evidence for the last or named
audit; none = no audit in this chat), card_profile (Q4 "Open profile" click), plus for Pre-Hire Check: prehire_<status> (live | degraded | unreachable |
unknown | not_found | invalid | error | pending) and prehire_need_target.
"""
from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Iterable, Optional, Protocol

from agent import cards, evidence, findability, guides, router
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
# Q12 findability: wait at most FIND_WAIT_S for the searches, and never past the reply budget
# minus FIND_MARGIN_S. Less than MIN_FIND_S left: start them (cache warms), don't wait.
FIND_WAIT_S = 7.0
FIND_MARGIN_S = 0.5
MIN_FIND_S = 1.0


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
    input_type: str  # address | handle | none | soft_miss (guessed handle not found)
    targets: int = 0
    via_url: bool = False
    cached: bool = False
    live: str = ""  # Q2 live check: "" (not run) | pending | live | degraded | unreachable | ...
    card: Optional[dict] = None  # Q4: MetadataContent.metadata of an ASI:One card, audits only
    find: str = ""  # Q12: "<checked>/<phrases>" when the findability test ran
    find_top50: int = -1  # Q12: phrases where the agent was in the top 50


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
    if intent.kind == "explain" and not intent.targets:
        return _explain(chat_key, text)
    if intent.kind not in ("audit", "prehire", "explain"):
        text_, outcome = router.reply(intent)
        return Result(text_, outcome, "none")

    def soft_miss() -> Result:
        """A guessed mid-sentence handle Agentverse didn't confirm: answer the message as if
        there were no handle in it. Never an error reply for a guess."""
        fb = intent.fallback or router.Intent("help")
        if fb.kind == "explain":
            r = _explain(chat_key, text)
            return Result(r.text, r.outcome, "soft_miss")
        text_, outcome = router.reply(fb)
        return Result(text_, outcome, "soft_miss")

    target: Target = intent.targets[0]
    n = len(intent.targets)
    footer = router.more_targets(n - 1) if n > 1 else ""

    def err(text: str, outcome: str) -> Result:
        return Result(text + footer, outcome, target.kind, n, target.from_url)

    if intent.kind == "prehire" and prehire is not None:
        try:
            body, status = await asyncio.wait_for(prehire(target), PREHIRE_HARD_TIMEOUT_S)
        except asyncio.TimeoutError:
            return soft_miss() if intent.soft else err(router.TIMEOUT, "prehire_error")
        if intent.soft and status in ("not_found", "invalid", "error"):
            return soft_miss()
        return Result(fit(body, footer), f"prehire_{status}", target.kind, n, target.from_url)

    try:
        lk = await asyncio.wait_for(_lookup(client, target), HARD_TIMEOUT_S)
    except asyncio.TimeoutError:
        return soft_miss() if intent.soft else err(router.TIMEOUT, "timeout")
    if intent.soft and (lk.outcome not in ("ok", "partial")
                        or lk.profile_status in ("timeout", "api_down")):
        return soft_miss()

    # Profile fetch failed (not "not found"): any score would be a guess. Say so instead.
    if lk.outcome == "partial" and lk.profile_status in ("timeout", "api_down"):
        return err(router.TIMEOUT if lk.profile_status == "timeout" else router.API_DOWN,
                   lk.profile_status)

    if lk.outcome in ("ok", "partial") and intent.kind == "explain":
        sc = score(lk)
        name = clean((lk.profile or {}).get("name")) or clean(target.label)
        shown = shown_for(lk, sc, name)
        guides.LAST.put(chat_key, shown)
        return Result(evidence.format_explain(shown, text), "explain", target.kind, n,
                      target.from_url, lk.cached)

    if lk.outcome in ("ok", "partial"):
        sc = score(lk)

        async def live_check() -> Any:
            if probe is not None and lk.address and sc.check("responsive").detail == UNRESPONSIVE_FLAG:
                return await _live_check(probe, lk.address,
                                         AUDIT_BUDGET_S - (time.monotonic() - started))
            return None

        live, find = await asyncio.gather(live_check(), _findability(client, lk, sc, started))
        body = format_report(lk, sc, live=live, footer=footer, find=find)
        name = clean((lk.profile or {}).get("name")) or clean(target.label)
        top = sc.fixes[:TOP_FIXES]
        guides.LAST.put(chat_key, shown_for(lk, sc, name))
        live_status = live if isinstance(live, str) else str(getattr(live, "status", "") or "")
        f_items = find.items if find is not None else ()
        return Result(body, lk.outcome, target.kind, n, target.from_url, lk.cached, live_status,
                      _card(name, lk.address or "", sc, top),
                      f"{sum(st == 'ok' for _, st, _ in f_items)}/{len(f_items)}" if f_items else "",
                      sum(st == "ok" and bool(rk) for _, st, rk in f_items) if f_items else -1)
    reply = {
        "not_found": router.not_found(target.label),
        "invalid": router.invalid(target.label),
        "api_down": router.API_DOWN,
        "timeout": router.TIMEOUT,
    }.get(lk.outcome, router.FALLBACK)
    outcome = lk.outcome if lk.outcome in ("not_found", "invalid", "api_down", "timeout") else "fallback"
    return err(reply, outcome)


async def _findability(client: Any, lk: Lookup, sc: Any, started: float) -> Any:
    """Q12: search rank for the agent's own starter prompts. None = not run. Never raises.
    Off switch: FINDABILITY=0 in the VPS .env (read per reply, like AUDIT_CARDS)."""
    try:
        if os.getenv("FINDABILITY", "1").strip() == "0" or not sc.indexed or not lk.address:
            return None
        if not hasattr(client, "search_addresses"):
            return None
        items = findability.phrases(lk.profile)
        if not items:
            return None
        wait = min(FIND_WAIT_S, started + REPLY_BUDGET_S - FIND_MARGIN_S - time.monotonic())
        return await findability.check(client, lk.address, items, wait if wait >= MIN_FIND_S else 0)
    except Exception:
        return None


def _card(name: str, address: str, sc: Any, top: Iterable[Any]) -> Optional[dict]:
    """Q4 card for an audit reply. Never breaks the reply: any error -> no card.
    Kill switch: AUDIT_CARDS=0 in the VPS .env (push_env.sh, then recreate the container)
    sends the same text with no card, without a rebuild. Read per reply."""
    if os.getenv("AUDIT_CARDS", "1").strip() == "0":
        return None
    try:
        url = PROFILE_URL.format(address=address) if address else ""
        payload = cards.audit_payload(name, address, sc.total, sc.verdict,
                                      [c.fix for c in top], url)
        return cards.card_metadata(payload)
    except Exception:
        return None


PROFILE_OPENED = ("Opened the profile on Agentverse: [Open profile on Agentverse]({url})\n\n"
                  "Changed something? Ask me to re-check it.")


async def handle_card(sel: "cards.Selection", client: LookupClient,
                      self_handles: Iterable[str] = (), self_addresses: Iterable[str] = (),
                      prehire: Optional[PreHireFn] = None, probe: Optional[ProbeFn] = None,
                      chat_key: str = "") -> Result:
    """Q4: a click on an audit card. Never raises, never returns an empty reply."""
    try:
        if sel.action == cards.FIX:
            shown = guides.LAST.get(chat_key)
            if sel.address and (shown is None or shown.address != sel.address):
                # This chat forgot that audit (restart, other chat): rebuild it quietly.
                lk = await asyncio.wait_for(client.lookup(sel.address), HARD_TIMEOUT_S)
                if lk.outcome not in ("ok", "partial") or (
                        lk.outcome == "partial" and lk.profile_status in ("timeout", "api_down")):
                    return Result(router.NO_AUDIT_YET, "fix_guide_none", "address")
                sc = score(lk)
                name = clean((lk.profile or {}).get("name")) or "this agent"
                guides.LAST.put(chat_key, shown_for(lk, sc, name, sel.address))
            return _fix_guide(sel.n, chat_key)
        if sel.action == cards.PROFILE:
            return Result(PROFILE_OPENED.format(url=PROFILE_URL.format(address=sel.address)),
                          "card_profile", "address", 1)
        command = (f"audit {sel.address}" if sel.action == cards.RECHECK
                   else f"is {sel.address} live?")
        return await _handle(command, client, self_handles, self_addresses, prehire, probe,
                             chat_key)
    except asyncio.TimeoutError:
        return Result(router.TIMEOUT, "timeout", "address", 1)
    except Exception:
        return Result(router.FALLBACK, "fallback", "none")


def shown_for(lk: Lookup, sc: Any, name: str, address: str = "") -> guides.Shown:
    """What a chat remembers about an audit: top fixes (Q5) + the evidence (Q10)."""
    return guides.Shown(name, lk.address or address, sc.fixes[:TOP_FIXES], sc.total, sc.verdict,
                        evidence.rows(lk, sc), tuple(evidence.facts(lk.profile).items()))


def _explain(chat_key: str, text: str) -> Result:
    """Q10: "why this score?" about this chat's last audit. No lookup, no I/O."""
    shown = guides.LAST.get(chat_key)
    if shown is None or not shown.rows:
        return Result(router.EXPLAIN_NONE, "explain_none", "none")
    return Result(evidence.format_explain(shown, text), "explain", "none")


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
