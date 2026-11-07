"""Q21 (FB-6) honest Testing wording + Q22a (FB-7) shorter replies.
Spec: docs/specs/q20-q22-builder-notes.md. User 2026-11-07: keep "no data scores 0" (no
rescale), website unchanged, How: on fix #1 only."""
import dataclasses
import json
from pathlib import Path

import pytest

from agent import agentverse as av
from agent import evidence, guides, router, service
from agent.report import checks_line, format_report
from agent.scorer import score

FIX = Path(__file__).parent / "fixtures"
FIXTURES = ["strong", "weak", "dead", "flagged"]
REPORT_CAP = 1000  # was 1,248-1,442 before Q22a; profile link alone is ~125
HELP_CAP = 600  # was 1,070


def load(name) -> av.Lookup:
    d = json.loads((FIX / f"{name}.json").read_text())
    d.pop("captured_at", None)
    d["notes"] = tuple(d.get("notes") or ())
    return av.Lookup(**d)


def with_profile(name, **kw) -> av.Lookup:
    lk = load(name)
    return dataclasses.replace(lk, profile=dict(lk.profile, **kw))


# ---------- Q22a ----------

@pytest.mark.parametrize("name", FIXTURES)
def test_report_is_short(name):
    out = format_report(load(name), score(load(name)))
    assert len(out) <= REPORT_CAP, len(out)
    assert "Weights are our estimate" not in out  # moved to "why this score?" + README
    assert "**Details**" not in out and out.count("**Checks:**") == 1


def test_help_is_short_and_keeps_entry_points():
    assert len(router.HELP) <= HELP_CAP
    for s in ("audit agent1q", "audit weather-bot", "how do I fix #1", "why this score?",
              "`re-check`", "is weather-bot live?", "pre-hire check",
              "find an agent that books flights", "forget", "Free", "@"):
        assert s in router.HELP, s


def test_checks_line_skips_what_top_fixes_say():
    sc = score(load("weak"))
    fixes = sc.fixes[:3]
    line = checks_line(sc, fixes)
    # weak: no README -> one combined README fix; neither README rule repeats in the line
    assert "README" not in line
    assert "Description" not in line  # fix #3
    assert "Avatar" in line and "Starter prompts 0" in line
    assert "Website" not in line  # Q21 (FB-6): optional, never pushed in the audit
    assert line.startswith("**Checks:** ✅ 5/11 full marks")  # 11 judged (3 not scored)


def test_checks_line_offline_does_not_repeat_responsive():
    sc = score(load("dead"))
    line = checks_line(sc, sc.fixes[:3])
    assert "Responsive" not in line and "Active" not in line


def test_checks_line_flag_and_values():
    lk = load("flagged")
    sc = score(lk)
    # Responsive not in the top 3 here -> shown with the Agentverse attribution, never "❌ Responsive"
    line = checks_line(sc, sc.fixes[:1], flagged=True)
    assert "Responsive (Agentverse flag)" in line and "Rating 2.5/5" in line


def test_no_fixes_report():
    lk = with_profile("strong", handle="weather", readme=_full_readme(), rating=5.0,
                      recent_success_rate=1.0, recent_eval_success_rate=1.0)
    sc = score(lk)
    assert not sc.fixes
    out = format_report(lk, sc)
    assert "No fixes needed" in out and "✅ 14/14 full marks" in out and "❌" not in out
    assert 'Ask "why this score?" or "re-check" after changes.' in out


def test_explain_keeps_weights_and_keywords_note():
    lk = load("strong")
    out = evidence.format_explain(service.shown_for(lk, score(lk), "Weather"), "why this score?")
    assert "our estimate" in out and "Keywords are private" in out


# ---------- Q21 ----------

def test_testing_tip_never_says_not_found():
    sc = score(load("strong"))
    c = sc.check("eval_rate")
    assert c.kind == "no_data" and c.points == 0 and c.max_points == 0  # Q21: not scored
    assert c.fix.startswith("Run Testing") and "Agentverse shares no recent Testing result" in c.fix
    assert "not found" not in c.fix.lower() and "No Testing score" not in c.fix


def test_testing_row_value_and_topic():
    lk = load("strong")
    rows = evidence.rows(lk, score(lk))
    assert next(r for r in rows if r.rule == "eval_rate").value == evidence.TESTING_NONE
    f = evidence.facts(lk.profile)
    text = " ".join(evidence._topics("testing score?", f, ()))
    assert "your Testing tab may still have runs" in text and "isn't counted in your score" in text
    f2 = dict(f, recent_eval_success_rate=0.8)
    assert "Testing score: 80%" in " ".join(evidence._topics("testing score?", f2, ()))


def test_testing_guide_says_scores_can_lag():
    assert "can lag" in guides.GUIDE_WHY["eval_rate"]
    out = guides.full_guide(1, score(load("strong")).check("eval_rate"), "Weather")
    assert "can lag" in out


from tests.test_explain import _full_readme  # noqa: E402  (same README the Q10 tests use)


# ---------- Q21 v2 (2026-11-08, FB-6 again via Slack): not scored ----------

def _perfect(**kw):
    base = dict(handle="weather", readme=_full_readme(), rating=5.0,
                recent_success_rate=1.0, recent_eval_success_rate=1.0)
    return with_profile("strong", **{**base, **kw})


def test_missing_website_never_lowers_score():
    none, verified = score(_perfect(domain=None)), score(_perfect(domain="example.com"))
    assert none.total == verified.total == 100
    w = none.check("website")
    assert w.kind == "optional" and w.max_points == 0 and w.lost == 0
    assert "website" not in {f.rule for f in none.fixes}
    assert verified.check("website").ok and verified.check("website").points == 3


def test_null_testing_does_not_lower_score():
    a = score(_perfect(recent_eval_success_rate=None))
    assert a.total == 100 and not a.fixes


def test_low_testing_still_counts():
    assert score(_perfect(recent_eval_success_rate=0.0)).total == 96


def test_explain_rows_show_not_scored():
    lk = load("strong")
    out = evidence.format_explain(service.shown_for(lk, score(lk), "Weather"), "why this score?")
    assert "❔ Evaluation success rate: none shared by Agentverse (not scored)" in out
    assert "/0" not in out


def test_scoring_version_breaks_comparability():
    from agent import recheck, rubric
    assert rubric.SCORING_VERSION == 2
    assert recheck.compare({"at": 0, "w": "old", "total": 76, "checks": {}},
                           score(load("strong")), 60).comparable is False
