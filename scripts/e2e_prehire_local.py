"""P3 end-to-end check, fully local: client agent -> dev Doctor -> throwaway target agents.

One process, uagents local dispatch (no mailbox, no Almanac/Agentverse calls, no third-party
agents). What is real: uagents runtime, envelopes, sessions, concurrent handlers, the
AgentDoctorPreHire protocol, the probe, the chat handlers, send_and_receive in the client
snippet. What is stubbed: Agentverse profile data (the 'strong' fixture, offline).

Agents:
- Doctor: agent.main.build() with the DEV seed (config refuses the prod seed outside prod).
- target-live: Chat Protocol agent that acks and answers           -> live
- target-ackonly: acks, never answers                               -> degraded
- target-chatty: answers 5 times per message (loop bait)            -> live, Doctor never replies
- an address with no agent behind it                                 -> unreachable
- client: examples/prehire_client.pre_hire_check()
- human: sends "is <target-live> live?" over the Chat Protocol (the ASI:One path)

Usage (from the repo root; never prints the seed):
    ENV_FILE=/abs/path/.env.dev .venv/bin/python scripts/e2e_prehire_local.py
Exit code 0 = every case passed.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import secrets
import sys
import time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from uagents import Agent, Context, Protocol  # noqa: E402
from uagents_core.contrib.protocols.chat import (  # noqa: E402
    ChatAcknowledgement,
    ChatMessage,
    TextContent,
    chat_protocol_spec,
)

from agent import agentverse as av  # noqa: E402
from agent import chat, config, main  # noqa: E402
from agent.probe import PROBE_TIMEOUT_S  # noqa: E402

NO_AGENT = "agent1qtxyynz433g33av2f0000k489xx6r590vfk6gcs0c2c2n6vnpc0nxehvvpm"  # never local


def load_client():
    spec = importlib.util.spec_from_file_location("prehire_client",
                                                  ROOT / "examples" / "prehire_client.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FixtureClient:
    """Offline Agentverse data: the 'strong' fixture for any address."""

    def __init__(self):
        d = json.loads((ROOT / "tests" / "fixtures" / "strong.json").read_text())
        d.pop("captured_at", None)
        d["notes"] = tuple(d.get("notes") or ())
        self.lk = av.Lookup(**d)

    async def lookup(self, address):
        return replace(self.lk, address=address, query=address)

    async def lookup_handle(self, handle):
        return replace(self.lk, query="@" + handle)

    async def resolve_handle(self, handle):
        return "not_found", None

    async def aclose(self):
        pass


async def _noop(*a, **k):
    return None


def offline(agent: Agent) -> Agent:
    agent._update_agent_status = _noop  # no Almanac status POST on start/stop
    return agent


def throwaway(name: str, loop, replies: int, counter: dict) -> Agent:
    a = offline(Agent(name=name, seed=secrets.token_hex(32), loop=loop, mailbox=False,
                      enable_agent_inspector=False, publish_agent_details=False,
                      report_events=False, mark_inactive_on_shutdown=False,
                      network="mainnet"))
    proto = Protocol(spec=chat_protocol_spec)

    @proto.on_message(ChatMessage)
    async def on_msg(ctx: Context, sender: str, msg: ChatMessage):
        counter["chat_in"] += 1
        await ctx.send(sender, ChatAcknowledgement(acknowledged_msg_id=msg.msg_id))
        for i in range(replies):
            await asyncio.sleep(0.3)
            await ctx.send(sender, ChatMessage(content=[TextContent(text=f"I can help ({i})")]))

    @proto.on_message(ChatAcknowledgement)
    async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
        counter["acks_in"] += 1

    a.include(proto)
    return a


async def scenario(loop) -> int:
    settings = config.load()  # dev only: refuses the prod seed / prod env file
    chat.CLIENT = FixtureClient()
    doctor = offline(main.build(settings, publish_manifests=False, loop=loop, mailbox=False,
                                enable_agent_inspector=False, publish_agent_details=False,
                                report_events=False, mark_inactive_on_shutdown=False))
    counters = {n: {"chat_in": 0, "acks_in": 0} for n in ("live", "ackonly", "chatty")}
    live = throwaway("target-live", loop, 1, counters["live"])
    ackonly = throwaway("target-ackonly", loop, 0, counters["ackonly"])
    chatty = throwaway("target-chatty", loop, 5, counters["chatty"])
    client = offline(Agent(name="prehire-client", seed=secrets.token_hex(32), loop=loop,
                           mailbox=False, enable_agent_inspector=False,
                           publish_agent_details=False, report_events=False,
                           mark_inactive_on_shutdown=False))
    human_replies: list[str] = []
    human = offline(Agent(name="human", seed=secrets.token_hex(32), loop=loop, mailbox=False,
                          enable_agent_inspector=False, publish_agent_details=False,
                          report_events=False, mark_inactive_on_shutdown=False))
    hproto = Protocol(spec=chat_protocol_spec)

    @hproto.on_message(ChatMessage)
    async def h_msg(ctx: Context, sender: str, msg: ChatMessage):
        human_replies.append(msg.text())

    @hproto.on_message(ChatAcknowledgement)
    async def h_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
        pass

    human.include(hproto)
    for a in (doctor, live, ackonly, chatty, client, human):
        a.setup()
    await asyncio.sleep(0.5)

    snippet = load_client()
    cctx = client._build_context()
    t0 = time.monotonic()
    cases = {
        "live": live.address,
        "degraded": ackonly.address,
        "live(chatty)": chatty.address,
        "unreachable": NO_AGENT,
    }
    # One context (= one session) per parallel call: send_and_receive keys on the session.
    results = await asyncio.gather(*[
        snippet.pre_hire_check(client._build_context(), addr, timeout=40, doctor=doctor.address)
        for addr in cases.values()])
    took = time.monotonic() - t0

    # Cached second call: no new probe message to the target.
    before = counters["live"]["chat_in"]
    again = await snippet.pre_hire_check(cctx, live.address, timeout=40, doctor=doctor.address)

    # Human chat path (ASI:One-style): one ChatMessage in, one text verdict out.
    hctx = human._build_context()
    await hctx.send(doctor.address, ChatMessage(content=[TextContent(
        text=f"is {live.address} live?")]))
    for _ in range(100):
        if human_replies:
            break
        await asyncio.sleep(0.1)
    await asyncio.sleep(3)  # let the chatty target finish its burst

    ok = True

    def check(name, cond, info=""):
        nonlocal ok
        ok &= bool(cond)
        print(f"{'PASS' if cond else 'FAIL'} {name} {info}")

    for (label, addr), r in zip(cases.items(), results):
        want = label.split("(")[0]
        info = (f"status={getattr(r, 'status', None)} ack_ms={getattr(r, 'ack_ms', None)} "
                f"reply_ms={getattr(r, 'reply_ms', None)} score={getattr(r, 'trust_score', None)}"
                f" detail={getattr(r, 'detail', None)}")
        check(f"protocol {label}", r is not None and r.status == want, info)
    check("all four answered within probe timeout + slack", took < PROBE_TIMEOUT_S + 8,
          f"{took:.1f}s")
    check("second call is cached, no new probe", again is not None and again.cached
          and counters["live"]["chat_in"] == before, f"cached={getattr(again, 'cached', None)}")
    check("each target got exactly one probe message",
          all(c["chat_in"] == 1 for c in counters.values()), str(counters))
    # Chatty sent 5 replies: Doctor acks each one and sends no ChatMessage back (chat_in == 1).
    check("chatty target: 5 acks from Doctor, no reply loop",
          counters["chatty"]["acks_in"] == 5 and counters["chatty"]["chat_in"] == 1,
          str(counters["chatty"]))
    check("human chat path got a LIVE verdict",
          len(human_replies) == 1 and "LIVE" in human_replies[0],
          (human_replies[0].splitlines()[1] if human_replies else "no reply"))
    return 0 if ok else 1


def main_() -> int:
    if not os.getenv("ENV_FILE"):
        sys.exit("Set ENV_FILE to the absolute path of .env.dev")
    os.environ.setdefault("RUN_MODE", "dev")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(scenario(loop))
    finally:
        for t in asyncio.all_tasks(loop):
            t.cancel()
        loop.run_until_complete(asyncio.sleep(0))
        loop.close()


if __name__ == "__main__":
    sys.exit(main_())
