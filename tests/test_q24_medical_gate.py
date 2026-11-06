"""Q24: medical questions never get an Agentverse explainer or audit data ("what is a drug
interaction?" is not about Agentverse interactions); "interaction" and "unresponsive" need a
context word. Spec: docs/specs/q24-off-topic-gate.md. Fake LLM transport only."""
import pytest

from agent import llm, router
from agent.report import MAX_CHARS
from tests.test_llm import STRONG, say, with_audit  # noqa: F401
from tests.test_q19_concepts import ME, ok4, use
from tests.test_llm import on  # noqa: F401  (fixture)

MEDICAL = [
    "what is a drug interaction?",                                   # P1
    "what does it mean when a patient is unresponsive?",             # P2
    "what does the patient being unresponsive mean?",
    "what is the active agent in ibuprofen?",                        # P3
    "what does it mean if my wound needs attention?",                # P4
    "what is a manual test for muscle strength?",                    # P5
    "what are drug interactions between ibuprofen and aspirin?",     # P7
    "what is the success rate of knee surgery?",                     # P8
    "explain the side effects of interactions with alcohol",
    "what is a contrast agent in an MRI?",
    "what's an infectious agent?",
    "how many pills is a safe dose?",
    "is it ok to take vitamins with antibiotics?",
    "@agent-doctor what does unresponsive mean for a patient?",
]


@pytest.mark.parametrize("has_audit", [False, True])
@pytest.mark.parametrize("text", MEDICAL)
def test_medical_questions_are_refused(text, has_audit):
    assert router.classify(text, ME, has_audit=has_audit).kind == "medical"


@pytest.mark.parametrize("text", MEDICAL[:3])
def test_medical_reply_no_model_call(text, on, monkeypatch):  # noqa: F811
    with_audit()
    m = use(monkeypatch, ok4("general", concept="interactions"))
    r = say(text)
    assert r.outcome == "off_scope_medical" and r.llm == "" and m._fetch.calls == []  # not asked
    assert "not people" in r.text and "health professional" in r.text
    assert "find an agent that" in r.text and len(r.text) <= MAX_CHARS


@pytest.mark.parametrize("text,kind", [
    # strong Agentverse words keep normal routing
    ("what does unresponsive mean for my agent?", "concept"),
    ("what counts as an interaction on agentverse?", "concept"),
    ("my pharmacy agent gives dose advice, what counts as an interaction for it?", "concept"),
    ("what does a drug interaction mean for my agent's README?", "concept"),
    # Scout, audit and Pre-Hire come first
    ("find an agent that checks drug interactions", "scout"),
    ("find me an agent for medication reminders", "scout"),
    (f"audit {STRONG} it gives medical advice", "audit"),
    ("is the pharmacy-bot live?", "prehire"),
])
def test_strong_words_and_earlier_routes_win(text, kind):
    assert router.classify(text, ME).kind == kind


@pytest.mark.parametrize("text", [
    "what is the active status of my agent?", "what are active agents?",
    "what is the doctor's score?", "how do I fix #1", "what is a testing run?",
    "what are pain points for agent builders?",
    # self-review 2026-11-07: idioms, Doctor's metaphor, AI terms
    "what's at the heart of the ranking?", "what are the side effects of fake chats?",
    "what are the symptoms of a low ranking?", "what is data poisoning?",
    "what are toxic prompts?", "what are the ingredients of a good agent profile?",
    "I'm sick of bleeding edge agents", "what is a psychological evaluation?",
])
def test_agent_talk_is_not_medical(text):
    assert not router.medical(text)


@pytest.mark.parametrize("text,kind", [
    # bare handles with medical words are agents, not medical questions (self-review 2026-11-07)
    ("how many users does pill-reminder have?", "explain"),
    ("what is the rating of drug-checker", "explain"),
    ("is pill-reminder any good?", "off_scope"),
])
def test_bare_handles_with_medical_words_are_agents(text, kind):
    assert router.classify(text, ME).kind == kind


@pytest.mark.parametrize("text", ["what counts as an interaction?", "what does unresponsive mean?"])
def test_bare_words_need_context_now(text):
    assert router.classify(text, ME).kind == "off_scope"  # LLM off: the refusal
    assert router.classify(text, ME, has_audit=True).kind == "off_scope"


@pytest.mark.parametrize("text,key", [
    ("what counts as an interaction in a chat?", "interactions"),
    ("what does unresponsive mean in a conversation?", "unresponsive"),
    ("what you mean by unresponsive?", "unresponsive"),
])
def test_docs_context_words_count(text, key):
    it = router.classify(text, ME)
    assert (it.kind, it.key) == ("concept", key)


def test_bare_word_may_still_get_the_concept_from_the_model(on, monkeypatch):  # noqa: F811
    with_audit()
    use(monkeypatch, ok4("general", concept="unresponsive"))
    r = say("what does unresponsive mean?")
    assert (r.outcome, r.llm) == ("concept_unresponsive", "used")


def test_bare_doctor_is_not_agent_context():
    assert router.classify("doctor, what is a rating?", ME).kind != "concept"


def test_prompt_sends_health_questions_to_other():
    assert "Health, medicine, drugs or patients" in llm.SYSTEM
