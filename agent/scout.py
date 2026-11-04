"""Q13 Agent Scout: "find me an agent that books flights". Spec: docs/specs/q13-agent-scout.md.

Agentverse search (active, responsive, Chat Protocol) -> top 5 in search order -> full audit
score each (lookup; profile-only "~" if slow) -> drop agents the audit calls down -> live-probe
the first 2 (SCOPE A2) -> pick one. Never imports agent.service (service imports this).
The phrase is never logged or stored here; lists keep addresses and names only.
"""
from __future__ import annotations

import asyncio
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, replace
from typing import Any, Awaitable, Callable, Iterable, Optional

from agent.agentverse import Lookup
from agent.report import PROFILE_URL, clean, fit, short_address
from agent.scorer import score

TOP_N = 5
PROBE_N = 2
SEARCH_WAIT_S = 6.0
LOOKUP_WAIT_S = 3.0
MARGIN_S = 1.5  # stop waiting this long before the reply deadline (send + format time)
MIN_PROBE_S = 1.0  # less than this left: start the probes, don't wait for them
SENDER_PROBED_PER_HOUR = 6  # scout searches with live tests per sender per rolling hour
GLOBAL_PROBES_PER_MIN = 12  # scout probes to third-party agents, all senders
CAPS_MAX_SENDERS = 2000
LIST_TTL_S = 24 * 3600.0
LIST_MAX = 500
PENDING = "pending"

ProbeFn = Callable[[str], Awaitable[Any]]


@dataclass(frozen=True)
class Cand:
    rank: int  # 1-based position in Agentverse search (after own agent removed)
    address: str
    name: str
    total: int
    profile_only: bool  # score from the search hit only (lookup slow or failed)
    rating: Optional[float] = None
    interactions: Optional[int] = None
    probe: Any = None  # ProbeResult | PENDING | None (not tested)


@dataclass(frozen=True)
class ScoutResult:
    status: str  # ok | none | timeout | api_down
    phrase: str
    cands: tuple[Cand, ...] = ()
    pick: int = 0  # 1-based index into cands, 0 = no pick
    pick_kind: str = ""  # live | pending | untested | none
    skipped_down: int = 0
    capped: bool = False  # live tests skipped by the probe caps

    @property
    def probed(self) -> int:
        return sum(c.probe is not None for c in self.cands)

    @property
    def live(self) -> int:
        return sum(_st(c.probe) == "live" for c in self.cands)


def _st(p: Any) -> str:
    if p is None:
        return ""
    if p == PENDING:
        return PENDING
    return str(getattr(p, "status", "") or "")


def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


# ---------- caps (SCOPE A2: bounded probing of unnamed agents) ----------

class Caps:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._senders: OrderedDict[str, deque] = OrderedDict()
        self._global: deque = deque()

    def allow(self, sender_key: str, n: int) -> bool:
        """Record and allow `n` scout probes for this sender, or refuse (no probes at all)."""
        now = self._clock()
        while self._global and now - self._global[0] >= 60.0:
            self._global.popleft()
        q = self._senders.get(sender_key)
        if q is None:
            q = deque()
        while q and now - q[0] >= 3600.0:
            q.popleft()
        if len(q) >= SENDER_PROBED_PER_HOUR or len(self._global) + n > GLOBAL_PROBES_PER_MIN:
            return False
        q.append(now)
        self._senders[sender_key] = q
        self._senders.move_to_end(sender_key)
        while len(self._senders) > CAPS_MAX_SENDERS:
            self._senders.popitem(last=False)
        self._global.extend([now] * n)
        return True


CAPS = Caps()


# ---------- last list per chat (for "audit #2") ----------

