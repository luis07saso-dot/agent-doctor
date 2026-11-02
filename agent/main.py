"""Entry point: python -m agent.main"""
from uagents import Agent

from agent import chat, config, profile
from agent.chat import chat_proto
from agent.prehire import prehire_proto
from agent.probe import PROBER


def build(settings: config.Settings, **overrides) -> Agent:
    """The Doctor agent. `overrides` go to Agent(...) (local tests: mailbox=False, ...)."""
    kwargs = dict(
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
        # Required by the live probe (agent/probe.py): a handler awaiting a probe must not
        # block the queue the probe's ack/reply arrive on. Also stops one slow audit from
        # delaying every other user.
        handle_messages_concurrently=True,
    )
    kwargs.update(overrides)
    agent = Agent(**kwargs)
    agent.include(chat_proto, publish_manifest=True)
    agent.include(prehire_proto, publish_manifest=True)
    chat.configure(settings.handle, agent.address)
    # Fresh session per probe so the target's replies can be told apart from user chats.
    # _build_context is uagents-internal (0.26.1, pinned): it is what on_interval uses.
    PROBER.configure(agent._build_context, chat.SELF_ADDRESSES)

    @agent.on_event("shutdown")
    async def _close_client(ctx) -> None:
        await chat.CLIENT.aclose()

    return agent


if __name__ == "__main__":
    build(config.load()).run()
