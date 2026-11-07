"""Q10 (FB-2): "Why this score?" — no data != 0, Found vs Tip, evidence rows, explain intent.
Spec: docs/specs/q10-why-this-score.md."""
import asyncio
import json
from dataclasses import replace
from pathlib import Path

import pytest

from agent import agentverse as av
from agent import evidence, guides, router, service
from agent.report import MAX_CHARS, format_report
from agent.scorer import score

FIX = Path(__file__).parent / "fixtures"
FIXTURES = ["strong", "weak", "dead", "flagged"]
ADDR = "agent1qfvydlgcxrvga2kqjxhj3hpngegtysm2c7uk48ywdue0kgvtc2f5cwhyffv"
# Q21 (2026-11-08): no-data checks and a missing website left out -> share of points possible.
BASELINE_TOTALS = {"strong": 83, "weak": 50, "dead": 6, "flagged": 74}


def load(name) -> av.Lookup:
    d = json.loads((FIX / f"{name}.json").read_text())
    d.pop("captured_at", None)
    d["notes"] = tuple(d.get("notes") or ())
    return av.Lookup(**d)


def with_profile(name="strong", **fields) -> av.Lookup:
    lk = load(name)
    return replace(lk, profile={**(lk.profile or {}), **fields})


@pytest.fixture(autouse=True)
def fresh_memory(monkeypatch):
    monkeypatch.setattr(guides, "LAST", guides.LastAudit())


# ---------- scorer: kind ----------

@pytest.mark.parametrize("name", FIXTURES)
def test_totals_unchanged(name):
    assert score(load(name)).total == BASELINE_TOTALS[name]


def test_null_success_rate_is_no_data_not_zero():
    c = score(load("strong")).check("success_rate")
    assert c.kind == "no_data" and c.points == 0 and c.detail == "no data"
    assert "0 verified chats" in c.fix and "Get real users" not in c.fix


def test_measured_zero_success_rate_is_found():
    c = score(load("flagged")).check("success_rate")  # 0.0 with 1 verified chat
    assert c.kind == "found" and c.detail == "0%"


def test_success_rate_no_data_without_verified_count():
    lk = with_profile(recent_success_rate=None, recent_verified_interactions=None)
    c = score(lk).check("success_rate")
    assert c.kind == "no_data" and "0 verified" not in c.fix


@pytest.mark.parametrize("field,rule", [("recent_eval_success_rate", "eval_rate"),
                                        ("rating", "rating"),
                                        ("total_interactions", "interactions")])
@pytest.mark.parametrize("value", [None, "x", True])
def test_non_numbers_are_no_data(field, rule, value):
    c = score(with_profile(**{field: value})).check(rule)
    assert c.kind == "no_data" and c.points == 0 and c.detail == "no data"


def test_full_marks_kind_ok():
    sc = score(load("strong"))
    assert sc.check("active").kind == "ok" and sc.check("chat_protocol").kind == "ok"


def test_unscored_checks_are_never_fixes():  # Q21 (FB-6)
    sc = score(load("strong"))
    assert all(f.kind == "found" for f in sc.fixes)
    for rule in ("eval_rate", "success_rate"):
        c = sc.check(rule)
        assert c.kind == "no_data" and c.max_points == 0 and c.lost == 0


def test_offline_still_first():
    assert score(load("dead")).fixes[0].rule == "active"


def test_unindexed_has_no_tips():
    lk = replace(load("strong"), profile=None, profile_status="not_found", outcome="partial")
    sc = score(lk)
    assert all(c.kind in ("ok", "found") for c in sc.checks if c.rule != "website")
    assert sc.check("website").kind == "optional"


# ---------- report ----------

@pytest.mark.parametrize("name", FIXTURES)
def test_report_keeps_one_how_and_limit(name):
    out = format_report(load(name), score(load(name)))
    assert len(out) <= MAX_CHARS
    assert out.count("How:") == 1  # Q22a: How on fix #1 only
    assert "why this score?" in out


def test_report_labels_found_and_tip():
    lk = with_profile("weak")  # all fixes found in top 3?
    out = format_report(lk, score(lk))
    assert "1. Found: " in out


