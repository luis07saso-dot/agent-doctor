"""Create .env.dev with a fresh random dev seed. Never prints the seed.

Usage: .venv/bin/python scripts/make_dev_env.py
Run locally with: ENV_FILE=.env.dev .venv/bin/python -m agent.main
"""
import os
import secrets
import sys

PATH = ".env.dev"

if os.path.exists(PATH):
    sys.exit(f"{PATH} exists. Not overwriting (it holds the dev identity).")
fd = os.open(PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w") as f:
    f.write(f"AGENT_SEED_PHRASE=dev-{secrets.token_hex(32)}\n")
    f.write("AGENT_HANDLE=agent-doctor-dev\n")
    f.write("FET_NETWORK=testnet\n")
    f.write("AGENT_PORT=8002\n")
print(f"OK: wrote {PATH} (mode 600, seed not shown)")
