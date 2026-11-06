"""Q23 (built as "Q19" in PR #2): prod issues seen in ASI:One on 2026-11-05 (screenshots in the private repo,
`prod-issues/`). Spec: docs/specs/q23-prod-issues.md.

1. 20:01 "@agent-doctor can i get banned for faking chats" after an audit of "bob": routed
   off_scope, the Q11 LLM mapped it to check=responsive, reply was "Responsive ... for bob:
   full marks". Fix: a fixed `rules` FAQ (beats the LLM), and the LLM prompt says such
   questions are "other".
2. 21:18 "@agent-doctor find and agent to help me manage my finances": the "and" typo missed
   Agent Scout and gave the help text. Fix: "and" accepted where "an" is.
"""
import pytest

from agent import llm, router
from agent.report import MAX_CHARS
from tests.test_llm import fresh, mapper, ok, on, say, use, with_audit  # noqa: F401

ME = ("agent-doctor",)


# ---------- 1. rules FAQ ----------

@pytest.mark.parametrize("text", [
    "@agent-doctor can i get banned for faking chats",
    "can i get banned for faking chats",
    "can I fake chats to rank higher?",
    "will my agent get suspended if I spam it",
    "can my agent get banned?",
    "is buying interactions allowed",
    "should i create multiple accounts to boost my rating",
    "how do I cheat the ranking",
    "is it against the terms of service to chat with my own agent",
    "is it ok to inflate my interactions",
    "does chatting with my own agent violate the terms of service?",
    "is that against the tos",
])
@pytest.mark.parametrize("has_audit", [False, True])
def test_rules_questions(text, has_audit):
    it = router.classify(text, ME, has_audit=has_audit)
    assert (it.kind, it.key) == ("faq", "rules")


@pytest.mark.parametrize("text,kind,key", [
    ("can i boost my ranking", "faq", "rank"),
    ("how do I improve my ranking?", "faq", "rank"),
    ("is Agent Doctor free?", "faq", "free"),
    ("is this agent fake?", "help", ""),
    ("what search terms should I use", "off_scope", ""),
    ("spam filter agent", "help", ""),
    ("how do I bake bread?", "off_scope", ""),
    # Q19 concepts (merged 2026-11-07): a README question gets the README explainer; not rules.
    ("how do I add a terms of service to my README", "concept", "readme"),
    ("is the terms of service in my README", "help", ""),
    ("find and audit agents", "need_target", ""),
])
def test_rules_does_not_steal(text, kind, key):
    it = router.classify(text, ME)
    assert (it.kind, it.key) == (kind, key)


def test_scout_for_fake_news_stays_scout():
    it = router.classify("find an agent that detects fake news", ME)
    assert it.kind == "scout" and it.query == "detects fake news"


def test_rules_reply_quotes_the_terms_and_fits():
    text = router.FAQ["rules"]
    assert len(text) <= MAX_CHARS
    assert "falsify the Company's rating" in text and "§22" in text
    assert "address" in text and "handle" in text  # ends with the next step like every FAQ


def test_prod_case_after_audit_gives_rules_not_llm_check(on, monkeypatch):
    """The exact prod sequence: an audit in the chat, LLM on and (wrongly) mapping to a check."""
    with_audit()
    m = use(monkeypatch, ok("explain", "responsive", "none"))
    r = say("@agent-doctor can i get banned for faking chats")
    assert m._fetch.calls == []  # FAQ wins before the LLM is asked
    assert (r.text, r.outcome) == (router.FAQ["rules"], "faq_rules")


def test_llm_prompt_routes_rules_questions_to_other():
    assert "terms of service" in llm.SYSTEM and "faking" in llm.SYSTEM


# ---------- 2. "find and agent" typo ----------

@pytest.mark.parametrize("text,query", [
    ("@agent-doctor find and agent to help me manage my finances", "manage finances"),
    ("find and agent that books flights", "books flights"),
    ("find a agent that books flights", "books flights"),
])
def test_and_typo_is_scout(text, query):
    it = router.classify(text, ME)
    assert (it.kind, it.query) == ("scout", query)


def test_and_typo_without_what():
    assert router.classify("find and agent", ME).kind == "scout_need_what"


def test_find_and_fix_is_not_scout():
    assert router.classify("find and fix my agent", ME).kind == "need_target"
