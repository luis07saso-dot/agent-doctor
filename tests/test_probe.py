"""P2 live probe: verdicts, latency, cache, dedupe, routing of probe traffic (no loops). Mocks only."""
import asyncio
import itertools
import json
from uuid import uuid4
from types import SimpleNamespace

import pytest
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    EndSessionContent,
    TextContent,
)

from agent import chat, guard, probe
from agent.probe import Prober

TARGET = "agent1qfvydlgcxrvga2kqjxhj3hpngegtysm2c7uk48ywdue0kgvtc2f5cwhyffv"
OTHER = "agent1qtxyynz433g33av2f0000k489xx6r590vfk6gcs0c2c2n6vnpc0nxehvvpm"
_ids = itertools.count()


class Logger:
    def __init__(self):
        self.lines = []

    def info(self, m, *a, **k):
        self.lines.append(m)

    def error(self, m, *a, **k):
        self.lines.append("ERR " + m)


class Ctx:
    """Context with a session; records sends. send_raw = the probe's outbound path."""

    def __init__(self, net=None, session=None, logger=None):
        self.session = session or f"probe-session-{next(_ids)}"
        self.logger = logger or Logger()
        self.net = net
        self.sent = []

    async def send(self, dest, msg):
        self.sent.append((dest, msg))

    async def send_raw(self, **kw):
        self.sent.append((kw["destination"], kw))
        return await self.net.deliver(self, kw)


class Net:
    """Simulated target. behaviour: live | ack_only | silent | reply_only | fail | raise."""

    def __init__(self, prober, behaviour="live", ack_delay=0.0, reply_delay=0.0, replies=1):
        self.prober, self.behaviour = prober, behaviour
        self.ack_delay, self.reply_delay, self.replies = ack_delay, reply_delay, replies
        self.sends = 0
        self.logger = Logger()

    async def deliver(self, sctx, kw):
        self.sends += 1
        assert kw["protocol_digest"] == probe.CHAT_PROTOCOL_DIGEST
        if self.behaviour == "raise":
            raise RuntimeError("network down")
        if self.behaviour == "fail":
            return SimpleNamespace(status=SimpleNamespace(value="failed"),
                                   detail="Unable to resolve destination endpoint")
        msg = ChatMessage.parse_raw(kw["message_body"])
        target = kw["destination"]
        inbound = Ctx(session=sctx.session, logger=self.logger)  # replies come in our session

        async def ack():
            await asyncio.sleep(self.ack_delay)
            await self.prober.on_ack(inbound, target, ChatAcknowledgement(
                acknowledged_msg_id=msg.msg_id))

        async def reply():
            await asyncio.sleep(self.reply_delay)
            for _ in range(self.replies):
                await self.prober.on_chat(inbound, target,
                                          ChatMessage(content=[TextContent(text="I can help")]))

        if self.behaviour in ("live", "ack_only"):
            asyncio.ensure_future(ack())
        if self.behaviour in ("live", "reply_only"):
            asyncio.ensure_future(reply())
        return SimpleNamespace(status=SimpleNamespace(value="delivered"), detail="")


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make(behaviour="live", timeout=0.2, **kw):
    pr = Prober(timeout=timeout)
    net = Net(pr, behaviour, **kw)
    factory_calls = []

    def factory():
        c = Ctx(net)
        factory_calls.append(c)
        return c

    pr.configure(factory, ["agent1qself"])
    return pr, net, factory_calls


def run(coro):
    return asyncio.run(coro)


# ---------- verdicts ----------

def test_live_measures_ack_and_reply_separately():
    pr, net, _ = make("live", ack_delay=0.01, reply_delay=0.05)
    r = run(pr.probe(Ctx(), TARGET))
    assert r.status == "live" and r.live and r.detail == "ok"
    assert r.ack_ms is not None and r.reply_ms is not None
    assert r.reply_ms >= r.ack_ms >= 0
    assert r.checked_at.endswith("Z") and not r.cached
    assert net.sends == 1


def test_ack_without_reply_is_degraded():
    pr, _, _ = make("ack_only", timeout=0.05)
    r = run(pr.probe(Ctx(), TARGET))
    assert r.status == "degraded" and not r.live
    assert r.ack_ms is not None and r.reply_ms is None and r.detail == "no_reply"


def test_nothing_is_unreachable_within_timeout():
    pr, _, _ = make("silent", timeout=0.05)

    async def go():
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        r = await pr.probe(Ctx(), TARGET)
        return r, loop.time() - t0

    r, took = run(go())
    assert r.status == "unreachable" and r.detail == "timeout"
    assert r.ack_ms is None and r.reply_ms is None
    assert took < 1.0


