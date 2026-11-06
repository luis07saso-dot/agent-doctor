"""Q3 (profile link on its own paragraph) and Q5 (how-to per fix + "how do I fix #N")."""
import asyncio
import dataclasses
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from uagents import Agent

from agent import agentverse as av
from agent import chat, guides, router, service
from agent import rubric as R
from agent.report import MAX_CHARS, PROFILE_URL, format_report
from agent.scorer import Check, score

FIX = Path(__file__).parent / "fixtures"
FIXTURES = ["strong", "weak", "dead", "flagged"]


def load(name) -> av.Lookup:
    d = json.loads((FIX / f"{name}.json").read_text())
    d.pop("captured_at", None)
    d["notes"] = tuple(d.get("notes") or ())
    return av.Lookup(**d)


class FixtureClient:
    def __init__(self, name):
        self.name = name

    async def lookup(self, address):
        return load(self.name)

    async def lookup_handle(self, handle):
        return load(self.name)


@pytest.fixture(autouse=True)
def fresh_memory(monkeypatch):
    monkeypatch.setattr(guides, "LAST", guides.LastAudit())


def ask(text, name="flagged", key="chat-1"):
    return asyncio.run(service.handle(text, FixtureClient(name), ["agent-doctor"], chat_key=key))


# ---------- Q3: profile link ----------

def _link(lk):
    return f"[Open profile on Agentverse]({PROFILE_URL.format(address=lk.address)})"


@pytest.mark.parametrize("name", FIXTURES)
def test_profile_link_is_its_own_paragraph_at_the_end(name):
    lk = load(name)
    out = format_report(lk, score(lk))
    # ASI:One joins single-newline lines into one paragraph: the link needs blank lines.
    assert out.endswith("\n\n" + _link(lk))


@pytest.mark.parametrize("live", [None, "pending", SimpleNamespace(status="live", reply_ms=4200),
                                  SimpleNamespace(status="unreachable")])
def test_link_survives_longest_reports(live):
    lk = load("flagged")
    footer = router.more_targets(12)
    out = format_report(lk, score(lk), live=live, footer=footer)
    assert len(out) <= MAX_CHARS
    assert out.endswith(footer) and _link(lk) in out


def test_link_survives_even_when_body_must_be_cut():
    lk = load("flagged")
    lk.profile["name"] = "N" * 60
    out = format_report(lk, score(lk), footer="\n\n" + "x" * 700)
    assert len(out) <= MAX_CHARS and _link(lk) in out


def test_no_address_no_link_but_still_valid():
    lk = dataclasses.replace(load("weak"), address=None)
    out = format_report(lk, score(lk))
    assert "Open profile" not in out and "\"re-check\" after changes" in out


# ---------- Q5: how-to under each fix ----------

@pytest.mark.parametrize("name", FIXTURES)
def test_every_top_fix_has_a_how_line(name):
    lk = load(name)
    sc = score(lk)
    out = format_report(lk, sc)
    assert len(out) <= MAX_CHARS
    assert out.count("\n   How: ") == min(1, len(sc.fixes))  # Q22a: fix #1 only
    assert 'Ask "how do I fix #1"' in out


def test_how_line_is_a_hard_break_under_its_fix():
    """ASI:One joins single-newline lines; two trailing spaces force the line break."""
    lk = load("flagged")
    lines = format_report(lk, score(lk)).split("\n")
    for i, line in enumerate(lines):
        if line.startswith("   How: "):
            assert re.match(r"[123]\. .* pts\)  $", lines[i - 1])
    # FB-3: every line followed by another (non-list) line is a hard break, not just fixes.
    for i, line in enumerate(lines[:-1]):
        nxt = lines[i + 1]
        if line.strip() and nxt.strip() and not re.match(r"\d\. ", nxt):
            assert line.endswith("  "), line


def test_offline_agent_does_not_repeat_the_same_how():
    lk = load("dead")
    sc = score(lk)
    # Leave only "active" and "responsive" failing: both map to the same how-to.
    keep = {"active", "responsive"}
    checks = tuple(c if c.rule in keep else dataclasses.replace(c, points=c.max_points, ok=True, fix="")
                   for c in sc.checks)
    sc = dataclasses.replace(sc, checks=checks)
    assert [c.rule for c in sc.fixes] == ["active", "responsive"]
    out = format_report(lk, sc)
    assert out.count(guides.SHORT["active"]) == 1
    assert out.count("\n   How: ") == 1


