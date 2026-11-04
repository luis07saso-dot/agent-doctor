"""L5: router intents, service error paths, guard, and the chat handler end to end (fake ctx)."""
import asyncio
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    EndSessionContent,
    MetadataContent,
    ResourceContent,
    StartSessionContent,
    TextContent,
)

from agent import agentverse as av
from agent import chat, guard, router, service
from agent.report import MAX_CHARS

FIX = Path(__file__).parent / "fixtures"
STRONG = "agent1qfvydlgcxrvga2kqjxhj3hpngegtysm2c7uk48ywdue0kgvtc2f5cwhyffv"
WEAK = "agent1qtxyynz433g33av2f0000k489xx6r590vfk6gcs0c2c2n6vnpc0nxehvvpm"


def fixture_lookup(name) -> av.Lookup:
    d = json.loads((FIX / f"{name}.json").read_text())
    d.pop("captured_at", None)
    d["notes"] = tuple(d.get("notes") or ())
    return av.Lookup(**d)


class FakeClient:
    """Returns a fixed outcome; records calls."""

    def __init__(self, outcome="ok", fixture="strong", delay=0.0, raise_exc=False):
        self.outcome, self.fixture, self.delay, self.raise_exc = outcome, fixture, delay, raise_exc
        self.calls = []

    async def _result(self, query):
        self.calls.append(query)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.raise_exc:
            raise RuntimeError("boom")
        if self.outcome in ("ok", "partial"):
            return replace(fixture_lookup(self.fixture), outcome=self.outcome)
        return av.Lookup(query=query, outcome=self.outcome)

    async def lookup(self, address):
        return await self._result(address)

    async def lookup_handle(self, handle):
        return await self._result("@" + handle)


class FakeCtx:
    def __init__(self, session="s1"):
        self.sent = []
        self.logs = []
        self.session = session
        self.logger = SimpleNamespace(
            info=lambda m, *a, **k: self.logs.append(m),
            error=lambda m, *a, **k: self.logs.append("ERR " + m),
        )

    async def send(self, dest, msg):
        self.sent.append((dest, msg))

    def replies(self):
        return [m.text() for _, m in self.sent if isinstance(m, ChatMessage)]

    def reqs(self):
        return [json.loads(m[4:]) for m in self.logs if m.startswith("REQ ")]


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch):
    monkeypatch.setattr(chat, "GUARD", guard.Guard())
    monkeypatch.setattr(chat, "CLIENT", FakeClient())
    monkeypatch.setattr(chat, "SELF_HANDLES", ("agent-doctor",))


def run(ctx, content, sender="agent1qsender"):
    if isinstance(content, str):
        content = [TextContent(text=content)]
    msg = ChatMessage(content=content)
    asyncio.run(chat.on_chat(ctx, sender, msg))
    return msg


# ---------- router ----------

@pytest.mark.parametrize("text,kind", [
    ("", "help"),
    ("hi", "help"),
    ("what can you do?", "help"),
    ("@agent-doctor hello", "help"),
    ("@agent-doctor what is the capital of France?", "off_scope"),
    ("how do I fix my car", "off_scope"),
    ("check the weather in Paris", "off_scope"),
    (f"audit {STRONG}", "audit"),
    ("check @weather-bot", "audit"),
    (f"https://agentverse.ai/agents/details/{STRONG}/profile", "audit"),
    ("audit my agent", "need_target"),
    ("check the Weather Agent please", "need_target"),
    ("can you review my bot's profile", "need_target"),
    (f"audit {STRONG[:-4]}", "bad_address"),
    ("what's the capital of France?", "off_scope"),
    ("write me a poem about cats", "off_scope"),
    ("bitcoin price now", "off_scope"),
    ("how do I bake bread?", "off_scope"),
    ("who are you?", "help"),
])
def test_classify(text, kind):
    assert router.classify(text, ["agent-doctor"]).kind == kind


# ---------- service: every intent and error path returns a non-empty reply ----------