def test_reply_without_ack_is_still_live():
    pr, _, _ = make("reply_only")
    r = run(pr.probe(Ctx(), TARGET))
    assert r.status == "live" and r.detail == "no_ack" and r.ack_ms is None


@pytest.mark.parametrize("behaviour,detail", [("fail", "no_endpoint"), ("raise", "send_failed")])
def test_send_failure_is_unreachable(behaviour, detail):
    pr, _, _ = make(behaviour)
    r = run(pr.probe(Ctx(), TARGET))
    assert r.status == "unreachable" and r.detail == detail


def test_hard_timeout_even_if_send_hangs(monkeypatch):
    monkeypatch.setattr(probe, "SEND_TIMEOUT_S", 0.01)
    pr = Prober(timeout=0.05)

    class Hang(Ctx):
        async def send_raw(self, **kw):
            await asyncio.sleep(10)

    pr.configure(lambda: Hang(), [])
    r = run(pr.probe(Ctx(), TARGET))
    assert r.status == "unreachable" and r.detail == "send_failed"


def test_never_probes_itself():
    pr, net, calls = make()
    r = run(pr.probe(Ctx(), "agent1qself"))
    assert r.status == "skipped" and r.detail == "self"
    assert net.sends == 0 and not calls


# ---------- cache, dedupe, bounds ----------

def test_cached_for_ten_minutes_including_failures():
    assert probe.CACHE_TTL_S == 600
    clock = Clock()
    pr = Prober(timeout=0.02, clock=clock)
    net = Net(pr, "silent")
    pr.configure(lambda: Ctx(net), [])

    async def go():
        a = await pr.probe(Ctx(), TARGET)
        b = await pr.probe(Ctx(), TARGET.upper())  # normalised
        clock.t += 599
        c = await pr.probe(Ctx(), TARGET)
        clock.t += 2
        d = await pr.probe(Ctx(), TARGET)
        return a, b, c, d

    a, b, c, d = run(go())
    assert a.status == "unreachable" and not a.cached
    assert b.cached and c.cached and not d.cached
    assert net.sends == 2


def test_concurrent_requests_share_one_probe():
    pr, net, _ = make("live", reply_delay=0.05)

    async def go():
        return await asyncio.gather(*[pr.probe(Ctx(), TARGET) for _ in range(5)])

    results = run(go())
    assert all(r.status == "live" for r in results)
    assert net.sends == 1


def test_busy_when_too_many_targets_in_flight(monkeypatch):
    monkeypatch.setattr(probe, "MAX_INFLIGHT", 1)
    pr, net, _ = make("silent", timeout=0.05)

    async def go():
        return await asyncio.gather(pr.probe(Ctx(), TARGET), pr.probe(Ctx(), OTHER))

    a, b = run(go())
    assert a.status == "unreachable"
    assert b.status == "error" and b.detail == "busy"
    assert net.sends == 1
    assert pr._cache_get(OTHER) is None  # our own limit is never cached as a verdict


def test_each_probe_uses_a_fresh_session():
    pr, net, calls = make("silent", timeout=0.01)
    run(pr.probe(Ctx(), TARGET))
    run(pr.probe(Ctx(), OTHER))
    assert len({c.session for c in calls}) == 2


# ---------- routing: probe traffic never reaches the user path ----------

def test_owns_only_target_in_probe_session_then_late_window():
    clock = Clock()
    pr = Prober(timeout=0.01, clock=clock)
    net = Net(pr, "silent")
    sctx = Ctx(net)
    pr.configure(lambda: sctx, [])
    run(pr.probe(Ctx(), TARGET))
    assert pr.owns(TARGET, sctx.session)  # closed, inside late window
    assert not pr.owns(OTHER, sctx.session)  # someone else in that session: not ours
    assert not pr.owns(TARGET, "user-session")  # target chatting normally: user path
    clock.t += probe.LATE_TTL_S + 1
    assert not pr.owns(TARGET, sctx.session)


@pytest.fixture
def chat_state(monkeypatch):
    monkeypatch.setattr(chat, "GUARD", guard.Guard())
    pr = Prober(timeout=0.05)
    monkeypatch.setattr(chat, "PROBER", pr)
    return pr


def _probe_session(pr):
    s = "probe-sess"
    pr._remember_closed(s, TARGET)
    return s


