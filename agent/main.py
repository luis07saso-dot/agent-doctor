"""Entry point: python -m agent.main"""
from uagents import Agent

from agent import chat, config, profile
from agent.chat import chat_proto

settings = config.load()

agent = Agent(
    name=profile.NAME,  # display name only; the address comes from the seed
    seed=settings.seed,
    port=settings.port,
    mailbox=True,
    network="mainnet",  # identity + Almanac. Never change: prefix/address context would change.
    handle=settings.handle,
    description=profile.DESCRIPTION,
    readme_path=profile.readme_path(),
    avatar_url=profile.AVATAR_URL,
    publish_agent_details=True,  # profile is sent on mailbox /connect (deploy/connect.sh)
)
agent.include(chat_proto, publish_manifest=True)
chat.configure(settings.handle, agent.address)


@agent.on_event("shutdown")
async def _close_client(ctx) -> None:
    await chat.CLIENT.aclose()


if __name__ == "__main__":
    agent.run()