@pytest.mark.parametrize("outcome,expected", [
    ("ok", "Score "),
    ("partial", "Score "),
    ("not_found", "couldn't find"),
    ("invalid", "isn't a valid"),
    ("api_down", "isn't answering"),
    ("timeout", "too long"),
    ("weird", router.FALLBACK),
])
def test_service_outcomes(outcome, expected):
    res = asyncio.run(service.handle(f"audit {STRONG}", FakeClient(outcome)))
    assert res.text and expected in res.text and len(res.text) <= MAX_CHARS
    assert res.outcome == (outcome if outcome != "weird" else "fallback")
    assert res.input_type == "address"


def test_service_hard_timeout(monkeypatch):
    monkeypatch.setattr(service, "HARD_TIMEOUT_S", 0.05)
    res = asyncio.run(service.handle("check @slow", FakeClient(delay=1)))
    assert res.outcome == "timeout" and res.text == router.TIMEOUT and res.input_type == "handle"


def test_service_client_crash_falls_back():
    res = asyncio.run(service.handle(f"audit {STRONG}", FakeClient(raise_exc=True)))
    assert res.outcome == "fallback" and res.text == router.FALLBACK


def test_service_handle_and_url_routes():
    c = FakeClient()
    res = asyncio.run(service.handle("check @Weather-Bot", c))
    assert c.calls == ["@weather-bot"] and res.input_type == "handle" and not res.via_url
    res = asyncio.run(service.handle(f"https://agentverse.ai/agents/details/{STRONG}/profile", c))
    assert c.calls[-1] == STRONG and res.via_url


def test_service_multiple_targets_checks_first_only():
    c = FakeClient()
    res = asyncio.run(service.handle(f"compare {STRONG} and {WEAK} and @x", c))
    assert c.calls == [STRONG] and res.targets == 3
    assert "2 more agents" in res.text and len(res.text) <= MAX_CHARS


@pytest.mark.parametrize("text,reply", [
    ("hi", router.HELP),
    ("audit my agent", router.NEED_TARGET),
    (f"audit {STRONG[:-4]}", router.BAD_ADDRESS),
    ("tell me a joke", router.OFF_SCOPE),
])
def test_service_non_audit_replies(text, reply):
    c = FakeClient()
    res = asyncio.run(service.handle(text, c))
    assert res.text == reply and c.calls == []


# ---------- chat handler ----------

def test_ack_first_then_reply_and_log():
    ctx = FakeCtx()
    msg = run(ctx, f"audit {STRONG}")
    assert isinstance(ctx.sent[0][1], ChatAcknowledgement)
    assert ctx.sent[0][1].acknowledged_msg_id == msg.msg_id
    assert "Score " in ctx.replies()[0]
    (rec,) = ctx.reqs()
    assert rec["outcome"] == "ok" and rec["input"] == "address" and rec["latency_ms"] >= 0
    assert rec["sender"] == chat.hash_id("agent1qsender")
    assert "agent1qsender" not in ctx.logs[0] and STRONG not in ctx.logs[0]  # no raw ids/bodies


@pytest.mark.parametrize("outcome", ["not_found", "api_down", "timeout", "invalid"])
def test_chat_error_paths_reply_and_log(monkeypatch, outcome):
    monkeypatch.setattr(chat, "CLIENT", FakeClient(outcome))
    ctx = FakeCtx()
    run(ctx, "check @abc")
    assert ctx.replies() and ctx.replies()[0]
    assert ctx.reqs()[0]["outcome"] == outcome


@pytest.mark.parametrize("text", ["hi", "audit my agent", "write a poem", f"audit {STRONG[:-4]}"])
def test_chat_every_intent_replies_and_logs(text):
    ctx = FakeCtx()
    run(ctx, text)
    assert len(ctx.replies()) == 1 and ctx.replies()[0]
    assert len(ctx.reqs()) == 1


@pytest.mark.parametrize("content", [
    [StartSessionContent()],
    [EndSessionContent()],
    [MetadataContent(metadata={"k": "v"})],
    [StartSessionContent(), TextContent(text="  ")],
])
def test_control_messages_ack_only(content):
    ctx = FakeCtx()
    run(ctx, content)
    assert len(ctx.sent) == 1 and isinstance(ctx.sent[0][1], ChatAcknowledgement)
    assert ctx.reqs()[0]["outcome"] == "no_reply"


