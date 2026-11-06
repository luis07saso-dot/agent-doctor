"""P1 Pre-Hire Check: protocol digest, result building, protocol handler, chat path. Mocks only."""
import asyncio
import importlib.util
import json
import re
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from uagents import Model
from uagents_core.contrib.protocols.chat import ChatMessage, TextContent

from agent import agentverse as av
from agent import chat, guard, prehire, report, router, service
from agent.probe import ProbeResult
from agent.report import MAX_CHARS

ROOT = Path(__file__).parent.parent
FIX = Path(__file__).parent / "fixtures"
STRONG = "agent1qfvydlgcxrvga2kqjxhj3hpngegtysm2c7uk48ywdue0kgvtc2f5cwhyffv"
NOW = "2026-11-04T10:42:00Z"


def fixture_lookup(name) -> av.Lookup:
    d = json.loads((FIX / f"{name}.json").read_text())
    d.pop("captured_at", None)
    d["notes"] = tuple(d.get("notes") or ())
    return av.Lookup(**d)


class FakeClient:
    def __init__(self, outcome="ok", fixture="strong", resolve=("ok", STRONG), unresponsive=None):
        self.outcome, self.fixture, self.resolve = outcome, fixture, resolve
        self.unresponsive = unresponsive
        self.calls = []

    async def lookup(self, address):
        self.calls.append(("lookup", address))
        if self.outcome in ("ok", "partial"):
            lk = replace(fixture_lookup(self.fixture), outcome=self.outcome)
            if self.unresponsive is not None:
                lk = replace(lk, profile={**lk.profile, "unresponsive": self.unresponsive})
            return lk
        return av.Lookup(query=address, outcome=self.outcome)

    async def lookup_handle(self, handle):
        return await self.lookup(handle)

    async def resolve_handle(self, handle):
        self.calls.append(("resolve", handle))
        return self.resolve


class FakeProber:
    def __init__(self, status="live", ack=800, reply=3200, detail="ok", cached=False):
        self.r = dict(status=status, ack_ms=ack, reply_ms=reply, detail=detail, cached=cached)
        self.calls = []

    async def probe(self, ctx, address):
        self.calls.append(address)
        return ProbeResult(address, checked_at=NOW, **self.r)


class Ctx:
    def __init__(self, session="s1"):
        self.session, self.sent, self.logs = session, [], []
        self.logger = SimpleNamespace(info=lambda m, *a, **k: self.logs.append(m),
                                      error=lambda m, *a, **k: self.logs.append("ERR " + m))

    async def send(self, dest, msg):
        self.sent.append((dest, msg))


# ---------- P1 protocol: published, fixed digest ----------

def test_protocol_digest_is_pinned_and_stable():
    assert prehire.prehire_proto.digest == prehire.PROTOCOL_DIGEST
    assert prehire.prehire_protocol_spec.digest == prehire.PROTOCOL_DIGEST
    # Rebuilding from the same models gives the same digest (no timestamps, no ordering drift).
    again = prehire.ProtocolSpecification(
        name=prehire.PROTOCOL_NAME, version=prehire.PROTOCOL_VERSION,
        interactions={prehire.PreHireRequest: {prehire.PreHireResult}})
    assert again.digest == prehire.PROTOCOL_DIGEST


def test_manifest_lists_request_and_result():
    m = prehire.prehire_proto.manifest()
    assert m["metadata"]["name"] == "AgentDoctorPreHire"
    titles = {x["schema"]["title"] for x in m["models"]}
    assert titles == {"PreHireRequest", "PreHireResult"}
    (inter,) = m["interactions"]
    assert inter["request"] == Model.build_schema_digest(prehire.PreHireRequest)
    assert inter["responses"] == [Model.build_schema_digest(prehire.PreHireResult)]