def test_link_precedes_multi_target_note():
    """Decision: the multi-target note stays last; the link is still its own paragraph."""
    lk = load("weak")
    footer = router.more_targets(2)
    out = format_report(lk, score(lk), footer=footer)
    assert out.endswith("\n\n" + _link(lk) + footer) and footer.startswith("\n\n")


def test_how_lines_drop_from_last_fix_first_when_too_long():
    lk = load("flagged")
    out = format_report(lk, score(lk), live="pending", footer="\n\n" + "x" * 160)
    assert len(out) <= MAX_CHARS
    lines = out.split("\n")
    first = lines.index(next(l for l in lines if l.startswith("1. ")))
    assert lines[first + 1].startswith("   How: ")  # fix 1 keeps its how-to
    assert out.count("   How: ") < 3


def test_short_how_exists_for_every_rule_and_is_short():
    for rule in R.WEIGHTS:
        c = Check(rule, 0, R.WEIGHTS[rule], False, "x", "Add README sections: Use cases")
        how = guides.short_how(c)
        assert how.startswith("How: ") and len(how) <= 110, rule


def test_sections_how_names_the_first_missing_section():
    c = Check("readme_sections", 7.5, 15, False, "3/6 sections",
              "Add README sections: Use cases, Limitations, Metadata")
    assert "`## Use cases`" in guides.short_how(c)
    assert guides.missing_sections(c) == ["Use cases", "Limitations", "Metadata"]


@pytest.mark.parametrize("rule", list(R.WEIGHTS))
def test_full_guide_for_every_rule_fits_with_link(rule):
    fix = ("Add README sections: " + ", ".join(R.README_SECTIONS) if rule == "readme_sections"
           else "Some fix text of a realistic length for this rule, here")
    c = Check(rule, 0, R.WEIGHTS[rule], False, "0/6 sections", fix)
    g = guides.full_guide(3, c, "N" * 60)
    link = "\n\n" + _link(SimpleNamespace(address="agent1q" + "x" * 58))
    assert len(g) + len(link) <= MAX_CHARS, rule
    assert g.startswith("**Fix #3 for ") and "**Steps**" in g
    assert g.count("```") % 2 == 0  # code fences closed


def test_offline_responsive_gets_the_bring_online_guide():
    c = Check("responsive", 0, 6, False, "offline", "Answer every message")
    assert "restart the process" in guides.full_guide(1, c)
    assert guides.short_how(c) == guides.SHORT["active"]


def test_short_readme_guide_says_how_long():
    c = Check("readme", 3, 8, False, "120 chars", "Expand the README")
    g = guides.full_guide(1, c)
    assert "120 chars" in g and f"{R.README_MIN_CHARS}+" in g


@pytest.mark.filterwarnings("ignore:coroutine .Agent.publish_manifest. was never awaited")
def test_chat_protocol_snippet_runs_and_publishes_the_chat_protocol():
    """The guide's code must work as pasted (uagents as pinned)."""
    code = re.search(r"```python\n(.*?)```", guides._GUIDES["chat_protocol"][2], re.S).group(1)
    loop = asyncio.new_event_loop()
    try:
        agent = Agent(name="t", seed="guide-test-" + "x" * 40, port=8998, loop=loop,
                      enable_agent_inspector=False)
        exec(compile(code, "guide-snippet", "exec"), {"agent": agent})
        assert "proto:" + R.CHAT_PROTOCOL_DIGEST in set(agent.protocols)
    finally:
        loop.close()


# ---------- Q5: "how do I fix #N" ----------

@pytest.mark.parametrize("has_audit", [False, True])
@pytest.mark.parametrize("text,n", [
    ("how do I fix #2", 2), ("fix 3", 3), ("Fix #2?", 2), ("explain the second fix", 2),
    ("how to fix number 1?", 1), ("@agent-doctor how do I fix #1", 1),
    ("what about fix no. 2", 2), ("fix no. 2 please", 2), ("how do I fix #1 for my agent", 1),
])
def test_classify_fix_followups(text, n, has_audit):
    i = router.classify(text, ["agent-doctor"], has_audit=has_audit)
    assert (i.kind, i.n) == ("fix_guide", n)


@pytest.mark.parametrize("text,n", [("#1", 1), ("more on #3", 3), ("number 2?", 2),
                                    ("show me #2 please", 2)])
def test_bare_number_means_a_fix_only_after_an_audit(text, n):
    i = router.classify(text, ["agent-doctor"], has_audit=True)
    assert (i.kind, i.n) == ("fix_guide", n)
    assert router.classify(text, ["agent-doctor"]).kind != "fix_guide"