def test_start_session_with_text_is_answered():
    ctx = FakeCtx()
    run(ctx, [StartSessionContent(), TextContent(text="hi")])
    assert ctx.replies() == [router.HELP]


def test_resource_only_gets_text_hint():
    import uuid

    from uagents_core.contrib.protocols.chat import Resource

    res = ResourceContent(resource_id=uuid.uuid4(),
                          resource=Resource(uri="https://x/y.png", metadata={}))
    ctx = FakeCtx()
    run(ctx, [res])
    assert ctx.replies() == [router.NON_TEXT]


def test_reply_even_when_service_crashes(monkeypatch):
    async def boom(*a, **k):
        raise ValueError("x")

    monkeypatch.setattr(chat.service, "handle", boom)
    ctx = FakeCtx()
    run(ctx, "hi")
    assert ctx.replies() == [router.FALLBACK]
    assert ctx.reqs()[0]["outcome"] == "fallback"


def test_five_rapid_messages_all_answered():
    ctx = FakeCtx()
    for i in range(5):
        run(ctx, f"check @agent-{i}")
    assert len(ctx.replies()) == 5 and all("Score " in r for r in ctx.replies())


def test_rate_limit_warns_once_then_drops():
    ctx = FakeCtx()
    for i in range(guard.PER_SESSION_PER_MIN + 3):
        run(ctx, f"hi {i}")
    replies = ctx.replies()
    assert len(replies) == guard.PER_SESSION_PER_MIN + 1
    assert replies[-1] == router.RATE_LIMITED
    outcomes = [r["outcome"] for r in ctx.reqs()]
    assert outcomes.count("rate_limited") == 1 and outcomes.count("dropped") == 2
    acks = [m for _, m in ctx.sent if isinstance(m, ChatAcknowledgement)]
    assert len(acks) == guard.PER_SESSION_PER_MIN + 3  # every message still acked


def test_blank_text_only_gets_help():
    ctx = FakeCtx()
    run(ctx, [TextContent(text="   ")])
    assert ctx.replies() == [router.HELP]


def test_ack_failure_still_replies():
    ctx = FakeCtx()
    orig = ctx.send

    async def flaky(dest, msg):
        if isinstance(msg, ChatAcknowledgement):
            raise ConnectionError("x")
        await orig(dest, msg)

    ctx.send = flaky
    run(ctx, "hi")
    assert ctx.replies() == [router.HELP]


def test_repeat_gets_one_note_then_quiet():
    ctx = FakeCtx()
    for _ in range(guard.LOOP_REPEAT + 2):
        run(ctx, "check @same")
    replies = ctx.replies()
    assert len(replies) == guard.LOOP_REPEAT + 1 and replies[-1] == router.REPEATED


def test_log_has_session_hash_and_no_error_text(monkeypatch):
    async def boom(*a, **k):
        raise ValueError("secret-ish body text")

    monkeypatch.setattr(chat.service, "handle", boom)
    ctx = FakeCtx()
    run(ctx, "hi")
    assert "secret-ish" not in "".join(ctx.logs)
    assert ctx.reqs()[0]["session"] == chat.hash_id("s1")[:8]


