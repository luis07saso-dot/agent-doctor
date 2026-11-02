"""Pure text routing + every fixed reply text. No I/O, so it is unit-testable and can never hang."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Literal

from agent.extract import Target, extract

HELP = (
    "**Agent Doctor** audits any Agentverse agent and tells you how to rank higher "
    "on Agentverse and ASI:One.\n\n"
    "Send an agent address, @handle or Agentverse profile link, e.g.:\n"
    "- `audit agent1q...`\n"
    "- `check @some-handle`\n"
    "- `https://agentverse.ai/agents/details/agent1q.../profile`\n\n"
    "You get a 0-100 score, a verdict and the top 3 fixes (README, Chat Protocol, "
    "handle, avatar, status, rating, Testing and more). Free."
)

OFF_SCOPE = (
    "I only audit Agentverse agents, so I can't help with that.\n\n"
    "Send an agent address (`agent1q...`), @handle or Agentverse profile link "
    "and I'll score it and list the top fixes."
)

NEED_TARGET = (
    "Which agent? I need its address (`agent1q...`), @handle or Agentverse profile link. "
    "I can't search by name yet.\n\n"
    "Find it on agentverse.ai: open the agent, copy the address or @handle."
)

BAD_ADDRESS = (
    "That address looks incomplete or mistyped. Agent addresses start with `agent1q` "
    "and are 65 characters long. Copy it again from the agent's Agentverse page."
)

NON_TEXT = "I can only read text. Send an agent address, @handle or Agentverse profile link."

RATE_LIMITED = "You're sending messages fast. Please wait a minute, then try again."

REPEATED = (
    "Same request as before, so the answer hasn't changed (results are cached for 5 minutes, "
    "and Agentverse can take a while to update). Try again in 10 minutes."
)

FALLBACK = "Sorry, something went wrong on my side. Please try again in a minute."


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
_GREETING = re.compile(r"^\W*(hi|hello|hey|help|start|menu|commands?|usage|what can you do|"
                       r"what do you do|who are you|how does (?:this|it) work|thanks?|thank you)\b",
                       re.IGNORECASE)

Kind = Literal["audit", "help", "need_target", "bad_address", "off_scope"]


@dataclass(frozen=True)
class Intent:
    kind: Kind
    targets: tuple[Target, ...] = ()


def classify(text: str, self_handles: Iterable[str] = (),
             self_addresses: Iterable[str] = ()) -> Intent:
    text = (text or "").strip()
    self_addresses = tuple(a for a in self_addresses if a)
    ex = extract(text, ignore_handles=self_handles, ignore_addresses=self_addresses)
    if ex.targets:
        return Intent("audit", ex.targets)
    if ex.bad_address:
        return Intent("bad_address")
    for h in self_handles:  # "@agent-doctor hi" from ASI:One: judge the rest of the text
        text = re.sub(rf"@{re.escape(h.lstrip('@'))}(?![A-Za-z0-9_-])", " ", text, flags=re.I).strip()
    for a in self_addresses:  # "@<own address> ..." = ASI:One's first message of a new chat
        text = re.sub(rf"@{re.escape(a)}(?![0-9a-z])", " ", text, flags=re.I).strip()
    if not text:
        return Intent("help")
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
        "bad_address": BAD_ADDRESS,
        "off_scope": OFF_SCOPE,
    }[kind]
