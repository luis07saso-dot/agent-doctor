"""Agent Chat Protocol wiring: ack first, guard, route, reply, log one line per request.

Log line (JSON after "REQ "): hashed sender, input type, outcome, latency, content types and
message shape (words masked, see agent/shape.py). Never message
bodies, never raw addresses of senders.

Live-probe traffic (agent/probe.py) is split off FIRST, right after the ack: a message from a
probed agent in a probe session goes to the prober, never to the guard/router/user path, so
Doctor never answers a probe reply (no reply loops). Logged as "PROBE {json}", not REQ.
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from uagents import Context, Protocol
from uagents_core.contrib.protocols.chat import (  # noqa: I001
    ChatAcknowledgement,
    ChatMessage,
    MetadataContent,
    ResourceContent,
    TextContent,
    chat_protocol_spec,
)

from agent import cards, prehire, profile, router, service
from agent.probe import PROBER
from agent.shape import shape
from agent.agentverse import AgentverseClient
from agent.guard import Guard

chat_proto = Protocol(spec=chat_protocol_spec)

MAX_TEXT_CHARS = 4000  # longer messages are cut (at a space) before routing

CLIENT: service.LookupClient = AgentverseClient()
GUARD = Guard()
SELF_HANDLES: tuple[str, ...] = ("agent-doctor", "agent-doctor-dev")
# "@<one of these>" in a message is a mention of us (ASI:One adds it to a new chat's first
# message), not an audit target. A bare own address is still audited (self-audit prompt).
SELF_ADDRESSES: tuple[str, ...] = (profile.SELF_ADDRESS,)


def configure(handle: str, address: str = "") -> None:
    """Called from main with the running agent's handle and address."""
    global SELF_HANDLES, SELF_ADDRESSES
    SELF_HANDLES = tuple(dict.fromkeys((handle, "agent-doctor", "agent-doctor-dev")))
    SELF_ADDRESSES = tuple(a for a in dict.fromkeys((address, profile.SELF_ADDRESS)) if a)


def hash_id(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:12]


def _session(ctx: Context) -> str:
    try:
        return str(ctx.session or "")
    except Exception:
        return ""


def _cut(text: str) -> str:
    if len(text) <= MAX_TEXT_CHARS:
        return text
    head = text[:MAX_TEXT_CHARS]
    return head[: head.rfind(" ")] if " " in head else head  # don't split an address


def log_request(ctx: Context, sender: str, input_type: str, outcome: str, started: float,
                **extra) -> None:
    rec = {
        "sender": hash_id(sender),
        "session": hash_id(_session(ctx))[:8],  # L8: tells us if ASI:One reuses sessions/senders
        "input": input_type,
        "outcome": outcome,
        "latency_ms": int((time.monotonic() - started) * 1000),
        **extra,
    }
    try:
        ctx.logger.info("REQ " + json.dumps(rec, separators=(",", ":"), sort_keys=True))
    except Exception:
        pass  # logging must never break a reply


async def _reply(ctx: Context, sender: str, text: str, card: dict | None = None) -> None:
    """Q4: an ASI:One card rides in the SAME message as the full text (Fetch's news-card
    example), so clients without cards still get the whole reply."""
    content: list = [TextContent(text=text)]
    if card:
        content.append(MetadataContent(metadata=card))
    await ctx.send(sender, ChatMessage(content=content))


