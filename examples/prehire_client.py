"""Pre-Hire Check client: ask Agent Doctor if an agent really answers before you hire it.

Copy-paste into your uAgent (uagents >= 0.25.5). Keep the two models EXACTLY as they are:
class names, field names, types and defaults define the schema digest Doctor matches on.

    result = await pre_hire_check(ctx, "agent1q...")      # or "@handle" / profile URL
    if result and result.live: ...hire it...

Result fields: status (live | degraded | unreachable | unknown | not_found | invalid |
rate_limited | error), live, ack_ms, reply_ms (Doctor's one test message), chat_protocol,
active, unresponsive_flag, rating (0-5), trust_score (Doctor's 0-100 profile score),
checked_at (UTC), cached (Doctor caches each target for 10 min), detail, profile_url.

Run this file as a demo:  CLIENT_SEED="<your own long random seed>" TARGET="agent1q..." \
    python prehire_client.py
"""
import asyncio
import os
from typing import Optional

from uagents import Agent, Context, Model

AGENT_DOCTOR = "agent1qwm50eahtwxe2jsjnqqgj3yqmcrpft3rkd42g8frh9twvdwugazfg3897tp"


class PreHireRequest(Model):
    address: str
    live_probe: bool = True


class PreHireResult(Model):
    query: str
    address: str = ""
    status: str
    live: bool = False
    detail: str = ""
    chat_protocol: Optional[bool] = None
    active: Optional[bool] = None
    unresponsive_flag: Optional[bool] = None
    rating: Optional[float] = None
    trust_score: Optional[int] = None
    ack_ms: Optional[int] = None
    reply_ms: Optional[int] = None
    checked_at: str = ""
    cached: bool = False
    profile_url: str = ""


async def pre_hire_check(ctx: Context, agent: str, live_probe: bool = True,
                         timeout: int = 45, doctor: str = AGENT_DOCTOR
                         ) -> Optional[PreHireResult]:
    """Ask Doctor about `agent`. None if Doctor didn't answer in `timeout` seconds.
    live_probe=False skips the test message: profile data only, answers in ~1s.
    One call at a time per ctx: send_and_receive matches the answer by session, so run
    parallel checks from separate contexts (e.g. separate handler invocations)."""
    reply, _status = await ctx.send_and_receive(
        doctor, PreHireRequest(address=agent, live_probe=live_probe),
        response_type=PreHireResult, timeout=timeout)
    return reply if isinstance(reply, PreHireResult) else None


def should_hire(r: Optional[PreHireResult], min_score: int = 0) -> bool:
    """Example policy: it answered just now, and (optionally) a minimum profile score."""
    return bool(r and r.live and (r.trust_score or 0) >= min_score)


if __name__ == "__main__":
    agent = Agent(name="prehire-demo-client", seed=os.environ["CLIENT_SEED"], mailbox=True)
    target = os.environ["TARGET"]  # the agent you want to hire

    @agent.on_event("startup")
    async def _start(ctx: Context) -> None:
        async def run() -> None:
            r = await pre_hire_check(ctx, target)
            if r is None:
                ctx.logger.info("Agent Doctor did not answer in time")
            else:
                ctx.logger.info(f"{r.status} live={r.live} ack_ms={r.ack_ms} "
                                f"reply_ms={r.reply_ms} score={r.trust_score} "
                                f"hire={should_hire(r)}")

        asyncio.ensure_future(run())  # don't block startup

    agent.run()
