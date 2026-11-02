import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent import rubric as R
from agent.scorer import readme_sections_found, score

FIX = Path(__file__).parent / "fixtures"

FULL_README = """# Demo Agent

Demo agent turns long articles into short bullet summaries for busy readers. It works
with any public URL and replies in plain English within seconds.

## Key features
- Summaries
## Usage
Send a URL.
## Use cases
News triage.
## Limitations
English only.
## Metadata
Author: me. Version 1.0.
""" + ("More description. " * 20)


def lk(profile=None, almanac=None, almanac_status="ok"):
    return SimpleNamespace(profile=profile, almanac=almanac, almanac_status=almanac_status)


def perfect():
    profile = {
        "status": "active",
        "protocols": [{"digest": "proto:" + R.CHAT_PROTOCOL_DIGEST, "name": "AgentChatProtocol"}],
        "readme": FULL_README,
        "rating": 5.0,
        "description": "Summarises long news articles into five bullet points for busy readers.",
        "unresponsive": False,
        "handle": "demo-agent",
        "avatar_href": "https://example.com/a.png",
        "total_interactions": 500,
        "recent_success_rate": 1.0,
        "recent_eval_success_rate": 1.0,
        "domain": "example.com",
        "starter_prompts": ["Summarise https://example.com/news"],
    }
    almanac = {"status": "active", "protocols": [R.CHAT_PROTOCOL_DIGEST]}
    return profile, almanac


def fixture(name):
    d = json.loads((FIX / f"{name}.json").read_text())
    return lk(d["profile"], d["almanac"], d["almanac_status"])


def with_(rule_field, value, almanac_patch=None):
    p, a = perfect()
    if rule_field is not None:
        p[rule_field] = value
    if almanac_patch:
        a.update(almanac_patch)
    return score(lk(p, a))


# ---------- whole-score properties ----------

def test_weights_sum_to_100():
    assert sum(R.WEIGHTS.values()) == 100


def test_perfect_agent_scores_100():
    p, a = perfect()
    s = score(lk(p, a))
    assert s.total == 100 and s.verdict == "Strong" and not s.down and s.fixes == ()


def test_deterministic():
    for name in ("strong", "weak", "dead"):
        a, b = score(fixture(name)), score(copy.deepcopy(fixture(name)))
        assert a == b


def test_fixtures_in_expected_order():
    s, w, d = (score(fixture(n)) for n in ("strong", "weak", "dead"))
    assert s.total > w.total > d.total
    assert not s.down and not w.down and d.down
    assert d.verdict == R.DOWN_VERDICT
    assert d.fixes[0].rule == "active"


def test_fixes_ranked_by_points_lost():
    s = score(fixture("weak"))
    lost = [c.lost for c in s.fixes]
    assert lost == sorted(lost, reverse=True)
    d = score(fixture("dead"))
    assert d.fixes[0].rule == "active"  # offline first, even if a bigger fix exists
    rest = [c.lost for c in d.fixes[1:]]
    assert rest == sorted(rest, reverse=True)
    assert all(c.fix for c in s.fixes)


def test_empty_lookup_does_not_crash():
    s = score(lk(None, None, "api_down"))
    assert 0 <= s.total <= 100 and s.down and not s.indexed


@pytest.mark.parametrize("total,verdict", [(100, "Strong"), (80, "Strong"), (79, "Good, with gaps"),
                                           (40, "Needs work"), (39, "Weak"), (0, "Weak")])
def test_verdict_bands(total, verdict):
    assert next(v for m, v in R.VERDICTS if total >= m) == verdict


# ---------- one test per rule ----------

def test_rule_active():
    assert with_(None, None).check("active").ok
    s = with_("status", "inactive")
    assert not s.check("active").ok and s.down
    s = with_(None, None, {"status": "offline"})
    assert not s.check("active").ok and s.down
    # almanac 404 = not registered = down
    p, _ = perfect()
    s = score(lk(p, None, "not_found"))
    assert s.down and "Almanac" in s.check("active").detail
    # almanac unknown (API failed): fall back to profile status
    assert not score(lk(p, None, "timeout")).down


def test_rule_chat_protocol():
    assert with_(None, None).check("chat_protocol").ok
    p, a = perfect()
    p["protocols"] = [{"digest": "proto:abc", "name": "Default"}]
    a["protocols"] = ["abc"]
    assert not score(lk(p, a)).check("chat_protocol").ok
    # digest alone (unnamed) is enough
    p["protocols"] = [{"digest": "proto:" + R.CHAT_PROTOCOL_DIGEST, "name": ""}]
    assert score(lk(p, a)).check("chat_protocol").ok


