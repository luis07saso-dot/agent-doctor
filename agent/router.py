"""Pure text routing + every fixed reply text. No I/O, so it is unit-testable and can never hang."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Literal, Optional

from agent import concepts
from agent import rubric as R
from agent.extract import Target, extract, handle_anchored, soft_handles

HELP = (  # Q22a (FB-7): <= 600 chars
    "**Agent Doctor** audits any Agentverse agent and tells you how to rank higher "
    "on Agentverse and ASI:One. Free.\n\n"
    "Send an address, handle or profile link: `audit agent1q...` or `audit weather-bot`. "
    "Leave out the @: in ASI:One an @handle may send your message to that agent.\n\n"
    "You get a 0-100 score and the top 3 fixes. Then ask `how do I fix #1`, "
    "`why this score?` or `re-check`.\n\n"
    "Also: `is weather-bot live?` or `pre-hire check agent1q...` (I message it and see if it "
    "answers), `find an agent that books flights` (I search, score and test the best), "
    "`forget` (deletes what I stored)."
)

OFF_SCOPE = (
    "I only audit Agentverse agents, so I can't help with that.\n\n"
    "Send an agent address (`agent1q...`), @handle or Agentverse profile link "
    "and I'll score it and list the top fixes."
)

NEED_TARGET = (
    "Which agent? I need its address (`agent1q...`), handle (`audit weather-bot`, no @) "
    "or Agentverse profile link. I can't search by name yet.\n\n"
    "Find it on agentverse.ai: open the agent, copy the address, handle or profile link.\n\n"
    "Looking for an agent that does something? Ask `find an agent that books flights`."
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

# ---------- FAQ: one fixed reply per common question about Agent Doctor or ranking ----------
_NEXT = ("Send an agent address (`agent1q...`), handle (`audit weather-bot`, no @) or Agentverse "
         "profile link to get its score and top 3 fixes.")
# Display name per rubric rule; FAQ "score" lists every rule with its points (tests check it
# matches agent/rubric.py, so the text can't drift from the real weights).
RULE_NAMES: dict[str, str] = {
    "active": "Active status",
    "chat_protocol": "Chat Protocol",
    "readme_sections": "README sections",
    "readme": "README length",
    "rating": "Rating",
    "description": "Description",
    "responsive": "Responsive (no unresponsive flag)",
    "handle": "Custom @handle",
    "avatar": "Avatar",
    "interactions": "10+ interactions",
    "success_rate": "Success rate",
    "eval_rate": "Evaluation success rate",
    "website": "Website verification",
    "starter_prompts": "Starter prompts",
}


def _score_faq() -> str:
    rules = ", ".join(f"{RULE_NAMES[r]} {int(w)}" for r, w in R.WEIGHTS.items())
    bands = ", ".join(f"{v.replace(',', '')} {m}+" for m, v in R.VERDICTS if m) + \
        f", {R.VERDICTS[-1][1]} below {R.VERDICTS[-2][0]}"
    return (
        f"**How the score works:** {len(R.WEIGHTS)} checks, 100 points in total. Points per check: "
        f"{rules}.\n\n"
        "Agentverse doesn't publish its ranking weights. These are our estimates, weighted by "
        "what the Agentverse ranking docs stress most. The same agent data always gives the "
        f"same score.\n\nVerdicts: {bands}. An agent that isn't running is marked Offline.\n\n"
        + _NEXT
    )


FAQ: dict[str, str] = {
    "score": _score_faq(),
    "checks": (
        "**What I check** (from the Agentverse ranking and README docs):\n"
        "- Status: active, Chat Protocol, not flagged unresponsive\n"
        "- README: length and the 6 recommended sections (Summary, Key features, Usage, "
        "Use cases, Limitations, Metadata)\n"
        "- Profile: description, custom @handle, avatar, starter prompts\n"
        "- Track record: rating, 10+ interactions, success and evaluation rates\n"
        "- Website verification\n\n"
        "I also test findability: where the agent ranks in Agentverse search for its own "
        "starter prompts. Info only, not scored.\n\n"
        "You get a 0-100 score, a verdict and the top 3 fixes, each with how to do it. "
        "Pre-Hire Check (`is weather-bot live?`) also sends an agent one test message to see "
        "if it really answers.\n\n" + _NEXT
    ),
    "rank": (
        "**How to rank higher on Agentverse and ASI:One** (from the Agentverse docs):\n"
        "- Keep it running: only active agents are ranked; inactive ones are pushed down.\n"
        "- Support the Chat Protocol: it gives a ranking boost.\n"
        "- Write a good README (Summary, Key features, Usage, Use cases, Limitations, "
        "Metadata): it's the main document search reads.\n"
        "- Set a custom @handle, an avatar and a clear description.\n"
        "- Earn a good rating: real interactions (10+), successful ASI:One chats and "
        "Agentverse evaluations.\n"
        "- Verify a website if you can.\n\n"
        "For your agent's own top 3 fixes: " + _NEXT[0].lower() + _NEXT[1:]
    ),
    "free": (
        "Yes, Agent Doctor is free.\n\n" + _NEXT + " Then ask `how do I fix #1` for "
        "step-by-step help, or `is weather-bot live?` for a Pre-Hire Check."
    ),
    # Q23 (prod 2026-11-05 "can i get banned for faking chats"). Source: fetch.ai/terms
    # (effective 28 Sep 2026, covers agentverse.ai), re-read 2026-11-06: §10 "harm or falsify
    # the Company's rating", §10/§12 robots / "automated manner", §22 suspend or terminate.
    "rules": (
        "**Can faking chats or traffic get you banned?** Yes, it's a real risk. Fetch.ai's Terms "
        "of Service cover Agentverse. They ban actions that \"harm or falsify the Company's "
        "rating\", and using bots or scripts to use the service in an automated way (§10, §12). "
        "For a breach, Fetch.ai may suspend or close your account without notice (§22).\n\n"
        "What works instead: a complete profile (README, Chat Protocol, handle, avatar), "
        "staying online and answering fast, honest Testing runs, and real users.\n\n"
        "For your agent's top 3 fixes: " + _NEXT[0].lower() + _NEXT[1:]
    ),
}
# Q23: "rules" = asking about faking usage or getting banned. Strong cheat words alone; weaker
# ones ("spam", "inflate") only with a risk word; or a plain "get banned" / "terms of service".
_USAGE = (r"(?:chats?|conversations?|interactions?|traffic|users?|ratings?|reviews?|usage|messages?|"
          r"accounts?|picks|impressions|activity|numbers|stats|metrics|success(?:\s+rate)?)")
_CHEAT_STRONG = re.compile(
    r"\b(?:(?:fak(?:e|es|ed|ing)|falsif\w*|buy(?:s|ing)?|bought|purchas\w*)\s+(?:\w+\s+){0,2}?"
    + _USAGE + r"|fake\s+it|cheat(?:s|ed|ing)?|sock\s?puppets?|bot\s+traffic|"
    r"gam(?:e|ing)\s+(?:the\s+)?(?:system|ranking|algorithm|rating|search))\b", re.I)
_CHEAT_WEAK = re.compile(r"\b(?:spam\w*|inflat\w*|artificial\w*|self-?chat\w*|"
                         r"alt(?:ernate)?\s+accounts?|(?:multiple|many|several|extra)\s+accounts)\b",
                         re.I)
_RISK = re.compile(r"\b(?:bann?(?:ed|s|ing)?|suspend\w*|terminat\w*|delist\w*|penali[sz]\w*|"
                   r"punish\w*|get caught|allowed|against the (?:rules|terms|tos)|"
                   r"violat\w*|breach\w*|break(?:s|ing)?|legal|illegal|risky|safe|ok(?:ay)? to|"
                   r"can i|could i|should i)\b", re.I)
_BAN = re.compile(r"\b(?:get|got|be|been|getting|gets)\s+(?:my\s+\w+\s+)?"
                  r"(?:banned|suspended|terminated|delisted)\b", re.I)
# "terms of service" alone is not enough: "how do I add a terms of service to my README".
_TERMS = re.compile(r"\bterms of (?:service|use)\b|\btos\b", re.I)


def _rules_question(text: str) -> bool:
    return bool(_CHEAT_STRONG.search(text) or _BAN.search(text)
                or ((_CHEAT_WEAK.search(text) or _TERMS.search(text)) and _RISK.search(text)))
# Question patterns, checked in this order. A question about "my agent" with an address or
# handle in it is an audit, not an FAQ (targets are checked first).
_FAQ_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("score", re.compile(
        r"\bhow\b.{0,40}\bscor(?:e|es|ed|ing)\b|\bscor(?:e|es|ed|ing)\b.{0,40}\b(?:calculat|comput|"
        r"mean|work|determin|decid|based|weigh)\w*|\brubric\b|\bweights?\b", re.I | re.S)),
    ("checks", re.compile(
        r"\bwhat\b.{0,30}\b(?:do|does|will|can)\b.{0,30}\b(?:check|look|audit|test|review|measure|"
        r"score|cover|analy[sz])\w*", re.I | re.S)),
    ("free", re.compile(
        r"\bfree\b|\b(?:cost|costs|price|pricing|charge|fee|fees)\b.{0,40}\b(?:you|it|this|doctor|"
        r"agent|audit|check)\b|\b(?:you|it|this|doctor|audit|check)\b.{0,40}\b(?:cost|costs|price|"
        r"charge|fee)\b|\b(?:have|need|got) to pay\b|\b(?:do|must|should) i pay\b", re.I | re.S)),
    ("rank", re.compile(
        r"\b(?:how|why|tips?|ways?|advice|improve|boost|increase|more|higher|better)\b.{0,60}"
        r"\b(?:rank|ranks|ranking|ranked|picks?|discoverab\w*|visib\w*|found|find|show(?:s|ing)? up|"
        r"comes? up|appear\w*)\b", re.I | re.S)),
)


def faq_key(text: str) -> str:
    """Which FAQ a message asks, or "" if none. Rules questions first: "can I fake chats to
    rank higher?" is about the risk, not ranking tips."""
    if _rules_question(text):
        return "rules"
    return next((k for k, rx in _FAQ_PATTERNS if rx.search(text)), "")

