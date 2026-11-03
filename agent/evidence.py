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

from agent import rubric as R
from agent.report import PROFILE_URL, clean, fit, safe_domain
from agent.router import RULE_NAMES

INT_FIELDS = ("total_interactions", "recent_interactions", "recent_verified_interactions",
              "recent_success_verified_interactions")
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
        return "no data" if rate is None else _pct(rate)
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

LEGEND = "Found = the data shows a gap. Tip = no data, general advice."


def _counts(f: dict) -> str:
    return (f"{_count(f['total_interactions'])} total interactions, "
            f"{_count(f['recent_interactions'])} recent, and "
            f"{_count(f['recent_verified_interactions'])} verified chats "
            f"({_count(f['recent_success_verified_interactions'])} succeeded)")


def _topics(text: str, f: dict) -> list[str]:
    out: list[str] = []
    if _T_USERS.search(text):
        out.append("Agentverse's public data has no unique-user count. It shows " + _counts(f) + ".")
    elif _T_INTER.search(text):
        out.append("Agentverse shows " + _counts(f) + ".")
    if _T_SUCCESS.search(text):
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
    if _T_RATING.search(text):
        r = f["rating"]
        out.append(f"Rating {('no data' if r is None else f'{r:g}/5')} is Agentverse's own value "
                   "from recent and total interactions, successful ASI:One chats and evaluations. "
                   "Agentverse doesn't publish the formula.")
    if _T_TESTING.search(text):
        e = f["recent_eval_success_rate"]
        out.append(f"Testing score: {'no data from Agentverse' if e is None else _pct(e)}. "
                   "Agentverse doesn't say when it's empty.")
    return out


def format_explain(shown: Any, text: str) -> str:
    """Explain reply for `shown` (guides.Shown with rows). Topic paragraphs are kept; check
    lines are trimmed from the end; the legend, "how do I fix" line and link always stay."""
    f = shown.facts_dict
    head = [f"**Why {shown.name} scored {shown.total}/100 · {shown.verdict}**",
            "Data: Agentverse public profile + Almanac. Points are our estimate "
            "(weights not published)."]
    topics = _topics(text or "", f)
    if topics:
        head += [""] + [p for t in topics for p in (t, "")][:-1]
    order = list(R.WEIGHTS)
    lost = sorted((r for r in shown.rows if r.kind != "ok"),
                  key=lambda r: (r.kind == "no_data", order.index(r.rule)))
    lines = [f"{'❔' if r.kind == 'no_data' else '❌'} {r.label} {_pts(r.points)}/{_pts(r.max_points)}: "
             f"{r.value} ({'tip' if r.kind == 'no_data' else 'found'})" for r in lost]
    full = [r.label for r in shown.rows if r.kind == "ok"]
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
