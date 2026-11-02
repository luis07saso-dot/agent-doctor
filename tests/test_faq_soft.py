"""Canned FAQ replies, handles mid-sentence ("soft" targets), and the "showing up" misroute.

Root causes (2026-11-03, docs/debug-router.md):
- "What does Agent Doctor check?" / "How can I rank higher?" hit need_target: a request verb
  ("check", "rank") plus an agent word, with no intent for questions about Doctor itself.
- "my agent ticketlens-agent is ..." gave help: bare handles were read only right after an
  audit word, so a handle anywhere else in the sentence was ignored.
- "why is X not showing up?" read "up" as a liveness word (Pre-Hire wording).
"""
import asyncio

import pytest

from agent import agentverse as av
from agent import rubric as R
from agent import router, service
from agent.extract import soft_handles
from agent.report import MAX_CHARS
from tests.test_chat import FakeClient

ME = ["agent-doctor"]


# ---------- FAQ ----------

@pytest.mark.parametrize("text,key", [
    ("How is the score calculated?", "score"),
    ("how do you score agents?", "score"),
    ("What does the score mean?", "score"),
    ("how are scores worked out", "score"),
    ("What does Agent Doctor check?", "checks"),
    ("what do you check?", "checks"),
    ("What do you look at?", "checks"),
    ("what does the audit check?", "checks"),
    ("How can I rank higher on Agentverse?", "rank"),
    ("how do I rank higher", "rank"),
    ("how do I improve my ranking?", "rank"),
    ("how do I get more picks on ASI:One?", "rank"),
    ("why is my agent not ranking?", "rank"),
    ("tips to rank my agent", "rank"),
    ("why is my agent not showing up in ASI:One search?", "rank"),
    ("Is Agent Doctor free?", "free"),
    ("how much does it cost?", "free"),
    ("do I have to pay?", "free"),
])
def test_faq_intents(text, key):
    it = router.classify(text, ME)
    assert (it.kind, it.key) == ("faq", key)


@pytest.mark.parametrize("text,kind", [
    ("audit my agent", "need_target"),
    ("score my agent", "need_target"),
    ("check the Weather Agent please", "need_target"),
    ("what can you do?", "help"),
    ("how does this work?", "help"),
    ("is my agent live?", "prehire_need_target"),
    ("what is pre-hire check?", "prehire_need_target"),
    ("how do I bake bread?", "off_scope"),
    ("what's the capital of France?", "off_scope"),
    ("bitcoin price now", "off_scope"),
])
def test_non_faq_unchanged(text, kind):
    assert router.classify(text, ME).kind == kind


def test_fix_followup_beats_faq():
    assert router.classify("how do I fix #1", ME, has_audit=True).kind == "fix_guide"


def test_faq_replies_fit_and_end_with_a_next_step():
    for key, text in router.FAQ.items():
        assert text and len(text) <= MAX_CHARS, key
        assert "address" in text and "handle" in text, key


def test_faq_score_lists_every_rule_with_its_weight():
    text = router.FAQ["score"]
    assert set(router.RULE_NAMES) == set(R.WEIGHTS)
    for rule, w in R.WEIGHTS.items():
        assert f"{router.RULE_NAMES[rule]} {int(w)}" in text, rule
    for _, verdict in R.VERDICTS:
        assert verdict.split(",")[0] in text


def test_faq_free_says_free():
    assert router.FAQ["free"].startswith("Yes")


def test_service_faq_reply_and_outcome():
    c = FakeClient()
    res = asyncio.run(service.handle("How is the score calculated?", c, ME))
    assert res.text == router.FAQ["score"] and res.outcome == "faq_score" and c.calls == []


# ---------- handles mid-sentence (soft targets) ----------