def test_report_tip_label_and_legend_only_with_tip():
    strong = load("strong")
    out = format_report(strong, score(strong))
    assert "Tip" not in out
    # Q21: only no-data gaps left -> full score, no fixes, no-data shown as not scored.
    perfect_but_data = with_profile("strong", handle="weather", readme=_full_readme(),
                                    rating=5.0, domain="example.com")
    sc = score(perfect_but_data)
    out = format_report(perfect_but_data, sc)
    assert sc.total == 100 and "No fixes needed" in out and "Tip" not in out
    assert "❔ Not scored (no data): ASI:One success, Testing (none shared)" in out


def test_report_no_data_wording():
    out = format_report(load("strong"), score(load("strong")))
    assert "❔ Not scored (no data): ASI:One success, Testing (none shared)" in out  # Q21/Q22a
    assert "none yet" not in out


def _full_readme():
    body = "\n".join(f"## {s}\ntext about {s}." for s in
                     ("Summary", "Key features", "Usage", "Use cases", "Limitations", "Metadata"))
    return "# W\n" + body + "\n" + "Plain description of the weather agent. " * 10


# ---------- evidence ----------

def test_facts_none_for_non_numbers():
    f = evidence.facts({"total_interactions": True, "recent_success_rate": "x", "rating": 4.5})
    assert f["total_interactions"] is None and f["recent_success_rate"] is None
    assert f["rating"] == 4.5 and f["recent_verified_interactions"] is None


def test_rows_values():
    lk = load("strong")
    rows = {r.rule: r for r in evidence.rows(lk, score(lk))}
    assert rows["success_rate"].value == "no data (0 verified chats)"
    assert rows["success_rate"].kind == "no_data"
    assert "93,470 total" in rows["interactions"].value
    lk = load("flagged")
    rows = {r.rule: r for r in evidence.rows(lk, score(lk))}
    assert rows["success_rate"].value == "0% (0 of 1 verified chats succeeded)"


def _shown(name="strong"):
    lk = load(name)
    return service.shown_for(lk, score(lk), "Weather")


def test_explain_lists_checks_and_legend():
    out = evidence.format_explain(_shown(), "why this score?")
    assert out.startswith("**Why Weather scored 83/100")
    assert "❔ Success rate: no data (0 verified chats) (not scored)" in out
    assert "✅ Full marks:" in out and "Found = the data shows a gap" in out
    assert "0%" not in out.split("Success rate", 1)[1].split("\n", 1)[0]
    assert len(out) <= MAX_CHARS


def test_explain_unique_users_topic():
    out = evidence.format_explain(_shown(), "how many unique users does it have?")
    assert "no unique-user count" in out and "93,470 total interactions" in out
    assert "0 verified chats" in out


def test_explain_success_topic():
    out = evidence.format_explain(_shown("flagged"), "what about the ASI:One success rate?")
    assert "Wilson" in out and "0 succeeded of 1 verified chats" in out


def test_explain_rating_and_testing_topics():
    out = evidence.format_explain(_shown(), "what's the rating and testing score?")
    assert "doesn't publish the formula" in out and "Agentverse shares no recent Testing result" in out
    assert "your Testing tab may still have runs" in out and "not found" not in out  # Q21


@pytest.mark.parametrize("name", FIXTURES)
def test_explain_fits_with_all_topics(name):
    out = evidence.format_explain(_shown(name), "unique users success rating testing interactions")
    assert len(out) <= MAX_CHARS and "how do I fix #1" in out


# ---------- router ----------

