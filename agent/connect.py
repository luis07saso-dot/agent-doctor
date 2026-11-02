"""One-shot mailbox connect. Run INSIDE the running container:

    docker compose exec -T agent python -m agent.connect

uagents only accepts /connect from 127.0.0.1, so this must run in the agent's
own network namespace. Reads AGENTVERSE_KEY from env. Never prints the key.
Re-runnable: re-publishes handle, description, README, avatar to Agentverse.
"""
import json
import os
import sys
import urllib.error
import urllib.request


def main() -> int:
    key = os.getenv("AGENTVERSE_KEY", "")
    if not key:
        print("FAIL: AGENTVERSE_KEY not set")
        return 2
    try:
        port = int(os.getenv("AGENT_PORT", "8001"))
    except ValueError:
        print("FAIL: AGENT_PORT not an integer")
        return 2
    body = json.dumps({"user_token": key, "agent_type": "mailbox"}).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/connect",
        data=body,
        headers={"content-type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        print(f"FAIL: HTTP {e.code}")
        return 1
    except (OSError, ValueError) as e:  # URLError, resets, timeouts, bad JSON
        print(f"FAIL: {type(e).__name__}")
        return 1
    if not isinstance(data, dict):
        print("FAIL: unexpected response")
        return 1
    if data.get("success"):
        print("OK: mailbox connected, profile published")
        return 0
    # Server detail is an Agentverse error string. Strip the key defensively.
    detail = str(data.get("detail", "unknown")).replace(key, "***")[:200]
    print(f"FAIL: {detail}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
