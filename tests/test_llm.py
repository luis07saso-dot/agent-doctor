"""Q11 guarded LLM follow-up. Spec: docs/specs/q11-llm-followup.md. Fake transport only."""
import asyncio
import json
from dataclasses import replace
from pathlib import Path

import pytest

from agent import agentverse as av
from agent import evidence, guides, llm, router, service
from agent import rubric as R
from agent.report import MAX_CHARS

FIX = Path(__file__).parent / "fixtures"
STRONG = "agent1qfvydlgcxrvga2kqjxhj3hpngegtysm2c7uk48ywdue0kgvtc2f5cwhyffv"
SELF = ("agent-doctor",)


def load(name) -> av.Lookup:
    d = json.loads((FIX / f"{name}.json").read_text())
    d.pop("captured_at", None)
    d["notes"] = tuple(d.get("notes") or ())
    return av.Lookup(**d)


def run(coro):
    return asyncio.run(coro)


def ok(ask="explain", check="none", topic="none"):
    return 200, {"choices": [{"message": {"content": json.dumps(
        {"ask": ask, "check": check, "topic": topic})}}]}


class Fake:
    def __init__(self, *responses, delay=0.0, exc=None):
        self.responses = list(responses) or [ok()]
        self.delay, self.exc, self.calls = delay, exc, []

    async def __call__(self, body, headers, timeout):
        self.calls.append((body, headers, timeout))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.exc:
            raise self.exc
        return self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv("LLM_FOLLOWUP", "1")
    monkeypatch.setenv("ASI1_API_KEY", "test-key")


def mapper(*responses, **kw):
    clock = kw.pop("clock", None) or Clock()
    return llm.Mapper(Fake(*responses, **{k: v for k, v in kw.items() if k in ("delay", "exc")}),
                      clock=clock, timeout=kw.get("timeout", llm.LLM_TIMEOUT_S)), clock


# ---------- mapper ----------

def test_off_by_default_in_tests():
    m, _ = mapper()
    assert run(m.map("why?")) == (None, "off") and m._fetch.calls == []


def test_switch_and_missing_key(on, monkeypatch):
    monkeypatch.setenv("LLM_FOLLOWUP", "0")
    assert not llm.enabled()
    monkeypatch.setenv("LLM_FOLLOWUP", "1")
    monkeypatch.delenv("ASI1_API_KEY")
    assert not llm.enabled()


def test_request_body_and_headers(on):
    m, _ = mapper(ok("explain", "rating", "rating"))
    text = f"why is {STRONG} rated low? see https://x.io/a " + "z" * 600
    f, label = run(m.map(text, "c1"))
    assert (f.ask, f.check, f.topic, label) == ("explain", "rating", "rating", "used")
    body, headers, timeout = m._fetch.calls[0]
    assert body["model"] == "asi1-mini" and body["temperature"] == 0
    assert body["enable_thinking"] is False and body["max_tokens"] == llm.MAX_TOKENS
    js = body["response_format"]["json_schema"]
    assert body["response_format"]["type"] == "json_schema" and js["strict"] is True
    sch = js["schema"]
    assert sch["additionalProperties"] is False and sch["required"] == ["ask", "check", "topic"]
    assert sch["properties"]["check"]["enum"] == list(R.WEIGHTS) + ["none"]
    user = body["messages"][1]["content"]
    assert STRONG not in user and "https://" not in user and "[agent]" in user and "[link]" in user
    assert len(user) <= llm.MAX_TEXT_CHARS
    assert headers["Authorization"] == "Bearer test-key" and timeout == llm.LLM_TIMEOUT_S


@pytest.mark.parametrize("resp", [
    (200, {"choices": [{"message": {"content": "not json"}}]}),
    (200, {"choices": [{"message": {"content": ""}}]}),
    (200, {"choices": [{"message": {"content": '{"ask": "explain", "check": "rat'}}]}),
    (200, {"choices": [{"message": {"content": json.dumps(
        {"ask": "explain", "check": "rating", "topic": "none", "x": 1})}}]}),
    (200, {"choices": [{"message": {"content": json.dumps(
        {"ask": "explain", "check": "score_hack", "topic": "none"})}}]}),
    (200, {"choices": []}), (200, {}), (200, None), (200, "x"),
])
def test_bad_output_falls_back(on, resp):
    m, _ = mapper(resp)
    assert run(m.map("why low?")) == (None, "fallback")


