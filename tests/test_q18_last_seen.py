"""Q18 (FB-3, owner's ASI:One Scout test 2026-11-04): after a scout list and "is #1 live?",
"audit this agent for me" audited an OLDER agent of the chat. Also: Pre-Hire title by name,
and Markdown hard breaks so ASI:One doesn't join lines ("answer none Profile: ...")."""
from dataclasses import replace

from agent import prehire, report, service
from agent.prehire import PreHireResult
from tests.test_scout import (ADDR, STRONG, Client, Probe, fresh, hit, load,  # noqa: F401
                              say)

OLD = load("weak").address  # an agent audited earlier in the same chat (valid checksum)


class Old(Client):
    async def lookup(self, a):
        if a == OLD:
            self.looked.append(a)
            return replace(STRONG, address=a, query=a,
                           profile={**STRONG.profile, "address": a, "name": "Sheffield United FC"})
        return await super().lookup(a)


def checked(client):
    """Fake chat Pre-Hire: like chat.run_prehire, returns the profile Lookup as 3rd item."""
    seen = []

    async def pre(target):
        seen.append(target.value)
        return "verdict", "degraded", await client.lookup(target.value)
    return pre, seen


def test_video_case_audit_this_agent_after_prehire_of_pick():
    c = Old(hits=[hit(0, "Flights Agent"), hit(1, "Autonomad Travel"), hit(2)])
    assert say(f"audit {OLD}", c).outcome == "ok"
    assert say("find an agent that books flights", c, probe=Probe()).outcome == "scout_ok"
    pre, seen = checked(c)
    assert say("is #1 live?", c, prehire=pre).outcome == "prehire_degraded" and seen == [ADDR[0]]
    r = say("audit this agent for me", c)
    assert r.outcome == "ok" and r.input_type == "last" and c.looked[-1] == ADDR[0]
    assert "Flights Agent" in r.text and "Sheffield" not in r.text


def test_prehire_makes_fix_and_why_about_that_agent():
    c = Old(hits=[hit(0, "Flights Agent")])
    say(f"audit {OLD}", c)
    say("find an agent that books flights", c)
    pre, _ = checked(c)
    say("is #1 live?", c, prehire=pre)
    assert "Flights Agent" in say("how do I fix #1", c).text
    assert "Flights Agent" in say("why this score?", c).text


def test_prehire_without_lookup_keeps_old_audit():
    c = Old()
    say(f"audit {OLD}", c)

    async def pre(target):  # 2-tuple (old shape): nothing changes
        return "verdict", "unknown"
    say(f"is {STRONG.address} live?", c, prehire=pre)
    r = say("audit this agent", c)
    assert r.outcome == "ok" and c.looked[-1] == OLD


def test_prehire_failed_lookup_not_remembered():
    c = Old()
    say(f"audit {OLD}", c)

    async def pre(target):
        return "verdict", "error", replace(STRONG, outcome="timeout", address=target.value)
    say(f"is {STRONG.address} live?", c, prehire=pre)
    say("audit this agent", c)
    assert c.looked[-1] == OLD


def test_right_after_scout_weak_ref_asks_which():
    c = Old(hits=[hit(0, "Flights Agent"), hit(1, "Autonomad Travel"), hit(2)])
    say(f"audit {OLD}", c)
    say("find an agent that books flights", c)
    n = len(c.looked)
    for text in ("audit this agent for me", "audit it", "is it live?"):
        r = say(text, c)
        assert r.outcome == "scout_which" and r.input_type == "last", text
        assert "`audit #2`" in r.text and "1–3" in r.text
    assert len(c.looked) == n  # no lookup, no probe


def test_scout_which_without_any_audit():
    c = Client(hits=[hit(0), hit(1)])
    say("find an agent for weather", c)
    assert say("audit that agent", c).outcome == "scout_which"


def test_right_after_scout_name_word_picks_the_listed_agent():
    c = Old(hits=[hit(0, "Flights Agent"), hit(1, "Autonomad Travel"), hit(2)])
    say("find an agent that books flights", c)
    r = say("audit the autonomad agent", c)
    assert r.outcome == "ok" and c.looked[-1] == ADDR[1] and "Autonomad Travel" in r.text