def test_client_snippet_models_match_agent_exactly():
    spec = importlib.util.spec_from_file_location("prehire_client",
                                                  ROOT / "examples" / "prehire_client.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # guarded by __main__: builds no agent
    for name in ("PreHireRequest", "PreHireResult"):
        assert (Model.build_schema_digest(getattr(mod, name))
                == Model.build_schema_digest(getattr(prehire, name)))
    assert mod.AGENT_DOCTOR == chat.profile.SELF_ADDRESS


def test_readme_snippet_models_match_agent_exactly():
    """The README carries the client inline (repo is private). It must run as pasted and
    produce the same schema digests as the agent, or callers' requests never match."""
    readme = (ROOT / "README.md").read_text()
    blocks = re.findall(r"```python\n(.*?)```", readme, re.S)
    code = next(b for b in blocks if "class PreHireResult(Model)" in b)
    ns: dict = {}
    exec(compile(code, "README-snippet", "exec"), ns)  # defines models + function only
    for name in ("PreHireRequest", "PreHireResult"):
        assert (Model.build_schema_digest(ns[name])
                == Model.build_schema_digest(getattr(prehire, name)))
    assert ns["AGENT_DOCTOR"] == chat.profile.SELF_ADDRESS
    assert asyncio.iscoroutinefunction(ns["pre_hire_check"])
    assert "github.com" not in readme  # repo stays private: no dead links


@pytest.mark.filterwarnings("ignore:coroutine .Agent.publish_manifest. was never awaited")
def test_agent_publishes_both_protocols():
    from agent import main

    settings = SimpleNamespace(seed="test-seed-" + "x" * 40, port=8999, handle="agent-doctor-dev")
    loop = asyncio.new_event_loop()
    try:
        a = main.build(settings, mailbox=False, enable_agent_inspector=False,
                       publish_agent_details=False, report_events=False, loop=loop)
        digests = set(a.protocols)
        assert prehire.PROTOCOL_DIGEST in digests
        assert "proto:30a801ed3a83f9a0ff0a9f1e6fe958cb91da1fc2218b153df7b6cbf87bd33d62" in digests
        assert a._handle_messages_concurrently is True
    finally:
        loop.close()


@pytest.mark.filterwarnings("ignore:coroutine .Agent.publish_manifest. was never awaited")
def test_connect_profile_carries_starter_prompts():
    """Mailbox /connect must republish starter prompts, or each deploy wipes them."""
    from agent import main

    settings = SimpleNamespace(seed="test-seed-" + "x" * 40, port=8998, handle="agent-doctor-dev")
    loop = asyncio.new_event_loop()
    try:
        a = main.build(settings, mailbox=False, enable_agent_inspector=False,
                       report_events=False, loop=loop)
        prof = a._build_registration_profile()
        assert prof.starter_prompts == list(chat.profile.STARTER_PROMPTS)
        assert prof.description == chat.profile.DESCRIPTION
    finally:
        loop.close()


# ---------- the check ----------

def run_check(target, client=None, prober=None, live=True):
    return asyncio.run(prehire.run_check(Ctx(), target, client or FakeClient(),
                                         prober or FakeProber(), live))


def test_live_result_joins_probe_and_static():
    r = run_check(prehire.Target("address", STRONG))
    assert r.status == "live" and r.live and r.address == STRONG
    assert r.ack_ms == 800 and r.reply_ms == 3200 and r.checked_at == NOW
    assert r.chat_protocol is True and r.active is True
    assert isinstance(r.trust_score, int) and 0 <= r.trust_score <= 100
    assert r.rating is not None and r.profile_url.endswith(f"{STRONG}/profile")


@pytest.mark.parametrize("status", ["degraded", "unreachable"])
def test_not_live_statuses(status):
    r = run_check(prehire.Target("address", STRONG), prober=FakeProber(status, reply=None))
    assert r.status == status and not r.live


def test_probe_error_or_self_is_unknown_not_a_verdict():
    r = run_check(prehire.Target("address", STRONG), prober=FakeProber("error", None, None, "busy"))
    assert r.status == "unknown" and not r.live and "busy" in r.detail


def test_static_only_when_probe_not_requested():
    pr = FakeProber()
    r = run_check(prehire.Target("address", STRONG), prober=pr, live=False)
    assert pr.calls == [] and r.status == "unknown" and r.trust_score is not None


def test_handle_is_resolved_first():
    c, pr = FakeClient(), FakeProber()
    r = run_check(prehire.Target("handle", "weather-bot"), client=c, prober=pr)
    assert c.calls[0] == ("resolve", "weather-bot") and pr.calls == [STRONG]
    assert r.status == "live"


@pytest.mark.parametrize("outcome,status", [("not_found", "not_found"), ("timeout", "error"),
                                            ("api_down", "error"), ("invalid", "invalid")])
def test_handle_resolve_failures(outcome, status):
    pr = FakeProber()
    r = run_check(prehire.Target("handle", "nope-bot"), client=FakeClient(resolve=(outcome, None)),
                  prober=pr)
    assert r.status == status and pr.calls == []


def test_static_failure_still_gives_live_verdict():
    r = run_check(prehire.Target("address", STRONG), client=FakeClient("api_down"))
    assert r.status == "live" and r.trust_score is None and "profile api_down" in r.detail


def test_check_never_raises_and_is_bounded(monkeypatch):
    class Boom(FakeProber):
        async def probe(self, ctx, address):
            raise RuntimeError("x")

    r = run_check(prehire.Target("address", STRONG), prober=Boom())
    assert r.status == "error"

    class Slow(FakeProber):
        async def probe(self, ctx, address):
            await asyncio.sleep(5)

    monkeypatch.setattr(prehire, "CHECK_TIMEOUT_S", 0.05)
    r = run_check(prehire.Target("address", STRONG), prober=Slow())
    assert r.status == "error" and r.detail == "timeout"


@pytest.mark.parametrize("q,kind,value", [
    (STRONG, "address", STRONG),
    (STRONG.upper(), "address", STRONG),
    ("@weather-bot", "handle", "weather-bot"),
    ("weather-bot", "handle", "weather-bot"),
    ("weatherbot", "handle", "weatherbot"),
    (f"https://agentverse.ai/agents/details/{STRONG}/profile", "address", STRONG),
])
def test_parse_query(q, kind, value):
    t = prehire.parse_query(q)
    assert (t.kind, t.value) == (kind, value)


@pytest.mark.parametrize("q", ["", "   ", "not a handle!", "agent1qbad"])
def test_parse_query_rejects_junk(q):
    assert prehire.parse_query(q) is None


# ---------- protocol handler ----------

@pytest.fixture
def wired(monkeypatch):
    monkeypatch.setattr(chat, "CLIENT", FakeClient())
    pr = FakeProber()
    monkeypatch.setattr(prehire, "PROBER", pr)
    monkeypatch.setattr(prehire, "LIMITER", prehire._RateLimiter())
    return pr


def handle(req, sender="agent1qorchestrator"):
    ctx = Ctx()
    asyncio.run(prehire.on_prehire(ctx, sender, req))
    return ctx


def test_handler_replies_with_result_and_logs(wired):
    ctx = handle(prehire.PreHireRequest(address=STRONG))
    ((dest, res),) = ctx.sent
    assert dest == "agent1qorchestrator" and isinstance(res, prehire.PreHireResult)
    assert res.status == "live" and res.live
    (log,) = [json.loads(m[4:]) for m in ctx.logs if m.startswith("REQ ")]
    assert log["input"] == "prehire_protocol" and log["outcome"] == "live"
    assert STRONG not in " ".join(ctx.logs) and "agent1qorchestrator" not in " ".join(ctx.logs)


def test_handler_invalid_query(wired):
    ctx = handle(prehire.PreHireRequest(address="?? nope"))
    assert ctx.sent[0][1].status == "invalid" and wired.calls == []


def test_handler_static_only(wired):
    ctx = handle(prehire.PreHireRequest(address=STRONG, live_probe=False))
    assert ctx.sent[0][1].status == "unknown" and wired.calls == []


def test_handler_rate_limits_per_sender(wired, monkeypatch):
    monkeypatch.setattr(prehire, "LIMITER", prehire._RateLimiter(per_min=2))
    statuses = [handle(prehire.PreHireRequest(address=STRONG)).sent[0][1].status
                for _ in range(3)]
    assert statuses == ["live", "live", "rate_limited"]
    other = handle(prehire.PreHireRequest(address=STRONG), sender="agent1qsomeoneelse")
    assert other.sent[0][1].status == "live"


def test_handler_always_replies_even_on_crash(wired, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("x")

    monkeypatch.setattr(prehire, "run_check", boom)
    ctx = handle(prehire.PreHireRequest(address=STRONG))
    assert ctx.sent[0][1].status == "error"


# ---------- chat path (humans) ----------

@pytest.fixture
def chat_wired(monkeypatch):
    monkeypatch.setattr(chat, "GUARD", guard.Guard())
    monkeypatch.setattr(chat, "CLIENT", FakeClient(unresponsive=True))
    monkeypatch.setattr(chat, "SELF_HANDLES", ("agent-doctor",))
    pr = FakeProber()
    monkeypatch.setattr(chat, "PROBER", SimpleNamespace(probe=pr.probe,
                                                        owns=lambda s, sess: False))
    return pr


def say(text, session="u1"):
    ctx = Ctx(session)
    asyncio.run(chat.on_chat(ctx, "agent1quser", ChatMessage(content=[TextContent(text=text)])))
    replies = [m.text() for _, m in ctx.sent if isinstance(m, ChatMessage)]
    reqs = [json.loads(m[4:]) for m in ctx.logs if m.startswith("REQ ")]
    return replies, reqs


@pytest.mark.parametrize("text", [
    f"is {STRONG} live?",
    f"pre-hire check {STRONG}",
    "pre-hire check weather-bot",
    "is weather-bot live?",
    "ping @weather-bot",
    f"{STRONG} not responding",
    "weather-bot not responding",
    "my agent weather-bot stopped answering",
    "@weather-bot doesn't respond",
])
def test_chat_prehire_routes_to_probe(chat_wired, text):
    (reply,), (req,) = say(text)
    assert "Pre-Hire Check" in reply and "LIVE" in reply
    assert req["outcome"] == "prehire_live" and len(reply) <= MAX_CHARS
    assert chat_wired.calls == [STRONG]


def test_chat_prehire_overturns_stale_unresponsive_flag(chat_wired):
    (reply,), _ = say(f"is {STRONG} live?")
    assert "unresponsive" in reply and "out of date" in reply


@pytest.mark.parametrize("text", [
    "agent not responding",
    "my agent not responding",
    "my agent is not replying",
    "my agent stopped responding",
    "agent doesn't respond on ASI:One",
    "why does my agent not answer?",
])
def test_not_responding_wording_asks_for_target(text):
    assert router.classify(text).kind == "prehire_need_target"


@pytest.mark.parametrize("text", [
    "why is my agent not getting picks",
    "my agent is not ranking",
    "fix my car, it is not responding",
])
def test_not_responding_wording_needs_agent_and_reply_verb(text):
    assert router.classify(text).kind != "prehire_need_target"


def test_chat_prehire_without_target(chat_wired):
    (reply,), (req,) = say("pre-hire check")
    assert reply == router.PREHIRE_NEED_TARGET and req["outcome"] == "prehire_need_target"
    assert chat_wired.calls == []


def test_chat_audit_of_flagged_agent_runs_live_check(chat_wired):
    """Q2 (user decisions Q2-D1/D2): flagged agent -> one probe, verdict in the same reply."""
    (reply,), (req,) = say(f"audit {STRONG}")
    assert "Score " in reply and req["outcome"] == "ok" and chat_wired.calls == [STRONG]
    assert "Our live check just got a reply in 3.2s" in reply and "out of date" in reply
    assert "We did not test it" not in reply and req["live"] == "live"


def test_chat_audit_of_unflagged_agent_probes_once(monkeypatch, chat_wired):
    """Q20a: single-agent audits send one test message too (was: flagged agents only)."""
    monkeypatch.setattr(chat, "CLIENT", FakeClient(unresponsive=False))
    (reply,), (req,) = say(f"audit {STRONG}")
    assert "Score " in reply and req["outcome"] == "ok" and len(chat_wired.calls) == 1
    assert req["live"] == "live" and "✅ Live test: it answered our test message in 3.2s" in reply


def test_chat_audit_live_kill_switch(monkeypatch, chat_wired):
    monkeypatch.setenv("AUDIT_LIVE", "0")
    monkeypatch.setattr(chat, "CLIENT", FakeClient(unresponsive=False))
    (reply,), (req,) = say(f"audit {STRONG}")
    assert "Score " in reply and chat_wired.calls == [] and "live" not in req


@pytest.mark.parametrize("status,word", [("live", "LIVE"), ("degraded", "DEGRADED"),
                                         ("unreachable", "UNREACHABLE"), ("unknown", "UNKNOWN"),
                                         ("not_found", "couldn't find"),
                                         ("invalid", "isn't a valid"), ("error", "try again"),
                                         ("pending", "CHECKING")])
def test_format_text_every_status(status, word):
    r = prehire.PreHireResult(query="q", status=status, checked_at=NOW,
                              address=STRONG if status not in ("not_found", "invalid", "error")
                              else "")
    text = prehire.format_text(r, "@weather-bot")
    assert word in text and len(text) <= MAX_CHARS


def test_format_text_strips_untrusted_label():
    r = prehire.PreHireResult(query="q", status="live", address=STRONG, checked_at=NOW)
    text = prehire.format_text(r, "@x[evil](http://x.y)`")
    assert "http" not in text and "[" not in text.split("\n")[0]


def test_service_prehire_timeout(monkeypatch):
    monkeypatch.setattr(service, "PREHIRE_HARD_TIMEOUT_S", 0.05)

    async def slow(target):
        await asyncio.sleep(5)

    res = asyncio.run(service.handle(f"is {STRONG} live?", FakeClient(), prehire=slow))
    assert res.outcome == "prehire_error" and res.text


# ---------- reply deadline (user decision 2026-11-02: probe waits 14s, reply <= 15s) ----------

def test_timing_budget_is_consistent():
    import inspect

    from agent import probe as probe_mod
    spec = importlib.util.spec_from_file_location("prehire_client",
                                                  ROOT / "examples" / "prehire_client.py")
    prehire_client = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prehire_client)
    assert probe_mod.PROBE_TIMEOUT_S == 14.0 and report.PROBE_WAIT_S == 14
    assert service.REPLY_BUDGET_S == 15.0 and service.AUDIT_BUDGET_S == service.REPLY_BUDGET_S
    assert probe_mod.PROBE_TIMEOUT_S < service.REPLY_BUDGET_S < service.PREHIRE_HARD_TIMEOUT_S
    # protocol path: handle resolve (<=12s) + full probe must fit, and the client must wait longer
    assert prehire.CHECK_TIMEOUT_S >= 12 + probe_mod.PROBE_TIMEOUT_S
    default = inspect.signature(prehire_client.pre_hire_check).parameters["timeout"].default
    assert default > prehire.CHECK_TIMEOUT_S


class SlowProber(FakeProber):
    def __init__(self, delay, **kw):
        super().__init__(**kw)
        self.delay, self.finished = delay, False

    async def probe(self, ctx, address):
        self.calls.append(address)
        await asyncio.sleep(self.delay)
        self.finished = True
        return ProbeResult(address, checked_at=NOW, **self.r)


def test_deadline_gives_pending_and_probe_keeps_running():
    async def go():
        pr = SlowProber(0.2)
        r = await prehire.run_check(Ctx(), prehire.Target("address", STRONG), FakeClient(), pr,
                                    True, "q", deadline=time.monotonic() + 0.05)
        assert r.status == prehire.PENDING and not r.live and r.detail == "still_running"
        assert r.trust_score is not None and r.ack_ms is None and r.reply_ms is None
        assert not pr.finished
        await asyncio.sleep(0.3)
        assert pr.finished  # shielded: giving up on waiting did not cancel the probe
    asyncio.run(go())


def test_deadline_not_hit_gives_verdict():
    r = asyncio.run(prehire.run_check(Ctx(), prehire.Target("address", STRONG), FakeClient(),
                                      SlowProber(0.01), True, "q",
                                      deadline=time.monotonic() + 5))
    assert r.status == "live"


def test_deadline_already_passed_still_starts_probe():
    async def go():
        pr = SlowProber(0.3)
        r = await prehire.run_check(Ctx(), prehire.Target("address", STRONG), FakeClient(), pr,
                                    True, "q", deadline=time.monotonic() - 1)
        assert r.status == prehire.PENDING and pr.calls == [STRONG]
        await asyncio.sleep(0.4)
        assert pr.finished
    asyncio.run(go())


def test_chat_prehire_slow_target_replies_pending(monkeypatch, chat_wired):
    pr = SlowProber(0.5)
    monkeypatch.setattr(chat, "PROBER", SimpleNamespace(probe=pr.probe,
                                                        owns=lambda s, sess: False))
    monkeypatch.setattr(service, "REPLY_BUDGET_S", 0.1)
    t0 = time.monotonic()
    (reply,), (req,) = say("is weather-bot live?")
    assert time.monotonic() - t0 < 0.45
    assert "CHECKING" in reply and 'Ask "is weather-bot live?" again' in reply
    assert "@weather-bot live" not in reply  # no "@" in the follow-up (ASI:One routing)
    assert "cached for 10 minutes" not in reply and len(reply) <= MAX_CHARS
    assert req["outcome"] == "prehire_pending"


def test_protocol_path_has_no_deadline(wired):
    """Agents calling the protocol wait for the full probe: no pending status there."""
    import inspect
    src = inspect.getsource(prehire.on_prehire)
    assert "deadline" not in src