@pytest.mark.parametrize("status,off", [(400, llm.OFF_AUTH_S), (401, llm.OFF_AUTH_S),
                                        (402, llm.OFF_AUTH_S), (403, llm.OFF_AUTH_S),
                                        (429, llm.OFF_BUSY_S), (500, llm.OFF_BUSY_S),
                                        (502, llm.OFF_BUSY_S)])
def test_breaker(on, status, off):
    m, clock = mapper((status, {"error": {"message": "x"}}), ok("explain", "rating"))
    assert run(m.map("why low?")) == (None, "fallback")
    assert run(m.map("why low?")) == (None, "skip") and len(m._fetch.calls) == 1
    clock.t += off + 0.1
    f, label = run(m.map("why low?"))
    assert label == "used" and not m.open()


def test_timeout_and_exception(on):
    m, _ = mapper(delay=1.0, timeout=0.05)
    assert run(m.map("why low?")) == (None, "fallback") and m.open()
    m2, _ = mapper(exc=RuntimeError("secret"))
    assert run(m2.map("why low?")) == (None, "fallback")


def test_other_or_nothing_is_none(on):
    for resp in (ok("other", "rating", "none"), ok("fix", "none", "none")):
        m, _ = mapper(resp)
        assert run(m.map("how do I fix my car"))[1] == "none"


def test_chat_cooldown_and_concurrency(on):
    m, clock = mapper(ok("explain", "rating"))
    assert run(m.map("why low?", "c1"))[1] == "used"
    assert run(m.map("why low?", "c1"))[1] == "skip"
    assert run(m.map("why low?", "c2"))[1] == "used"
    clock.t += llm.CHAT_COOLDOWN_S
    assert run(m.map("why low?", "c1"))[1] == "used"
    m._busy = llm.MAX_CONCURRENT
    assert run(m.map("why low?", "c3"))[1] == "skip"


def test_parallel_calls_capped(on):
    m, _ = mapper(ok("explain", "rating"), delay=0.05)

    async def go():
        return await asyncio.gather(*(m.map("why low?", f"c{i}") for i in range(6)))
    labels = [x[1] for x in run(go())]
    assert labels.count("used") == llm.MAX_CONCURRENT and labels.count("skip") == 2


def test_system_prompt_lists_every_check():
    assert all(rule in llm.SYSTEM for rule in R.WEIGHTS)


# ---------- service ----------

@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.setattr(guides, "LAST", guides.LastAudit())
    monkeypatch.setenv("FINDABILITY", "0")


class Client:
    async def lookup(self, a):
        return replace(load("weak"), address=STRONG)

    async def lookup_handle(self, h):
        return av.Lookup(query=h, outcome="not_found")


def say(text, chat="c1"):
    return run(service.handle(text, Client(), SELF, (), chat_key=chat, sender_key="s1"))


def with_audit():
    say(f"audit {STRONG}")
    return guides.LAST.get("c1")


def use(monkeypatch, *responses):
    m, clock = mapper(*responses)
    monkeypatch.setattr(llm, "MAPPER", m)
    return m


def test_why_question_gets_focus_and_topic(on, monkeypatch):
    shown = with_audit()
    m = use(monkeypatch, ok("explain", "rating", "users"))
    r = say("why does it look so bad")
    assert (r.outcome, r.llm) == ("explain", "used") and len(m._fetch.calls) == 1
    assert "no unique-user count" in r.text
    row = next(x for x in shown.rows if x.rule == "rating")
    assert evidence.row_line(row) in r.text
    assert r.text.index(evidence.row_line(row)) < r.text.index("Found = ")


def test_fix_of_a_top_fix_equals_fix_guide(on, monkeypatch):
    shown = with_audit()
    rule = shown.fixes[1].rule
    use(monkeypatch, ok("fix", rule, "none"))
    r = say("hmm and what about that second thing you said")
    assert (r.outcome, r.llm) == ("fix_guide", "used")
    assert r.text == say("how do I fix #2").text


def test_fix_of_other_check(on, monkeypatch):
    shown = with_audit()
    top = {c.rule for c in shown.fixes}
    lost = next(x for x in shown.rows if x.kind != "ok" and x.rule not in top)
    use(monkeypatch, ok("fix", lost.rule, "none"))
    r = say("how can I improve that bit then")
    assert (r.outcome, r.llm) == ("explain", "used") and lost.label in r.text
    how = guides.SHORT.get(lost.rule) or guides.README_HOW
    assert how in r.text


