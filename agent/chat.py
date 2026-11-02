"""Agent Chat Protocol: ack first, then always reply."""
from uagents import Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    TextContent,
    chat_protocol_spec,
)

from agent.router import FALLBACK, route

chat_proto = Protocol(spec=chat_protocol_spec)


@chat_proto.on_message(ChatMessage)
async def on_chat(ctx: Context, sender: str, msg: ChatMessage) -> None:
    await ctx.send(sender, ChatAcknowledgement(acknowledged_msg_id=msg.msg_id))
    try:
        reply = route(msg.text().strip())
    except Exception:
        ctx.logger.exception("route failed")
        reply = FALLBACK
    await ctx.send(sender, ChatMessage(content=[TextContent(text=reply)]))


@chat_proto.on_message(ChatAcknowledgement)
async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement) -> None:
    pass
