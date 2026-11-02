"""Capture real Agentverse lookups as test fixtures (live network).

Usage: .venv/bin/python scripts/capture_fixtures.py
Writes tests/fixtures/{strong,weak,dead}.json. Re-run to refresh.
"""
import asyncio
import dataclasses
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent.agentverse import AgentverseClient  # noqa: E402

TARGETS = {
    # Full profile: README, description, avatar, starter prompts, Chat Protocol.
    "strong": "agent1qfvydlgcxrvga2kqjxhj3hpngegtysm2c7uk48ywdue0kgvtc2f5cwhyffv",
    # Active + Chat Protocol, but blank: no README, description or avatar.
    "weak": "agent1qtxyynz433g33av2f0000k489xx6r590vfk6gcs0c2c2n6vnpc0nxehvvpm",
    # Status inactive.
    "dead": "agent1qddwng42rgf0sm2nkvz7whf4xtmcfx8j725kz9nsd7zk4qx8jmwugr8p379",
}
OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures"


async def main() -> int:
    client = AgentverseClient()
    OUT.mkdir(parents=True, exist_ok=True)
    rc = 0
    try:
        for name, addr in TARGETS.items():
            lk = await client.lookup(addr)
            p = lk.profile or {}
            a = lk.almanac or {}
            print(
                f"{name}: outcome={lk.outcome} {lk.elapsed_s}s "
                f"profile={lk.profile_status} almanac={lk.almanac_status} "
                f"search_status={p.get('status')} almanac_status={a.get('status')} "
                f"readme={len(p.get('readme') or '')} avatar={bool(p.get('avatar_href'))} "
                f"desc={bool(p.get('description'))} handle={p.get('handle')}"
            )
            if lk.outcome not in ("ok", "partial"):
                rc = 1
                continue
            data = dataclasses.asdict(lk)
            data["captured_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            (OUT / f"{name}.json").write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    finally:
        await client.aclose()
    return rc


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