class Lists:
    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._d: OrderedDict[str, tuple[float, str, tuple[tuple[str, str], ...]]] = OrderedDict()

    def put(self, chat_key: str, sender_key: str, items: Iterable[tuple[str, str]]) -> None:
        items = tuple(items)
        if not chat_key or not items:
            return
        self._d[chat_key] = (self._clock() + LIST_TTL_S, sender_key, items)
        self._d.move_to_end(chat_key)
        while len(self._d) > LIST_MAX:
            self._d.popitem(last=False)

    def get(self, chat_key: str) -> Optional[tuple[tuple[str, str], ...]]:
        hit = self._d.get(chat_key)
        if hit is None:
            return None
        if self._clock() >= hit[0]:
            self._d.pop(chat_key, None)
            return None
        return hit[2]

    def drop_sender(self, sender_key: str, chat_key: str = "") -> None:
        """`forget`: every list of this sender, plus this chat's."""
        for k in [k for k, v in self._d.items() if (sender_key and v[1] == sender_key) or k == chat_key]:
            self._d.pop(k, None)


LISTS = Lists()


# ---------- core ----------

def _retrieve(t: "asyncio.Future") -> None:
    if not t.cancelled():
        t.exception()


def _name(hit: dict, address: str) -> str:
    n = clean(hit.get("name"), 30).replace("@", "").strip()
    return n or short_address(address)


def candidates(hits: Iterable[Any], self_addresses: Iterable[str] = (),
               self_handles: Iterable[str] = ()) -> list[tuple[int, dict]]:
    """(rank, hit) for the first TOP_N hits that aren't Doctor itself or duplicates."""
    own_a = {a.lower() for a in self_addresses if a}
    own_h = {h.lstrip("@").lower() for h in self_handles if h}
    out: list[tuple[int, dict]] = []
    seen: set[str] = set()
    for h in hits:
        if not isinstance(h, dict):
            continue
        a = str(h.get("address") or "").lower()
        handle = str(h.get("handle") or "").lower()
        if not a or a in own_a or a in seen or (handle and handle in own_h):
            continue
        seen.add(a)
        out.append((len(out) + 1, h))
        if len(out) == TOP_N:
            break
    return out


def _cand(rank: int, hit: dict, lk: Optional[Lookup]) -> Optional[Cand]:
    """Full audit score when the lookup worked, else profile-only. None = the audit says down."""
    address = str(hit.get("address") or "")
    full = (lk is not None and lk.outcome in ("ok", "partial") and bool(lk.profile)
            and lk.profile_status not in ("timeout", "api_down"))
    if full:
        sc = score(lk)
        if sc.down:
            return None
        prof = lk.profile or {}
    else:
        sc = score(Lookup(query=address, outcome="ok", address=address, profile=hit,
                          profile_status="ok"))
        prof = hit
    rating = prof.get("rating")
    inter = prof.get("total_interactions")
    return Cand(rank, address, _name(prof, address), sc.total, not full,
                float(rating) if _num(rating) else None,
                inter if isinstance(inter, int) and not isinstance(inter, bool) else None)


FAILED = ("unreachable", "degraded")


def _choose(cands: list[Cand]) -> tuple[int, str]:
    """Live: the higher score of those that answered. Else the first still being tested.
    (0, "none") when every agent tested really failed (unreachable / degraded). Else the first
    not shown to fail ("untested": busy, capped or not probed)."""
    live = [c for c in cands if _st(c.probe) == "live"]
    if live:
        best = max(live, key=lambda c: (c.total, -c.rank))
        return cands.index(best) + 1, "live"
    for i, c in enumerate(cands):
        if _st(c.probe) == PENDING:
            return i + 1, "pending"
    tested = [c for c in cands if c.probe is not None]
    if tested and all(_st(c.probe) in FAILED for c in tested):
        return 0, "none"  # the top ones really failed; the rest are suggested, not picked
    for i, c in enumerate(cands):
        if _st(c.probe) not in FAILED:
            return i + 1, "untested"
    return 0, "none"


