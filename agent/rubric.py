"""L3 rubric: every scoring constant lives here (open-source rubric).

Sources (verified 2026-11-02): docs.agentverse.ai v2 -> agent-optimization/ranking,
agent-discovery/readme-guidelines, agent-discovery/profile, agent-discovery/verifications,
agent-optimization/growth-metrics. Agentverse does NOT publish weights; these are our
estimates, ordered by the docs' emphasis:
- Only active agents are considered in ranking; inactive ones are de-prioritized unless
  searched for directly  -> biggest single weight. (Re-checked 2026-11-03.)
- Chat Protocol = boost, none = penalty; README = "primary" indexing document.
- Handle, avatar ("slight" boost), description, >=10 interactions = listed factors.
- Rating = recent + total interactions, successful ASI:One conversations, evaluations.
- Website verification = "immediate" lift. Starter prompts: UX only (not a listed factor).
Not scored: keywords (GET /v1/search/agents/{addr}/target-keywords needs auth: 401).

Field scales (sampled from 150 live search results): rating 0-5; recent_success_rate and
recent_eval_success_rate 0-1 floats or null; unresponsive bool; status active|inactive
(profile) and active|offline (almanac).
"""

# Chat Protocol 0.3.0 digest (computed from uagents_core chat_protocol_spec).
CHAT_PROTOCOL_NAME = "AgentChatProtocol"
CHAT_PROTOCOL_DIGEST = "30a801ed3a83f9a0ff0a9f1e6fe958cb91da1fc2218b153df7b6cbf87bd33d62"

RATING_MAX = 5.0
MIN_INTERACTIONS = 10
README_MIN_CHARS = 300  # below this a README is "too short to embed well"
README_SHORT_POINTS = 3.0  # partial credit for a README under README_MIN_CHARS
DESCRIPTION_MIN_CHARS = 40
DESCRIPTION_SHORT_POINTS = 2.0
HANDLE_MAX_CHARS = 20  # docs: custom handles are limited to 20 characters
SUMMARY_INTRO_MIN_CHARS = 80  # intro text before the first section counts as a Summary

# (rule id, max points). Order = tie-break order for fixes. Sums to 100.
WEIGHTS: dict[str, float] = {
    "active": 15,
    "chat_protocol": 12,
    "readme_sections": 15,
    "readme": 8,
    "rating": 10,
    "description": 6,
    "responsive": 6,
    "handle": 5,
    "avatar": 5,
    "interactions": 5,
    "success_rate": 4,
    "eval_rate": 4,
    "website": 3,
    "starter_prompts": 2,
}
assert sum(WEIGHTS.values()) == 100

# README sections from the Agentverse README guidelines. A section counts as present if a
# Markdown heading (outside code fences) has a word starting with any of its phrases
# (case-insensitive), e.g. "feature" matches "Key Features".
README_SECTIONS: dict[str, tuple[str, ...]] = {
    "Summary": ("summary", "overview", "about", "introduction", "description",
                "what it does", "what this agent does", "what the agent does"),
    "Key features": ("feature", "capabilit", "what you can ask", "what it can do",
                     "what the agent can do"),
    "Usage": ("usage", "how to use", "getting started", "quick start", "quickstart",
              "example input", "example output", "example quer", "example request",
              "example prompt", "how to call", "commands", "input and output", "inputs"),
    "Use cases": ("use case", "use-case", "usecase", "scenario", "who is it for",
                  "who it's for", "applications"),
    "Limitations": ("limitation", "known issue", "caveat", "cannot do", "can't do",
                    "not supported", "disclaimer", "constraints"),
    "Metadata": ("metadata", "credit", "author", "version", "license", "licence",
                 "contact", "changelog", "maintainer"),
}

VERDICTS: tuple[tuple[int, str], ...] = (  # (min score, label), first match wins
    (80, "Strong"),
    (60, "Good, with gaps"),
    (40, "Needs work"),
    (0, "Weak"),
)
DOWN_VERDICT = "Offline: de-prioritized in ranking"
