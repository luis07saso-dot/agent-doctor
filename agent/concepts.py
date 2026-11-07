"""Q19 (user, 2026-11-05): answer in-scope questions about the words Doctor uses ("what do you
mean by 'bring real users'?", "what is a Testing run?", "explain step 2").

Before Q19 these went to `off_scope`, or (after an audit) the Q11 model picked a data topic and
the reply was the whole score breakdown: near the topic, not an answer.

Every answer here is fixed text. Agentverse facts are from docs.agentverse.ai v2, read
2026-11-05 (testing, growth-metrics, ranking, setup-guide, verifications pages) and
docs.asi1.ai; our own advice is labelled as ours. Pure: no I/O.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

from agent import guides
from agent import rubric as R
from agent.report import PROFILE_URL, fit

_NO_FAKE = "Don't script fake chats: Fetch.ai's terms ban falsifying ratings."


@dataclass(frozen=True)
class Concept:
    title: str
    text: str
    rule: str = ""  # rubric check this is about: with an audit, its line for that agent is added
    pattern: str = ""  # regex for an Agentverse-specific phrase: enough on its own
    loose: str = ""  # regex for a common word ("rating", "logo"): only with an agent-context word


CONCEPTS: dict[str, Concept] = {
    "real_users": Concept(
        "Real users",
        "People other than you and your team who chat with your agent, for example through "
        "ASI:One. The Agentverse ranking docs list recent and total interactions and successful "
        "ASI:One interactions as rating factors.\n\n"
        "**How to get them** (our tips, not from the Agentverse docs):\n"
        "- Post your @handle plus one example prompt where your users already are "
        "(Discord, X, Telegram, forums).\n"
        "- Link your Agentverse profile from your site or repo.\n"
        "- Make the README and starter prompts match what people really ask.\n\n"
        + _NO_FAKE,
        "interactions",
        r"\breal\s+(?:users?|people|chats?|use)\b|\bbring(?:ing)?\s+(?:in\s+)?(?:real\s+)?users\b|"
        r"\boutside\s+users?\b",
        r"\b(?:get|find|attract|more)\s+(?:new\s+|some\s+)?users\b"),
    "testing": Concept(
        "Agentverse Testing runs",
        "In your agent's **Testing** tab:\n"
        "- **Questions**: generate a set of questions, add your own, or upload a `.csv`, "
        "then run them automatically.\n"
        "- **Runs**: the results of each run. Failed prompts are listed under "
        "**Needs attention**, each with a short reason.\n"
        "- **Manual Test**: chat with your agent yourself, for custom prompts and edge cases.\n\n"
        "Successful agent evaluations are one of Agentverse's rating factors.",
        "eval_rate",
        r"\btesting\s+(?:tab|runs?|page|score)\b|\btest(?:ing)?\s+runs?\b|\bruns\s+tab\b|"
        r"\bquestions\s+tab\b|\bgenerate\s+(?:the\s+|some\s+)?questions\b|"
        r"\beval(?:uation)?\s+(?:success\s+)?rate\b",
        r"\bevaluations?\b|\bevals?\b"),
    "needs_attention": Concept(
        "Needs attention",
        "In a Testing run, each failed prompt shows a short reason under **Needs attention**. "
        "Reasons include:\n"
        "- **Readme mismatch**: the reply contradicts what the README says the agent does.\n"
        "- **Poor response quality**: it didn't answer the question asked.\n"
        "- **Capability gap**: the question was outside its declared capabilities.\n"
        "- Also: Expected response mismatch, No meaningful response, Technical error.\n\n"
        "Our tip: fix the reply (or the README), then run the questions again.",
        "eval_rate",
        r"\bneeds?\s+attention\b|\bfailed\s+prompts?\b|\breadme\s+mismatch\b|"
        r"\bcapability\s+gap\b|\bpoor\s+response\s+quality\b"),
    "manual_test": Concept(
        "Manual Test",
        "Manual Test is in your agent's Testing tab: you chat with your own agent there, for "
        "custom prompts and edge cases. Your starter prompts show up there to start a chat. "
        "An answered message also clears an \"unresponsive\" flag.",
        "",
        r"\bmanual\s+tests?\b"),
    "interactions": Concept(
        "Interactions",
        "Agentverse counts each agent's interactions (total and recent). It doesn't publish an "
        "exact definition. Recent and total interactions are ranking factors, and the setup "
        f"guide asks for at least {R.MIN_INTERACTIONS}. It says: \"Trigger your Agent with "
        "real or test prompts so usage signals can build.\"",
        "interactions",
        "",
        r"\binteractions?\b"),  # Q24: needs a context word ("drug interaction")
    "verified_chats": Concept(
        "Verified chats",
        "Agentverse's public profile data has two counts: recent verified conversations, and "
        "how many of them succeeded. Agentverse doesn't document them. Our reading: in every "
        "agent we sampled, the success rate matched these two counts, and agents with 0 "
        "verified chats had no rate at all. So 0 verified chats means no data, not 0%.",
        "success_rate",
        r"\bverified\s+(?:chats?|conversations?|interactions?)\b"),
    "success_rate": Concept(
        "Success rate",
        "Agentverse's success rate (Growth tab) is a rolling 30-day Wilson score over your "
        "agent's ASI:One conversations, including ones other agents start. Each conversation "
        "counts as a success if the reply answered the request, judged against what the README "
        "says the agent does.",
        "success_rate",
        "",
        r"\bsuccess(?:ful)?\s+(?:rate|rates|chats?|conversations?)\b|\bwilson\b"),
    "rating": Concept(
        "Rating",
        "The Agentverse ranking docs list these rating factors: recent interactions, total "
        "interactions, successful ASI:One interactions and successful agent evaluations. They "
        "don't mention user star ratings or give a formula.",
        "rating",
        "",
        r"\bratings?\b|\brated\b|\bstars?\b"),
    "unresponsive": Concept(
        "Unresponsive flag",
        "Agentverse marks an agent unresponsive when a conversation with it times out with no "
        "reply. The flag clears automatically the next time the agent answers a message, for "
        "example from a Testing run or a Manual Test.",
        "responsive",
        "",
        r"\b(?:un)?responsive\b"),  # Q24: needs a context word ("patient unresponsive")
    "active": Concept(
        "Active status",
        guides.GUIDE_WHY["active"],
        "active",
        r"\b(?:in)?active\s+(?:status|agents?)\b",
        r"\b(?:in)?active\b"),
    "chat_protocol": Concept(
        "Agent Chat Protocol",
        guides.GUIDE_WHY["chat_protocol"] + "\n\n" + guides.SHORT["chat_protocol"],
        "chat_protocol",
        r"\bchat\s*protocol\b",
        r"\bprotocols?\b"),
    "readme": Concept(
        "README",
        guides.GUIDE_WHY["readme"] + " Agentverse's guidelines list six sections: "
        + ", ".join(R.README_SECTIONS) + ".",
        "readme_sections",
        r"\breadme\b",
        r"\bsections?\b"),
    "handle": Concept(
        "@handle",
        guides.GUIDE_WHY["handle"] + "\n\n" + guides.SHORT["handle"],
        "handle",
        r"@handles?\b|\bcustom\s+handles?\b",
        r"\bhandles?\b"),
    "avatar": Concept(
        "Avatar",
        guides.GUIDE_WHY["avatar"] + "\n\n" + guides.SHORT["avatar"],
        "avatar",
        "",
        r"\bavatars?\b|\blogo\b"),
    "description": Concept(
        "Description",
        guides.GUIDE_WHY["description"] + "\n\n" + guides.SHORT["description"],
        "description",
        r"\bagent\s+descriptions?\b",
        r"\bdescriptions?\b"),
    "starter_prompts": Concept(
        "Starter prompts",
        guides.GUIDE_WHY["starter_prompts"] + "\n\n" + guides.SHORT["starter_prompts"],
        "starter_prompts",
        r"\bstarter\s+prompts?\b",
        r"\bprompts?\b"),
    "website": Concept(
        "Website verification",
        guides.GUIDE_WHY["website"] + " Verified agents can rank higher in the Marketplace and "
        "ASI:One search. Today only Website verification is live. Optional: Doctor counts it "
        "only when verified, never against you.\n\n" + guides.SHORT["website"],
        "website",
        r"\bwebsite\s+verif\w*|\bverif\w*\s+(?:my\s+|a\s+|the\s+)?website\b|\btxt\s+record\b|"
        r"\bverifications\s+tab\b",
        r"\bwebsite\b|\bverif(?:y|ied|ication)\b|\bdomain\b"),
    "found_tip": Concept(
        "Found vs Tip",
        "In \"why this score?\": **found** = Agentverse's data shows the gap for this agent. "
        "**not scored** = Agentverse has no data for that check (or it's optional, like a "
        "website), so it's left out of the score. No data is not a 0% result.",
        "",
        r"\bfound\b.{0,20}\btip\b|\btip\b.{0,20}\bfound\b|\(found\)|\(tip\)|\bnot scored\b",
        r"\bno data\b"),
    "points": Concept(
        "Points and estimates",
        "Agentverse doesn't publish its ranking weights. Doctor's points per check are our "
        "estimate, weighted by what the Agentverse ranking docs stress most. The same agent "
        "data always gives the same score. Ask `how is the score calculated?` for every check "
        "and its points.",
        "",
        r"\bgood,? with gaps\b",
        r"\bpts\b|\bpoints?\b|\bestimates?\b|\bweights?\b|\bverdicts?\b"),
    "fake_chats": Concept(
        "Why not fake chats",
        "Fetch.ai's terms of use (section 10) ban actions that falsify ratings. Scripted chats "
        "to your own agent risk that. Our advice: build usage with real users and Agentverse "
        "Testing runs instead.",
        "",
        r"\bfake\s+(?:chats?|users?|traffic|interactions?|ratings?)\b|\bscript(?:ed)?\s+(?:fake\s+)?chats?\b|"
        r"\bfalsif\w+|\bbots?\s+traffic\b",
        r"\bfake\b|\bterms\b"),
    "asi_one": Concept(
        "ASI:One",
        "ASI:One is built by Fetch.ai. Its models plan multi-step work and call specialist "
        "agents on Agentverse, and Agentverse agents can be discovered there. You can also "
        "reach an agent in ASI:One chat by its @handle (what we see in use).",
        "",
        r"\basi:?\s?one\b|\basi1\b"),
    "findability": Concept(
        "Findability",
        "Doctor runs your agent's starter prompts as Agentverse searches and reports where it "
        "ranks, e.g. `#3 of 50` or not in the top 50. Info only, not part of the score. If "
        "it isn't found, put those words in your README and description.",
        "",
        r"\bfindab\w*|\bfound\s+in\s+search\b",
        r"\btop\s+50\b"),
    "prehire": Concept(
        "Pre-Hire Check",
        "Before you rely on an agent, ask `is weather-bot live?` or `pre-hire check agent1q...`. "
        "Doctor sends it one test message and tells you if it really answers, how fast, plus "
        "its Doctor score.",
        "",
        r"\bpre-?hire\b"),
}
assert all(c.rule in R.WEIGHTS for c in CONCEPTS.values() if c.rule)

# Which concept wins when several terms appear: specific before generic.
ORDER = ("needs_attention", "manual_test", "real_users", "fake_chats", "verified_chats",
         "success_rate", "testing", "found_tip", "findability", "prehire", "unresponsive",
         "website", "starter_prompts", "chat_protocol", "interactions", "rating", "readme",
         "handle", "avatar", "description", "active", "asi_one", "points")
assert set(ORDER) == set(CONCEPTS)
_PATTERNS = tuple((k, re.compile(CONCEPTS[k].pattern, re.I | re.S)) for k in ORDER
                  if CONCEPTS[k].pattern)
_LOOSE = tuple((k, re.compile(CONCEPTS[k].loose, re.I | re.S)) for k in ORDER
               if CONCEPTS[k].loose)
# A common word counts only next to one of these ("what is the rating" alone could be a movie).
# Q24: no bare "doctor" (medical questions say it); "agent doctor" still counts via "agent".
_CONTEXT = re.compile(
    r"\bagents?\b|\bagentverse\b|\basi:?\s?one\b|\basi1\b|\bbots?\b|\buagents?\b|\breadme\b|"
    r"\bprofile\b|\bconversations?\b|\bchats?\b|\bscor\w*|\brank\w*|\baudit\w*|\bfix(?:es)?\b|\bsteps?\b|"
    r"\byou\s+(?:mean|meant|said|say|wrote|mentioned|told)\b|\bmarketplace\b|\bdashboard\b",
    re.I)

# A question about a word or idea (not "audit X", not "is X live?").
_ASK = re.compile(
    r"\bwhat\s+(?:do|did)\s+you\s+mean\b|\bwhat(?:'s|s|\s+is|\s+are|\s+was|\s+were)\b|"
    r"\bwhat\s+(?:does|do|did)\b.{0,60}\bmean\w*\b|\bmeaning\b|\bmeans?\b|\bdefin\w+|"
    r"\bexplain\w*|\bclarif\w+|\belaborate\b|\btell\s+me\s+(?:more\s+)?about\b|"
    r"\bmore\s+(?:info|detail\w*)\b|\bhow\s+(?:do|can|could|should|would)\s+(?:i|we|you)\s+"
    r"(?:get|find|bring|attract|grow|use|run|start|do|set\s+up|generate|add|create|make|write|"
    r"upload|pass|clear|verify|choose|pick|see|open)\b|\bhow\s+(?:does|do|is|are)\b"
    r".{0,40}\b(?:work|works|done|used|measured|counted)\b|\bwhat\s+counts?\b|"
    r"\bwhere\s+(?:do|can|is|are)\b|\bwhich\s+(?:tab|page|one)\b|\bi\s+don'?t\s+(?:get|understand)\b|"
    r"\bconfus\w+|\bwhy\s+(?:do|should|would|shouldn'?t|can'?t|not)\b|\bunclear\b",
    re.I | re.S)


def match_cue(text: str) -> bool:
    """The message asks what something means or how it works."""
    return bool(_ASK.search(text or ""))


def match(text: str) -> str:
    """Concept key a question asks about, or "". Needs a question cue and a known term."""
    t = text or ""
    if not _ASK.search(t):
        return ""
    return term(t, bool(_CONTEXT.search(t)))


def term(text: str, loose: bool = True) -> str:
    """Concept key of the first known term in `text`, no question cue needed (step texts are
    our own, so common words count). `loose=False`: Agentverse-specific phrases only."""
    for key, rx in _PATTERNS:
        if rx.search(text or ""):
            return key
    if loose:
        for key, rx in _LOOSE:
            if rx.search(text or ""):
                return key
    return ""


def _footer(shown: Any) -> str:
    if shown is None:
        return ("\n\nSend an agent address, handle or Agentverse profile link and I'll score it "
                "and list the top fixes.")
    tail = "\n\nAsk \"how do I fix #1\" for steps, or \"why this score?\" for every check."
    if getattr(shown, "address", ""):
        tail += f"\n\n[Open profile on Agentverse]({PROFILE_URL.format(address=shown.address)})"
    return tail


def _agent_line(shown: Any, rule: str) -> str:
    from agent import evidence  # evidence imports guides; keep the import graph acyclic
    if shown is None or not rule:
        return ""
    row = next((r for r in getattr(shown, "rows", ()) if r.rule == rule), None)
    if row is None:
        return ""
    return f"For {shown.name or 'this agent'}: " + evidence.row_line(row)


def reply(key: str, shown: Any = None) -> str:
    """Answer for concept `key`. `shown` (guides.Shown) adds that agent's line for the check."""
    c = CONCEPTS[key]
    body = f"**{c.title}**\n\n{c.text}"
    line = _agent_line(shown, c.rule)
    if line:
        body += "\n\n" + line
    return fit(body, _footer(shown))


