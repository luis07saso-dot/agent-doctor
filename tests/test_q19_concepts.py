"""Q19: in-scope questions get a real answer (concept explainers, "explain step N"); off-topic
small talk is still refused. Fake LLM transport only."""
import json

import pytest

from agent import concepts, guides, llm, router, service
from agent.report import MAX_CHARS
from tests.test_llm import STRONG, mapper, on, say, with_audit  # noqa: F401  (on = fixture)

ME = ("agent-doctor",)


def ok4(ask="general", check="none", topic="none", concept="none"):
    return 200, {"choices": [{"message": {"content": json.dumps(
        {"ask": ask, "check": check, "topic": topic, "concept": concept})}}]}


def use(monkeypatch, *responses):
    m, _ = mapper(*responses)
    monkeypatch.setattr(llm, "MAPPER", m)
    return m


# ---------- the reported case (user screenshots 2026-11-05) ----------

def test_bring_real_users_after_fix_guide_is_answered():
    with_audit()
    say("how do I fix #2")  # rating guide: step 3 = "Bring real users: ..."
    r = say("@agent-doctor what do you mean by 'bring real users'?")
    assert r.outcome == "concept_real_users"
    assert "**Real users**" in r.text and "Discord" in r.text
    assert "Why Agent scored" not in r.text  # not the whole score breakdown any more


def test_off_topic_small_talk_still_refused(on, monkeypatch):  # noqa: F811
    with_audit()
    use(monkeypatch, ok4("other"))
    r = say("@agent-doctor how was your day today?")
    assert r.outcome == "off_scope" and r.text.startswith("I only audit Agentverse agents")


@pytest.mark.parametrize("text,key", [
    ("what do you mean by 'bring real users'?", "real_users"),
    ("how do I get real users?", "real_users"),
    ("what is a testing run?", "testing"),
    ("how do I generate questions in the testing tab?", "testing"),
    ("what does needs attention mean?", "needs_attention"),
    ("what is manual test?", "manual_test"),
    ("what counts as an interaction?", "interactions"),
    ("what are verified chats?", "verified_chats"),
    ("what does unresponsive mean?", "unresponsive"),
    ("what is the chat protocol?", "chat_protocol"),
    ("what's a starter prompt?", "starter_prompts"),
    ("what does found and tip mean?", "found_tip"),
    ("what is ASI:One?", "asi_one"),
    ("what are scripted chats?", "fake_chats"),  # "fake chats" + why/can I = Q23 rules FAQ
    ("what is website verification?", "website"),
])
def test_concept_questions_without_audit(text, key):
    assert router.classify(text, ME).kind == "concept"
    assert router.classify(text, ME).key == key
    r = say(text)
    assert r.outcome == f"concept_{key}" and len(r.text) <= MAX_CHARS


@pytest.mark.parametrize("text,kind", [
    ("how do I fix #1", "fix_guide"),
    ("how is the score calculated?", "faq"),
    ("how do I rank higher?", "faq"),
    ("is it free?", "faq"),
    ("is my agent live?", "prehire_need_target"),
    ("what is pre-hire check?", "prehire_need_target"),
    ("how do I bake bread?", "off_scope"),
    ("what's the capital of France?", "off_scope"),
    ("how was your day today?", "off_scope"),
    ("find an agent that books flights", "scout"),
    (f"what is the rating of {STRONG}?", "explain"),
])
def test_other_routes_unchanged(text, kind):
    assert router.classify(text, ME).kind == kind


@pytest.mark.parametrize("text,concept", [
    # common words count only next to an agent-context word ("what is the rating" = a movie?)
    ("what is the rating?", False),
    ("what does responsive mean?", False),
    ("what is a description?", False),
    ("what is my agent's rating?", True),
    ("how do I add an avatar to my agent?", True),
])
def test_common_words_need_agent_context(text, concept):
    assert (router.classify(text, ME).kind == "concept") is concept


def test_rules_faq_beats_fake_chats_concept():
    # Q23 (merged 2026-11-07): FAQs win over concepts; the rules FAQ is the fuller answer
    assert router.classify("why shouldn't I script fake chats?", ME).key == "rules"


def test_data_question_with_audit_stays_explain():
    assert router.classify("why is my rating so low?", ME, has_audit=True).kind == "explain"
    assert router.classify("what is the success rate?", ME, has_audit=True).kind == "explain"


def test_concept_with_audit_adds_that_agents_line():
    shown = with_audit()
    r = say("what does unresponsive mean?")
    row = next(x for x in shown.rows if x.rule == "responsive")
    assert r.outcome == "concept_unresponsive" and f"For {shown.name}:" in r.text
    assert row.label in r.text and "Open profile on Agentverse" in r.text


# ---------- "explain step N" ----------

def test_step_of_last_fix_guide_explains_its_term():
    shown = with_audit()
    k = 1 + [c.rule for c in shown.fixes].index("rating")
    say(f"how do I fix #{k}")
    r = say("can you explain step 3?")
    assert r.outcome == "step" and f"**Fix #{k}, step 3:** Bring real users" in r.text
    assert "**Real users**" in r.text
    r1 = say("what does step 1 mean?")
    assert "Testing tab" in r1.text and "**Agentverse Testing runs**" in r1.text
    assert "Needs attention" in say("explain the second step").text