def test_name_word_for_old_audit_still_works_after_scout():
    c = Old(hits=[hit(0, "Flights Agent"), hit(1, "Autonomad Travel")])
    say(f"audit {OLD}", c)
    say("find an agent that books flights", c)
    r = say("audit that sheffield agent", c)
    assert r.outcome == "ok" and c.looked[-1] == OLD


def test_listed_name_after_a_later_check():
    c = Old(hits=[hit(0, "Flights Agent"), hit(1, "Autonomad Travel")])
    say("find an agent that books flights", c)
    pre, _ = checked(c)
    say("is #1 live?", c, prehire=pre)
    r = say("audit the autonomad agent", c)  # not the last checked (Flights), but listed
    assert r.outcome == "ok" and c.looked[-1] == ADDR[1]


def test_strong_ref_after_scout_keeps_old_meaning():
    c = Old(hits=[hit(0), hit(1)])
    say(f"audit {OLD}", c)
    say("find an agent for weather", c)
    r = say("re-check the same agent", c)
    assert r.outcome == "ok" and c.looked[-1] == OLD


def test_forget_clears_marker():
    c = Old(hits=[hit(0), hit(1)])
    say("find an agent for weather", c)
    say("forget", c)
    assert "c1" not in service._LATEST


def test_scout_which_copy():
    from agent import router
    assert router.scout_which(5) == ("Which agent from my list do you mean (1–5)? Say "
                                     "`audit #2` for a full report, or `is #2 live?` for a live "
                                     "test.")
    assert router.scout_which(5, True).startswith("Which agent from my list do you mean (1–5)? "
                                                 "Say `is #2 live?`")
    assert "#1" in router.scout_which(1) and "1–1" not in router.scout_which(1)


# ---------- Pre-Hire text ----------

def res(**kw):
    base = dict(query=ADDR[0], address=ADDR[0], status="degraded", ack_ms=1800, reply_ms=None,
                trust_score=84, active=True, chat_protocol=True, rating=4.8,
                checked_at="2026-11-04T10:19:00Z")
    base.update(kw)
    return PreHireResult(**base)


def test_prehire_title_uses_name_and_keeps_address_command():
    t = prehire.format_text(res(), ADDR[0], "Flights Agent")
    assert t.startswith("**Pre-Hire Check: Flights Agent**")
    assert f"`audit {ADDR[0]}`" in t


def test_prehire_title_falls_back_to_label():
    assert prehire.format_text(res(), "weather-bot").startswith("**Pre-Hire Check: weather-bot**")
    t = prehire.format_text(res(), "x", "@evil `name`")
    assert "@" not in t.split("\n")[0]


def test_prehire_lines_are_hard_breaks():
    lines = prehire.format_text(res(), ADDR[0], "Flights Agent").split("\n")
    live = next(i for i, ln in enumerate(lines) if ln.startswith("Live test:"))
    assert lines[live].endswith("  ") and lines[live + 1].startswith("Profile:")
    for i, ln in enumerate(lines[:-1]):
        if ln.strip() and lines[i + 1].strip():
            assert ln.endswith("  "), ln


# ---------- hard_breaks ----------

def test_hard_breaks_rules():
    t = "a\nb\n\nc\n1. x\n2. y  \n   how\n```\ncode\nmore\n```\nz"
    out = report.hard_breaks(t).split("\n")
    assert out[0] == "a  " and out[1] == "b" and out[2] == ""
    assert out[3] == "c"  # next line is a list item: starts its own line anyway
    assert out[5] == "2. y  "  # already a hard break: not doubled
    assert out[8] == "code" and out[9] == "more"  # fence content untouched
    assert report.hard_breaks("") == "" and report.hard_breaks("one") == "one"
    # "2." can't interrupt a paragraph (CommonMark §5.2): it needs the hard break
    assert report.hard_breaks("text\n2. x") == "text  \n2. x"
    assert report.hard_breaks("text\n- x") == "text\n- x"


def test_report_details_lines_do_not_join():
    from agent.scorer import score
    out = report.format_report(STRONG, score(STRONG)).split("\n")
    i = out.index(next(ln for ln in out if ln.startswith("**Details**")))
    assert out[i].endswith("  ") and out[i + 1].endswith("  ") and out[i + 2].endswith("  ")
