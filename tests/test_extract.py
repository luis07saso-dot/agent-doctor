import pytest

from agent.extract import Target, extract, valid_checksum

STRONG = "agent1qfvydlgcxrvga2kqjxhj3hpngegtysm2c7uk48ywdue0kgvtc2f5cwhyffv"
WEAK = "agent1qtxyynz433g33av2f0000k489xx6r590vfk6gcs0c2c2n6vnpc0nxehvvpm"


def addrs(text, **kw):
    return [t.value for t in extract(text, **kw).targets if t.kind == "address"]


def handles(text, **kw):
    return [t.value for t in extract(text, **kw).targets if t.kind == "handle"]


def test_checksum_valid_and_typo():
    assert valid_checksum(STRONG)
    assert not valid_checksum(STRONG[:-1] + ("q" if STRONG[-1] != "q" else "p"))


@pytest.mark.parametrize(
    "text",
    [
        STRONG,
        f"audit {STRONG}",
        f"Can you check {STRONG}? thanks",
        f"Please audit the agent with address `{STRONG}`.",
        f"Check **{STRONG}**",
        f"(see {STRONG})",
        f"check {STRONG.upper()}",
        f"https://agentverse.ai/agents/details/{STRONG}/profile",
        f"how does https://agentverse.ai/agents/details/{STRONG}/profile rank?",
        f"test-agent://{STRONG}",
    ],
)
def test_address_in_sentence(text):
    assert addrs(text) == [STRONG]


@pytest.mark.parametrize(
    "text,expected",
    [
        ("check @weather-bot", "weather-bot"),
        ("audit @TripPlanner please", "tripplanner"),
        ("How good is @agent-doctor-dev?", "agent-doctor-dev"),
        ("@crypto-whale-radar", "crypto-whale-radar"),
        ("rank of https://agentverse.ai/@some-agent ?", "some-agent"),
        ("https://asi1.ai/agents/@abc123/profile", "abc123"),
    ],
)
def test_handle_in_sentence(text, expected):
    assert handles(text) == [expected]


def test_multiple_targets_in_order_and_deduped():
    text = f"compare @alpha with {STRONG} and {WEAK}, also @alpha and {STRONG}"
    ex = extract(text)
    assert [t.label for t in ex.targets] == ["@alpha", STRONG, WEAK]


def test_own_handle_ignored():
    text = "@agent-doctor please audit @weather-bot"
    assert handles(text, ignore_handles=["agent-doctor"]) == ["weather-bot"]
    assert extract("@agent-doctor hi", ignore_handles=["@agent-doctor"]).targets == ()


@pytest.mark.parametrize(
    "text",
    [
        "",
        "hello",
        "what can you do?",
        "email me at bob@example.com",
        "follow https://x.com/@someone",
        "see https://github.com/@org/repo",
        "the weather agent",
        "@",
        "@-bad",
        "price is $5 @ 3pm",
        "agent1",
        "my agent is great",
        "check @foo_bar",
        "mail @example.com now",
        "agent1qxyz12345678 hi",
        "check @foo-",
    ],
)
def test_junk_has_no_targets(text):
    ex = extract(text)
    assert ex.targets == ()
    assert not ex.bad_address


@pytest.mark.parametrize(
    "text",
    [
        f"audit {STRONG[:-5]}",  # truncated paste
        f"audit {STRONG}xyz",  # too long
        f"audit {STRONG[:-1]}{'q' if STRONG[-1] != 'q' else 'p'}",  # checksum typo
    ],
)
def test_bad_address_flagged(text):
    ex = extract(text)
    assert ex.targets == ()
    assert ex.bad_address


def test_bad_address_ignored_when_good_target_present():
    ex = extract(f"{STRONG[:-5]} or {WEAK}")
    assert [t.value for t in ex.targets] == [WEAK]
    assert not ex.bad_address


def test_target_label():
    assert Target("handle", "abc").label == "@abc"
    assert Target("address", STRONG).label == STRONG