def test_rule_readme_sections():
    assert readme_sections_found(FULL_README) == list(R.README_SECTIONS)
    s = with_("readme", "# X\n## Features\nstuff")
    c = s.check("readme_sections")
    assert c.detail == "1/6 sections" and "Usage" in c.fix and "Key features" not in c.fix
    assert readme_sections_found("") == []
    assert readme_sections_found("# T\n## Overview\n## How to use\n") == ["Summary", "Usage"]


def test_rule_readme():
    assert with_(None, None).check("readme").ok
    assert with_("readme", "").check("readme").points == 0
    assert with_("readme", None).check("readme").points == 0
    assert with_("readme", "short").check("readme").points == R.README_SHORT_POINTS


def test_rule_rating():
    assert with_("rating", 2.5).check("rating").points == R.WEIGHTS["rating"] / 2
    assert with_("rating", None).check("rating").points == 0
    assert with_("rating", 9).check("rating").points == R.WEIGHTS["rating"]  # clamped


def test_rule_description():
    assert with_(None, None).check("description").ok
    assert with_("description", "").check("description").points == 0
    assert with_("description", "Short.").check("description").points == R.DESCRIPTION_SHORT_POINTS


def test_rule_responsive():
    assert with_(None, None).check("responsive").ok
    assert not with_("unresponsive", True).check("responsive").ok
    assert not with_("status", "inactive").check("responsive").ok


def test_rule_handle():
    assert with_(None, None).check("handle").ok
    assert not with_("handle", None).check("handle").ok
    # Docs: a custom handle is the factor; 20 chars is the limit for setting one now.
    # Older, longer handles still exist (e.g. @agent-listing-generator): they have one.
    long = with_("handle", "agent-listing-generator").check("handle")
    assert long.ok and long.fix == ""
    assert not with_("handle", "").check("handle").ok


def test_rule_avatar():
    assert not with_("avatar_href", "").check("avatar").ok
    assert not with_("avatar_href", None).check("avatar").ok


def test_rule_interactions():
    assert with_("total_interactions", 10).check("interactions").ok
    assert not with_("total_interactions", 9).check("interactions").ok
    assert not with_("total_interactions", None).check("interactions").ok


def test_rule_success_rate():
    assert with_("recent_success_rate", 0.5).check("success_rate").points == 2
    c = with_("recent_success_rate", None).check("success_rate")
    assert c.points == 0 and c.detail == "none yet"


def test_rule_eval_rate():
    assert with_("recent_eval_success_rate", 0.25).check("eval_rate").points == 1
    assert with_("recent_eval_success_rate", None).check("eval_rate").points == 0


def test_rule_website():
    assert with_(None, None).check("website").ok
    assert not with_("domain", None).check("website").ok


def test_rule_starter_prompts():
    assert not with_("starter_prompts", None).check("starter_prompts").ok
    assert not with_("starter_prompts", ["  "]).check("starter_prompts").ok


def test_missing_readme_is_one_merged_fix():
    s = with_("readme", "")
    readme_fixes = [c for c in s.fixes if c.rule.startswith("readme")]
    assert len(readme_fixes) == 1
    assert readme_fixes[0].lost == R.WEIGHTS["readme"] + R.WEIGHTS["readme_sections"]
    assert "Limitations" in readme_fixes[0].fix


def test_readme_code_fence_comments_are_not_headings():
    readme = "# Bot\n```python\n# Usage\n# Limitations\n# Metadata\n```\n"
    assert readme_sections_found(readme) == []


def test_readme_phrase_matches_word_start_only():
    assert readme_sections_found("# T\n## Key Features\n") == ["Key features"]
    assert readme_sections_found("# T\n## Unfeatured stuff\n") == []


def test_readme_length_boundary():
    assert with_("readme", "x" * (R.README_MIN_CHARS - 1)).check("readme").points == R.README_SHORT_POINTS
    assert with_("readme", "x" * R.README_MIN_CHARS).check("readme").ok


def test_rating_bounds():
    assert with_("rating", 0).check("rating").points == 0
    assert with_("rating", 5).check("rating").ok
    assert with_("rating", -3).check("rating").points == 0
    assert with_("rating", True).check("rating").points == 0  # bool is not a rating
