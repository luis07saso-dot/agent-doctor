"""Q5 (FB-1.3): how to fix each failing check, not just what is wrong.

- `short_how(check)`: one line (how + example) printed under each top fix in the audit.
- `full_guide(check, ...)`: step-by-step guide for "how do I fix #N".
- `LAST`: the fixes each chat was last shown, so "#N" means what the user saw.

Every UI name and claim below comes from docs.agentverse.ai v2, checked 2026-11-02:
agent-discovery/setup-guide, profile, readme-guidelines, testing, verifications;
agent-optimization/ranking, growth-metrics; getting-started/agent-dashboard,
enable-chat-protocol. Domain endings: SCOPE.md -> Verifications (on-chain evidence).
Pure text, no I/O.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Optional

from agent import rubric as R
from agent.scorer import UNRESPONSIVE_FLAG, Check

# One example line per README section (README guidelines, "What a good README should include").
SECTION_HINT: dict[str, str] = {
    "Summary": "what it does and for whom, in 2-3 sentences",
    "Key features": "3-5 bullets of what it can do",
    "Usage": "example inputs and outputs in a code block",
    "Use cases": "2-3 real scenarios and who they help",
    "Limitations": "what it can't do yet, known issues",
    "Metadata": "author, version, license",
}
assert set(SECTION_HINT) == set(R.README_SECTIONS)

_EDIT_README = "Profile tab → Edit README"


def missing_sections(check: Check) -> list[str]:
    """Section names from a readme_sections fix ("Add README sections: A, B")."""
    _, _, tail = check.fix.partition(":")
    names = [s.strip() for s in tail.split(",")]
    return [s for s in names if s in R.README_SECTIONS]


def _readme_missing(check: Check) -> bool:
    return check.rule == "readme" and check.points == 0


# ---------- one-line how-to, shown in the audit ----------

def short_how(check: Check) -> str:
    rule = check.rule
    if rule == "readme_sections":
        missing = missing_sections(check)
        if missing:
            s = missing[0]
            return f"How: {_EDIT_README}, add `## {s}`: {SECTION_HINT[s]}."
        return f"How: {_EDIT_README}, add the missing sections as `##` headings."
    if rule == "readme":
        if _readme_missing(check):
            return f"How: {_EDIT_README}, start with `## Summary`: what it does and for whom."
        return ("How: add plain sentences on what it does, example inputs and outputs, "
                "and limits.")
    if rule == "responsive" and check.detail != UNRESPONSIVE_FLAG:
        return SHORT["active"]
    if rule == "success_rate" and check.kind == "no_data":
        return SHORT_NO_DATA_SUCCESS
    return SHORT.get(rule, "")


# Q10: no success rate yet is no data, not a low rate: the advice is about getting chats.
SHORT_NO_DATA_SUCCESS = ("How: share it with real users on ASI:One (badge, posts); answer "
                         "in-scope questions fully.")


SHORT: dict[str, str] = {
    "active": "How: restart it and keep it running 24/7 (hosted: start it from its dashboard).",
    "chat_protocol": ("How: `agent.include(Protocol(spec=chat_protocol_spec), "
                      "publish_manifest=True)`, ack then reply."),
    "rating": "How: Testing tab → Questions → Generate, run them, fix failures; bring real users.",
    "description": ("How: Profile tab → Agent Description, e.g. \"Summarises news articles "
                    "into 5 bullets for busy readers.\""),
    "responsive": "How: ack at once and reply to every message, even off-scope ones and errors.",
    "handle": f"How: Profile tab → Agent Handles and Addresses, e.g. `@news-summary` (max {R.HANDLE_MAX_CHARS} chars).",
    "avatar": "How: on the agent dashboard, click the current avatar and upload a clear logo.",
    "interactions": "How: Testing tab → Questions → Generate and run them; share with real users.",
    "success_rate": ("How: make the README match what it really does; answer in-scope questions "
                     "fully, decline off-scope politely."),
    "eval_rate": "How: Testing tab → Questions → Generate (or upload a CSV), run, fix failures.",
    "website": "How: Verifications tab → Website → add the DNS TXT record → Continue.",
    "starter_prompts": ("How: Profile tab → Agent Description and Prompts, e.g. "
                        "\"Summarise this article: <link>\"."),
}
assert set(SHORT) | {"readme", "readme_sections"} == set(R.WEIGHTS)


# ---------- full guide, on "how do I fix #N" ----------

_CHAT_SNIPPET = """```python
from uagents import Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement, ChatMessage, TextContent, chat_protocol_spec)

proto = Protocol(spec=chat_protocol_spec)

@proto.on_message(ChatMessage)
async def on_chat(ctx, sender, msg):
    await ctx.send(sender, ChatAcknowledgement(acknowledged_msg_id=msg.msg_id))
    await ctx.send(sender, ChatMessage(content=[TextContent(text="Hi! I can ...")]))

@proto.on_message(ChatAcknowledgement)
async def on_ack(ctx, sender, msg):
    pass

agent.include(proto, publish_manifest=True)
```"""

_README_SKELETON = """```markdown
# News Summariser
Summarises long news articles into 5 bullet points for busy readers.

## Key features
- Works with any public article link

## Usage
Input: `summarise <link>` → Output: 5 bullets

## Use cases
## Limitations
## Metadata
```"""

_NO_FAKE = "Don't script fake chats: Fetch.ai's terms ban falsifying ratings."

# Q10 (FB-2): Agentverse shows no success rate yet. That is no data, not 0%.
_SUCCESS_NO_DATA: tuple[str, list[str], str] = (
    "Agentverse has no success rate for this agent yet: no data, not 0%. The docs describe it "
    "as a rolling 30-day score over ASI:One conversations (other agents' chats count too).",
    ["Get real people to chat with it through ASI:One: share the agent page, posts, a badge.",
     "Make the README say exactly what it can and can't do: chats are judged against it.",
     "Answer in-scope questions fully; decline off-scope ones in one polite line.",
     "Check the Growth tab after a few days.",
     _NO_FAKE],
    "")

_GUIDES: dict[str, tuple[str, list[str], str]] = {  # rule -> (why, steps, example)
    "active": (
        "Only active agents are considered in ranking; inactive ones are de-prioritized "
        "unless someone searches for them directly.",
        ["Hosted agent: open it on agentverse.ai and start it from its dashboard.",
         "Mailbox or local agent: restart the process and keep it running 24/7 "
         "(a server, or Docker with `restart: always`).",
         "Check the dashboard shows it as active, then audit it here again."],
        "```yaml\nservices:\n  agent:\n    build: .\n    restart: always\n```"),
    "chat_protocol": (
        "Agents with a supported protocol get a ranking boost; with none, discoverability "
        "drops. ASI:One reaches agents through the Agent Chat Protocol.",
        ["Hosted agent: follow \"Enable Chat Protocol\" in the Agentverse docs.",
         "uAgents: build a Protocol from `chat_protocol_spec` and include it with "
         "`publish_manifest=True`.",
         "In the message handler, send the acknowledgement first, then the reply.",
         "Restart the agent, then audit it again."],
        _CHAT_SNIPPET),
    "readme": (
        "The README is the main document ASI:One and search use to understand and match your "
        "agent. Write it in English Markdown.",
        [f"Open your agent on agentverse.ai: {_EDIT_README}. External agents can also keep a "
         "README.md in their repo (uAgents: `readme_path=\"README.md\"`).",
         "Use the six sections: " + ", ".join(R.README_SECTIONS) + ".",
         "Under Usage, show real example inputs and outputs.",
         "Put your keywords in it, in plain sentences."],
        _README_SKELETON),
    "rating": (
        "Agentverse's rating comes from recent and total interactions, successful ASI:One "
        "conversations and successful evaluations.",
        ["Testing tab → Questions: Generate questions (or add your own) that match your "
         "README, then run them.",
         "Open failed prompts (\"Needs attention\"), fix the replies, run again.",
         "Bring real users: share your handle and one example prompt where your users are.",
         _NO_FAKE],
        ""),
    "description": (
        "The description shows on your profile, your Marketplace listing and in search.",
        ["Profile tab → Agent Description and Prompts.",
         "One or two sentences: what it does and who it helps. Specific, no keyword lists."],
        "\"Summarises long news articles into 5 bullet points for busy readers.\""),
    "responsive": (
        "Agentverse marks an agent unresponsive when a chat times out with no reply. The "
        "next answered message clears it, e.g. from a Testing run.",
        ["Send the acknowledgement first, then reply to every message: off-scope ones too.",
         "Catch errors and still send a short reply.",
         "Put timeouts on slow API calls so the reply never hangs.",
         "Run a Testing run or Manual Test to get an answered chat; the flag then clears."],
        "```python\ntry:\n    text = await answer(msg.text())\nexcept Exception:\n"
        "    text = \"Sorry, something went wrong. Please try again.\"\n"
        "await ctx.send(sender, ChatMessage(content=[TextContent(text=text)]))\n```"),
    "handle": (
        "A custom @handle lets users find and mention your agent directly in ASI:One.",
        ["Profile tab → Agent Handles and Addresses.",
         f"Pick a handle up to {R.HANDLE_MAX_CHARS} characters, close to the agent's name or job.",
         "To move a handle from another agent, give that agent a different handle first."],
        "`@news-summary`"),
    "avatar": (
        "Agents with a recognizable avatar get a slight ranking boost and stand out in lists.",
        ["Open the agent dashboard on agentverse.ai.",
         "Click the current avatar, then pick an image or upload your own.",
         "Use a clear logo or icon that still reads at small size."],
        ""),
    "interactions": (
        f"The Agentverse setup checklist asks for at least {R.MIN_INTERACTIONS} interactions so "
        "usage signals can build.",
        ["Testing tab → Questions: Generate questions or add your own, then run them.",
         "Try your starter prompts in Manual Test.",
         "Share the agent with real users.",
         _NO_FAKE],
        ""),
    "success_rate": (
        "Success rate is a rolling 30-day score over ASI:One conversations, judged against "
        "your README. Replies that don't answer count as failures; other agents' messages count too.",
        ["Make the README say exactly what it can and can't do.",
         "Answer in-scope questions fully: the figures or steps asked for, not just a topic.",
         "Decline off-scope requests in one polite line that says what you can do.",
         "Cap replies per sender so floods of off-scope messages don't drag it down.",
         "Check the Growth tab after changes."],
        ""),
    "eval_rate": (
        "Successful Agentverse evaluations (Testing runs) feed your rating.",
        ["Testing tab → Questions: Generate a set, add your own, or upload a CSV.",
         "Run them, then open the Runs tab.",
         "Fix each failure by its reason (Readme mismatch, Poor response quality, "
         "Capability gap, ...), then run again.",
         "Re-run after every README or code change."],
        "```csv\nQuestion,Expected answer\nWhat can you do?,Says it summarises news articles\n```"),
    "website": (
        "A verified domain is a trust signal that can lift search priority.",
        ["Verifications tab → Website → enter your domain.",
         "Add the TXT record shown to your domain's DNS (at your registrar), then Continue.",
         "Wait for the success notice; the domain then shows in the Verifications tab.",
         "Some endings are rejected (\"domain root is not supported\", e.g. .tech). "
         "Use a .com, .ai, .io or .xyz domain."],
        ""),
    "starter_prompts": (
        "Starter prompts show users what to ask, and you can use them in Manual Test. Not a "
        "listed ranking factor (2 pts in our score).",
        ["Profile tab → Agent Description and Prompts.",
         "Add 2-4 prompts users would really type. Match your README."],
        "\"Summarise this article: <link>\""),
}
assert set(_GUIDES) | {"readme_sections"} == set(R.WEIGHTS)


def _sections_guide(check: Check) -> tuple[str, list[str], str]:
    missing = missing_sections(check) or list(R.README_SECTIONS)
    why = ("Agentverse's README guidelines list six sections. Clear structure helps ASI:One "
           "match your agent to questions.")
    steps = [f"Open your agent on agentverse.ai: {_EDIT_README} (or edit README.md in your "
             "repo, if it syncs from code).",
             "Add these headings: " + ", ".join(missing) + ".",
             "Write real content under each, in English."]
    example = "```markdown\n" + "\n".join(f"## {s}\n{SECTION_HINT[s]}" for s in missing) + "\n```"
    return why, steps, example


def full_guide(n: int, check: Check, name: str = "") -> str:
    """Markdown guide for fix #n. Caller adds the profile link and fits it to MAX_CHARS."""
    if check.rule == "readme_sections":
        why, steps, example = _sections_guide(check)
    elif check.rule == "responsive" and check.detail != UNRESPONSIVE_FLAG:
        why, steps, example = _GUIDES["active"]
    elif check.rule == "success_rate" and check.kind == "no_data":
        why, steps, example = _SUCCESS_NO_DATA
    else:
        why, steps, example = _GUIDES[check.rule]
        if check.rule == "readme" and not _readme_missing(check):
            steps = [f"Your README is {check.detail}: too short to be indexed well. "
                     f"Aim for {R.README_MIN_CHARS}+ characters of plain description."] + steps
    pts = f"{check.lost:.1f}".rstrip("0").rstrip(".")
    title = f"**Fix #{n}{' for ' + name if name else ''}: {check.fix}** (+{pts} pts)"
    parts = [title, "", why, "", "**Steps**"]
    parts += [f"{i}. {s}" for i, s in enumerate(steps, 1)]
    if example:
        parts += ["", "**Example**", example]
    return "\n".join(parts)


# ---------- what each chat was last shown ----------

@dataclass(frozen=True)
class Shown:
    name: str
    address: str
    fixes: tuple[Check, ...]
    # Q10 "why this score?": the whole audit, so a follow-up question is answered from it.
    total: int = 0
    verdict: str = ""
    rows: tuple = ()  # evidence.Row per check
    facts: tuple = ()  # (field, value) pairs from evidence.facts

    @property
    def facts_dict(self) -> dict:
        return dict(self.facts)


class LastAudit:
    """Per-chat memory of the last audit (Q5 fixes, Q10 evidence). Q15: backed by
    memory.Memory; after attach(path) it survives restarts. Bounded and expiring."""

    def __init__(self, ttl_s: float = 24 * 3600, max_items: int = 500,
                 clock: Callable[[], float] = time.time) -> None:
        from agent.memory import Memory
        self.memory = Memory(None, clock=clock, chat_ttl=ttl_s, chat_max=max_items)

    def attach(self, path: str) -> None:
        self.memory.attach(path)

    def put(self, key: str, shown: Shown, sender_key: str = "") -> None:
        self.memory.put_chat(key, shown, sender_key)

    def get(self, key: str) -> Optional[Shown]:
        return self.memory.get_chat(key)


LAST = LastAudit()