# Q24: a health / medicine question. Doctor checks AI agents, not people: never answer it, never
# map it to an Agentverse explainer ("what is a drug interaction?" is not about Agentverse
# interactions). Left out on purpose (Doctor's own metaphor, idioms, AI terms): doctor, health,
# diagnosis, symptom, treatment, check-up, pain, pulse, heart (alone), side effects, sick of,
# bleeding edge, toxic, poisoning, ingredients (alone), psychology, tablet, "active agent".
_MEDICAL = re.compile(
    r"\b(?:drugs?|medications?|medicines?|medical(?:ly)?|pills?|capsules?|dos(?:e|es|age|ing)|"
    r"patients?|prescri(?:be|bed|ption)s?|ibuprofen|aspirin|paracetamol|acetaminophen|tylenol|"
    r"advil|antibiotics?|antidepressants?|opioids?|insulin|vaccin\w*|"
    r"allerg\w*|diseases?|illness(?:es)?|sickness|injur(?:y|ies|ed)|wounds?|"
    r"blood|surger(?:y|ies)|surgical|surgeons?|hospital\w*|clinics?|clinical(?:ly)?|nurses?|"
    r"pharmac\w*|overdos\w*|alcohol|coma(?:tose)?|unconscious\w*|seizures?|cpr|first\s+aid|"
    r"pregnan\w*|(?:in)?active\s+ingredients?|vitamins?|supplements?|therap(?:y|ies|ists?)|"
    r"mri|x-?rays?|muscles?|heart\s+(?:attack|rate|disease|failure)|fever|cancer|tumou?rs?|"
    r"diabet\w*|infect\w*|chemo\w*|psychologists?|psychiatr\w*|mental\s+health|ana?esthe\w*|"
    r"dementia|physicians?|dentists?|ambulance|(?:chemical|nerve|contrast|biological)\s+agents?)\b",
    re.IGNORECASE)
