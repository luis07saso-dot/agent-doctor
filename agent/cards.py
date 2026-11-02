"""Q4 (FB-1.2): ASI:One interactive card under each audit reply.

Sources (read 2026-11-02):
- https://innovationlab.fetch.ai/resources/docs/interactive-cards/asi-interactive-cards
- https://innovationlab.fetch.ai/resources/docs/interactive-cards/asi-card-playground
- Fetch's examples github.com/fetchai/innovation-lab-examples/tree/main/dynamic-ui-on-asi1
  (news-card-agent: `custom` card + text in ONE ChatMessage; tripmate: button `redirect`).

The card rides as one MetadataContent next to the full text report (TextContent), so every
client that ignores cards still gets the whole report. ASI:One drops an invalid card and
shows the text ("silently falls back").

Kind = `custom`: the only kind Fetch's own examples send for a detail view. The "Open
profile" button uses `action.redirect` (seen in tripmate, NOT in the docs). If ASI:One
ignores it, the click still sends a selection and we reply with the link.

A click comes back as a new chat message: the selection as a JSON string (direct @mention)
or as planner prose that names every value. Actions carry a `doctor_` prefix so prose can't
match by accident (plain words like "back" or "fix" would).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Optional, Sequence

from agent.extract import _ADDRESS  # same validation regex as the extractor

PROTOCOL_VERSION = "1"
FIX = "doctor_fix"
RECHECK = "doctor_recheck"
LIVE = "doctor_live_check"
PROFILE = "doctor_profile"
ACTIONS = (FIX, RECHECK, LIVE, PROFILE)
MAX_FIX_CHARS = 120
MAX_PAYLOAD_BYTES = 64 * 1024  # documented limit for card_payload

_JSON_OBJ = re.compile(r"\{.*\}", re.DOTALL)
_ACTION = re.compile(r"\b(" + "|".join(ACTIONS) + r")\b", re.IGNORECASE)
_PROSE_N = re.compile(r"(?:\bn\b|#|\bfix(?:\s+number)?)\W{0,3}([1-9])(?!\d)", re.IGNORECASE)


@dataclass(frozen=True)
class Selection:
    action: str
    n: int = 0
    address: str = ""


def _button(label: str, selection: dict, primary: bool = False,
            redirect: str = "") -> dict:
    action: dict[str, Any] = {"selection": selection}
    if redirect:
        action["redirect"] = redirect
    b: dict[str, Any] = {"type": "button", "label": label, "action": action}
    if primary:
        b["primary"] = True
    return b


def _short(text: str, limit: int = MAX_FIX_CHARS) -> str:
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"


def audit_payload(name: str, address: str, total: int, verdict: str,
                  fixes: Sequence[str], profile_url: str = "") -> dict:
    """Card payload for one audit. `name` must already be cleaned (report.clean);
    `fixes` = the top fixes' one-line texts, in report order."""
    variant = "success" if total >= 70 else "warning" if total >= 40 else "info"
    children: list[dict] = [
        {"type": "badge", "label": f"Score {total}/100", "variant": variant},
    ]
    if fixes:
        children.append({"type": "heading", "value": "Top fixes", "level": 3})
        children += [{"type": "text", "value": f"#{i} {_short(f)}"}
                     for i, f in enumerate(fixes, 1)]
        children.append({"type": "group", "direction": "row", "children": [
            _button(f"How to fix #{i}", {"action": FIX, "n": str(i), "address": address},
                    primary=(i == 1))
            for i in range(1, len(fixes) + 1)]})
    else:
        children.append({"type": "text", "value": "No fixes needed. Nice work."})
    if address:
        actions = [
            _button("Re-check", {"action": RECHECK, "address": address}),
            _button("Live check", {"action": LIVE, "address": address}),
        ]
        if profile_url:
            actions.append(_button("Open profile", {"action": PROFILE, "address": address},
                                   redirect=profile_url))
        children += [{"type": "divider"},
                     {"type": "group", "direction": "row", "children": actions}]
    return {"root": {"type": "section", "title": name or "Agent audit",
                     "subtitle": f"Agent Doctor · {verdict}", "children": children}}


def card_metadata(payload: dict) -> Optional[dict[str, str]]:
    """MetadataContent.metadata for a custom card, or None if the payload is too big."""
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if len(body.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        return None
    return {
        "card_protocol_version": PROTOCOL_VERSION,
        "requires_card_interaction": "true",
        "card_kind": "custom",
        "card_payload": body,
    }


def _address(value: Any) -> str:
    m = _ADDRESS.search(str(value or ""))
    return m.group(0).lower() if m else ""


def parse_selection(text: str) -> Optional[Selection]:
    """A card click -> Selection, else None (a normal message). JSON first, then prose."""
    if not text or "doctor_" not in text.lower():
        return None
    m = _JSON_OBJ.search(text)
    if m:
        try:
            data = json.loads(m.group(0))
        except ValueError:
            data = None
        if isinstance(data, dict) and str(data.get("action", "")).lower() in ACTIONS:
            action = str(data["action"]).lower()
            try:
                n = int(str(data.get("n", "0")))
            except ValueError:
                n = 0
            return _valid(Selection(action, n if 1 <= n <= 9 else 0,
                                    _address(data.get("address"))))
    a = _ACTION.search(text)
    if not a:
        return None
    action = a.group(1).lower()
    n_m = _PROSE_N.search(text) if action == FIX else None
    return _valid(Selection(action, int(n_m.group(1)) if n_m else 0, _address(text)))


def _valid(sel: Selection) -> Optional[Selection]:
    if sel.action == FIX:
        return sel if sel.n else None
    return sel if sel.address else None
