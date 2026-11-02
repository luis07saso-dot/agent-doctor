import json
from pathlib import Path

import pytest

from agent import agentverse as av
from agent.report import MAX_CHARS, clean, format_report, short_address
from agent.scorer import score

FIX = Path(__file__).parent / "fixtures"


def load(name) -> av.Lookup:
    d = json.loads((FIX / f"{name}.json").read_text())
    d.pop("captured_at", None)
    d["notes"] = tuple(d.get("notes") or ())
    return av.Lookup(**d)


@pytest.mark.parametrize("name", ["strong", "weak", "dead"])
def test_fixtures_render_under_limit(name):
    lk = load(name)
    sc = score(lk)
    out = format_report(lk, sc)
    assert out and len(out) <= MAX_CHARS
    assert f"Score {sc.total}/100" in out
    assert "**Top fixes**" in out
    assert out.count("\n1. ") == 1 and "\n3. " in out
    assert lk.address in out  # profile link


def test_dead_agent_says_offline_first():
    lk = load("dead")
    out = format_report(lk, score(lk))
    assert "Offline" in out
    assert out.index("Bring the agent online") < out.index("README")


def test_handle_shown_when_present():
    lk = load("weak")
    assert "(@blank-agent-621)" in format_report(lk, score(lk))


def test_hostile_profile_text_is_cleaned_and_bounded():
    lk = load("weak")
    prof = dict(lk.profile, name="**pwn**\n# [x](http://evil) `code` " + "A" * 500,
                handle="h" * 300, domain="d" * 500)
    lk2 = av.Lookup(query=lk.query, outcome="ok", address=lk.address, profile=prof,
                    almanac=lk.almanac, almanac_status="ok")
    out = format_report(lk2, score(lk2))
    assert len(out) <= MAX_CHARS
    first = out.splitlines()[0]
    assert "](" not in first and "`" not in first and "#" not in first


def test_not_indexed_and_partial_notes():
    lk = av.Lookup(query="x", outcome="partial", address=load("weak").address, profile=None,
                   almanac={"status": "active"}, profile_status="not_found",
                   almanac_status="ok", notes=("registered in almanac but not in search index",))
    out = format_report(lk, score(lk))
    assert "Not in the Agentverse search index" in out
    assert "Almanac check failed" not in out
    lk = load("strong")
    lk = av.Lookup(**{**lk.__dict__, "outcome": "partial", "almanac": None,
                      "almanac_status": "timeout", "notes": ("almanac timeout",)})
    out = format_report(lk, score(lk))
    assert "Almanac check failed" in out and len(out) <= MAX_CHARS


def test_perfect_agent_has_no_fixes_line():
    from tests.test_scorer import lk as mk, perfect

    p, a = perfect()
    look = mk(p, a)
    look.address = "agent1qfvydlgcxrvga2kqjxhj3hpngegtysm2c7uk48ywdue0kgvtc2f5cwhyffv"
    look.notes = ()
    out = format_report(look, score(look))
    assert "No fixes needed" in out and "Top fixes" not in out


def test_helpers():
    assert clean(None) == ""
    assert clean("a\nb  c") == "a b c"
    assert len(clean("x" * 100)) == 60
    assert short_address(None) == "unknown address"
    assert short_address("agent1qfvydlgcxrvga2kq").startswith("agent1qfvy…")


def test_links_and_invisible_chars_stripped():
    assert "evil" not in clean("Free money https://evil.com/x now")
    assert "www" not in clean("visit www.evil.com today")
    assert clean("ab\u202ecd\u200b") == "abcd"


def test_untrusted_domain_not_printed_raw():
    from agent.report import safe_domain

    assert safe_domain("weather.fetch.ai") == "weather.fetch.ai"
    assert safe_domain("[x](https://evil)") == "set"