# A strong Agentverse word keeps a message in normal routing ("my agent gives dose advice, why
# is it unresponsive?").
_STRONG = re.compile(
    r"\bagentverse\b|\basi:?\s?one\b|\basi1\b|\buagents?\b|\breadme\b|\bmarketplace\b|"
    r"\baudit\w*|\b(?:my|our|your)\s+(?:[\w'-]+\s+){0,2}?(?:agents?|bots?)\b|\bai\s+agents?\b|"
    r"\bchat\s?bots?\b|\bagent\s+doctor\b",
    re.IGNORECASE)


def medical(text: str, handles: Iterable[str] = ()) -> bool:
    """Q24: a health / medicine question with no strong Agentverse word in it. `handles`: bare
    agent handles found in the text ("pill-reminder"): their words don't count."""
    t = text or ""
    for h in handles:
        t = re.sub(rf"(?<![\w-]){re.escape(h)}(?![\w-])", " ", t, flags=re.I)
    return bool(_MEDICAL.search(t)) and not _STRONG.search(t)


MEDICAL = (
    "I'm Agent Doctor: I check AI agents on Agentverse, not people, so I can't answer health or "
    "medicine questions. Please ask a pharmacist, doctor or other health professional. In an "
    "emergency, call your local emergency number.\n\n"
    "Looking for a health agent on Agentverse? Ask `find an agent that ...`. To check an agent, "
    "send its address (`agent1q...`), @handle or Agentverse profile link."
)

EXPLAIN_NONE = (
    "I don't have an audit in this chat yet, so there's no score to explain. "
    "Send an agent address or handle first (e.g. `audit weather-bot`, no @), "
    "then ask `why this score?`."
)

NO_AUDIT_YET = (
    "I don't have an audit in this chat yet, so I don't know which fix you mean. "
    "Send an agent address or handle first (e.g. `audit weather-bot`, no @), "
    "then ask `how do I fix #1`."
)


def no_such_fix(n: int, count: int, name: str) -> str:
    if count == 0:
        return (f"The last audit of {name} found nothing to fix. "
                "Say \"re-check\" any time after changes.")
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
    r"\b(?:live|alive|online|reachable|responsive|responding|answering|working|"
    # "is it up?" is liveness; "showing up", "come up" (search visibility) are not.
    r"(?<!show )(?<!shows )(?<!showing )(?<!come )(?<!comes )(?<!coming )(?<!pop )(?<!pops )"
    r"(?<!popping )(?<!turn )(?<!turns )(?<!turning )(?<!end )up(?=\s*[?.!]*\s*$))\b"
    # "agent not responding", "doesn't answer", "stopped replying" (keyword: agent not responding).
    r"|(?:\bnot|n't|\bnever|\bno longer|\bstopped|\bstops)\s+(?:respond|answer|repl)\w*",
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

# Q11: a whole message that is only a greeting / thanks / "what can you do" (no question about
# the audit in it). "help me fix my README" is not one.
_BARE_GREETING = re.compile(
    r"^\W*(?:hi|hello|hey|yo|help|start|menu|commands?|usage|thanks?|thank you|thx|ok(?:ay)?|"
    r"cool|great|nice|what can you do|what do you do|who are you|how does (?:this|it) work)"
    r"(?:\s+(?:there|again|so much|a lot|doctor|agent doctor))?\W*$", re.IGNORECASE)


def is_greeting(text: str) -> bool:
    return bool(_BARE_GREETING.match(text or ""))