@pytest.mark.parametrize("text,has_audit,kind", [
    ("how many unique users does weather-bot have?", False, "explain"),
    ("how many unique users does weather-bot have?", True, "explain"),
    (f"what's {ADDR}'s success rate and how did you score it?", False, "explain"),
    ("how many interactions does weather-bot have?", False, "explain"),
    ("why this score?", True, "explain"),
    ("how did you calculate that?", True, "explain"),
    ("why did you recommend getting real users?", True, "explain"),
    ("how is the score calculated?", True, "explain"),
    ("why this score?", False, "explain_none"),
    ("how is this score calculated?", False, "faq"),
    ("how is the score calculated?", False, "faq"),
    ("what evidence do you check?", False, "faq"),
    ("why is ticketlens-agent not showing up?", False, "audit"),
    ("why isn't weather-bot ranking?", False, "audit"),
    ("why is my agent not ranking?", True, "faq"),
    ("is weather-bot open-source?", False, "audit"),
    ("show weather-bot metrics", False, "audit"),
    ("explain fix #2 for weather-bot", False, "fix_guide"),  # unchanged
    ("how do I fix #2", True, "fix_guide"),
    ("explain the second fix", True, "fix_guide"),
    ("audit weather-bot and explain the score", False, "audit"),
    (f"audit {ADDR}", True, "audit"),
    ("is weather-bot live?", False, "prehire"),
    (f"why is {ADDR} scored like this?", False, "explain"),
    (f"why is https://agentverse.ai/agents/details/{ADDR}/profile rated so low?", False, "explain"),
    ("is it free?", True, "faq"),
    ("how do I rank higher?", True, "faq"),
])
def test_router_explain_table(text, has_audit, kind):
    assert router.classify(text, ("agent-doctor",), (), has_audit).kind == kind


def test_soft_explain_falls_back_to_last_audit():
    i = router.classify("how many unique users does weather-bot have?", ("agent-doctor",), (), True)
    assert i.soft and i.fallback is not None and i.fallback.kind == "explain"


def test_card_recheck_command_stays_audit():
    assert router.classify(f"audit {ADDR}", (), (), True).kind == "audit"


# ---------- service ----------

class FakeClient:
    def __init__(self, outcome="ok", fixture="strong"):
        self.outcome, self.fixture, self.calls = outcome, fixture, []

    async def _r(self, q):
        self.calls.append(q)
        if self.outcome == "ok":
            return load(self.fixture)
        return av.Lookup(query=q, outcome=self.outcome)

    async def lookup(self, a):
        return await self._r(a)

    async def lookup_handle(self, h):
        return await self._r("@" + h)


def run(coro):
    return asyncio.run(coro)


def test_explain_after_audit_uses_memory_no_lookup():
    c = FakeClient()
    run(service.handle(f"audit {ADDR}", c, chat_key="k"))
    n = len(c.calls)
    r = run(service.handle("why this score?", c, chat_key="k"))
    assert r.outcome == "explain" and len(c.calls) == n and "scored 83/100" in r.text


def test_explain_without_audit():
    r = run(service.handle("why this score?", FakeClient(), chat_key="k"))
    assert r.outcome == "explain_none" and r.text == router.EXPLAIN_NONE


def test_explain_with_target_then_fix_guide():
    c = FakeClient()
    r = run(service.handle(f"what's {ADDR}'s success rate?", c, chat_key="k"))
    assert r.outcome == "explain" and len(c.calls) == 1 and "Wilson" in r.text
    r = run(service.handle("how do I fix #1", c, chat_key="k"))
    assert r.outcome == "fix_guide"


def test_soft_explain_miss_uses_last_audit():
    run(service.handle(f"audit {ADDR}", FakeClient(), chat_key="k"))
    r = run(service.handle("how many unique users does weather-bot have?",
                           FakeClient(outcome="not_found"), chat_key="k"))
    assert r.outcome == "explain" and "no unique-user count" in r.text


def test_fb2_question_does_not_rerun_audit():
    c = FakeClient()
    run(service.handle(f"audit {ADDR}", c, chat_key="k"))
    r = run(service.handle(f"how many unique users does {ADDR} have and how did you score it?",
                           c, chat_key="k"))
    assert r.outcome == "explain" and "**Top fixes**" not in r.text


# ---------- guides ----------

def test_no_data_success_guides():
    c = score(load("strong")).check("success_rate")
    assert guides.short_how(c) == guides.SHORT_NO_DATA_SUCCESS
    g = guides.full_guide(1, c, "Weather")
    assert "no data, not 0%" in g and "Don't script fake chats" in g
    measured = score(load("flagged")).check("success_rate")
    assert guides.short_how(measured) == guides.SHORT["success_rate"]


def test_explain_lines_have_hard_breaks():
    out = evidence.format_explain(_shown(), "why this score?")
    check_lines = [ln for ln in out.split("\n") if ln.startswith(("❌", "❔"))]
    assert check_lines and all(ln.endswith("  ") for ln in check_lines)
    assert out.split("\n")[0].endswith("  ")
