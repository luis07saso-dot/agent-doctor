"""L4 report formatter: Score + Lookup -> Markdown chat reply, always <= MAX_CHARS."""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from agent.scorer import UNRESPONSIVE_FLAG, Score

MAX_CHARS = 1500
TOP_FIXES = 3
PROFILE_URL = "https://agentverse.ai/agents/details/{address}/profile"
PROBE_WAIT_S = 14  # agent/probe.py PROBE_TIMEOUT_S, for wording only (report stays I/O-free)
_UNSAFE = re.compile(r"[\r\n`*_\[\]<>|#~\\]+")
_LINKISH = re.compile(r"\S*(?:://|www\.)\S*", re.IGNORECASE)
_DOMAIN = re.compile(r"^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


def clean(text: Any, limit: int = 60) -> str:
    """Untrusted profile text -> one short plain line: no Markdown control chars, no links,
    no control/format chars (bidi overrides, zero-width)."""
    s = "".join(" " if unicodedata.category(ch) == "Cc" else ch for ch in str(text or "")
                if unicodedata.category(ch) != "Cf")
    s = _LINKISH.sub(" ", s)
    s = _UNSAFE.sub(" ", s).strip()
    s = re.sub(r"\s+", " ", s)
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"


def safe_domain(value: Any) -> str:
    d = str(value or "").strip().lower()
    return d if _DOMAIN.match(d) else "set"


def short_address(address: str | None) -> str:
    if not address:
        return "unknown address"
    return f"{address[:10]}…{address[-5:]}"


def _mark(ok: bool) -> str:
    return "✅" if ok else "❌"


def _pts(x: float) -> str:
    return f"{x:.1f}".rstrip("0").rstrip(".")


def format_report(lookup: Any, sc: Score, live: Any = None) -> str:
    """`live` (Q2): ProbeResult of a live check, "pending" if it didn't finish in time, or
    None (not run). Only used when Agentverse flags the agent unresponsive."""
    profile = lookup.profile or {}
    name = clean(profile.get("name")) or "Unnamed agent"
    handle = profile.get("handle")
    ident = f"@{clean(handle, 25)}" if handle else short_address(lookup.address)

    lines = [
        f"**Agent Doctor: {name}** ({ident})",
        f"**Score {sc.total}/100 · {sc.verdict}**",
    ]
    if getattr(lookup, "profile_status", None) == "not_found":
        lines.append("_Not in the Agentverse search index, so users can't find it. "
                     "Publish a profile (README + description) and keep it online._")
    for note in getattr(lookup, "notes", ()) or ():
        if note.startswith("almanac "):
            lines.append("_Almanac check failed, so status comes from the profile only._")
        elif note.startswith("profile "):
            lines.append("_Profile lookup failed, so most checks show as missing. Try again later._")

    c = sc.check
    flagged = c("responsive").detail == UNRESPONSIVE_FLAG
    if flagged:
        # No "@" in the follow-up: on ASI:One "@other" routes the message to the other agent.
        ask = clean(handle, 25) if handle else (lookup.address or "")
        lines.append(_flag_note(profile, live, ask))

    fixes = sc.fixes[:TOP_FIXES]
    if fixes:
        lines += ["", "**Top fixes**"]
        lines += [f"{i}. {c.fix} (+{_pts(c.lost)} pts)" for i, c in enumerate(fixes, 1)]
    else:
        lines += ["", "No fixes needed. Keep it online and answering."]

    lines += [
        "",
        "**Details**",
        " · ".join([
            f"{_mark(c('active').ok)} Active",
            f"{_mark(c('chat_protocol').ok)} Chat Protocol",
            f"{_mark(c('handle').ok)} Handle",
            f"{_mark(c('avatar').ok)} Avatar",
            f"{_mark(c('description').ok)} Description",
            "⚠️ Agentverse flag: unresponsive" if flagged
            else f"{_mark(c('responsive').ok)} Responsive",
        ]),
        f"README: {c('readme').detail}, {c('readme_sections').detail} · "
        f"Rating {c('rating').detail} · Interactions {c('interactions').detail}",
        f"ASI:One success: {c('success_rate').detail} · Testing: {c('eval_rate').detail} · "
        f"Website: {safe_domain(c('website').detail) if c('website').ok else 'none'} · Starter prompts: {c('starter_prompts').detail}",
        "",
        "_Keywords are private, so not scored: make sure each appears in your README. "
        "Weights are our estimate; Agentverse doesn't publish them._",
    ]
    if lookup.address:
        lines.append(f"[Open profile]({PROFILE_URL.format(address=lookup.address)}) · "
                     "Re-check any time after changes.")
    return fit("\n".join(lines))


def _flag_note(profile: dict, live: Any = None, ask: str = "") -> str:
    """FB-1: the unresponsive flag is Agentverse's data, not our test. Say so, say why it's
    set and how it clears, and give the success-rate context. Q2: if we ran a live check,
    say what it found instead of "We did not test it"."""
    status = live if isinstance(live, str) else getattr(live, "status", None)
    head = "_Agentverse's own data flags this agent \"unresponsive\". "
    why = "Agentverse sets it when a chat with the agent times out; the next reply clears it."
    if status == "live":
        reply_ms = getattr(live, "reply_ms", None)
        took = f" in {reply_ms / 1000:.1f}s" if isinstance(reply_ms, (int, float)) else ""
        note = (head + f"Our live check just got a reply{took}, so the flag looks out of date. "
                "It should clear after the agent's next answered chat.")
    elif status == "degraded":
        note = (head + f"Our live check: it acknowledged but sent no answer within "
                f"{PROBE_WAIT_S}s. Slow or missing answers are what set the flag.")
    elif status == "unreachable":
        note = (head + f"Our live check got no reply within {PROBE_WAIT_S}s, so the flag "
                "looks right. Check the agent is running and its mailbox is connected.")
    elif status == "pending":
        note = (head + why + " Our live check is still running: ask "
                f"\"is {ask or 'this agent'} live?\" in a minute.")
    else:
        note = head + "We did not test it. " + why
    rate = profile.get("recent_success_rate")
    if isinstance(rate, (int, float)) and not isinstance(rate, bool):
        note += f" Recent ASI:One success rate: {max(0.0, min(1.0, float(rate))):.0%}."
    return note + "_"


def fit(text: str, footer: str = "") -> str:
    """Keep text + footer within MAX_CHARS. Drops whole trailing lines first, so links and
    Markdown are not cut mid-way; hard-cuts only as a last resort."""
    budget = MAX_CHARS - len(footer)
    lines = text.split("\n")
    while len("\n".join(lines)) > budget and len(lines) > 3:
        lines.pop()
    body = "\n".join(lines)
    if len(body) > budget:
        body = body[: max(0, budget - 1)].rstrip() + "…"
    return (body + footer)[:MAX_CHARS]
