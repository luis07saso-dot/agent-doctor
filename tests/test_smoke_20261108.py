"""ASI:One smoke 2026-11-08 (prod 1e9b471e5d73) fixes.
1. "@agent-doctor audit @agent-doctor" -> off_scope (log shape "@<SELF_H> w @<SELF_H>").
2. "why this score?" after an audit -> the LLM mapped it to the Points concept (concept_points).
3. Live-test hint for an address-only agent: 66-char address in an italic quote."""
import json

import pytest

from agent import guides, llm, router
from agent.extract import extract
from agent.report import live_line
from tests import test_llm as T

ME = dict(ignore_handles=("agent-doctor",))
ADDR = T.STRONG


# ---------- 1. self-audit by @handle ----------

@pytest.mark.parametrize("text", ["@agent-doctor audit @agent-doctor", "audit @agent-doctor",
                                  "@agent-doctor check @agent-doctor please"])
def test_at_own_handle_after_audit_word_is_a_self_audit(text):
    assert [t.value for t in extract(text, **ME).targets] == ["agent-doctor"]
    assert router.classify(text, ["agent-doctor"]).kind == "audit"


def test_question_naming_own_handle_is_not_a_target():
    # Review nit: "is @x <liveness word>" stays as before (own @handle ignored), so
    # "how is @agent-doctor working?" never becomes a self-check.
    assert extract("@agent-doctor how is @agent-doctor working?", **ME).targets == ()


@pytest.mark.parametrize("text,kind", [
    ("@agent-doctor What can you do?", "help"),
    ("@agent-doctor", "help"),
    ("@agent-doctor audit my agent", "need_target"),
])
def test_leading_mention_is_still_not_a_target(text, kind):
    assert extract(text, **ME).targets == ()
    assert router.classify(text, ["agent-doctor"]).kind == kind


def test_at_other_handle_unchanged():
    assert [t.value for t in extract("@agent-doctor audit @weather-bot", **ME).targets] == [
        "weather-bot"]


# ---------- 2. "why this score?" = the full breakdown ----------

@pytest.mark.parametrize("text", ["why this score?", "@agent-doctor why this score?",
                                  "why is my score so low?", "explain the score",
                                  "Why did I get this score"])
def test_whole_score(text):
    assert router.whole_score(text)


@pytest.mark.parametrize("text", ["why did it lose points on README?", "why this score on Testing?",
                                  "what are points?", "why does it look so bad"])
def test_not_whole_score(text):
    assert not router.whole_score(text)


def _concept(name):
    return 200, {"choices": [{"message": {"content": json.dumps(
        {"ask": "explain", "check": "none", "topic": "none", "concept": name})}}]}


@pytest.mark.parametrize("text", ["why this score?", "@agent-doctor why this score?"])
def test_why_this_score_skips_llm(T_on, monkeypatch, text):
    shown = T.with_audit()
    m = T.use(monkeypatch, _concept("points"))
    r = T.say(text)
    assert r.outcome == "explain" and m._fetch.calls == []
    assert shown.rows[0].label in r.text and "Points and estimates" not in r.text


def test_other_explain_still_uses_llm(T_on, monkeypatch):
    T.with_audit()
    m = T.use(monkeypatch, _concept("points"))
    r = T.say("what do the numbers next to each line mean")
    assert len(m._fetch.calls) == 1 and r.outcome == "concept_points"


@pytest.fixture
def T_on(monkeypatch):
    monkeypatch.setenv("LLM_FOLLOWUP", "1")
    monkeypatch.setenv("ASI1_API_KEY", "test-key")
    monkeypatch.setattr(guides, "LAST", guides.LastAudit())
    monkeypatch.setenv("FINDABILITY", "0")


# ---------- 3. live hint ----------

def test_address_hint_is_code():
    line = live_line("multi", ADDR)
    assert f"`is {ADDR} live?`" in line and '"' not in line


def test_handle_hint_unchanged():
    assert live_line("multi", "weather-bot") == '_Live test: ask "is weather-bot live?" to test it._'
    assert '"is this agent live?"' in live_line("capped", "")