@chat_proto.on_message(ChatMessage)
async def on_chat(ctx: Context, sender: str, msg: ChatMessage) -> None:
    started = time.monotonic()
    meta: dict = {}
    try:
        await ctx.send(sender, ChatAcknowledgement(acknowledged_msg_id=msg.msg_id))
    except Exception as e:  # still try to answer
        ctx.logger.error(f"ack failed: {type(e).__name__}")

    if PROBER.owns(sender, _session(ctx)):  # reply to our live probe: never a user message
        try:
            await PROBER.on_chat(ctx, sender, msg)
        except Exception as e:
            ctx.logger.error(f"probe reply handler failed: {type(e).__name__}")
        return

    async def run_prehire(target) -> tuple[str, str, Any]:
        r, lk = await prehire.run_check_full(ctx, target, CLIENT, PROBER, True, target.label,
                                             deadline=started + service.REPLY_BUDGET_S)
        name = ((lk.profile or {}).get("name") if lk is not None and r.trust_score is not None
                else "")  # Q18: title by name, not the raw address
        return prehire.format_text(r, target.label, name or ""), r.status, lk

    try:
        text = _cut(msg.text().strip()).strip()
        # Structure only (words masked): shows how ASI:One rewrites messages. Never the body.
        meta = {"types": ",".join(str(getattr(c, "type", "?")) for c in msg.content),
                "shape": shape(text, SELF_ADDRESSES, SELF_HANDLES)}
        if not text:
            if any(isinstance(c, ResourceContent) for c in msg.content):
                await _reply(ctx, sender, router.NON_TEXT)
                log_request(ctx, sender, "non_text", "non_text", started, **meta)
            elif all(isinstance(c, TextContent) for c in msg.content) and msg.content:
                await _reply(ctx, sender, router.HELP)  # blank text only, from a user
                log_request(ctx, sender, "text", "help", started, **meta)
            else:
                # Session markers / metadata only: ack, no reply (matches the official example).
                log_request(ctx, sender, "control", "no_reply", started, **meta)
            return

        decision = GUARD.check(sender, _session(ctx), text)
        if decision == "drop":
            log_request(ctx, sender, "text", "dropped", started, **meta)
            return
        if decision in ("warn", "repeat"):
            await _reply(ctx, sender, router.RATE_LIMITED if decision == "warn" else router.REPEATED)
            log_request(ctx, sender, "text", "rate_limited" if decision == "warn" else "repeat",
                        started, **meta)
            return

        common = dict(prehire=run_prehire, probe=lambda address: PROBER.probe(ctx, address),
                      chat_key=hash_id(f"{sender}|{_session(ctx)}"), sender_key=hash_id(sender))
        deadline = started + service.REPLY_BUDGET_S
        sel = cards.parse_selection(text)  # Q4: a click on an audit card?
        if sel is not None:
            res = await service.handle_card(sel, CLIENT, SELF_HANDLES, SELF_ADDRESSES, **common)
        else:
            res = await service.handle(text, CLIENT, SELF_HANDLES, SELF_ADDRESSES, **common,
                                       deadline=deadline)
        await _reply(ctx, sender, res.text, res.card)
        extra = {"live": res.live} if res.live else {}
        if sel is not None:
            extra["click"] = sel.action
        if res.card:
            extra["card"] = True
        if res.llm:  # Q11: used | none | fallback | skip | off (never the text or the model output)
            extra["llm"] = res.llm
        if res.scout_hits >= 0:  # Q13: counts only, never the search phrase
            extra["scout_hits"] = res.scout_hits
            if res.scout_live:
                extra["scout_live"] = res.scout_live
        if res.find:  # Q12: counts only, never the phrases
            extra["find"] = res.find
            extra["find_top50"] = res.find_top50
        log_request(ctx, sender, res.input_type, res.outcome, started, targets=res.targets,
                    via_url=res.via_url, cached=res.cached, **extra, **meta)
    except Exception as e:
        # Type name only: exception text could carry message content or URLs.
        ctx.logger.error(f"chat handler failed: {type(e).__name__}")
        try:
            await _reply(ctx, sender, router.FALLBACK)
        finally:
            log_request(ctx, sender, "unknown", "fallback", started, **meta)


@chat_proto.on_message(ChatAcknowledgement)
async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement) -> None:
    if PROBER.owns(sender, _session(ctx)):
        try:
            await PROBER.on_ack(ctx, sender, msg)
        except Exception as e:
            ctx.logger.error(f"probe ack handler failed: {type(e).__name__}")