# ---------- "explain step 2" after a fix guide ----------

_STEP = re.compile(
    r"\bstep\s*(?:#|no\.?|number)?\s*([1-9])\b|\b(first|second|third|fourth|fifth|last|1st|2nd|"
    r"3rd|4th|5th)\s+step\b", re.I)
_STEP_WORDS = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3, "fourth": 4,
               "4th": 4, "fifth": 5, "5th": 5, "last": -1}


def step_number(text: str) -> int:
    """1-based step a message asks about; -1 = "the last step"; 0 = none."""
    m = _STEP.search(text or "")
    if not m:
        return 0
    return int(m.group(1)) if m.group(1) else _STEP_WORDS[m.group(2).lower()]


STEP_NO_GUIDE = ("Which steps? Ask `how do I fix #1` first, then `explain step 2`.")


def step_reply(step: int, fix_n: int, check: Any, shown: Any) -> str:
    """Step `step` of the fix #`fix_n` guide, plus what its key term means."""
    steps = guides.guide_parts(check)[1]
    if step == -1:
        step = len(steps)
    if not 1 <= step <= len(steps):
        return fit(f"Fix #{fix_n} has {len(steps)} steps. Ask `explain step 1` to "
                   f"`explain step {len(steps)}`.", _footer(shown))
    body = f"**Fix #{fix_n}, step {step}:** {steps[step - 1]}"
    key = term(steps[step - 1])
    if key:
        c = CONCEPTS[key]
        body += f"\n\n**{c.title}**\n\n{c.text}"
    return fit(body, _footer(shown))


# ---------- in scope, but no rule knows what it means (Q11 model said "general") ----------

UNSURE = (
    "I'm not sure what you're asking. I can explain the words I use, e.g. `what are real "
    "users?`, `what is a Testing run?`, `what does needs attention mean?`, `what is the "
    "success rate?`, `what counts as an interaction?`, or `explain step 2` after a fix guide.")


def unsure(shown: Any = None) -> str:
    return fit(UNSURE, _footer(shown))


def known(key: str) -> Optional[Concept]:
    return CONCEPTS.get(key)
