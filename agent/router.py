"""Pure text routing + every fixed reply text. No I/O, so it is unit-testable and can never hang."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Literal

from agent.extract import Target, extract

HELP = (
    "**Agent Doctor** audits any Agentverse agent and tells you how to rank higher "
    "on Agentverse and ASI:One.\n\n"
    "Send an agent address, handle or Agentverse profile link, e.g.:\n"
    "- `audit agent1q...`\n"
    "- `audit weather-bot` (handle, no @)\n"
    "- `https://agentverse.ai/agents/details/agent1q.../profile`\n\n"
    "In ASI:One, leave out the @ before another agent's handle: an @handle may send "
    "your message to that agent instead.\n\n"
    "You get a 0-100 score, a verdict and the top 3 fixes (README, Chat Protocol, "
    "handle, avatar, status, rating, Testing and more), each with how to do it. "
    "Then ask `how do I fix #1` for step-by-step help. Free.\n\n"
    "Before you rely on an agent, ask `is weather-bot live?` or `pre-hire check agent1q...`: "
    "I send it one test message and tell you if it really answers."
)

OFF_SCOPE = (
    "I only audit Agentverse agents, so I can't help with that.\n\n"
    "Send an agent address (`agent1q...`), @handle or Agentverse profile link "
    "and I'll score it and list the top fixes."
)

NEED_TARGET = (
    "Which agent? I need its address (`agent1q...`), handle (`audit weather-bot`, no @) "
    "or Agentverse profile link. I can't search by name yet.\n\n"
    "Find it on agentverse.ai: open the agent, copy the address, handle or profile link."
)

BAD_ADDRESS = (
    "That address looks incomplete or mistyped. Agent addresses start with `agent1q` "
    "and are 65 characters long. Copy it again from the agent's Agentverse page."
)

NON_TEXT = "I can only read text. Send an agent address, @handle or Agentverse profile link."

PREHIRE_NEED_TARGET = (
    "**Pre-Hire Check** tells you if an agent really answers right now: I send it one test "
    "message, time its acknowledgement and answer, and add its Agentverse rating and profile "
    "score.\n\n"
    "Which agent? Send its address or handle, e.g. `pre-hire check agent1q...` or "
    "`is weather-bot live?` (no @)."
)

RATE_LIMITED = "You're sending messages fast. Please wait a minute, then try again."

REPEATED = (
    "Same request as before, so the answer hasn't changed (results are cached for 5 minutes, "
    "and Agentverse can take a while to update). Try again in 10 minutes."
)

FALLBACK = "Sorry, something went wrong on my side. Please try again in a minute."

NO_AUDIT_YET = (
    "I don't have an audit in this chat yet, so I don't know which fix you mean. "
    "Send an agent address or handle first (e.g. `audit weather-bot`, no @), "
    "then ask `how do I fix #1`."
)


def no_such_fix(n: int, count: int, name: str) -> str:
    if count == 0:
        return f"The last audit of {name} found nothing to fix. Re-check any time after changes."
    pick = "#1" if count == 1 else f"#1 to #{count}"
    return f"The last audit of {name} listed {count} fix{'es' if count > 1 else ''}, so there is no #{n}. Ask for {pick}."


def not_found(label: str) -> str:
    return (f"I couldn't find {label} on Agentverse (mainnet). "
            "Check the address or @handle and try again.")


def invalid(label: str) -> str:
    return (f"`{label[:80]}` isn't a valid agent address or @handle. "
            "Addresses start with `agent1q`; handles look like `@my-agent`.")


API_DOWN = "Agentverse isn't answering right now, so I can't audit. Please try again in a minute."
TIMEOUT = "Agentverse took too long to answer. Please try again in a minute."


def more_targets(n_extra: int) -> str:
    s = "s" if n_extra > 1 else ""
    return f"\n\n_You sent {n_extra} more agent{s}. I checked the first; send the others one at a time._"


# need_target = a request verb AND an agent word ("audit my agent"); "fix my car" is off-scope.
_REQUEST = re.compile(r"\b(audit|check|scan|review|rank|score|rate|fix|improve|analy[sz]e|test)\w*",
                      re.IGNORECASE)
_AGENT_WORD = re.compile(r"\b(agents?|agentverse|asi|uagents?|bot|handle|address|readme|profile|"
                         r"listing|marketplace|ranking|doctor|pre-?hire)\b", re.IGNORECASE)
# Pre-Hire Check wording: "pre-hire check X", "probe X", "ping X", "is X live/online/...?".
_PREHIRE = re.compile(r"\bpre-?hire\b|\bprobe\b|\bping\b", re.IGNORECASE)
_LIVE_Q = re.compile(
    r"\b(?:is|are|check (?:if|whether))\b.{0,100}?"
    r"\b(?:live|alive|online|reachable|responsive|responding|answering|up(?=\s*[?.!]*\s*$))\b",
    re.IGNORECASE | re.DOTALL)
# Q5 follow-ups: the n-th top fix of the last audit in this chat.
# Strong form (always): the word "fix" right before the number, the number ending the phrase
# ("how do I fix #2", "fix 2?", "fix no. 2 please", "explain the second fix"). "fix 2 bugs" is
# not one: a word other than a filler follows the number.
_FILLER = r"(?:please|pls|for|from|in|on|of|above|again|now|then|first|next)\b"
_FIX_STRONG = re.compile(
    r"\bfix(?:es)?\s*(?:#|no\.?|number)?\s*([1-9])(?![\d.,])(?!\s+(?!" + _FILLER + r")[A-Za-z])",
    re.IGNORECASE)
_FIX_ORDINAL = re.compile(r"\b(first|second|third|1st|2nd|3rd)\s+fix\b", re.IGNORECASE)
_ORDINALS = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3}
# Weak form (only after an audit in this chat): "#2", "more on #3", "number 2?", "item 1".
# Short, or with a how/explain word, and no agent/request/pre-hire words ("is agent #2 live?",
# "audit my agent #3", "how do I rank #1 on agentverse" keep their old meaning).
_FIX_WEAK = re.compile(r"(?<![\w#&])#\s*([1-9])(?!\d)|\b(?:number|no\.|item|point)\s*([1-9])(?![\d.])",
                       re.IGNORECASE)
_HOW = re.compile(r"\b(how|explain|help|steps?|guide|details?|more|what|show|tell|walk)\b",
                  re.IGNORECASE)
FIX_SHORT_WORDS = 4


def fix_number(text: str, has_audit: bool = False) -> int:
    """The fix number a follow-up asks about, or 0 if it isn't such a question."""
    m = _FIX_STRONG.search(text)
    if m:
        return int(m.group(1))
    o = _FIX_ORDINAL.search(text)
    if o:
        return _ORDINALS[o.group(1).lower()]
    if not has_audit:
        return 0
    w = _FIX_WEAK.search(text)
    if not w or any(r.search(text) for r in (_AGENT_WORD, _REQUEST, _PREHIRE, _LIVE_Q)):
        return 0
    short = len(re.findall(r"[A-Za-z0-9#]+", text)) <= FIX_SHORT_WORDS
    return int(w.group(1) or w.group(2)) if short or _HOW.search(text) else 0


