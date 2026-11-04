"""L6 Agentverse profile: one place for every public profile field.

Published on mailbox `/connect` (uagents 0.26.1 sends name, handle, description, README,
avatar; STARTER_PROMPTS added by agent/main.py). Keywords are NOT sent by `/connect`: set
them with scripts/set_keywords.py (Agentverse target-keywords API) or the dashboard.
KEYWORDS below is the source of truth; `set_keywords.py` shows live vs source.
After changing anything here: redeploy, then re-run deploy/connect.sh.
"""
from __future__ import annotations

from pathlib import Path

# Docs: name "ideally under 20 characters", task-oriented, no keyword stuffing.
# Registration hard limit: 32 chars. Never affects the address (that comes from the seed).
NAME = "Agent Doctor"

# Registration limit 300 chars. Shown on the profile and the Marketplace card.
DESCRIPTION = (
    "Free audit for Agentverse agents. Send an agent address or @handle and get a 0-100 "
    "ranking score plus the top fixes to improve agent ranking and discoverability on "
    "Agentverse and ASI:One search."
)

# Served by Caddy on the VPS (see HYDRATE.md). Source image: doctor-avatar.jpeg.
AVATAR_URL = "https://leedr.tech/agent-doctor/avatar.jpg"

# Repo root README.md (in the image at /app/README.md). Absolute path: the container's CWD
# is /data, and uagents joins readme_path onto the CWD.
README_PATH = Path(__file__).resolve().parent.parent / "README.md"

# Max 10. Each must appear in README.md (tests enforce it). Set in the Agentverse UI.
KEYWORDS: tuple[str, ...] = (
    "agent audit",
    "agentverse ranking",
    "improve agent ranking",
    "agentverse seo",
    "agent discoverability",
    "agent readme review",
    "agent not responding",
    "agent profile score",
    "audit my agent",
    "agentverse optimization",
)

# Each must route to a useful reply on its own (tests enforce it). Published on /connect.
SELF_ADDRESS = "agent1qwm50eahtwxe2jsjnqqgj3yqmcrpft3rkd42g8frh9twvdwugazfg3897tp"
STARTER_PROMPTS: tuple[str, ...] = (
    "What can you do?",
    "Audit my agent",
    f"Audit {SELF_ADDRESS}",
    "How do I improve my agent's ranking on ASI:One?",
)


def readme_path() -> str | None:
    """Absolute README path, or None if missing (agent still starts, just without README)."""
    return str(README_PATH) if README_PATH.is_file() else None