Kind = Literal["audit", "prehire", "help", "need_target", "prehire_need_target", "bad_address",
               "off_scope", "fix_guide", "faq", "explain", "explain_none", "forget",
               "recheck_none", "scout", "scout_need_what", "scout_pick_none", "concept", "step",
               "medical"]

# Q15: "forget me" / "delete my data". A verb needs a data noun ("delete this" is not enough),
# except "forget" on its own. Whole message only, so "forget it, audit X" is not one.
_FORGET = re.compile(
    r"^(?:please\s+)?(?:forget(?:\s+(?:me|us|everything|it all))?|"
    r"(?:forget|delete|erase|wipe|clear|remove)\s+(?:all\s+)?(?:of\s+)?(?:(?:my|our|the|this)\s+)?"
    r"(?:(?:stored|saved|audit|chat)\s+)?(?:data|history|memory|records?|info(?:rmation)?|"
    r"audits?|everything))(?:\s+(?:please|now|thanks?|thank you))?$", re.IGNORECASE)


def wants_forget(text: str) -> bool:
    t = re.sub(r"[^\w\s'-]+", " ", text or "")
    return bool(_FORGET.match(re.sub(r"\s+", " ", t).strip()))

FORGET_DONE = (
    "Done. I deleted what I stored for this ASI:One sender: recent audits and re-check "
    "history. Request logs keep only hashed IDs and no message text; this doesn't change them."
)
FORGET_ERROR = ("I removed it from memory, but couldn't update the saved copy. "
                "Please try `forget` again in a minute.")

# Q10 (FB-2): questions about an audit ("why this score?", "how many unique users does X have?")
# get the evidence, not a re-run of the audit. Narrow on purpose: "why isn't X ranking?" and
# "is X open-source?" stay audits (spec docs/specs/q10-why-this-score.md §3.6 table).
_EXPLAIN = re.compile("|".join((
    r"\bwhy\b.{0,40}\b(?:scor\w*|rated|rating|points?|recommend\w*|suggest\w*|tips?|found|"
    r"so low|so high)\b",
    r"\b(?:this|that|my|the|its|their) score\b.{0,20}\?|\bthis score\b",
    r"\bevidence\b",
    r"\bexplain\b.{0,30}\b(?:score|scoring|rating|points|audit|result|this|that)\b",
    r"\bbreak\s?down\b",
    r"\bunique users?\b|\bhow many (?:unique )?(?:users|people|chats|conversations|interactions)\b",
    r"\bsuccess (?:rate|metrics?)\b",
    r"\bwhat(?:'s|s| is| was| are)\b.{0,30}\b(?:rating|success|interactions)\b",
    r"\bhow\b.{0,30}\b(?:you|it|this|that|they)\b.{0,20}\b(?:scor\w*|calculat\w*|rated|rating|"
    r"measur\w*|got)\b",
    r"\bwhere\b.{0,30}\b(?:data|numbers?)\b.{0,20}\bcome\b",
)), re.IGNORECASE | re.DOTALL)
_AUDIT_CMD = re.compile(r"\baudit\w*|\bre-?check\w*|\bscan\b", re.IGNORECASE)
_STRONG_EXPLAIN = re.compile(r"\bthis score\b|\bwhy\b.{0,40}\bscor\w*|\bunique users?\b",
                             re.IGNORECASE | re.DOTALL)


_LONG_TARGET = re.compile(r"https?://\S+|(?<![0-9a-z])agent1[0-9a-z]{20,}", re.IGNORECASE)


def explain_wanted(text: str) -> bool:
    # A 65-char address must not break the ".{0,40}" windows ("why is agent1q… scored low?").
    text = _LONG_TARGET.sub("X", text)
    return bool(_EXPLAIN.search(text) and not _AUDIT_CMD.search(text)
                and not (_PREHIRE.search(text) or _LIVE_Q.search(text))
                and fix_number(text, True) == 0)


RECHECK_NONE = (
    "I don't have a recent audit to re-check, so I don't know which agent you mean "
    "(I keep the last one for 24 hours; `forget` deletes it).\n\n" + _NEXT
)

# Q17: back-references to the last audited agent, in a message with no target. Strong ("re-check
# the same agent", "check it again"): clearly an earlier agent, so it may come from an earlier
# chat of this sender. Weak ("audit it", "is that agent live?"): only this chat's last audit.
# Up to 3 describing words before the noun: "that same tavily agent", "the weather bot".
_MID = (r"(?:(?!(?:for|of|in|on|to|with|from|and|or|by|at|about|is|are|was|were|we|you|i)\b)"
        r"[a-z0-9][\w.'’-]*\s+){0,3}?")
