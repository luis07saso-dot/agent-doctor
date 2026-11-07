"""Q10 (FB-2): "Why this score?" — the data behind each check. Pure text, no I/O.

- `facts(profile)`: the raw numbers Agentverse gave (None = no data, never shown as 0).
- `rows(lookup, score)`: one evidence row per check (points, kind, raw value).
- `format_explain(shown, text)`: the explain reply for the last audited agent.

Wording rules (docs/specs/q10-why-this-score.md §2): per-agent counts use Agentverse's field
names in plain words ("verified chats"). Only the success-rate definition quotes the docs
(growth-metrics page). In 317 sampled agents the success rate was exactly the 95% Wilson lower
bound of succeeded / verified chats, and null when verified chats were 0.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

from agent import guides
from agent import rubric as R
from agent.report import PROFILE_URL, clean, fit, safe_domain
from agent.router import RULE_NAMES

INT_FIELDS = ("total_interactions", "recent_interactions", "recent_verified_interactions",
              "recent_success_verified_interactions")
TESTING_NONE = "none shared by Agentverse"  # Q21 (FB-6): null eval rate, never "not found"
FLOAT_FIELDS = ("recent_success_rate", "recent_eval_success_rate", "rating")


@dataclass(frozen=True)
class Row:
    rule: str
    label: str
    points: float
    max_points: float
    kind: str  # ok | found | no_data
    value: str


def _int(v: Any) -> Optional[int]:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _float(v: Any) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def facts(profile: Optional[dict]) -> dict:
    p = profile or {}
    out: dict = {k: _int(p.get(k)) for k in INT_FIELDS}
    out.update({k: _float(p.get(k)) for k in FLOAT_FIELDS})
    return out


def _pts(x: float) -> str:
    return f"{x:.1f}".rstrip("0").rstrip(".")


def _count(n: Optional[int]) -> str:
    return "no data" if n is None else f"{n:,}"


def _pct(x: float) -> str:
    return f"{max(0.0, min(1.0, x)):.0%}"


def _value(check: Any, f: dict, lookup: Any) -> str:
    rule = check.rule
    if rule == "active":
        if check.ok:
            both = getattr(lookup, "almanac_status", None) == "ok" and bool(lookup.profile)
            return "active (profile + Almanac)" if both else "active"
        return clean(check.detail)
    if rule == "readme_sections":
        _, _, tail = check.fix.partition(":")
        return check.detail + (f", missing {tail.strip()}" if tail.strip() else "")
    if rule == "success_rate":
        v, k, rate = (f["recent_verified_interactions"], f["recent_success_verified_interactions"],
                      f["recent_success_rate"])
        if rate is None:
            return "no data" + (" (0 verified chats)" if v == 0 else "")
        if v is not None and k is not None:
            return f"{_pct(rate)} ({k:,} of {v:,} verified chats succeeded)"
        return _pct(rate)
    if rule == "eval_rate":
        rate = f["recent_eval_success_rate"]
        return TESTING_NONE if rate is None else _pct(rate)
    if rule == "interactions":
        total, recent = f["total_interactions"], f["recent_interactions"]
        if total is None:
            return "no data"
        return f"{total:,} total" + (f", {recent:,} recent" if recent is not None else "")
    if rule == "website":
        return safe_domain(check.detail) if check.ok else "none"
    return clean(check.detail, 40)


def rows(lookup: Any, sc: Any) -> tuple[Row, ...]:
    f = facts(lookup.profile)
    return tuple(Row(c.rule, RULE_NAMES[c.rule], c.points, c.max_points, c.kind,
                     _value(c, f, lookup)) for c in sc.checks)


# ---------- explain reply ----------

_T_USERS = re.compile(r"\bunique users?\b|\bhow many (?:unique )?(?:users|people)\b|\busers?\b", re.I)
_T_INTER = re.compile(r"\binteractions?\b|\bchats?\b|\bconversations?\b", re.I)
_T_SUCCESS = re.compile(r"\bsuccess\w*|\basi:?\s?one\b|\basi1\b", re.I)
_T_RATING = re.compile(r"\brating\b|\brated\b|\bstars?\b", re.I)
_T_TESTING = re.compile(r"\btest(?:ing|s)?\b|\bevals?\b|\bevaluations?\b", re.I)

LEGEND = "Found = the data shows a gap. Not scored = no data from Agentverse, or optional."


def _counts(f: dict) -> str:
    return (f"{_count(f['total_interactions'])} total interactions, "
            f"{_count(f['recent_interactions'])} recent, and "
            f"{_count(f['recent_verified_interactions'])} verified chats "
            f"({_count(f['recent_success_verified_interactions'])} succeeded)")


TOPIC_ORDER = ("users", "interactions", "success", "rating", "testing")


def topics(text: str) -> list[str]:
    """Topic keys a question asks about (regex). Q11 adds the LLM's pick to these."""
    out: list[str] = []
    if _T_USERS.search(text or ""):
        out.append("users")
    elif _T_INTER.search(text or ""):
        out.append("interactions")
    for key, rx in (("success", _T_SUCCESS), ("rating", _T_RATING), ("testing", _T_TESTING)):
        if rx.search(text or ""):
            out.append(key)
    return out


