"""Privacy-safe message shape for the REQ log.

Shows how a message is built (mentions, addresses, URLs, punctuation) without its words:
every run of letters/digits becomes "w". Used to see how ASI:One rewrites what users type.
Example: "@agent1q<own> What can you do?" -> "@<SELF> w w w w?"
"""
from __future__ import annotations

import re
from collections.abc import Iterable

MAX_SHAPE_CHARS = 160

_TOKEN = re.compile(
    r"(?P<url>https?://\S+)"
    r"|(?P<addr>(?<![0-9a-z])agent1[0-9a-z]{20,})"
    r"|(?P<handle>(?<![A-Za-z0-9._%+\-/@])@(?!agent1)[A-Za-z0-9_-]+)"
    r"|(?P<word>[^\W_]+)",
    re.IGNORECASE,
)
_FULL_ADDR_LEN = 65


def shape(text: str, self_addresses: Iterable[str], self_handles: Iterable[str]) -> str:
    own_handles = {h.lower() for h in self_handles}
    own_addrs = {a.lower() for a in self_addresses if a}

    def sub(m: re.Match) -> str:
        if m.group("url"):
            return "<URL>"
        if m.group("addr"):
            a = m.group("addr").lower()
            if a in own_addrs:
                return "<SELF>"
            return "<ADDR>" if len(a) == _FULL_ADDR_LEN else "<ADDR?>"
        if m.group("handle"):
            return "@<SELF_H>" if m.group("handle")[1:].lower() in own_handles else "@<H>"
        return "w"

    out = _TOKEN.sub(sub, text)
    out = re.sub(r"\s+", " ", out).strip()
    return out[:MAX_SHAPE_CHARS]