_NOUN = r"(?:agent|one|bot)"
_BACK_STRONG = re.compile(
    r"\bre-?(?:check|audit|scan|run|test|score)(?:s|ed|ing)?\b"
    r"|\bsame\s+" + _MID + r"(?:agent|one|bot|address|handle)\b"
    r"|\bre-?do\s+(?:the\s+|that\s+)?(?:audit|check|scan|it)\b"
    r"|\b(?:last|previous|prior|earlier)\s+" + _MID + _NOUN + r"\b"
    # Q17b: "the agent we were just auditing", "the one you checked", "that bot we talked about"
    r"|\b(?:that|this|the)\s+" + _MID + _NOUN + r"\s+(?:(?:that|which)\s+)?(?:we|you|i)\s+"
    r"(?:(?:were|was|have|had|'ve|just)\s+){0,2}(?:audit|check|talk|discuss|look|review|scor|"
    r"test|scan)\w*"
    # "the agent from before", "that one above" (clause end): not "audit my agent before I submit"
    r"|\b(?:that|this|the)\s+" + _MID + _NOUN + r"\s+(?:from\s+(?:before|earlier|above)\b|"
    r"(?:before|earlier|above)\W*$)", re.IGNORECASE)
_AGAIN = re.compile(r"\bagain\b|\bone more time\b|\bonce more\b", re.IGNORECASE)
_BACK_WEAK = re.compile(r"\bit\b|\b(?:that|this|the)\s+" + _MID + _NOUN + r"\b", re.IGNORECASE)
# Narrow on purpose: "how do I fix it / test it / do it" are questions, not re-checks.
_RECHECK_VERB = re.compile(r"\b(?:audit|check|scan|score|analy[sz]e)\w*", re.IGNORECASE)
# Weak cue: the verb must act on the reference ("check it", "audit that agent").
_VERB_ON_REF = re.compile(r"\b(?:audit|check|scan|score|analy[sz]e)\s+(?:it|(?:that|this|the)\s+"
                          + _MID + _NOUN + r")\b", re.IGNORECASE)
# Q17b: describing words name the agent meant ("that same tavily agent"); the service checks
# them against the remembered agent's name and handle. "the other agent" is not a back-reference.
_HINT = re.compile(r"\b(?:same|that|this|the|last|previous|prior|earlier)\s+(" + _MID + r")"
                   + _NOUN + r"\b", re.IGNORECASE)
_HINT_SKIP = frozenset({"same", "that", "this", "the", "last", "previous", "prior", "earlier",
                        "very", "exact", "a", "an", "ai", "my", "your", "our", "s",
                        # describing words, not names: "the same old agent", "that broken agent"
                        "old", "slow", "broken", "bad", "good", "working", "live", "dead",
                        "offline", "online", "flagged", "unresponsive", "current", "original",
                        "little", "big", "cool", "nice", "great", "weird", "mentioned",
                        "above", "earlier", "audited", "checked", "one"})
_OTHER = frozenset({"other", "another", "different", "new", "next", "first", "second", "third"})


def name_hint(text: str) -> tuple[str, ...]:
    """Words naming the agent in a back-reference, e.g. ("tavily",). Lowercase, deduped."""
    words: list[str] = []
    for m in _HINT.finditer(text or ""):
        for w in re.findall(r"[a-z0-9]+", m.group(1).lower()):
            if w not in _HINT_SKIP and w not in words:
                words.append(w)
    return tuple(words)


def hint_matches(hint: Iterable[str], name: str, handle: str = "") -> bool:
    """True if no hint, or any hint word is in the agent's name or handle."""
    hint = tuple(hint)
    if not hint:
        return True
    tokens = set(re.findall(r"[a-z0-9]+", f"{name} {handle}".lower()))
    # Whole word, or the start of one ("tavily" in "TavilySearch"); "test" never in "latest".
    return any(w in tokens or (len(w) >= 4 and any(t.startswith(w) for t in tokens))
               for w in hint)


def last_mismatch(name: str, prehire: bool) -> str:
    ex = "`is weather-bot live?`" if prehire else "`audit weather-bot`"
    return (f"The last agent I checked for you is **{name}**, and that doesn't look like the one "
            f"you mean. Send the address, handle (no @) or Agentverse profile link of the agent "
            f"you want, e.g. {ex}.")
# Never a re-check request: questions about Doctor ("how do I re-check?", "what is a pre-hire
# check again"), deleting data, explaining, refusals, "check it out", "I'll check it later".
_NOT_RECHECK = re.compile(
    r"^\W*(?:(?:ok|okay|so|hey|hi|thanks?|thank you)\W+)*"
    r"(?:how|what|whats|when|why|where|which|who|does|did|do i|can i|could i|should i|"
    r"is there|are there)\b"
    r"|\b(?:delete|forget|erase|wipe|remove|clear|explain|don't|dont|do not|no need|never ?mind|"
    r"stop|i'll|i will|i'm going to|im going to|let me|later|tell me (?:about|more))\b"
    r"|\b(?:it|this|that) out\b", re.IGNORECASE)
_RE_VERB = re.compile(r"\bre-?(?:check|audit|scan|run|test|score|do)\w*", re.IGNORECASE)
# Guards apply per clause: "remove the bad keyword and re-check" is still a re-check.
_CLAUSE = re.compile(r"[,.;:!?]+|\s(?:and|then|but|just|so|now)\s", re.IGNORECASE)


