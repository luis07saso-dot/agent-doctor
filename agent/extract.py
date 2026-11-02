"""L2 extractor: find which Agentverse agent(s) a free-text message is about.

Accepted target forms (anywhere in a sentence; ASI:One often rewrites messages):
- address:  agent1q... (bech32, checksum verified)
- handle:   @some-handle (lowercased; emails like a@b.com are ignored)
            or a hyphenated handle WITHOUT "@" right after an audit word
            ("audit agent-listing-generator", "is weather-bot live?"): in a new ASI:One chat an @handle can route
            the message to that agent instead of us (docs/smoke-test.md).
- URL:      any URL containing an address, e.g.
            https://agentverse.ai/agents/details/agent1q.../profile
            or an agentverse.ai / asi1.ai URL with an @handle path segment.

No plain-name search (cut from launch). Pure: no I/O.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Literal

import bech32

from agent.agentverse import HANDLE_MAX, normalize_handle

_BECH32 = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
# Full-length address, not glued to more bech32 chars on either side.
_ADDRESS = re.compile(rf"(?<![0-9a-z])agent1[{_BECH32}]{{59}}(?![0-9a-z])", re.IGNORECASE)
# Something that starts like an address but is the wrong length / has bad chars.
_ADDRESS_LIKE = re.compile(r"(?<![0-9a-z])agent1[0-9a-z]{20,}", re.IGNORECASE)
_URL = re.compile(r"https?://[^\s<>()\[\]`'\"]+", re.IGNORECASE)
_HANDLE_HOSTS = ("agentverse.ai", "asi1.ai")
# "@token" not preceded by an email-ish char. The whole token is taken atomically (no
# backtracking to a shorter prefix), then validated against the Agentverse handle pattern,
# so "@foo_bar", "@foo-" and "@example.com" are rejected rather than read as "@foo".
_HANDLE = re.compile(r"(?<![A-Za-z0-9._%+\-/@])@([A-Za-z0-9_-]++)(?!@|\.[A-Za-z0-9])")
# Bare handle: audit word, up to 3 filler words, then a hyphenated handle-shaped token (no
# "@": @handles are step 3). Hyphen required so plain words ("audit agentbuilder", "check
# this") are never read as handles. Token not glued to "_", "@", "-" or a ".tld".
_BARE_HANDLE = re.compile(
    r"\b(?:audit|check|scan|review|score|rate|grade|analy[sz]e|diagnose|inspect|test|probe|ping)\b"
    r"(?:[\s:,]+(?:the|this|that|my|our|out|agent|handle|called|named|please|on|agentverse)\b){0,3}"
    r"[\s:,]+([a-z0-9]++(?:-[a-z0-9]++)++)(?![A-Za-z0-9_@-]|\.[A-Za-z0-9])",
    re.IGNORECASE,
)
# "is weather-bot live?" (Pre-Hire Check wording): hyphenated handle between "is" and a
# liveness word. Same token rules as _BARE_HANDLE.
_LIVE_HANDLE = re.compile(
    r"\b(?:is|are)[\s:,]+(?:the[\s:,]+)?(?:agent[\s:,]+)?([a-z0-9]++(?:-[a-z0-9]++)++)"
    r"(?![A-Za-z0-9_@-]|\.[A-Za-z0-9])[\s:,]+(?:still[\s:,]+)?"
    r"(?:live|alive|online|up|reachable|responsive|responding|answering|working)\b",
    re.IGNORECASE,
)
# Feature names and common hyphenated words that look like handles ("check pre-hire",
# "check my e-mail") are never targets.
_NOT_HANDLES = frozenset({
    "pre-hire", "pre-hire-check", "e-mail", "re-check", "real-time", "step-by-step", "follow-up",
    "how-to", "built-in", "state-of-the-art", "up-to-date", "well-known", "so-called",
    "e-commerce", "co-founder", "check-in", "sign-up", "sign-in", "log-in", "opt-in", "opt-out",
    "x-ray", "open-source", "end-to-end", "one-time", "long-term", "short-term", "high-quality",
    "user-friendly", "non-profit", "self-hosted", "third-party", "wi-fi", "t-shirt", "ai-powered",
    "multi-agent", "agent-to-agent", "full-time", "part-time", "add-on", "plug-in", "set-up",
    "start-up", "to-do", "how-tos", "one-off", "top-notch", "in-depth", "first-time",
})
# Soft handle: a hyphenated handle-shaped token ANYWHERE in the text ("my agent ticketlens-agent
# is ..."). Only a guess: the router uses it when the message is about agents, and the service
# falls back to the plain reply if Agentverse doesn't know it. Same token rules as _BARE_HANDLE.
_SOFT_HANDLE = re.compile(
    r"(?<![A-Za-z0-9_@./\-])([a-z0-9]++(?:-[a-z0-9]++)++)(?![A-Za-z0-9_@-]|\.[A-Za-z0-9])",
    re.IGNORECASE,
)
_URL_HANDLE = re.compile(r"/@([A-Za-z0-9_-]++)(?=[/?#]|$)")
_TRAILING_PUNCT = ".,;:!?)]}>'\"`*_"


@dataclass(frozen=True)
class Target:
    kind: Literal["address", "handle"]
    value: str  # address, or handle without "@"
    from_url: bool = field(default=False, compare=False)  # logged only; not part of identity

    @property
    def label(self) -> str:
        return self.value if self.kind == "address" else f"@{self.value}"


@dataclass(frozen=True)
class Extraction:
    targets: tuple[Target, ...] = field(default_factory=tuple)
    # Saw something address-like that failed length/checksum (typo, truncated paste).
    bad_address: bool = False


def valid_checksum(address: str) -> bool:
    hrp, data = bech32.bech32_decode(address)
    return hrp == "agent" and data is not None


def extract(text: str, ignore_handles: Iterable[str] = (),
            ignore_addresses: Iterable[str] = ()) -> Extraction:
    """Targets in order of appearance, de-duplicated. `ignore_handles` = our own handles
    (ASI:One may keep "@agent-doctor" in the forwarded message). `ignore_addresses` = our own
    addresses: "@<own address>" is a mention, not a target (ASI:One prepends it to the first
    message of a new chat). A bare own address is still a target (self-audit)."""
    if not text:
        return Extraction()
    ignore = {h.lower().lstrip("@") for h in ignore_handles}
    own = {a.lower() for a in ignore_addresses if a}
    found: list[tuple[int, Target]] = []
    bad = False

    # 1. Addresses anywhere (covers addresses inside URLs too).
    good_spans: list[tuple[int, int]] = []
    url_spans = [m.span() for m in _URL.finditer(text)]
    for m in _ADDRESS.finditer(text):
        addr = m.group(0).lower()
        if addr in own and m.start() > 0 and text[m.start() - 1] == "@":
            good_spans.append(m.span())  # mention of us: neither a target nor a typo
            continue
        if valid_checksum(addr):
            in_url = any(s <= m.start() < e for s, e in url_spans)
            found.append((m.start(), Target("address", addr, in_url)))
            good_spans.append(m.span())
        else:
            bad = True
    for m in _ADDRESS_LIKE.finditer(text):
        if not any(s <= m.start() < e for s, e in good_spans):
            bad = True

    # 2. Handles in agentverse.ai / asi1.ai URL paths. Then blank out every URL so
    #    "@" segments of unrelated URLs (x.com/@foo) are never read as handles.
    masked = list(text)
    for m in _URL.finditer(text):
        url = m.group(0).rstrip(_TRAILING_PUNCT)
        host = url.split("/", 3)[2].lower().split(":")[0]
        if any(host == h or host.endswith("." + h) for h in _HANDLE_HOSTS):
            for hm in _URL_HANDLE.finditer(url):
                _add_handle(found, m.start() + hm.start(), hm.group(1), ignore, True)
        for i in range(m.start(), m.end()):
            masked[i] = " "
    masked_text = "".join(masked)

    # 3. Bare @handles in the remaining text.
    for m in _HANDLE.finditer(masked_text):
        _add_handle(found, m.start(), m.group(1), ignore)

    # 4. Bare handles after an audit word. Not filtered by `ignore`: ASI:One adds
    #    "@agent-doctor", but a typed "audit agent-doctor" is a real self-audit request.
    for m in _BARE_HANDLE.finditer(masked_text):
        _add_handle(found, m.start(1), m.group(1), set(_NOT_HANDLES))
    for m in _LIVE_HANDLE.finditer(masked_text):
        _add_handle(found, m.start(1), m.group(1), set(_NOT_HANDLES))

    found.sort(key=lambda p: p[0])
    seen: set[Target] = set()
    targets: list[Target] = []
    for _, t in found:
        if t not in seen:
            seen.add(t)
            targets.append(t)
    return Extraction(targets=tuple(targets), bad_address=bad and not targets)


def _add_handle(found: list, pos: int, raw: str, ignore: set[str], from_url: bool = False) -> None:
    h = normalize_handle(raw)
    if h is None or len(h) > HANDLE_MAX or h in ignore:
        return
    found.append((pos, Target("handle", h, from_url)))


# Words that mark the next token as a handle ("my agent X", "handle is X", "called X"). Not
# glued to a "-" before it, so the "-agent" inside "ticketlens-agent" anchors nothing.
_ANCHOR = r"(?:(?<![\w-])(?:agent|bot|called|named)[\s:,]+|(?<![\w-])handle[\s:,]+(?:is[\s:,]+)?)"


def handle_anchored(text: str, handle: str) -> bool:
    """True if `handle` sits right after an anchor word, or is the whole message: then it is
    clearly meant as a handle, and a miss should say "couldn't find" rather than be dropped."""
    if text.strip(" \t\n.,!?:;'\"`*").lower() == handle:
        return True
    tok = re.escape(handle) + r"(?![A-Za-z0-9_@-]|\.[A-Za-z0-9])"
    return re.search(_ANCHOR + tok, text, re.IGNORECASE) is not None


def soft_handles(text: str, ignore_handles: Iterable[str] = ()) -> tuple[str, ...]:
    """First hyphenated handle-shaped token anywhere in `text`, as a 0/1-tuple. URLs, our own
    handles, common hyphenated words and number-only tokens ("2026-11-03", "24-7") never count."""
    if not text:
        return ()
    ignore = {h.lower().lstrip("@") for h in ignore_handles} | _NOT_HANDLES
    masked = _URL.sub(lambda m: " " * len(m.group(0)), text)
    for m in _SOFT_HANDLE.finditer(masked):
        h = normalize_handle(m.group(1))
        if h and len(h) <= HANDLE_MAX and h not in ignore and re.search(r"[a-z]", h):
            return (h,)
    return ()