def test_long_message_cut_at_space_keeps_address():
    ctx = FakeCtx()
    pad = "x " * ((chat.MAX_TEXT_CHARS - 40) // 2)
    run(ctx, pad + f"audit {STRONG} " + "y" * 100)
    # address straddles the cut: it's dropped whole, never half-read as a bad address
    assert ctx.reqs()[0]["outcome"] in ("ok", "off_scope", "need_target", "help")


def test_long_message_is_truncated_not_rejected():
    ctx = FakeCtx()
    run(ctx, "hi " + "x" * 50_000)
    assert ctx.replies() == [router.HELP]


@pytest.mark.parametrize("status,reply", [("timeout", router.TIMEOUT), ("api_down", router.API_DOWN)])
def test_profile_fetch_failure_is_inconclusive_not_scored(status, reply):
    class Partial(FakeClient):
        async def _result(self, query):
            return av.Lookup(query=query, outcome="partial", address=STRONG, profile=None,
                             almanac={"status": "active"}, profile_status=status,
                             almanac_status="ok", notes=(f"profile {status}",))

    res = asyncio.run(service.handle(f"audit {STRONG} and @other", Partial()))
    assert res.outcome == status and res.text.startswith(reply)
    assert "Score" not in res.text and "1 more agent" in res.text


def test_error_reply_keeps_multi_target_footer():
    res = asyncio.run(service.handle("check @a and @b", FakeClient("not_found")))
    assert "couldn't find @a" in res.text and "1 more agent" in res.text


def test_log_has_shape_and_types_never_words(monkeypatch):
    own = "agent1qwm50eahtwxe2jsjnqqgj3yqmcrpft3rkd42g8frh9twvdwugazfg3897tp"
    monkeypatch.setattr(chat, "SELF_ADDRESSES", (own,))
    ctx = FakeCtx()
    run(ctx, "@agent-doctor Tell me about bananas")
    rec = ctx.reqs()[0]
    assert rec["shape"] == "@<SELF_H> w w w w" and rec["types"] == "text"
    assert "bananas" not in "".join(ctx.logs)


OWN = "agent1qwm50eahtwxe2jsjnqqgj3yqmcrpft3rkd42g8frh9twvdwugazfg3897tp"


@pytest.mark.parametrize("text,kind", [
    # ASI:One first message of a new chat: "@<our address> " + what the user typed.
    (f"@{OWN} What can you do?", "help"),
    (f"@{OWN} @agent-doctor What can you do?", "help"),
    (f"@{OWN}", "help"),
    (f"@{OWN} what's the capital of France?", "off_scope"),
    (f"@{OWN} audit my agent", "need_target"),
    (f"@{OWN} audit {STRONG}", "audit"),
    (f"@{OWN} Audit {OWN}", "audit"),  # self-audit starter prompt, first message
    (f"@{OWN} audit agent-listing-generator", "audit"),  # handle typed without "@" (M2)
])
def test_classify_first_message_from_asi_one(text, kind):
    assert router.classify(text, ["agent-doctor"], [OWN]).kind == kind


def test_classify_bare_handle_targets_that_agent():
    intent = router.classify("@agent-doctor audit agent-listing-generator", ["agent-doctor"], [OWN])
    assert intent.kind == "audit"
    assert [t.label for t in intent.targets] == ["@agent-listing-generator"]


def test_first_message_from_asi_one_gets_help_not_self_audit(monkeypatch):
    monkeypatch.setattr(chat, "SELF_ADDRESSES", (OWN,))
    ctx = FakeCtx()
    run(ctx, f"@{OWN} @agent-doctor What can you do?")
    assert ctx.replies() == [router.HELP]
    assert ctx.reqs()[0]["outcome"] == "help"


def test_first_message_audit_reaches_the_real_target(monkeypatch):
    monkeypatch.setattr(chat, "SELF_ADDRESSES", (OWN,))
    ctx = FakeCtx()
    run(ctx, f"@{OWN} audit {STRONG}")
    rec = ctx.reqs()[0]
    assert rec["input"] == "address" and rec["targets"] == 1
    assert "send the others" not in ctx.replies()[0].lower()


def test_chat_prehire_title_by_name_then_audit_this_agent(monkeypatch):
    """Q18 (FB-3): the chat Pre-Hire names the agent and the chat remembers it."""
    from agent import guides, prehire
    monkeypatch.setattr(guides, "LAST", guides.LastAudit())
    lk = fixture_lookup("strong")

    async def fake_full(ctx, target, client, prober, live, query, deadline=None):
        from agent.probe import ProbeResult
        return prehire.build_result(query, target.value, lk,
                                    ProbeResult(target.value, "degraded", 1800, None)), lk
    monkeypatch.setattr(prehire, "run_check_full", fake_full)
    ctx = FakeCtx()
    run(ctx, f"is {STRONG} live?")
    name = lk.profile["name"]
    assert ctx.replies()[0].startswith(f"**Pre-Hire Check: {name}**")
    run(ctx, "audit this agent for me")
    rec = ctx.reqs()[-1]
    assert rec["outcome"] == "ok" and rec["input"] == "last" and chat.CLIENT.calls[-1] == STRONG