def back_ref(text: str, wants_prehire: bool, has_audit: bool) -> str:
    """"any" (strong), "chat" (weak, needs an audit in this chat) or "" (not a back-reference)."""
    found = ""
    asked = False  # an earlier clause was a question: "what is X, again?", "what's Y? and Z"
    if _OTHER.intersection(name_hint(text)):
        return ""  # "check the other agent": not the last one
    # "the agent we were just auditing": "just" here is not a clause break.
    text = re.sub(r"\b(we|you|i|were|was|have|had|'ve)\s+just\b", r"\1", text, flags=re.I)
    for part in _CLAUSE.split(f" {text} "):
        part = part.strip()
        if not part:
            continue
        if _NOT_RECHECK.search(part):
            asked = True
            continue
        if asked and not (_RECHECK_VERB.search(part) or _RE_VERB.search(part)):
            continue  # after a question, only an explicit "re-check X" / "check it" counts
        weak = _BACK_WEAK.search(part)
        if _BACK_STRONG.search(part) or (_AGAIN.search(part) and (
                _RECHECK_VERB.search(part) or _AGENT_WORD.search(part) or weak)):
            return "any"
        if has_audit and (_VERB_ON_REF.search(part) or (weak and wants_prehire)):
            found = "chat"
    return found


# ---------- Q13 Agent Scout: "find me an agent that books flights" ----------
SCOUT_NEED_WHAT = ("What should the agent do? e.g. `find an agent that books flights` or "
                   "`is there an agent for crypto prices?`")
SCOUT_PICK_NONE = ("I don't have a recent agent search in this chat. Ask `find an agent that …` "
                   "first, e.g. `find an agent that books flights`.")


def scout_which(count: int, prehire: bool = False) -> str:
    """Q18: "audit it" right after a scout list, with no name: which listed agent?"""
    n = 2 if count >= 2 else 1
    first = f"`is #{n} live?` for a live test, or `audit #{n}` for a full report" if prehire \
        else f"`audit #{n}` for a full report, or `is #{n} live?` for a live test"
    return (f"Which agent from my list do you mean (1–{count})? Say {first}."
            if count > 1 else f"Do you mean the agent in my list? Say {first}.")


def scout_pick_short(n: int, count: int) -> str:
    s = "" if count == 1 else "s"
    return (f"I listed only {count} agent{s} in my last search, so there's no #{n}. "
            f"Try `audit #1`.")


_LEAD = (r"\b(?:find|search(?:\s+for)?|look(?:ing)?\s+for|need|want|recommend|suggest|"
         r"show\s+me|get\s+me|is\s+there|are\s+there|any|which|what|best|top|know(?:\s+of)?)\b")
# "and" = the common typo of "an" (prod 2026-11-05: "find and agent to help me manage my finances"
# got the help text).
_FILL = (r"(?:me|us|a|an|and|some|any|the|one|good|great|best|top|reliable|ai|really|other|new|"
         r"free)")
_SNOUN = r"(?:agents?|bots?)\b"
_VIA = (r"(?:\s+(?:should\s+i\s+(?:use|hire|pick)|do\s+you\s+recommend|would\s+you\s+recommend|"
        r"can\s+i\s+use|could\s+i\s+use|is\s+best|is\s+good|works\s+best))?")
_CONN = (r"(?:that|which|who|to|for|capable\s+of|able\s+to|good\s+at|"
         r"(?:can|could)(?!\s+(?:you|u|i|we|doctor|it)\b))")
_SCOUT_A = re.compile(_LEAD + r"(?:\s+" + _FILL + r"){0,3}\s+" + _SNOUN + _VIA + r"\s+" + _CONN
                      + r"\s+(?P<cap>.+)", re.IGNORECASE | re.DOTALL)
# Form B ("find me a weather agent") only after a request lead: "what is the number 1 agent"
# is a question, not a search.
_LEAD_B = (r"\b(?:find|search(?:\s+for)?|look(?:ing)?\s+for|need|want|recommend|suggest|"
           r"show\s+me|get\s+me|is\s+there|are\s+there|any|know\s+of)\b")
_SCOUT_B = re.compile(_LEAD_B + r"(?:\s+" + _FILL + r"){0,3}\s+(?P<cap>(?:(?!(?:my|our|your|this|that|is|are|was|were)\b)"
                      r"[\w'-]+\s+){1,4}?)" + _SNOUN + r"\s*(?:on\s+agentverse|please|pls)?\s*"
                      r"(?:[?.!,;:]|$)", re.IGNORECASE)
_CAP_CUT = re.compile(r"[?!\n]|\.(?:\s|$)")
_CAP_TAIL = re.compile(r"(?:\s+(?:please|pls|thanks|thank\s+you|for\s+me|on\s+agentverse|"
                       r"on\s+asi:?\s?one|in\s+agentverse))+\s*$", re.IGNORECASE)
_CAP_HEAD = re.compile(r"^(?:(?:can|could|will|does|do|is\s+able\s+to|helps?(?:\s+me)?(?:\s+to)?|"
                       r"use\s+(?:to|for))\s+)+", re.IGNORECASE)
_STOP = frozenset("a an the to of for me my i you your some any that which who can could will "
                  "would please with and or in on at from by is are be it this do does help "
                  "helps us we if whether".split())
_VAGUE = frozenset("good great best better top new nice cool smart ai real reliable working "
                   "live fast".split())
