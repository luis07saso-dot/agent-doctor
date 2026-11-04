"""L5 service: text -> reply. Orchestrates router -> Agentverse lookup -> scorer -> report.

Never raises and never returns an empty reply. Outcome labels go to the request log:
ok | partial | not_found | invalid | api_down | timeout | help | need_target | bad_address |
off_scope | fallback | fix_guide | fix_guide_none (Q5: no audit in this chat, or no such
fix number), explain | explain_none (Q10 "why this score?": evidence for the last or named
audit; none = no audit in this chat), forget | forget_error (Q15), recheck_none | last_mismatch
(Q17: nothing remembered | remembered agent isn't the one named; input=last on re-use),
scout_which (Q18: "audit it" right after a scout list: which one?), card_profile (Q4 "Open profile" click), plus for Pre-Hire Check: prehire_<status> (live | degraded | unreachable |
unknown | not_found | invalid | error | pending) and prehire_need_target.
"""
from __future__ import annotations

import asyncio
import os
import re
import time
from collections import OrderedDict
from dataclasses import dataclass, replace
from typing import Any, Awaitable, Callable, Iterable, Optional, Protocol

from agent import cards, evidence, findability, guides, llm, recheck, router, scout
from agent.agentverse import Lookup
from agent.extract import Target
from agent.report import PROFILE_URL, TOP_FIXES, clean, fit, format_report, short_address
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
# Q18: may add a 3rd item, the profile Lookup, so the chat remembers the agent it checked.
PreHireFn = Callable[[Target], Awaitable[tuple]]
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
    scout_hits: int = -1  # Q13: agents listed by a scout reply
    scout_live: str = ""  # Q13: "<answered>/<probed>" when live tests ran
    llm: str = ""  # Q11: "" not asked | used | none | fallback | skip | off


async def handle(text: str, client: LookupClient, self_handles: Iterable[str] = (),
                 self_addresses: Iterable[str] = (), prehire: Optional[PreHireFn] = None,
                 probe: Optional[ProbeFn] = None, chat_key: str = "",
                 sender_key: str = "", deadline: Optional[float] = None) -> Result:
    """`chat_key` identifies one chat (hashed sender + session). An audit remembers its top
    fixes under it, so a later "how do I fix #2" in the same chat gets that fix's guide.
    `sender_key` (hashed sender, Q15) keys the re-check diff and `forget`.
    `deadline` (Q13): monotonic time the reply must go out by (chat.py: arrival + budget)."""
    try:
        return await _handle(text, client, self_handles, self_addresses, prehire, probe, chat_key,
                             sender_key, deadline)
    except Exception:  # last line of defence: the caller still gets a reply
        return Result(router.FALLBACK, "fallback", "none")