def test_step_of_named_fix_and_bounds():
    shown = with_audit()
    k = 1 + [c.rule for c in shown.fixes].index("rating")
    r = say(f"explain step 2 of fix #{k}")
    assert r.outcome == "step" and f"Fix #{k}, step 2" in r.text
    assert "has 4 steps" in say(f"explain step 9 of fix #{k}").text
    assert "fake chats" in say("explain the last step").text  # step 4 of the last guide (#k)


def test_step_without_guide_or_audit():
    assert router.classify("explain step 2", ME).kind != "step"  # no audit: not a step question
    with_audit()
    r = say("explain step 2")
    assert r.outcome == "step_none" and r.text.startswith("Which steps?")


def test_step_words_in_other_sentences_are_not_steps():
    assert router.classify("step 1 of my plan is cooking pasta", ME, has_audit=True).kind \
        != "step"


def test_forget_clears_last_guide():
    with_audit()
    say("how do I fix #1")
    say("forget")
    assert "c1" not in service._LAST_FIX


def test_guide_of_older_agent_is_not_used(monkeypatch):
    shown = with_audit()
    say("how do I fix #1")
    service._LAST_FIX["c1"] = (1, "agent1qsomeotheragent")
    assert service.last_fix("c1", shown) == 0


# ---------- the model's concept pick (Q11 mapper, Q19 field) ----------

def test_llm_concept_pick_after_audit(on, monkeypatch):  # noqa: F811
    with_audit()
    m = use(monkeypatch, ok4("general", "rating", "users", "real_users"))
    r = say("so the people bit, any ideas")
    assert (r.outcome, r.llm) == ("concept_real_users", "used") and len(m._fetch.calls) == 1


def test_llm_concept_pick_without_audit(on, monkeypatch):  # noqa: F811
    use(monkeypatch, ok4("general", concept="testing"))
    r = say("so those question sets, are they any good")
    assert (r.outcome, r.llm) == ("concept_testing", "used")


def test_llm_general_without_concept_says_what_i_can_explain(on, monkeypatch):  # noqa: F811
    use(monkeypatch, ok4("general"))
    r = say("is it better than other places to list stuff")
    assert (r.outcome, r.llm) == ("unsure", "used") and "not sure" in r.text


def test_llm_general_on_help_keeps_help(on, monkeypatch):  # noqa: F811
    use(monkeypatch, ok4("general"))
    r = say("what can agent doctor do for my agent")
    assert r.outcome == "help" and r.llm == "none"


def test_llm_fix_pick_still_beats_concept(on, monkeypatch):  # noqa: F811
    shown = with_audit()
    k = 1 + [c.rule for c in shown.fixes].index("description")
    use(monkeypatch, ok4("fix", "description", "none", "description"))
    r = say("ok but how do i sort that blurb thing out")
    assert r.outcome == "fix_guide" and f"Fix #{k}" in r.text


def test_llm_gets_last_guide_as_context(on, monkeypatch):  # noqa: F811
    with_audit()
    say("how do I fix #2")
    m = use(monkeypatch, ok4("general", concept="real_users"))
    say("hmm what do you mean by that one")
    user = m._fetch.calls[0][0]["messages"][1]["content"]
    assert user.startswith("Doctor's last reply (context):") and "Bring real users" in user
    assert user.endswith("hmm what do you mean by that one")
    assert "agent1q" not in user  # addresses scrubbed


def test_llm_three_key_answer_still_parses():
    f = llm.parse(200, {"choices": [{"message": {"content": json.dumps(
        {"ask": "explain", "check": "rating", "topic": "none"})}}]})
    assert f is not None and f.concept == "none"
    assert llm.parse(200, {"choices": [{"message": {"content": json.dumps(
        {"ask": "explain", "check": "rating", "topic": "none", "concept": "bogus"})}}]}) is None


def test_schema_concepts_match_module():
    sch = llm.SCHEMA["properties"]["concept"]["enum"]
    assert set(sch) == set(concepts.CONCEPTS) | {"none"}


# ---------- every fixed answer ----------

@pytest.mark.parametrize("key", list(concepts.CONCEPTS))
def test_every_concept_fits_with_and_without_audit(key):
    shown = with_audit()
    for s in (None, shown):
        t = concepts.reply(key, s)
        assert len(t) <= MAX_CHARS and t.startswith(f"**{concepts.CONCEPTS[key].title}**")


@pytest.mark.parametrize("key", list(concepts.CONCEPTS))
def test_every_concept_has_a_rule_match(key):
    # its own title, asked as a question, routes to it (or to a more specific concept first)
    assert concepts.term(concepts.CONCEPTS[key].title) != ""


def test_every_guide_step_fits():
    shown = with_audit()
    for i, c in enumerate(shown.fixes, 1):
        for step in range(1, len(guides.guide_parts(c)[1]) + 1):
            assert len(concepts.step_reply(step, i, c, shown)) <= MAX_CHARS