_CAP_RANK = re.compile(r"\b(?:rank\w*|found|discover\w*|visib\w*|picked|appear\w*)\b", re.I)
_CAP_AUDIT = re.compile(r"^(?:audit|scan|score|re-?check)\w*\b", re.I)
SCOUT_MAX_WORDS = 6
# An audit / Pre-Hire verb before the lead word means the message is about checking an agent.
_SCOUT_PREFIX_BAD = re.compile(r"\b(?:audit|scan|review|score|rate|fix|improve|analy[sz]e|"
                               r"pre-?hire|probe|ping|re-?check)\w*|\bcheck\w*", re.IGNORECASE)


def _capability(raw: str) -> Optional[str]:
    """Search phrase from the words after "an agent that ...". "" = nothing usable,
    None = this is not a scout request after all (ranking or audit wording)."""
    cap = _CAP_CUT.split(raw, maxsplit=1)[0]
    cap = _CAP_TAIL.sub("", cap.strip())
    cap = _CAP_HEAD.sub("", cap.strip())
    from agent.report import clean  # local: report imports nothing from router at load time
    cap = re.sub(r"\s+", " ", clean(cap, 120)).strip(" .,!?:;-'\"`").lower()
    if _CAP_RANK.search(cap) or _CAP_AUDIT.search(cap):
        return None
    if cap and " " not in cap and not cap.isascii():  # CJK etc.: one "word"
        return cap if 2 <= len(cap) <= 60 else ""
    words = [w.strip(".,!?:;'\"`") for w in cap.split(" ")]
    words = [w for w in words if w and w not in _STOP and w not in _VAGUE]
    return " ".join(words[:SCOUT_MAX_WORDS])


def scout_query(text: str) -> Optional[str]:
    """Q13: the search phrase of "find me an agent that books flights", "" if the request has
    no usable capability ("find me an agent"), None if this isn't a scout request."""
    t = text or ""
    for rx in (_SCOUT_A, _SCOUT_B):
        m = rx.search(t)
        if m:
            if _SCOUT_PREFIX_BAD.search(t[:m.start()]):
                return None  # "audit any agent for me", "I want to check which agent..."
            return _capability(m.group("cap"))
    if re.search(r"\b(?:find|recommend|suggest)\s+(?:me\s+)?(?:an?d?\s+|some\s+)?(?:good\s+)?"
                 + _SNOUN + r"\s*(?:on\s+agentverse)?\s*[?.!]*\s*$", t, re.I):
        return ""  # "find me an agent": a scout request without the what
    return None


_PICK_N = re.compile(r"(?<![\w&])#\s*([1-5])(?!\d)")
_PICK_MINE = re.compile(r"\b(?:my|our|your)\s+(?:\w+\s+)?(?:agents?|bots?)\b", re.IGNORECASE)
_PICK_HIRE = re.compile(r"\b(?:hire|test|live|alive|online|responding|reachable)\w*", re.IGNORECASE)
_PICK_AUDIT = re.compile(r"\b(?:audit|check|scan|review|score|analy[sz]e|re-?check)\w*",
                         re.IGNORECASE)


def scout_pick(text: str) -> Optional[Intent]:
    """Q13: "audit #2" / "is #1 live?" about this chat's last scout list."""
    m = _PICK_N.search(text)
    if not m or _PICK_MINE.search(text):
        return None
    n = int(m.group(1))
    if _PREHIRE.search(text) or _LIVE_Q.search(text) or _PICK_HIRE.search(text):
        return Intent("prehire", pick=n)
    if _PICK_AUDIT.search(text):
        return Intent("audit", pick=n)
    return None


@dataclass(frozen=True)
class Intent:
    kind: Kind
    targets: tuple[Target, ...] = ()
    n: int = 0  # fix_guide: which fix (1-based)
    key: str = ""  # faq: which FAQ
    # soft = the target is a guess (a handle mid-sentence). If Agentverse doesn't know it, the
    # service answers with `fallback` (what the message means without the guess) instead.
    soft: bool = False
    fallback: Optional["Intent"] = None
    # Q17: target = the last audited agent ("any": this chat, else this sender's latest;
    # "chat": this chat only). None remembered -> `fallback`.
    last: str = ""
    hint: tuple[str, ...] = ()  # Q17b: words naming the agent meant ("tavily")
    query: str = ""  # Q13 scout: the search phrase
    pick: int = 0  # Q13: "audit #2" = agent #2 of this chat's last scout list (1-based)
    fix: int = 0  # Q19 step: which fix guide ("step 2 of fix #1"); 0 = the last one shown


