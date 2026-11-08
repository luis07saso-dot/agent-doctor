"""TQ6 demo (not scored, not a counted run): snapshot real Agentverse listings in the eval task shape.

Usage (from the repo root):
  python3 scripts/demo_snapshot.py <agent1... address> [<address> ...]

Fetches each public profile + almanac with Agent Doctor's own client (agent/agentverse.py, no key),
and writes tmp/demo/snapshots/NN-<slug>.json. "expected" = Agent Doctor's live scorer on the real
lookup (same rule as evals/gen_expected.py). "job" = the listing's own description (real listings
have no owner's note), else its name. Never writes to evals/ or runs/.
"""
import asyncio
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from agent import scorer  # noqa: E402
from agent.agentverse import AgentverseClient, is_address  # noqa: E402
from agent.rubric import CHAT_PROTOCOL_DIGEST  # noqa: E402
from evals.gen_expected import lookup as snapshot_lookup  # noqa: E402

OUT = ROOT / "tmp" / "demo" / "snapshots"


def snapshot(p: dict) -> dict:
    """Raw Agentverse profile -> the eval task's profile shape (evals/tasks/*.json)."""
    digest = "proto:" + CHAT_PROTOCOL_DIGEST
    return {
        "name": p.get("name") or "",
        "handle": p.get("handle") or "",
        "description": p.get("description") or "",
        "readme": p.get("readme") or "",
        "avatar": bool(p.get("avatar_href")),
        "chat_protocol": any(x.get("digest") == digest for x in p.get("protocols") or []),
        "status": p.get("status") or "inactive",
        "unresponsive": bool(p.get("unresponsive")),
        "rating": p.get("rating"),
        "total_interactions": p.get("total_interactions") or 0,
        "recent_success_rate": p.get("recent_success_rate"),
        "recent_verified_interactions": p.get("recent_verified_interactions") or 0,
        "recent_eval_success_rate": p.get("recent_eval_success_rate"),
        "domain": p.get("domain"),
        "starter_prompts": p.get("starter_prompts") or [],
    }


def findings(s) -> list[dict]:
    return [{"rule": c.rule, "why": f"{c.detail}: {c.fix}"} for c in s.checks if not c.ok and c.kind == "found"]


async def main(addrs: list[str]) -> int:
    bad = [a for a in addrs if not is_address(a)]
    if not addrs or bad:
        print(f"usage: python3 scripts/demo_snapshot.py <agent1... address> ...  (invalid: {bad})")
        return 2
    OUT.mkdir(parents=True, exist_ok=True)
    client = AgentverseClient()
    try:
        for i, a in enumerate(addrs, 1):
            lk = await client.lookup(a)
            if lk.outcome != "ok" or not lk.profile:
                print(f"{a[:14]}…  lookup {lk.outcome}: skipped")
                continue
            prof = snapshot(lk.profile)
            expected = findings(scorer.score(lk))
            # The agent only sees the snapshot: make sure Doctor gives the same answer on it.
            again = findings(scorer.score(snapshot_lookup(prof)))
            if [e["rule"] for e in again] != [e["rule"] for e in expected]:
                print(f"{a[:14]}…  WARN snapshot changes Doctor's findings: {[e['rule'] for e in again]}")
            slug = re.sub(r"[^a-z0-9]+", "-", prof["name"].lower()).strip("-")[:40] or "agent"
            task = {
                "id": f"{i:02d}-{slug}",
                "title": prof["name"],
                "holdout": False,
                "profile": prof,
                "job": prof["description"] or prof["name"],
                "must_keep": [],
                "expected": expected,
            }
            path = OUT / f"{task['id']}.json"
            path.write_text(json.dumps(task, indent=2, ensure_ascii=False) + "\n")
            print(f"{task['id']:<44} doctor={scorer.score(lk).total:>3} expected={[e['rule'] for e in expected]}")
    finally:
        await client.aclose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
