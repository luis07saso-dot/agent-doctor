"""Entry point: python -m agent.main"""
import os
from typing import Optional

from uagents import Agent

from agent import chat, config, guides, llm, profile
from agent.chat import chat_proto
from agent.prehire import prehire_proto
from agent.probe import PROBER


def build(settings: config.Settings, publish_manifests: bool = True, **overrides) -> Agent:
    """The Doctor agent. `overrides` go to Agent(...) (local tests: mailbox=False, ...).
    publish_manifests=False keeps offline/local runs from posting manifests to Agentverse."""
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
    _publish_starter_prompts(agent)
    agent.include(chat_proto, publish_manifest=publish_manifests)
    agent.include(prehire_proto, publish_manifest=publish_manifests)
    chat.configure(settings.handle, agent.address)
    # Fresh session per probe so the target's replies can be told apart from user chats.
    # _build_context is uagents-internal (0.26.1, pinned): it is what on_interval uses.
    PROBER.configure(agent._build_context, chat.SELF_ADDRESSES)

    @agent.on_event("shutdown")
    async def _close_client(ctx) -> None:
        try:
            await guides.LAST.memory.flush()  # Q15: don't lose the last debounced save
        finally:
            try:
                await chat.CLIENT.aclose()
            finally:
                await llm.MAPPER.aclose()  # Q11

    return agent


def _publish_starter_prompts(agent: Agent) -> None:
    """uagents 0.26.1 sends an empty starter_prompts list on mailbox /connect, which wipes
    prompts set in the dashboard on every deploy. Fill them from profile.STARTER_PROMPTS.
    Patches uagents-internal _build_registration_profile (pinned version)."""
    base = agent._build_registration_profile

    def _with_prompts():
        prof = base()
        if agent._publish_agent_details:
            prof.starter_prompts = list(profile.STARTER_PROMPTS)
        return prof

    agent._build_registration_profile = _with_prompts


def memory_path(address: str) -> Optional[str]:
    """Q15 memory file. MEMORY=0 -> in memory only. MEMORY_PATH overrides. Default: the cwd
    (/data in Docker, on the agent-data volume), one file per agent address."""
    if os.getenv("MEMORY", "").strip() == "0":
        return None
    return os.getenv("MEMORY_PATH") or os.path.join(os.getcwd(), f"doctor_memory_{address[:16]}.json")


if __name__ == "__main__":
    agent = build(config.load())
    path = memory_path(agent.address)
    if path:  # never in build(): tests build agents too
        guides.LAST.attach(path)
    agent.run()
