"""Q12: findability test. Where does the agent rank in Agentverse search for its own starter
prompts? Info only: never scored (spec docs/specs/q12-findability.md).

Starter prompts only: the agent's own description words rank it #1 almost always (11 of 12
sampled agents, 2026-11-04), so they would test nothing.
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any, Optional

from agent.report import clean

MAX_PHRASES = 3
_PLACEHOLDER = re.compile(r"<[^>]*>|\{[^}]*\}|\[[^\]]*\]")
_STRIP = re.compile(
    r"https?://\S+|www\.\S+"  # URLs
    r"|\S+@\S+\.\S+"  # emails
    r"|(?<![0-9a-z])agent1[0-9a-z]{20,}"  # agent addresses
    r"|@[A-Za-z0-9_-]+",  # @handles
    re.IGNORECASE)
_GENERIC = {"what can you do", "what do you do", "who are you", "help", "hi", "hello", "hey",
            "start", "menu", "test"}


@dataclass(frozen=True)
class Find:
    items: tuple[tuple[str, str, Optional[int]], ...] = ()  # (phrase, ok|not_checked, rank)


def _phrase(prompt: Any) -> str:
    if not isinstance(prompt, str) or _PLACEHOLDER.search(prompt):
        return ""
    s = _STRIP.sub(" ", prompt)
    s = clean(s, 120).replace('"', " ")
    s = re.sub(r"\s+", " ", s).strip(" .,!?:;-'`")
    if not s or s.lower() in _GENERIC:
        return ""
    words = s.split(" ")
    if len(words) > 1:
        return s if 2 <= len(words) <= 12 else ""
    return s if 4 <= len(s) <= 60 and not s.isascii() else ""  # no spaces: CJK etc.


def phrases(profile: Optional[dict]) -> tuple[str, ...]:
    prompts = (profile or {}).get("starter_prompts")
    if not isinstance(prompts, list):
        return ()
    out: list[str] = []
    for p in prompts:
        s = _phrase(p)
        if s and s.lower() not in {o.lower() for o in out}:
            out.append(s)
        if len(out) == MAX_PHRASES:
            break
    return tuple(out)


async def check(client: Any, address: str, items: tuple[str, ...], wait_s: float) -> Find:
    """One search per phrase, waits up to `wait_s`. Unfinished searches keep running (the
    client caches them), so a re-audit shows them. Never raises."""
    target = (address or "").lower()
    tasks = [asyncio.ensure_future(client.search_addresses(p)) for p in items]
    if tasks and wait_s > 0:
        await asyncio.wait(tasks, timeout=wait_s)
    elif tasks:
        await asyncio.sleep(0)  # let them start (they warm the cache), don't wait
    out = []
    for phrase, t in zip(items, tasks):
        res = None
        if t.done() and not t.cancelled() and t.exception() is None:
            res = t.result()
        else:
            t.add_done_callback(_retrieve)
        if res and res[0] == "ok":
            addrs = [a.lower() for a in res[1]]
            out.append((phrase, "ok", addrs.index(target) + 1 if target in addrs else None))
        else:
            out.append((phrase, "not_checked", None))
    return Find(tuple(out))


def _retrieve(t: "asyncio.Future") -> None:
    if not t.cancelled():
        t.exception()  # mark retrieved: no "exception was never retrieved" warning