async def run(phrase: str, client: Any, probe: Optional[ProbeFn], deadline: float,
              self_addresses: Iterable[str] = (), self_handles: Iterable[str] = (),
              sender_key: str = "", clock: Callable[[], float] = time.monotonic,
              caps: Optional[Caps] = None) -> ScoutResult:
    """Never raises once the search worked: a later error returns the list built so far."""
    caps = caps or CAPS

    def left() -> float:
        return deadline - MARGIN_S - clock()

    if not hasattr(client, "scout_search"):
        return ScoutResult("api_down", phrase)
    task = asyncio.ensure_future(client.scout_search(phrase))
    wait = min(SEARCH_WAIT_S, left())
    done, _ = await asyncio.wait({task}, timeout=max(0.0, wait))
    if not done:
        task.add_done_callback(_retrieve)  # keeps running, fills the cache
        return ScoutResult("timeout", phrase)
    try:
        st, hits = task.result()
    except Exception:
        return ScoutResult("api_down", phrase)
    if st != "ok":
        return ScoutResult("timeout" if st == "timeout" else "api_down", phrase)
    try:
        picked = candidates(hits, self_addresses, self_handles)
        if not picked:
            return ScoutResult("none", phrase)
        # Static list first: any later error still returns it.
        cands: list[Cand] = [c for c in (_cand(r, h, None) for r, h in picked) if c is not None]
    except Exception:  # odd search data: a scout reply, never the generic fallback
        return ScoutResult("api_down", phrase)
    res = ScoutResult("ok", phrase, tuple(cands), 1 if cands else 0, "untested" if cands else "none")
    try:
        # Lookups: same score as an audit (Almanac included, spec F14).
        tasks = [asyncio.ensure_future(client.lookup(str(h.get("address")))) for _, h in picked]
        if left() > 0:
            await asyncio.wait(tasks, timeout=min(LOOKUP_WAIT_S, left()))
        cands = []
        down = 0
        for (r, h), t in zip(picked, tasks):
            lk = None
            if t.done() and not t.cancelled() and t.exception() is None:
                lk = t.result()
            else:
                t.add_done_callback(_retrieve)
            c = _cand(r, h, lk)
            if c is None:
                down += 1
            else:
                cands.append(c)
        if not cands:
            return ScoutResult("none", phrase, skipped_down=down)
        res = ScoutResult("ok", phrase, tuple(cands), 1, "untested", down)

        # Live tests: first PROBE_N in search order (SCOPE A2), within the caps.
        top = cands[:PROBE_N]
        capped = False
        if probe is not None and top:
            if not caps.allow(sender_key, len(top)):
                capped = True
            else:
                ptasks = [asyncio.ensure_future(probe(c.address)) for c in top]
                if left() >= MIN_PROBE_S:
                    await asyncio.wait(ptasks, timeout=left())
                else:
                    await asyncio.sleep(0)
                for i, t in enumerate(ptasks):
                    if t.done() and not t.cancelled() and t.exception() is None:
                        cands[i] = replace(cands[i], probe=t.result())
                    else:
                        if not t.done():
                            t.add_done_callback(_retrieve)
                        cands[i] = replace(cands[i], probe=PENDING if not t.done() else None)
        n, kind = _choose(cands)
        return ScoutResult("ok", phrase, tuple(cands), n, kind, down, capped)
    except Exception:
        return res


# ---------- reply ----------

def _secs(p: Any) -> str:
    ms = getattr(p, "reply_ms", None)
    return f"{ms / 1000:.1f} s" if isinstance(ms, int) else ""


def _status(p: Any) -> str:
    st = _st(p)
    if st == "live":
        s = _secs(p)
        return f"✅ answered{' in ' + s if s else ''}" + (" (checked <10 min ago)"
                                                          if getattr(p, "cached", False) else "")
    if st == PENDING:
        return "⏳ still checking"
    if st == "degraded":
        return "⚠️ got it, no answer"
    if st == "unreachable":
        return "❌ no answer"
    return "not tested"


