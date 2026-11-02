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


# ASI:One prepends "@<agent address>" to the FIRST message of a new chat (seen live in the
# REQ log shape "@<SELF> w w w w?", 2026-11-02). That is a mention of us, not a target.
SELF = "agent1qwm50eahtwxe2jsjnqqgj3yqmcrpft3rkd42g8frh9twvdwugazfg3897tp"
ME = {"ignore_handles": ["agent-doctor"], "ignore_addresses": [SELF]}


def test_own_address_mention_is_not_a_target():
    ex = extract(f"@{SELF} What can you do?", **ME)
    assert ex.targets == () and not ex.bad_address
    assert extract(f"@{SELF} @agent-doctor What can you do?", **ME).targets == ()


def test_first_message_audit_targets_the_real_agent():
    assert addrs(f"@{SELF} audit {STRONG}", **ME) == [STRONG]
    assert handles(f"@{SELF} @agent-doctor check @agent-listing-generator", **ME) == [
        "agent-listing-generator"]


def test_bare_own_address_is_still_a_self_audit():
    assert addrs(f"@{SELF} Audit {SELF}", **ME) == [SELF]
    assert addrs(f"is {SELF} set up well?", **ME) == [SELF]


def test_other_address_mention_is_still_a_target():
    assert addrs(f"audit @{STRONG}", **ME) == [STRONG]


# M2: a handle typed WITHOUT "@" right after an audit word. In a new ASI:One chat an
# @handle can route the message to that agent instead of us (docs/smoke-test.md), so users
# can drop the "@". Only hyphenated, handle-shaped tokens count, so plain words never do.
@pytest.mark.parametrize(
    "text,expected",
    [
        ("audit agent-listing-generator", "agent-listing-generator"),
        ("@agent-doctor audit agent-listing-generator", "agent-listing-generator"),
        (f"@{SELF} audit agent-listing-generator", "agent-listing-generator"),
        ("Can you check the agent weather-bot-2?", "weather-bot-2"),
        ("review handle: crypto-whale-radar please", "crypto-whale-radar"),
        ("Audit Agent-Listing-Generator.", "agent-listing-generator"),
        ("check out trip-planner", "trip-planner"),
    ],
)
def test_bare_handle_after_audit_word(text, expected):
    assert handles(text, **ME) == [expected]


@pytest.mark.parametrize(
    "text",
    [
        "audit my agent",
        "audit the agent please",
        "check agentbuilder",  # no hyphen: too close to a plain word
        "agent-listing-generator is great",  # no audit word before it
        "I love well-known agents",
        "check my-site.com",
        "check https://example.com/foo-bar",
        "check foo_bar-baz",
        "audit foo-",
        "audit -foo-bar",
    ],
)
def test_bare_handle_not_read_from_plain_text(text):
    ex = extract(text, **ME)
    assert ex.targets == ()
    assert not ex.bad_address


def test_bare_own_handle_after_audit_word_is_a_self_audit():
    # "@agent-doctor" is ASI:One's mention of us; a typed "agent-doctor" is a request.
    assert handles("audit agent-doctor", **ME) == ["agent-doctor"]
    assert handles("@agent-doctor audit agent-doctor", **ME) == ["agent-doctor"]


def test_bare_and_at_handle_deduped():
    assert handles("audit weather-bot, i.e. @weather-bot", **ME) == ["weather-bot"]
