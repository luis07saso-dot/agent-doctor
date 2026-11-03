"""P6 hire-flow demo client (run ONCE via scripts/run_temp_agent.sh; never as a traffic source).

"Our demo client" needs a job done. It asks Agent Doctor (prod, AgentDoctorPreHire protocol)
to Pre-Hire Check each candidate, hires the best LIVE one, sends it ONE job message and waits
for the answer. Approved by the user 2026-11-03: candidates, job text, temp mailbox client
(registered via /connect, removed via /disconnect after the run).

Env: CLIENT_SEED (throwaway, never printed), AGENT_PORT, GO_FILE (run starts when it exists),
OUT_FILE (JSON results). Logs carry no seed or key.
"""
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    TextContent,
    chat_protocol_spec,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))
from prehire_client import PreHireResult, pre_hire_check, should_hire  # noqa: E402

CANDIDATES = [
    "ticketlens-agent",
    "agent-listing-generator",
    "agent1qddwng42rgf0sm2nkvz7whf4xtmcfx8j725kz9nsd7zk4qx8jmwugr8p379",  # known dead agent
]
JOB = ("Write a short Agentverse listing description for an agent that summarises "
       "news articles into 5 bullets.")
JOB_WAIT_S = 120

agent = Agent(name="doctor-p6-demo-client", seed=os.environ["CLIENT_SEED"],
              port=int(os.environ["AGENT_PORT"]), mailbox=True, network="mainnet")
chat = Protocol(spec=chat_protocol_spec)
STATE: dict = {"started": False, "hired": None, "sent_at": None,
               "ack_ms": None, "reply_ms": None, "reply": None}
GOT_REPLY = asyncio.Event()


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@chat.on_message(ChatAcknowledgement)
async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement) -> None:
    if sender == STATE["hired"] and STATE["sent_at"] and STATE["ack_ms"] is None:
        STATE["ack_ms"] = int((time.monotonic() - STATE["sent_at"]) * 1000)


@chat.on_message(ChatMessage)
async def on_chat(ctx: Context, sender: str, msg: ChatMessage) -> None:
    await ctx.send(sender, ChatAcknowledgement(acknowledged_msg_id=msg.msg_id))
    if sender != STATE["hired"] or STATE["reply"] is not None:
        return
    text = " ".join(c.text for c in msg.content if isinstance(c, TextContent)).strip()
    STATE["reply_ms"] = int((time.monotonic() - STATE["sent_at"]) * 1000)
    STATE["reply"] = text[:2000]
    GOT_REPLY.set()


agent.include(chat, publish_manifest=False)


def row(query: str, r: PreHireResult | None, took_ms: int) -> dict:
    if r is None:
        return {"query": query, "status": "no_answer_from_doctor", "took_ms": took_ms}
    keep = ("address", "status", "live", "detail", "chat_protocol", "active",
            "unresponsive_flag", "rating", "trust_score", "ack_ms", "reply_ms",
            "checked_at", "cached")
    return {"query": query, **{k: getattr(r, k) for k in keep}, "took_ms": took_ms}


async def run(ctx: Context) -> None:
    out: dict = {"client": agent.address, "started": now(), "candidates": [], "job": JOB}
    results = []
    for q in CANDIDATES:  # one call at a time per ctx (send_and_receive matches by session)
        t0 = time.monotonic()
        r = await pre_hire_check(ctx, q)
        took = int((time.monotonic() - t0) * 1000)
        out["candidates"].append(row(q, r, took))
        ctx.logger.info(f"pre-hire {q[:24]}: {r.status if r else 'no answer'} ({took} ms)")
        results.append((q, r))
    live = [(q, r) for q, r in results if should_hire(r)]
    if not live:
        out["decision"] = "no live candidate: hire nobody"
    else:
        q, best = max(live, key=lambda x: x[1].trust_score or 0)
        out["decision"] = f"hire {q} (live, trust_score {best.trust_score})"
        STATE["hired"] = best.address
        STATE["sent_at"] = time.monotonic()
        out["job_sent"] = now()
        await ctx.send(best.address, ChatMessage(content=[TextContent(text=JOB)]))
        try:
            await asyncio.wait_for(GOT_REPLY.wait(), JOB_WAIT_S)
        except asyncio.TimeoutError:
            pass
        out["job_ack_ms"] = STATE["ack_ms"]
        out["job_reply_ms"] = STATE["reply_ms"]
        out["job_reply"] = STATE["reply"]
    out["finished"] = now()
    Path(os.environ["OUT_FILE"]).write_text(json.dumps(out, indent=2))
    ctx.logger.info(f"done: {out['decision']}")


@agent.on_interval(period=3.0)
async def trigger(ctx: Context) -> None:
    if not STATE["started"] and Path(os.environ["GO_FILE"]).exists():
        STATE["started"] = True
        asyncio.ensure_future(run(ctx))


if __name__ == "__main__":
    agent.run()