def _facts(c: Cand) -> list[str]:
    out = []
    if c.rating is not None:
        out.append(f"★{c.rating:g}")
    if c.interactions is not None:
        out.append(f"{c.interactions:,} chats")
    return out


def _line(i: int, c: Cand) -> str:
    sc = f"{'~' if c.profile_only else ''}{c.total}/100"
    return " · ".join([f"{i}. {c.name}: {sc}", _status(c.probe)] + _facts(c))


def _pick_text(res: ScoutResult) -> str:
    cands = res.cands
    if res.pick_kind == "none":
        nxt = next((i + 1 for i, c in enumerate(cands) if c.probe is None), 0)
        if nxt:
            return (f"Neither of the top {res.probed} answered my test message. "
                    f"#{nxt} {cands[nxt - 1].name} is next, not tested: ask `is #{nxt} live?`")
        return "None of these answered my test message. Try other words."
    c = cands[res.pick - 1]
    link = f"[{c.name}]({PROFILE_URL.format(address=c.address)})"
    bits = []
    if c.profile_only:
        bits.append(f"profile ~{c.total}/100")
    else:
        bits.append(f"profile {c.total}/100")
    if c.rating is not None:
        bits.append(f"rated {c.rating:g}")
    if c.interactions is not None:
        bits.append(f"{c.interactions:,} chats")
    facts = ", ".join(bits)
    facts = facts[0].upper() + facts[1:]
    if res.pick_kind == "live":
        s = _secs(c.probe)
        when = " (checked <10 min ago)" if getattr(c.probe, "cached", False) else ""
        why = f"answered my test message{' in ' + s if s else ''}{when}"
        if res.live >= 2:
            why += ", the higher profile score of the ones that answered"
        return f"**Pick: {link}**: {why}. {facts}."
    if res.pick_kind == "pending":
        return (f"**Likely pick: {link}**: live test still running, ask `is #{res.pick} live?` "
                f"in a minute. {facts}.")
    return f"**Likely pick: {link}**: top search match, not tested live. {facts}."


def format_reply(res: ScoutResult) -> str:
    q = clean(res.phrase, 60).replace('"', "")
    if res.status in ("timeout", "api_down"):
        return "Agentverse search isn't answering right now. Please try again in a minute."
    if res.status == "none" or not res.cands:
        extra = (f" ({res.skipped_down} matched but are offline in the Almanac.)"
                 if res.skipped_down else "")
        return (f"No active agent with the Chat Protocol matched \"{q}\" on Agentverse.{extra} "
                "Try fewer or other words, e.g. `find an agent that books flights`.")
    head = (f"**Agent Scout**: searched Agentverse for \"{q}\" "
            "(active, responsive, Chat Protocol).")
    lines = [_line(i + 1, c) for i, c in enumerate(res.cands)]
    if res.skipped_down:
        lines.append(f"({res.skipped_down} more skipped: offline in the Almanac)")
    body = "\n\n".join([head, _pick_text(res), "\n".join(ln + "  " for ln in lines[:-1])
                        + ("\n" if len(lines) > 1 else "") + lines[-1]])
    note = ("Order = Agentverse search relevance. Profile score = how well the listing follows "
            "Agentverse ranking signals, not answer quality")
    note += " (~ = profile only)." if any(c.profile_only for c in res.cands) else "."
    note += (" Live tests skipped: many searches just now, ask `is #1 live?`." if res.capped
             else f" I test the top {PROBE_N} live.")
    second = 2 if len(res.cands) >= 2 else 1
    footer = (f"\n\n{note}\n\nNext: `audit #{second}` full report · "
              f"`is #{min(3, len(res.cands))} live?` Pre-Hire Check")
    return fit(body, footer)


def items(res: ScoutResult) -> tuple[tuple[str, str], ...]:
    return tuple((c.address, c.name) for c in res.cands)