@pytest.mark.parametrize("has_audit", [False, True])
@pytest.mark.parametrize("text,kind", [
    ("fix 2 bugs in my code", "off_scope"),
    ("fix 2 more bugs", "off_scope"),
    ("can you help me fix 2 bugs in my code", "off_scope"),
    ("step 1 of my plan is cooking pasta", "off_scope"),
    ("help me with the first point of my essay", "help"),
    ("how do I fix my agent", "need_target"),
    ("how do I fix my car", "off_scope"),
    ("I have 2 agents", "help"),
    ("pre-hire check #1", "prehire_need_target"),
    ("audit my agent #3", "need_target"),
    ("is agent #2 live?", "prehire_need_target"),
    ("how do I rank #1 on agentverse", "faq"),
    ("what is the number 1 agent on agentverse", "help"),
])
def test_classify_not_fix_followups(text, kind, has_audit):
    """Review finding: the fix intent must not steal other messages, audit or not."""
    assert router.classify(text, ["agent-doctor"], has_audit=has_audit).kind == kind


def test_audit_then_fix_guide_matches_what_was_shown():
    audit = ask("audit ticketlens-agent")
    shown = [l for l in audit.text.split("\n") if re.match(r"[123]\. ", l)]
    for n in (1, 2, 3):
        res = ask(f"how do I fix #{n}")
        assert res.outcome == "fix_guide" and len(res.text) <= MAX_CHARS
        fix_text = shown[n - 1][3:].rsplit(" (+", 1)[0].split(": ", 1)[1]  # drop Found:/Tip:
        assert res.text.startswith(f"**Fix #{n} for ticketlens agent: {fix_text}**")
        assert res.text.endswith(_link(load("flagged")))


def test_fix_guide_without_audit_asks_for_one():
    res = ask("how do I fix #1", key="new-chat")
    assert (res.text, res.outcome) == (router.NO_AUDIT_YET, "fix_guide_none")


def test_fix_guide_is_per_chat():
    ask("audit ticketlens-agent", key="chat-a")
    assert ask("how do I fix #1", key="chat-b").outcome == "fix_guide_none"
    assert ask("#1", key="chat-b").outcome == "off_scope"  # bare "#1" without an audit
    assert ask("#1", key="chat-a").outcome == "fix_guide"


def test_fix_number_out_of_range():
    ask("audit ticketlens-agent")
    res = ask("fix 4")
    assert res.outcome == "fix_guide_none" and "no #4" in res.text and "#1 to #3" in res.text


def test_no_fixes_needed_reply():
    guides.LAST.put("k", guides.Shown("Perfect", "agent1qx", ()))
    res = ask("fix 1", key="k")
    assert "found nothing to fix" in res.text


def test_latest_audit_wins():
    ask("audit ticketlens-agent")
    ask("audit weak-agent", name="weak")
    assert ask("#1").text.startswith("**Fix #1 for Agent: Write a Markdown README")


def test_memory_expires_and_is_bounded(monkeypatch):
    t = [100.0]
    mem = guides.LastAudit(ttl_s=10, max_items=2, clock=lambda: t[0])  # Q15: injected clock
    s = guides.Shown("A", "", ())
    mem.put("a", s), mem.put("b", s), mem.put("c", s)
    assert mem.get("a") is None and mem.get("c") is s
    t[0] += 11
    assert mem.get("c") is None
    mem.put("", s)
    assert mem.get("") is None


def test_chat_handler_keys_memory_by_sender_and_session(monkeypatch):
    from uagents_core.contrib.protocols.chat import ChatMessage, TextContent

    from agent import guard
    from tests.test_chat import FakeCtx

    monkeypatch.setattr(chat, "GUARD", guard.Guard())
    monkeypatch.setattr(chat, "CLIENT", FixtureClient("flagged"))

    def say(ctx, text, sender="agent1qsender"):
        asyncio.run(chat.on_chat(ctx, sender, ChatMessage(content=[TextContent(text=text)])))
        return ctx.replies()[-1]

    ctx = FakeCtx(session="s1")
    say(ctx, "audit ticketlens-agent")
    assert say(ctx, "how do I fix #2").startswith("**Fix #2 for ticketlens agent")
    assert ctx.reqs()[-1]["outcome"] == "fix_guide"
    assert say(FakeCtx(session="s2"), "how do I fix #2") == router.NO_AUDIT_YET
    assert say(FakeCtx(session="s1"), "fix #2", sender="agent1qother") == router.NO_AUDIT_YET
