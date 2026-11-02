"""L3 scorer: pure function of a Lookup. Same input -> same output. No I/O.

Input: `agentverse.Lookup` (or anything with .profile/.almanac/.almanac_status).
Output: Score with 0-100 total, verdict, one Check per rule, and fixes ranked by
points lost (ties: rubric order).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from agent import rubric as R

_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")


@dataclass(frozen=True)
class Check:
    rule: str
    points: float
    max_points: float
    ok: bool  # full marks
    detail: str  # short, user-facing ("4.5/5", "missing", ...)
    fix: str  # what to do; empty when ok

    @property
    def lost(self) -> float:
        return round(self.max_points - self.points, 2)


@dataclass(frozen=True)
class Score:
    total: int
    verdict: str
    down: bool
    indexed: bool  # profile found in the search index
    checks: tuple[Check, ...]

    @property
    def fixes(self) -> tuple[Check, ...]:
        order = list(R.WEIGHTS)
        bad = [c for c in self.checks if c.lost > 0]
        readme = self.check("readme")
        if readme.points == 0:  # no README: one fix covers both README rules
            sections = self.check("readme_sections")
            bad = [c for c in bad if c.rule not in ("readme", "readme_sections")]
            bad.append(Check("readme", 0.0, readme.max_points + sections.max_points, False,
                             readme.detail, "Write a Markdown README with sections: "
                             + ", ".join(R.README_SECTIONS)))
        # Offline trumps everything: inactive agents are excluded from ranking entirely.
        return tuple(sorted(bad, key=lambda c: (c.rule != "active", -c.lost, order.index(c.rule))))

    def check(self, rule: str) -> Check:
        return next(c for c in self.checks if c.rule == rule)


def score(lookup: Any) -> Score:
    profile: dict = lookup.profile or {}
    almanac: dict = lookup.almanac or {}
    indexed = bool(lookup.profile)
    almanac_known = getattr(lookup, "almanac_status", None) in ("ok", "not_found")

    active = _is_active(profile, almanac, almanac_known, indexed)
    checks = [
        _active(active, profile, almanac, almanac_known),
        _chat_protocol(profile, almanac),
        _readme_sections(profile.get("readme")),
        _readme(profile.get("readme")),
        _rating(profile.get("rating")),
        _description(profile.get("description")),
        _responsive(active, profile.get("unresponsive")),
        _handle(profile.get("handle")),
        _avatar(profile.get("avatar_href")),
        _interactions(profile.get("total_interactions")),
        _rate("success_rate", profile.get("recent_success_rate"),
              "Get real users chatting via ASI:One; answer every in-scope question well",
              "none yet"),
        _rate("eval_rate", profile.get("recent_eval_success_rate"),
              "Run Agentverse Testing (Testing tab) with real in-scope questions",
              "none yet"),
        _website(profile.get("domain")),
        _starter_prompts(profile.get("starter_prompts")),
    ]
    assert [c.rule for c in checks] == list(R.WEIGHTS)
    total = int(round(sum(c.points for c in checks)))
    total = max(0, min(100, total))
    down = not active
    verdict = R.DOWN_VERDICT if down else next(v for m, v in R.VERDICTS if total >= m)
    return Score(total=total, verdict=verdict, down=down, indexed=indexed, checks=tuple(checks))


# ---------- rules ----------

def _w(rule: str) -> float:
    return float(R.WEIGHTS[rule])


def _mk(rule: str, frac: float, detail: str, fix: str) -> Check:
    frac = max(0.0, min(1.0, frac))
    pts = round(_w(rule) * frac, 2)
    ok = pts >= _w(rule)
    return Check(rule, pts, _w(rule), ok, detail, "" if ok else fix)


def _is_active(profile: dict, almanac: dict, almanac_known: bool, indexed: bool) -> bool:
    # Anything other than "active" counts as down (almanac uses "offline", search "inactive").
    if almanac_known:
        if almanac.get("status") != "active":
            return False
        return profile.get("status") == "active" if indexed else True
    return profile.get("status") == "active"


def _active(active: bool, profile: dict, almanac: dict, almanac_known: bool) -> Check:
    if active:
        return _mk("active", 1, "active", "")
    if almanac_known and not almanac:
        detail = "not registered in the Almanac"
    else:
        detail = str(almanac.get("status") or profile.get("status") or "unknown")
    return _mk("active", 0, detail,
               "Bring the agent online and keep it running (inactive agents are excluded from ranking)")


def _chat_protocol(profile: dict, almanac: dict) -> Check:
    names = {(p or {}).get("name") for p in profile.get("protocols") or [] if isinstance(p, dict)}
    digests = {str((p or {}).get("digest", "")).removeprefix("proto:")
               for p in profile.get("protocols") or [] if isinstance(p, dict)}
    digests |= {str(d).removeprefix("proto:") for d in almanac.get("protocols") or []}
    has = R.CHAT_PROTOCOL_NAME in names or R.CHAT_PROTOCOL_DIGEST in digests
    return _mk("chat_protocol", 1 if has else 0, "yes" if has else "missing",
               "Add the Agent Chat Protocol (agent.include(chat_proto, publish_manifest=True))")


def readme_sections_found(readme: str | None) -> list[str]:
    """README guideline sections present, in rubric order."""
    text = readme or ""
    headings = []
    intro_chars = 0
    seen_section = False
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence:
            continue  # "# comment" lines in code blocks are not headings
        m = _HEADING.match(line)
        if m:
            headings.append(m.group(1).lower())
            if len(headings) > 1:
                seen_section = True
        elif not seen_section:
            intro_chars += len(line.strip())
    found = []
    for section, phrases in R.README_SECTIONS.items():
        hit = any(re.search(r"(?<![a-z0-9])" + re.escape(p), h) for h in headings for p in phrases)
        if section == "Summary" and not hit:
            hit = intro_chars >= R.SUMMARY_INTRO_MIN_CHARS
        if hit:
            found.append(section)
    return found


def _readme_sections(readme: str | None) -> Check:
    found = readme_sections_found(readme)
    missing = [s for s in R.README_SECTIONS if s not in found]
    n = len(R.README_SECTIONS)
    return _mk("readme_sections", len(found) / n, f"{len(found)}/{n} sections",
               "Add README sections: " + ", ".join(missing))


def _readme(readme: str | None) -> Check:
    n = len((readme or "").strip())
    if n == 0:
        return _mk("readme", 0, "missing", "Write a Markdown README (it is the main search document)")
    if n < R.README_MIN_CHARS:
        return _mk("readme", R.README_SHORT_POINTS / _w("readme"), f"{n} chars",
                   f"Expand the README to at least {R.README_MIN_CHARS} characters of plain description")
    return _mk("readme", 1, f"{n} chars", "")


def _rating(rating: Any) -> Check:
    r = rating if isinstance(rating, (int, float)) and not isinstance(rating, bool) else 0.0
    r = max(0.0, min(R.RATING_MAX, float(r)))
    return _mk("rating", r / R.RATING_MAX, f"{r:g}/{R.RATING_MAX:g}",
               "Raise rating: pass Agentverse Testing runs and get real ASI:One users")


def _description(desc: Any) -> Check:
    n = len(desc.strip()) if isinstance(desc, str) else 0
    if n == 0:
        return _mk("description", 0, "missing", "Add a one-line Agent Description")
    if n < R.DESCRIPTION_MIN_CHARS:
        return _mk("description", R.DESCRIPTION_SHORT_POINTS / _w("description"), f"{n} chars",
                   "Make the description say what the agent does and for whom")
    return _mk("description", 1, f"{n} chars", "")


def _responsive(active: bool, unresponsive: Any) -> Check:
    if not active:
        return _mk("responsive", 0, "offline", "Answer every message (offline agents time out)")
    if unresponsive is True:
        return _mk("responsive", 0, "flagged unresponsive",
                   "Reply to every message: a timed-out conversation flagged it unresponsive")
    return _mk("responsive", 1, "ok", "")


def _handle(handle: Any) -> Check:
    if isinstance(handle, str) and 0 < len(handle) <= R.HANDLE_MAX_CHARS:
        return _mk("handle", 1, f"@{handle}", "")
    return _mk("handle", 0, "none", "Set a custom @handle (max 20 chars) close to the agent's job")


def _avatar(href: Any) -> Check:
    has = isinstance(href, str) and bool(href.strip())
    return _mk("avatar", 1 if has else 0, "yes" if has else "missing", "Upload an avatar")


def _interactions(total: Any) -> Check:
    n = total if isinstance(total, int) and not isinstance(total, bool) else 0
    return _mk("interactions", 1 if n >= R.MIN_INTERACTIONS else 0, f"{n:,}",
               f"Reach {R.MIN_INTERACTIONS}+ interactions (run Testing; share with real users)")


def _rate(rule: str, value: Any, fix: str, none_detail: str) -> Check:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return _mk(rule, 0, none_detail, fix)
    v = max(0.0, min(1.0, float(value)))
    return _mk(rule, v, f"{v:.0%}", fix)


def _website(domain: Any) -> Check:
    has = isinstance(domain, str) and bool(domain.strip())
    return _mk("website", 1 if has else 0, domain if has else "none",
               "Verify a website domain (Verifications tab, DNS TXT record)")


def _starter_prompts(prompts: Any) -> Check:
    n = len([p for p in prompts if isinstance(p, str) and p.strip()]) if isinstance(prompts, list) else 0
    return _mk("starter_prompts", 1 if n else 0, str(n),
               "Add 2-4 starter prompts that match your README")
