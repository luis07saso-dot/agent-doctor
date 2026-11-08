"""Generate each task's "expected" findings from Agent Doctor's real scorer (agent/scorer.py).

Usage (from the repo root):
  python3 evals/gen_expected.py          rewrite "expected" in every evals/tasks/*.json
  python3 evals/gen_expected.py --check  exit 1 if any "expected" would change (writes nothing)

Expected = Doctor checks with kind == "found" that are not ok. why = "<detail>: <fix>".
Checks Doctor does not score (no_data, optional) are never findings. Never hand-edit "expected".
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / "evals" / "tasks"
sys.path.insert(0, str(ROOT))
from agent import scorer  # noqa: E402
from agent.rubric import CHAT_PROTOCOL_DIGEST, CHAT_PROTOCOL_NAME  # noqa: E402


def lookup(p: dict) -> SimpleNamespace:
    """A task's profile snapshot -> the lookup object Doctor's scorer reads."""
    protos = [{"name": CHAT_PROTOCOL_NAME, "digest": "proto:" + CHAT_PROTOCOL_DIGEST}] if p["chat_protocol"] else []
    profile = {
        "name": p["name"], "handle": p["handle"], "description": p["description"], "readme": p["readme"],
        "avatar_href": "https://example.invalid/a.png" if p["avatar"] else "",
        "protocols": protos, "status": p["status"], "unresponsive": p["unresponsive"],
        "rating": p["rating"], "total_interactions": p["total_interactions"],
        "recent_success_rate": p["recent_success_rate"], "recent_verified_interactions": p.get("recent_verified_interactions", 0),
        "recent_eval_success_rate": p["recent_eval_success_rate"], "domain": p["domain"],
        "starter_prompts": p["starter_prompts"],
    }
    almanac = {"status": "active" if p["status"] == "active" else "offline",
               "protocols": [CHAT_PROTOCOL_DIGEST] if p["chat_protocol"] else []}
    return SimpleNamespace(profile=profile, almanac=almanac, almanac_status="ok")


def main() -> int:
    check = "--check" in sys.argv[1:]
    files = sorted(TASKS_DIR.glob("*.json"))
    stale = []
    for f in files:
        t = json.loads(f.read_text())
        s = scorer.score(lookup(t["profile"]))
        expected = [{"rule": c.rule, "why": f"{c.detail}: {c.fix}"} for c in s.checks if not c.ok and c.kind == "found"]
        if check:
            if expected != t["expected"]:
                stale.append(t["id"])
            continue
        t["expected"] = expected
        f.write_text(json.dumps(t, indent=2, ensure_ascii=False) + "\n")
        not_findings = [f"{c.rule} ({c.kind}: {c.detail})" for c in s.checks if not c.ok and c.kind != "found"]
        print(f"{t['id']:<24} doctor={s.total:>3} expected={[e['rule'] for e in expected]} not_scored={not_findings}")
    if check:
        if stale:
            print(f"expected out of date: {', '.join(stale)} (run python3 evals/gen_expected.py)")
            return 1
        print(f"expected up to date ({len(files)} tasks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