async def _handle(text: str, client: LookupClient, self_handles: Iterable[str],
                  self_addresses: Iterable[str] = (), prehire: Optional[PreHireFn] = None,
                  probe: Optional[ProbeFn] = None, chat_key: str = "",
                  sender_key: str = "", deadline: Optional[float] = None) -> Result:
    started = time.monotonic()
    has_audit = guides.LAST.get(chat_key) is not None
    listed = scout.LISTS.get(chat_key)
    intent = router.classify(text, self_handles, self_addresses, has_audit, listed is not None)
    if intent.kind == "scout":
        return await _scout(intent.query, client, probe, self_handles, self_addresses, chat_key,
                            sender_key, deadline if deadline is not None
                            else started + REPLY_BUDGET_S)
    if intent.kind in ("scout_need_what", "scout_pick_none"):
        text_, outcome = router.reply(intent)
        return Result(text_, outcome, "none")
    via_pick = intent.pick > 0
    if via_pick:  # Q13: "audit #2" = agent #2 of this chat's last scout list
        if not listed:
            return Result(router.SCOUT_PICK_NONE, "scout_pick_none", "pick")
        if intent.pick > len(listed):
            return Result(router.scout_pick_short(intent.pick, len(listed)), "scout_pick_none",
                          "pick")
        intent = replace(intent, targets=(Target("address", listed[intent.pick - 1][0]),), pick=0)
    via_last = bool(intent.last)
    if via_last and listed and _LATEST.get(chat_key) == "scout":
        # Q18: right after a scout list, "audit it" / "is that agent live?" can mean any listed
        # agent. A name word that fits one of them picks it; no name (weak wording) -> ask.
        hits = _list_hits(listed, intent.hint)
        if len(hits) == 1:
            intent = replace(intent, targets=(Target("address", hits[0]),), last="",
                             fallback=None)
        elif len(hits) > 1 or (intent.last == "chat" and not intent.hint):
            return Result(router.scout_which(len(listed), intent.kind == "prehire"),
                          "scout_which", "last")
    if via_last and intent.last:  # Q17: "re-check the same agent" -> the remembered agent's address
        shown, other = _remembered(chat_key, sender_key, intent.last == "any", intent.hint)
        if shown is None and listed:  # Q18: "audit the autonomad one": a listed agent's name
            hits = _list_hits(listed, intent.hint)
            if len(hits) == 1:
                shown, other = guides.Shown("", hits[0], ()), None
        if shown is None and other is not None:  # Q17b: remembered agent isn't the one named
            return Result(router.last_mismatch(other.name, intent.kind == "prehire"),
                          "last_mismatch", "last")
        if shown is None:
            text_, outcome = router.reply(intent.fallback or router.Intent("recheck_none"))
            return Result(text_, outcome, "none")
        intent = replace(intent, targets=(Target("address", shown.address),), last="",
                         fallback=None)
    if intent.kind == "fix_guide":
        return _fix_guide(intent.n, chat_key)
    if intent.kind == "forget":
        ok = await guides.LAST.memory.forget(diff_key(sender_key, chat_key), chat_key, sender_key)
        scout.LISTS.drop_sender(sender_key, chat_key)
        _LATEST.pop(chat_key, None)
        return Result(router.FORGET_DONE if ok else router.FORGET_ERROR,
                      "forget" if ok else "forget_error", "none")
    if intent.kind == "explain" and not intent.targets:
        return await _followup(text, chat_key, _explain(chat_key, text), "explain")
    if intent.kind not in ("audit", "prehire", "explain"):
        text_, outcome = router.reply(intent)
        return await _followup(text, chat_key, Result(text_, outcome, "none"), intent.kind)

    async def soft_miss() -> Result:
        """A guessed mid-sentence handle Agentverse didn't confirm: answer the message as if
        there were no handle in it. Never an error reply for a guess."""
        fb = intent.fallback or router.Intent("help")
        if fb.kind == "explain":
            r = _explain(chat_key, text)
            return await _followup(text, chat_key, Result(r.text, r.outcome, "soft_miss"),
                                   "explain")
        text_, outcome = router.reply(fb)
        return await _followup(text, chat_key, Result(text_, outcome, "soft_miss"), fb.kind)

    target: Target = intent.targets[0]
    itype = "last" if via_last else "pick" if via_pick else target.kind  # log input type
    n = len(intent.targets)
    footer = router.more_targets(n - 1) if n > 1 else ""

    def err(text: str, outcome: str) -> Result:
        return Result(text + footer, outcome, itype, n, target.from_url)

    if intent.kind == "prehire" and prehire is not None:
        try:
            res = await asyncio.wait_for(prehire(target), PREHIRE_HARD_TIMEOUT_S)
        except asyncio.TimeoutError:
            return await soft_miss() if intent.soft else err(router.TIMEOUT, "prehire_error")
        body, status = res[0], res[1]
        if intent.soft and status in ("not_found", "invalid", "error"):
            return await soft_miss()
        _remember_checked(res[2] if len(res) > 2 else None, chat_key, sender_key)
        return Result(fit(body, footer), f"prehire_{status}", itype, n, target.from_url)

    try:
        lk = await asyncio.wait_for(_lookup(client, target), HARD_TIMEOUT_S)
    except asyncio.TimeoutError:
        return await soft_miss() if intent.soft else err(router.TIMEOUT, "timeout")
    if intent.soft and (lk.outcome not in ("ok", "partial")
                        or lk.profile_status in ("timeout", "api_down")):
        return await soft_miss()

    # Profile fetch failed (not "not found"): any score would be a guess. Say so instead.
    if lk.outcome == "partial" and lk.profile_status in ("timeout", "api_down"):
        return err(router.TIMEOUT if lk.profile_status == "timeout" else router.API_DOWN,
                   lk.profile_status)

    if lk.outcome in ("ok", "partial") and intent.kind == "explain":
        sc = score(lk)
        name = clean((lk.profile or {}).get("name")) or clean(target.label)
        shown = shown_for(lk, sc, name)
        _remember(chat_key, shown, sender_key)
        return Result(evidence.format_explain(shown, text), "explain", itype, n,
                      target.from_url, lk.cached)

    if lk.outcome in ("ok", "partial"):
        sc = score(lk)

        async def live_check() -> Any:
            if probe is not None and lk.address and sc.check("responsive").detail == UNRESPONSIVE_FLAG:
                return await _live_check(probe, lk.address,
                                         AUDIT_BUDGET_S - (time.monotonic() - started))
            return None

        live, find = await asyncio.gather(live_check(), _findability(client, lk, sc, started))
        diff = _recheck(lk, sc, diff_key(sender_key, chat_key))
        body = format_report(lk, sc, live=live, footer=footer, find=find, diff=diff)
        name = clean((lk.profile or {}).get("name")) or clean(target.label)
        top = sc.fixes[:TOP_FIXES]
        _remember(chat_key, shown_for(lk, sc, name), sender_key)
        live_status = live if isinstance(live, str) else str(getattr(live, "status", "") or "")
        f_items = find.items if find is not None else ()
        return Result(body, lk.outcome, itype, n, target.from_url, lk.cached, live_status,
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


async def _scout(phrase: str, client: Any, probe: Optional[ProbeFn], self_handles: Iterable[str],
                 self_addresses: Iterable[str], chat_key: str, sender_key: str,
                 deadline: float) -> Result:
    """Q13 Agent Scout. Belt: never waits past REPLY_BUDGET_S + 2 whatever happens inside."""
    try:
        res = await asyncio.wait_for(
            scout.run(phrase, client, probe, deadline, tuple(self_addresses), tuple(self_handles),
                      sender_key), REPLY_BUDGET_S + 2.0)
    except asyncio.TimeoutError:
        res = scout.ScoutResult("timeout", phrase)
    if res.cands:
        scout.LISTS.put(chat_key, sender_key, scout.items(res))
        _mark(chat_key, "scout")
    return Result(scout.format_reply(res), f"scout_{res.status}", "none",
                  scout_hits=len(res.cands),
                  scout_live=f"{res.live}/{res.probed}" if res.probed else "")


# Q18 (FB-3): what this chat saw last, "agent" (audit, explain, Pre-Hire Check, card) or
# "scout" (a list). "audit this agent" means the newest of them, not an older audit. In memory
# only: after a restart the remembered audit (Q15) is used, as before.
_LATEST: "OrderedDict[str, str]" = OrderedDict()
LATEST_MAX = 2000


def _mark(chat_key: str, kind: str) -> None:
    if not chat_key:
        return
    _LATEST[chat_key] = kind
    _LATEST.move_to_end(chat_key)
    while len(_LATEST) > LATEST_MAX:
        _LATEST.popitem(last=False)


def _remember(chat_key: str, shown: guides.Shown, sender_key: str) -> None:
    guides.LAST.put(chat_key, shown, sender_key)
    _mark(chat_key, "agent")


def _remember_checked(lk: Any, chat_key: str, sender_key: str) -> None:
    """Q18 (FB-3): after a Pre-Hire Check, "audit this agent", "why this score?" and "how do I
    fix #1" are about the agent just checked (its reply showed its Doctor score). Only with a
    clean profile lookup; else the chat keeps what it had. Never raises."""
    try:
        if lk is None or lk.outcome not in ("ok", "partial") or not lk.address or (
                lk.profile_status in ("timeout", "api_down")):
            return
        sc = score(lk)
        name = clean((lk.profile or {}).get("name")) or short_address(lk.address)
        _remember(chat_key, shown_for(lk, sc, name), sender_key)
    except Exception:
        return


def _list_hits(listed: Iterable[tuple[str, str]], hint: Iterable[str]) -> list[str]:
    """Addresses of listed (scout) agents whose name fits the name words. None without words."""
    hint = tuple(hint)
    if not hint:
        return []
    return [a for a, name in listed if router.hint_matches(hint, name)]


def diff_key(sender_key: str, chat_key: str) -> str:
    """Q15: re-check diff + forget key. Default per hashed sender (user decision 2026-11-03).
    DIFF_KEY=chat in the VPS .env switches to per chat, e.g. if ASI:One turns out to relay
    many people under one sender (unverified). Read per reply."""
    return chat_key if os.getenv("DIFF_KEY", "").strip().lower() == "chat" else sender_key


def _remembered(chat_key: str, sender_key: str, any_chat: bool,
                hint: Iterable[str] = ()) -> tuple[Optional[guides.Shown], Optional[guides.Shown]]:
    """Q17: the agent "re-check the same agent" means: this chat's last audit, else (strong
    wording only) this sender's latest audits in any chat. Not across chats when DIFF_KEY=chat
    (ASI:One may relay many people under one sender: unverified, spec q15 F9).
    Q17b: with name words ("that same tavily agent"), the newest candidate whose name or handle
    matches. Returns (match, None), or (None, newest candidate) when none matches, or (None, None)."""
    found = [guides.LAST.get(chat_key)]
    if any_chat and diff_key(sender_key, chat_key) == sender_key:
        found += guides.LAST.memory.recent_for_sender(sender_key)
    cands = [s for s in found if s is not None and s.address]
    for s in cands:
        if router.hint_matches(hint, s.name, s.handle):
            return s, None
    return None, (cands[0] if cands else None)


def _recheck(lk: Lookup, sc: Any, key: str) -> Any:
    """Q15: diff vs the last check of this agent under `key`, then record this one. Only
    clean data is recorded (no partial lookups or notes), so no false Fixed/New. Never raises."""
    try:
        if not key or not lk.address or lk.outcome != "ok" or lk.notes:
            return None
        mem = guides.LAST.memory
        now = mem.clock()
        prev = mem.seen_get(key, lk.address)
        mem.seen_put(key, lk.address, recheck.record(sc, now))
        return recheck.compare(prev, sc, now)
    except Exception:
        return None


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
                      chat_key: str = "", sender_key: str = "") -> Result:
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
                _remember(chat_key, shown_for(lk, sc, name, sel.address), sender_key)
            return _fix_guide(sel.n, chat_key)
        if sel.action == cards.PROFILE:
            return Result(PROFILE_OPENED.format(url=PROFILE_URL.format(address=sel.address)),
                          "card_profile", "address", 1)
        command = (f"audit {sel.address}" if sel.action == cards.RECHECK
                   else f"is {sel.address} live?")
        return await _handle(command, client, self_handles, self_addresses, prehire, probe,
                             chat_key, sender_key)
    except asyncio.TimeoutError:
        return Result(router.TIMEOUT, "timeout", "address", 1)
    except Exception:
        return Result(router.FALLBACK, "fallback", "none")