def classify(text: str, self_handles: Iterable[str] = (),
             self_addresses: Iterable[str] = (), has_audit: bool = False,
             has_scout: bool = False) -> Intent:
    """`has_audit`: this chat has a remembered audit, so a bare "#2" means fix #2.
    `has_scout` (Q13): this chat has a scout list, so "audit #2" means agent #2 of it."""
    text = (text or "").strip()
    self_addresses = tuple(a for a in self_addresses if a)
    ex = extract(text, ignore_handles=self_handles, ignore_addresses=self_addresses)
    wants_prehire = bool(_PREHIRE.search(text) or _LIVE_Q.search(text))
    if ex.targets:
        if wants_prehire:
            return Intent("prehire", ex.targets)
        return Intent("explain" if explain_wanted(text) else "audit", ex.targets)
    if ex.bad_address:
        return Intent("bad_address")
    for h in self_handles:  # "@agent-doctor hi" from ASI:One: judge the rest of the text
        text = re.sub(rf"@{re.escape(h.lstrip('@'))}(?![A-Za-z0-9_-])", " ", text, flags=re.I).strip()
    for a in self_addresses:  # "@<own address> ..." = ASI:One's first message of a new chat
        text = re.sub(rf"@{re.escape(a)}(?![0-9a-z])", " ", text, flags=re.I).strip()
    if not text:
        return Intent("help")
    if wants_forget(text):
        return Intent("forget")
    step = concepts.step_number(text)
    if step and has_audit and (_HOW.search(re.sub(r"\bsteps?\b", " ", text, flags=re.I))
                               or concepts.match_cue(text)
                               or len(re.findall(r"[A-Za-z0-9#]+", text)) <= FIX_SHORT_WORDS):
        # Q19: "explain step 2" (of the last fix guide, or "of fix #1")
        return Intent("step", n=step, fix=fix_number(text, False))
    n = fix_number(text, has_audit)
    if n:
        return Intent("fix_guide", n=n)
    if has_scout:
        p = scout_pick(text)
        if p is not None:
            return p
    q = scout_query(text)
    if q is not None:  # Q13: "find me an agent that books flights"
        return Intent("scout", query=q) if q else Intent("scout_need_what")
    if not wants_prehire and medical(text, soft_handles(text, self_handles)):  # Q24: before
        # data questions, FAQs and concepts; bare handles ("pill-reminder") are agents
        return Intent("medical")
    explain = explain_wanted(text)
    key = faq_key(text)
    base = _no_target(text)
    soft = soft_handles(text, self_handles)
    if soft and explain:  # "how many users does weather-bot have?": about that agent
        return Intent("explain", (Target("handle", soft[0]),), soft=True,
                      fallback=Intent("explain") if has_audit else base)
    if has_audit and key in ("", "score") and (explain or key == "score") and not wants_prehire \
            and not _AUDIT_CMD.search(text):
        return Intent("explain")  # about the last audit in this chat
    # Q19: "what do you mean by 'bring real users'?", "what is a Testing run?". FAQs win;
    # audits, fixes, scout and data questions about the last audit were matched above.
    ck = "" if key or wants_prehire or _AUDIT_CMD.search(text) else concepts.match(text)
    if ck:
        return Intent("concept", key=ck)
    # Q18: a scout list also gives "audit it" something to mean (the service asks which one).
    ref = "" if soft else back_ref(text, wants_prehire, has_audit or has_scout)
    if ref and not key:  # Q17: "re-check the same agent", "is it live?". FAQs win.
        return Intent("prehire" if wants_prehire else "audit", last=ref,
                      hint=name_hint(text),
                      fallback=(Intent("prehire_need_target") if wants_prehire
                                else Intent("recheck_none")) if ref == "any" else base)
    if soft:
        kind = "prehire" if wants_prehire else "audit"
        target = (Target("handle", soft[0]),)
        if handle_anchored(text, soft[0]):  # "my agent X", "handle is X", X alone: a firm target
            return Intent(kind, target)
        if base.kind != "off_scope":  # elsewhere: a guess, only in a message about agents
            return Intent(kind, target, soft=True, fallback=base)
    if base.kind in ("need_target", "help", "off_scope") and _STRONG_EXPLAIN.search(text):
        return Intent("explain_none")
    return base


def _no_target(text: str) -> Intent:
    """Intent of a message with no address or handle in it."""
    if _PREHIRE.search(text) and _AGENT_WORD.search(text) or (
            _LIVE_Q.search(text) and _AGENT_WORD.search(text)):
        return Intent("prehire_need_target")  # "pre-hire check", "is my agent live?"
    key = faq_key(text)
    if key:
        return Intent("faq", key=key)  # "how is the score calculated?", "how do I rank higher?"
    if _REQUEST.search(text) and _AGENT_WORD.search(text):
        return Intent("need_target")  # "audit my agent": about agents but no target yet
    if _AGENT_WORD.search(text) or _GREETING.search(text):
        return Intent("help")
    return Intent("off_scope")


def reply_for(kind: Kind) -> str:
    """Fixed reply for every non-audit, non-FAQ intent."""
    return {
        "help": HELP,
        "need_target": NEED_TARGET,
        "prehire_need_target": PREHIRE_NEED_TARGET,
        "bad_address": BAD_ADDRESS,
        "off_scope": OFF_SCOPE,
        "medical": MEDICAL,
        "explain_none": EXPLAIN_NONE,
        "recheck_none": RECHECK_NONE,
        "scout_need_what": SCOUT_NEED_WHAT,
        "scout_pick_none": SCOUT_PICK_NONE,
    }[kind]


def reply(intent: Intent) -> tuple[str, str]:
    """(reply text, log outcome) for an intent with no lookup to do."""
    if intent.kind == "faq":
        return FAQ[intent.key], f"faq_{intent.key}"
    if intent.kind == "medical":
        return MEDICAL, "off_scope_medical"
    return reply_for(intent.kind), intent.kind
