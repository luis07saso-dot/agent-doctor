"""Q15 re-check diff: what changed since the last check of the same agent. Pure, no I/O.

Wording never says "your": the key is a hashed ASI:One sender, and whether ASI:One relays
many people under one sender is unverified (spec docs/specs/q15-memory.md F9).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Optional

from agent import rubric as R
from agent.router import RULE_NAMES

MAX_LISTED = 3


def weights_hash() -> str:
    return hashlib.sha256(json.dumps(R.WEIGHTS, sort_keys=True).encode()).hexdigest()[:8]


def record(sc: Any, now: float) -> dict:
    return {"at": now, "w": weights_hash(), "total": int(sc.total),
            "checks": {c.rule: bool(c.ok) for c in sc.checks}}


def age(seconds: float) -> str:
    s = max(0.0, seconds)
    if s < 60:
        return "just now"
    if s < 3600:
        return f"{int(s // 60)} min ago"
    if s < 86400:
        return f"{int(s // 3600)} h ago"
    return f"{int(s // 86400)} d ago"


def _names(rules: list[str]) -> str:
    order = list(R.WEIGHTS)
    rules = sorted(rules, key=lambda r: order.index(r) if r in order else len(order))
    shown = [RULE_NAMES.get(r, r) for r in rules[:MAX_LISTED]]
    more = len(rules) - MAX_LISTED
    return ", ".join(shown) + (f" +{more} more" if more > 0 else "")


@dataclass(frozen=True)
class Diff:
    when: str  # "2 d ago" / "just now"
    prev_total: int
    total: int
    fixed: tuple[str, ...]
    new: tuple[str, ...]
    comparable: bool  # same weights as the last check

    def line(self, level: int = 0) -> str:
        """0 full, 1 short, 2+ nothing."""
        if level >= 2:
            return ""
        head = f"Since the last check ({self.when})"
        lists = []
        if level == 0:
            if self.fixed:
                lists.append("Fixed: " + _names(list(self.fixed)))
            if self.new:
                lists.append("New: " + _names(list(self.new)))
        if not self.comparable:
            body = f"{head}: scoring changed, so points aren't comparable"
            return "_" + " · ".join([body] + lists) + "._" if lists else f"_{body}._"
        if not self.fixed and not self.new and self.prev_total == self.total:
            return f"_Same score as the last check ({self.when})._"
        d = self.total - self.prev_total
        delta = "±0" if d == 0 else f"{d:+d}"
        body = f"{head}: {self.prev_total} → {self.total} ({delta})"
        return "_" + " · ".join([body] + lists) + "_" if lists else f"_{body}._"


def compare(prev: Optional[dict], sc: Any, now: float) -> Optional[Diff]:
    """None if there is no usable previous record."""
    if not isinstance(prev, dict) or not isinstance(prev.get("checks"), dict):
        return None
    before = prev["checks"]
    now_ok = {c.rule: bool(c.ok) for c in sc.checks}
    common = [r for r in now_ok if r in before]
    fixed = tuple(r for r in common if not before[r] and now_ok[r])
    new = tuple(r for r in common if before[r] and not now_ok[r])
    try:
        prev_total = int(prev.get("total", 0))
        when = age(now - float(prev.get("at", now)))
    except (TypeError, ValueError):
        return None
    return Diff(when, prev_total, int(sc.total), fixed, new, prev.get("w") == weights_hash())
