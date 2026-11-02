"""Entry point: python -m agent.main"""
from uagents import Agent

from agent import chat, config
from agent.chat import chat_proto

settings = config.load()

agent = Agent(
    name="agent-doctor",
    seed=settings.seed,
    port=settings.port,
    mailbox=True,
    network="mainnet",  # identity + Almanac. Never change: prefix/address context would change.
    handle=settings.handle,
    description="Audits any Agentverse agent and returns a ranking fix-list.",
    publish_agent_details=True,
)
agent.include(chat_proto, publish_manifest=True)
chat.configure(settings.handle)


@agent.on_event("shutdown")
async def _close_client(ctx) -> None:
    await chat.CLIENT.aclose()


if __name__ == "__main__":
    agent.run()