_GREETING = re.compile(r"^\W*(hi|hello|hey|help|start|menu|commands?|usage|what can you do|"
                       r"what do you do|who are you|how does (?:this|it) work|thanks?|thank you)\b",
                       re.IGNORECASE)

Kind = Literal["audit", "prehire", "help", "need_target", "prehire_need_target", "bad_address",
               "off_scope", "fix_guide"]


@dataclass(frozen=True)
class Intent:
    kind: Kind
    targets: tuple[Target, ...] = ()
    n: int = 0  # fix_guide: which fix (1-based)


def classify(text: str, self_handles: Iterable[str] = (),
             self_addresses: Iterable[str] = (), has_audit: bool = False) -> Intent:
    """`has_audit`: this chat has a remembered audit, so a bare "#2" means fix #2."""
    text = (text or "").strip()
    self_addresses = tuple(a for a in self_addresses if a)
    ex = extract(text, ignore_handles=self_handles, ignore_addresses=self_addresses)
    wants_prehire = bool(_PREHIRE.search(text) or _LIVE_Q.search(text))
    if ex.targets:
        return Intent("prehire" if wants_prehire else "audit", ex.targets)
    if ex.bad_address:
        return Intent("bad_address")
    for h in self_handles:  # "@agent-doctor hi" from ASI:One: judge the rest of the text
        text = re.sub(rf"@{re.escape(h.lstrip('@'))}(?![A-Za-z0-9_-])", " ", text, flags=re.I).strip()
    for a in self_addresses:  # "@<own address> ..." = ASI:One's first message of a new chat
        text = re.sub(rf"@{re.escape(a)}(?![0-9a-z])", " ", text, flags=re.I).strip()
    if not text:
        return Intent("help")
    n = fix_number(text, has_audit)
    if n:
        return Intent("fix_guide", n=n)
    if _PREHIRE.search(text) and _AGENT_WORD.search(text) or (
            _LIVE_Q.search(text) and _AGENT_WORD.search(text)):
        return Intent("prehire_need_target")  # "pre-hire check", "is my agent live?"
    if _REQUEST.search(text) and _AGENT_WORD.search(text):
        return Intent("need_target")  # "audit my agent": about agents but no target yet
    if _AGENT_WORD.search(text) or _GREETING.search(text):
        return Intent("help")
    return Intent("off_scope")


def reply_for(kind: Kind) -> str:
    """Fixed reply for every non-audit intent."""
    return {
        "help": HELP,
        "need_target": NEED_TARGET,
        "prehire_need_target": PREHIRE_NEED_TARGET,
        "bad_address": BAD_ADDRESS,
        "off_scope": OFF_SCOPE,
    }[kind]