def test_chat_handler_swallows_probe_replies_no_loop(chat_state):
    pr = chat_state
    s = _probe_session(pr)
    ctx = Ctx(session=s)
    for _ in range(30):  # a chatty target replying forever
        asyncio.run(chat.on_chat(ctx, TARGET, ChatMessage(content=[TextContent(text="hello?")])))
    asyncio.run(chat.on_chat(ctx, TARGET, ChatMessage(content=[EndSessionContent()])))
    sent_types = {type(m).__name__ for _, m in ctx.sent}
    assert sent_types == {"ChatAcknowledgement"}  # acks only, never a ChatMessage
    assert not any(line.startswith("REQ ") for line in ctx.logger.lines)
    assert any(line.startswith("PROBE ") for line in ctx.logger.lines)


def test_chat_handler_routes_probe_ack_to_prober(chat_state):
    pr = chat_state
    s = _probe_session(pr)
    ctx = Ctx(session=s)
    asyncio.run(chat.on_ack(ctx, TARGET, ChatAcknowledgement(acknowledged_msg_id=uuid4())))
    assert ctx.sent == []
    assert any('"event":"late_ack"' in line for line in ctx.logger.lines)


def test_same_agent_outside_probe_session_is_a_normal_user(chat_state, monkeypatch):
    pr = chat_state
    _probe_session(pr)

    class FakeClient:
        async def lookup(self, a):
            from agent.agentverse import Lookup
            return Lookup(query=a, outcome="not_found")

        async def lookup_handle(self, h):
            from agent.agentverse import Lookup
            return Lookup(query=h, outcome="not_found")

    monkeypatch.setattr(chat, "CLIENT", FakeClient())
    ctx = Ctx(session="user-session")
    asyncio.run(chat.on_chat(ctx, TARGET, ChatMessage(content=[TextContent(text="hi")])))
    assert any(isinstance(m, ChatMessage) for _, m in ctx.sent)
    assert any(line.startswith("REQ ") for line in ctx.logger.lines)


def test_live_probe_end_to_end_through_chat_handlers(chat_state):
    """The probe's ack and reply come back through chat.on_ack / chat.on_chat (as uagents
    would deliver them) and resolve the probe; Doctor sends nothing but acks to the target."""
    pr = chat_state
    inbound = []

    class Wire(Ctx):
        async def send_raw(self, **kw):
            self.sent.append(kw)
            msg = ChatMessage.parse_raw(kw["message_body"])
            c = Ctx(session=self.session)
            inbound.append(c)

            async def target_side():
                await asyncio.sleep(0.005)
                await chat.on_ack(c, TARGET, ChatAcknowledgement(acknowledged_msg_id=msg.msg_id))
                await asyncio.sleep(0.005)
                await chat.on_chat(c, TARGET, ChatMessage(content=[TextContent(text="I can.")]))

            asyncio.ensure_future(target_side())
            return SimpleNamespace(status=SimpleNamespace(value="delivered"), detail="")

    pr.configure(lambda: Wire(), [])
    r = asyncio.run(pr.probe(Ctx(), TARGET))
    assert r.status == "live" and r.ack_ms is not None and r.reply_ms is not None
    to_target = [m for c in inbound for _, m in c.sent]
    assert all(isinstance(m, ChatAcknowledgement) for m in to_target)


def test_probe_logs_have_no_bodies_or_raw_addresses():
    pr, net, _ = make("live")
    log = Ctx()
    run(pr.probe(log, TARGET))
    lines = log.logger.lines + net.logger.lines
    assert lines
    for line in lines:
        assert line.startswith("PROBE ")
        assert TARGET not in line and "I can help" not in line and probe.PROBE_TEXT not in line
        json.loads(line[6:])


def test_plain_audit_never_probes(chat_state, monkeypatch):
    """Probes run only on request: an audit message must not touch the prober."""
    pr = chat_state
    calls = []
    pr.configure(lambda: calls.append(1) or Ctx(), [])

    class FakeClient:
        async def lookup(self, a):
            from agent.agentverse import Lookup
            return Lookup(query=a, outcome="not_found")

        async def lookup_handle(self, h):
            return await self.lookup(h)

    monkeypatch.setattr(chat, "CLIENT", FakeClient())
    ctx = Ctx(session="u1")
    asyncio.run(chat.on_chat(ctx, "agent1quser", ChatMessage(content=[TextContent(
        text=f"audit {TARGET}")])))
    assert calls == []