def test_fix_of_full_marks_check(on, monkeypatch):
    shown = with_audit()
    full = next(x for x in shown.rows if x.kind == "ok")
    use(monkeypatch, ok("fix", full.rule, "none"))
    r = say("how can I improve that bit then")
    assert "full marks" in r.text and "nothing to fix" in r.text and "How:" not in r.text


@pytest.mark.parametrize("rule", ["readme", "readme_sections"])
def test_focus_reply_readme_rules_have_how(rule):
    shown = guides.Shown("A", STRONG, (), 50, "x",
                         (evidence.Row(rule, router.RULE_NAMES[rule], 0, 10, "found", "short"),))
    assert guides.README_HOW in evidence.focus_reply(shown, shown.rows[0])


@pytest.mark.parametrize("ask", ["explain", "fix"])
@pytest.mark.parametrize("rule", list(R.WEIGHTS))
def test_every_reply_fits(on, monkeypatch, ask, rule):
    with_audit()
    use(monkeypatch, ok(ask, rule, "users"))
    r = say("tell me about this part please")
    assert r.llm == "used" and len(r.text) <= MAX_CHARS


MUST_NOT_CHANGE = [  # existing help / off_scope strings (tests/test_chat.py, tests/test_guides.py)
    "@agent-doctor what is the capital of France?", "how do I fix my car",
    "check the weather in Paris", "what's the capital of France?", "write me a poem about cats",
    "bitcoin price now", "how do I bake bread?", "fix 2 bugs in my code",
    "help me with the first point of my essay", "I have 2 agents",
    "what is the number 1 agent on agentverse", "step 1 of my plan is cooking pasta",
]


@pytest.mark.parametrize("text", MUST_NOT_CHANGE)
@pytest.mark.parametrize("resp", [ok("other"), ok("fix", "none", "none"),
                                  (429, None), (500, None)])
def test_unrelated_text_unchanged(on, monkeypatch, text, resp):
    with_audit()
    monkeypatch.setenv("LLM_FOLLOWUP", "0")
    before = say(text)
    monkeypatch.setenv("LLM_FOLLOWUP", "1")
    use(monkeypatch, resp)
    after = say(text)
    assert (after.text, after.outcome) == (before.text, before.outcome)
    assert after.llm in ("none", "fallback", "")


@pytest.mark.parametrize("text", ["hi", "thanks!", "what can you do?", "why?",
                                  "how do I fix #1", f"audit {STRONG}", "how is the score calculated",
                                  "find an agent that books flights", "forget",
                                  "how many unique users does it have?"])
def test_not_asked(on, monkeypatch, text):
    with_audit()
    m = use(monkeypatch, ok("explain", "rating"))
    r = say(text)
    assert m._fetch.calls == [] and r.llm in ("", "off")


def test_not_asked_without_audit(on, monkeypatch):
    m = use(monkeypatch, ok("explain", "rating"))
    r = say("why does it look so bad")
    assert m._fetch.calls == [] and r.llm == ""


def test_llm_off_same_reply_byte_for_byte(on, monkeypatch):
    with_audit()
    monkeypatch.setenv("LLM_FOLLOWUP", "0")
    a = say("why does it look so bad")
    monkeypatch.setenv("LLM_FOLLOWUP", "1")
    use(monkeypatch, (503, None))
    b = say("why does it look so bad")
    assert a.text == b.text and (a.llm, b.llm) == ("off", "fallback")


def test_format_explain_defaults_unchanged():
    shown = with_audit()
    assert evidence.format_explain(shown, "why") == evidence.format_explain(shown, "why", (), "")


def test_chat_logs_llm_label_not_text(on, monkeypatch):
    from agent import chat
    from tests.test_chat import FakeCtx
    from uagents_core.contrib.protocols.chat import ChatMessage, TextContent
    monkeypatch.setattr(chat, "CLIENT", Client())
    monkeypatch.setattr(chat, "GUARD", chat.Guard())
    use(monkeypatch, ok("explain", "rating", "none"))
    ctx = FakeCtx()

    def send(t):
        run(chat.on_chat(ctx, "user1", ChatMessage(content=[TextContent(text=t)])))
    send(f"audit {STRONG}")
    send("why does it look so bad")
    req = [m for m in ctx.logs if m.startswith("REQ ")][-1]
    rec = json.loads(req[4:])
    assert rec["llm"] == "used" and rec["outcome"] == "explain"
    assert "bad" not in req and "rating" not in req