@pytest.mark.parametrize("text,kind", [
    ("my agent ticketlens-agent is not getting picks", "audit"),
    ("ticketlens-agent isn't ranking", "audit"),
    ("why is ticketlens-agent not showing up?", "audit"),
    ("can you look at ticketlens-agent", "audit"),
    ("help with ticketlens-agent", "audit"),
    ("what's wrong with ticketlens-agent?", "audit"),
    ("my agent is ticketlens-agent", "audit"),
    ("my handle is ticketlens-agent", "audit"),
    ("ticketlens-agent", "audit"),
    ("Ticketlens-Agent.", "audit"),
    ("here's my agent: ticketlens-agent", "audit"),
    ("my agent called ticketlens-agent has a low score", "audit"),
    ("how can ticketlens-agent rank higher?", "audit"),
    ("ticketlens-agent score?", "audit"),
    ("why is ticketlens-agent not responding?", "prehire"),
])
def test_soft_handle_mid_sentence(text, kind):
    it = router.classify(text, ME)
    assert it.kind == kind and it.soft
    assert [t.value for t in it.targets] == ["ticketlens-agent"]


def test_hard_targets_are_not_soft():
    it = router.classify("audit my agent ticketlens-agent", ME)
    assert it.kind == "audit" and not it.soft
    assert not router.classify("is ticketlens-agent live?", ME).soft


@pytest.mark.parametrize("text", [
    "give me a step-by-step guide",     # off-scope text: never guessed
    "is it real-time?",
    "my agent is state-of-the-art",     # common hyphenated word
    "how do I write a how-to readme",
    "what is pre-hire check?",
    "what does agent-doctor check?",    # our own handle
    "@agent-doctor what can you do?",
    "my agent was updated 2026-11-03",  # dates are not handles
    "check https://example.com/foo-bar",
    "my agent runs 24-7",
])
def test_soft_handle_not_guessed(text):
    it = router.classify(text, ME)
    assert not it.soft and it.targets == ()


def test_soft_handles_takes_first_candidate_only():
    assert soft_handles("compare weather-bot and trip-planner agents", ME) == ("weather-bot",)


def test_check_my_email_is_not_a_handle():
    it = router.classify("check my e-mail", ME)
    assert it.targets == ()


@pytest.mark.parametrize("outcome", ["not_found", "invalid", "timeout", "api_down", "weird"])
def test_soft_miss_falls_back_to_the_plain_reply(outcome):
    c = FakeClient(outcome)
    res = asyncio.run(service.handle("my agent ticketlens-agent is not getting picks", c, ME))
    assert c.calls == ["@ticketlens-agent"]
    assert res.text == router.HELP and res.outcome == "help" and res.input_type == "soft_miss"


def test_soft_miss_on_faq_question_gives_the_faq():
    c = FakeClient("not_found")
    res = asyncio.run(service.handle("how can my-new-bot rank higher?", c, ME))
    assert res.text == router.FAQ["rank"] and res.outcome == "faq_rank"


def test_soft_hit_audits():
    c = FakeClient("ok")
    res = asyncio.run(service.handle("my agent ticketlens-agent is not getting picks", c, ME))
    assert c.calls == ["@ticketlens-agent"] and res.outcome == "ok" and "Score " in res.text
    assert res.input_type == "handle"


def test_soft_prehire_miss_falls_back():
    async def prehire(target):
        return "couldn't find it", "not_found"
    c = FakeClient()
    res = asyncio.run(service.handle("why is my-new-bot not responding?", c, ME, prehire=prehire))
    assert res.input_type == "soft_miss" and res.text == router.PREHIRE_NEED_TARGET


def test_soft_prehire_hit():
    async def prehire(target):
        return f"{target.value} is live", "live"
    res = asyncio.run(service.handle("why is my-new-bot not responding?", FakeClient(), ME,
                                     prehire=prehire))
    assert res.outcome == "prehire_live" and "my-new-bot is live" in res.text


# ---------- "showing up" is not a liveness word ----------

@pytest.mark.parametrize("text", [
    "why is my agent not showing up?",
    "my agent doesn't come up in search",
    "is my agent popping up anywhere?",
])
def test_showing_up_is_not_prehire(text):
    assert router.classify(text, ME).kind != "prehire_need_target"


def test_is_it_up_is_still_prehire():
    assert router.classify("is my agent up?", ME).kind == "prehire_need_target"
