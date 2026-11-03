"""R11 before/after test agent (dev seed). Run via scripts/temp_agent.sh; temporary.

Applies Agent Doctor's own fixes for a blank agent: bring it online, README with the six
sections (docs/r11/README.md), handle, description, avatar. Replies to every chat (echo).
Approved by the user 2026-11-03. Removed from Agentverse with `temp_agent.sh stop` after.
Env: CLIENT_SEED (dev seed, never printed), AGENT_PORT.
"""
import os
from pathlib import Path

from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    TextContent,
    chat_protocol_spec,
)

ROOT = Path(__file__).resolve().parents[1]

agent = Agent(
    name="R11 Test Agent",
    seed=os.environ["CLIENT_SEED"],
    port=int(os.environ["AGENT_PORT"]),
    mailbox=True,
    network="mainnet",
    handle="doctor-r11-test",
    description="Temporary echo agent used to test Agent Doctor's fix guides. Will be removed.",
    readme_path=str(ROOT / "docs" / "r11" / "README.md"),
    avatar_url="https://leedr.tech/agent-doctor/avatar.jpg",
    publish_agent_details=True,
)
chat = Protocol(spec=chat_protocol_spec)


@chat.on_message(ChatMessage)
async def on_chat(ctx: Context, sender: str, msg: ChatMessage) -> None:
    await ctx.send(sender, ChatAcknowledgement(acknowledged_msg_id=msg.msg_id))
    text = " ".join(c.text for c in msg.content if isinstance(c, TextContent)).strip()[:300]
    await ctx.send(sender, ChatMessage(content=[TextContent(
        text=f"Echo: {text or '(empty)'} (I am a temporary test agent for Agent Doctor.)")]))


@chat.on_message(ChatAcknowledgement)
async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement) -> None:
    pass


agent.include(chat, publish_manifest=True)

if __name__ == "__main__":
    agent.run()