def shown_for(lk: Lookup, sc: Any, name: str, address: str = "") -> guides.Shown:
    """What a chat remembers about an audit: top fixes (Q5) + the evidence (Q10)."""
    return guides.Shown(name, lk.address or address, sc.fixes[:TOP_FIXES], sc.total, sc.verdict,
                        evidence.rows(lk, sc), tuple(evidence.facts(lk.profile).items()),
                        clean((lk.profile or {}).get("handle")))


LLM_KINDS = ("explain", "help", "off_scope")  # Q11: rules replies the LLM may improve
LLM_MIN_WORDS, LLM_MAX_WORDS = 2, 60


async def _followup(text: str, chat_key: str, rules: Result, kind: str) -> Result:
    """Q11 (SCOPE A1): after an audit in this chat, a question the rules only answered
    generically. The LLM picks (ask, check, topic) from fixed lists; the reply is built from
    the remembered audit. Not asked, off, slow or unsure -> `rules`, unchanged. Never raises."""
    try:
        shown = guides.LAST.get(chat_key)
        if kind not in LLM_KINDS or shown is None or not shown.rows:
            return rules
        if not LLM_MIN_WORDS <= len(re.findall(r"\S+", text or "")) <= LLM_MAX_WORDS:
            return rules
        if kind == "help" and router.is_greeting(text):
            return rules
        if (kind == "explain" and evidence.topics(text)) or router.faq_key(text):
            return rules  # the rules already know what it's about
        f, label = await llm.MAPPER.map(text, chat_key)
        if f is None or label != "used":
            return replace(rules, llm=label)
        if f.ask == "fix" and f.check != "none":
            k = next((i + 1 for i, c in enumerate(shown.fixes) if c.rule == f.check), 0)
            if k:
                return replace(_fix_guide(k, chat_key), input_type=rules.input_type, llm="used")
            row = next((r for r in shown.rows if r.rule == f.check), None)
            if row is not None:
                return Result(evidence.focus_reply(shown, row), "explain", rules.input_type,
                              llm="used")
        body = evidence.format_explain(shown, text,
                                       (f.topic,) if f.topic != "none" else (),
                                       f.check if f.check != "none" else "")
        return Result(body, "explain", rules.input_type, llm="used")
    except Exception:
        return rules


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
