"""Message shape: structure of an incoming message with every word masked (privacy-safe)."""
from agent.shape import shape

SELF = "agent1qwm50eahtwxe2jsjnqqgj3yqmcrpft3rkd42g8frh9twvdwugazfg3897tp"
OTHER = "agent1qfvydlgcxrvga2kqjxhj3hpngegtysm2c7uk48ywdue0kgvtc2f5cwhyffv"
HANDLES = ("agent-doctor",)


def s(text):
    return shape(text, SELF, HANDLES)


def test_words_are_masked():
    assert s("What can you do?") == "w w w w?"


def test_own_address_and_mention_forms():
    assert s(f"@{SELF} What can you do?") == "@<SELF> w w w w?"
    assert s(f"{SELF}: hi") == "<SELF>: w"


def test_other_address_url_and_handles():
    assert s(f"audit {OTHER} please") == "w <ADDR> w"
    assert s("see https://agentverse.ai/agents/x now") == "w <URL> w"
    assert s("@agent-doctor @agent-listing-generator w") == "@<SELF_H> @<H> w"


def test_address_like_typo_and_newlines():
    assert s(f"{OTHER[:-4]} x") == "<ADDR?> w"
    assert s("hi\n\n  there") == "w w"


def test_no_letters_or_digits_leak_and_capped():
    out = s("Secret plan 42 for ACME Corp " * 50)
    assert len(out) <= 160
    assert not any(c.isalnum() for c in out.replace("w", ""))


def test_empty():
    assert s("") == ""
