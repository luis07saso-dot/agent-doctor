"""Pure text routing. No I/O, so it is unit-testable and can never hang."""

HELP = (
    "**Agent Doctor** checks any Agentverse agent and tells you how to rank higher.\n\n"
    "Send me an agent address (`agent1q...`) or handle, e.g.:\n"
    "- `audit agent1q...`\n"
    "- `check @some-handle`\n\n"
    "Coming soon: full audit, Pre-Hire Check, Fix Pack."
)

FALLBACK = "Sorry, something went wrong on my side. Please try again in a minute."


def route(text: str) -> str:
    """Return the reply for a user message. Always returns a non-empty string."""
    return HELP