def _topics(text: str, f: dict, extra: tuple[str, ...] = ()) -> list[str]:
    keys = set(topics(text)) | {k for k in extra if k in TOPIC_ORDER}
    if "users" in keys:
        keys.discard("interactions")  # the users paragraph already gives the counts
    out: list[str] = []
    if "users" in keys:
        out.append("Agentverse's public data has no unique-user count. It shows " + _counts(f) + ".")
    elif "interactions" in keys:
        out.append("Agentverse shows " + _counts(f) + ".")
    if "success" in keys:
        v, k, rate = (f["recent_verified_interactions"], f["recent_success_verified_interactions"],
                      f["recent_success_rate"])
        s = ("Success rate: Agentverse docs call it a rolling 30-day Wilson score over the "
             "agent's ASI:One conversations (chats started by other agents count). ")
        if v is not None and k is not None:
            s += f"Its value matches {k:,} succeeded of {v:,} verified chats. "
        if rate is not None:
            s += f"Rate {_pct(rate)}."
        elif v == 0:
            s += "No rate yet: 0 verified chats, so it's no data, not 0%."
        else:
            s += "No rate from Agentverse yet (no data, not 0%)."
        out.append(s)
    if "rating" in keys:
        r = f["rating"]
        out.append(f"Rating {('no data' if r is None else f'{r:g}/5')} is Agentverse's own value "
                   "from recent and total interactions, successful ASI:One chats and evaluations. "
                   "Agentverse doesn't publish the formula.")
    if "testing" in keys:
        e = f["recent_eval_success_rate"]
        if e is None:  # Q21 (FB-6): never "not found"; the owner's Testing tab may have runs
            out.append("Testing score: Agentverse shares no recent Testing result for this agent "
                       "(most agents we checked have none). It doesn't say which runs it shares "
                       "or when, so your Testing tab may still have runs. It isn't counted "
                       "in your score until Agentverse shares one.")
        else:
            out.append(f"Testing score: {_pct(e)}. Agentverse doesn't say which runs it counts.")
    return out


_UNSCORED = {"no_data": "not scored", "optional": "optional, not scored"}


def row_line(r: Row) -> str:
    """One evidence line: "❌ Rating 1.2/10: 1.8/5 (found)"."""
    if r.kind == "ok":
        return f"✅ {r.label} {_pts(r.points)}/{_pts(r.max_points)}: {r.value} (full marks)"
    if r.kind in _UNSCORED:  # Q21: 0 of 0 points, so no points shown
        return f"{'❔' if r.kind == 'no_data' else '➕'} {r.label}: {r.value} ({_UNSCORED[r.kind]})"
    return (f"{'❔' if r.kind == 'no_data' else '❌'} {r.label} {_pts(r.points)}/{_pts(r.max_points)}: "
            f"{r.value} ({'tip' if r.kind == 'no_data' else 'found'})")


def format_explain(shown: Any, text: str, extra_topics: tuple[str, ...] = (),
                   focus: str = "") -> str:
    """Explain reply for `shown` (guides.Shown with rows). Topic paragraphs are kept; check
    lines are trimmed from the end; the legend, "how do I fix" line and link always stay.
    Q11: `extra_topics` (the LLM's topic pick) and `focus` (a check id, its line first).
    Defaults give exactly the Q10 reply."""
    f = shown.facts_dict
    head = [f"**Why {shown.name} scored {shown.total}/100 · {shown.verdict}**",
            "Data: Agentverse public profile + Almanac. Points are our estimate "
            "(weights not published). Keywords are private, so not scored."]
    topics_ = _topics(text or "", f, tuple(extra_topics))
    focus_row = next((r for r in shown.rows if r.rule == focus), None) if focus else None
    if focus_row is not None:
        topics_ = [row_line(focus_row)] + topics_
    if topics_:
        head += [""] + [p for t in topics_ for p in (t, "")][:-1]
    order = list(R.WEIGHTS)
    lost = sorted((r for r in shown.rows if r.kind != "ok" and r is not focus_row),
                  key=lambda r: (r.kind in _UNSCORED, order.index(r.rule)))
    lines = [row_line(r) for r in lost]
    full = [r.label for r in shown.rows if r.kind == "ok" and r is not focus_row]
    if full:
        lines.append("✅ Full marks: " + ", ".join(full))
    footer = f"\n\n{LEGEND} Ask \"how do I fix #1\" for steps."
    if shown.address:
        footer += f"\n\n[Open profile on Agentverse]({PROFILE_URL.format(address=shown.address)})"
    # Two trailing spaces = Markdown hard break: ASI:One joins single-newline lines into one
    # paragraph otherwise (same trick as report.format_report).
    head[0] += "  "
    body = "\n".join(head + [""] + [ln + "  " for ln in lines[:-1]] + lines[-1:])
    return fit(body, footer)  # always <= MAX_CHARS


def focus_reply(shown: Any, row: Row) -> str:
    """Q11: "how do I improve my avatar?" when that check isn't one of the top 3 fixes. Built
    from the remembered audit row and fixed How texts only."""
    if row.kind == "ok":
        body = f"**{row.label}** for {shown.name}: full marks ({row.value}), nothing to fix."
    elif row.kind in _UNSCORED:
        how = guides.SHORT.get(row.rule) or guides.README_HOW
        body = (f"**{row.label}** for {shown.name}: {row.value} ({_UNSCORED[row.kind]}). "
                f"It doesn't change the score.\n\n{how}")
    else:
        how = guides.SHORT.get(row.rule) or guides.README_HOW
        body = (f"**{row.label}** for {shown.name}: {_pts(row.points)}/{_pts(row.max_points)}, "
                f"{row.value} ({'tip' if row.kind == 'no_data' else 'found'}).\n\n{how}")
    footer = "\n\nAsk \"why this score?\" for every check."
    if shown.address:
        footer += f"\n\n[Open profile on Agentverse]({PROFILE_URL.format(address=shown.address)})"
    return fit(body, footer)
