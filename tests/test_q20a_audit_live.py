"""Q20a (FB-5): single-agent audits send the agent one test message. User decision
2026-11-07: single-target only (the probe counts in the target's own Agentverse metrics),
offline agents never, flagged agents keep the Q2 note, result never changes the score."""
import asyncio

import pytest

from agent import report, scout, service
from agent.probe import ProbeResult
from agent.scorer import score
from tests.test_live_check import Client, load, prober

STRONG = load("strong").address
WEAK = load("weak").address


def audit(text, probe, **kw):
    return asyncio.run(service.handle(text, Client("strong"), probe=probe, **kw))


@pytest.mark.parametrize("status,phrase", [
    ("live", "✅ Live test: it answered our test message in 2.4s. Not part of the score."),
    ("degraded", "⚠️ Live test: it acknowledged our test message but sent no answer within 14s."),
    ("unreachable", "❌ Live test: no reply to our test message within 14s."),
])
def test_live_line_per_status(status, phrase):
    probe, calls = prober(status=status)
    res = audit(f"audit {STRONG}", probe)
    assert calls == [STRONG] and res.live == status and phrase in res.text
    assert res.text.index("Live test") < res.text.index("**Top fixes**")


def test_live_result_never_changes_score():
    lk = load("strong")
    for status in ("live", "unreachable"):
        probe, _ = prober(status=status)
        assert f"Score {score(lk).total}/100" in audit(f"audit {STRONG}", probe).text


def test_skipped_and_error_results_show_nothing():
    for status, detail in (("skipped", "self"), ("error", "busy")):
        async def probe(address, s=status, d=detail):
            return ProbeResult(address, s, detail=d)
        res = audit(f"audit {STRONG}", probe)
        assert "Live test" not in res.text and res.live == ""


def test_self_is_never_probed():
    probe, calls = prober()
    res = audit(f"audit {STRONG}", probe, self_addresses=(STRONG.upper(),))
    assert calls == [] and "Live test" not in res.text


def test_multi_target_audit_does_not_probe():
    probe, calls = prober()
    res = audit(f"audit {STRONG} and {WEAK}", probe)
    assert calls == [] and res.live == service.LIVE_MULTI
    assert f"_Live test: ask `is {STRONG} live?` to test it._" in res.text  # address -> code


def test_kill_switch(monkeypatch):
    monkeypatch.setenv("AUDIT_LIVE", "0")
    probe, calls = prober()
    res = audit(f"audit {STRONG}", probe)
    assert calls == [] and "Live test" not in res.text


def test_slow_probe_reports_pending(monkeypatch):
    monkeypatch.setattr(service, "LIVE_WAIT_S", 0.1)
    monkeypatch.setattr(service, "MIN_PROBE_S", 0.05)
    probe, calls = prober(delay=1.0)
    res = audit(f"audit {STRONG}", probe)
    assert len(calls) == 1 and res.live == "pending"
    assert f"⏳ Live test still running: ask `is {STRONG} live?` in a minute" in res.text


def test_no_time_left_still_starts_the_probe(monkeypatch):
    """"still running, ask again" must be true: the probe is sent even with no time to wait."""
    monkeypatch.setattr(service, "LIVE_WAIT_S", 0.01)  # < MIN_PROBE_S
    probe, calls = prober(delay=0.0)

    async def go():
        res = await service.handle(f"audit {STRONG}", Client("strong"), probe=probe)
        for _ in range(20):  # let the fire-and-forget task run (no wall-clock wait)
            if calls:
                break
            await asyncio.sleep(0)
        return res
    res = asyncio.run(go())
    assert res.live == "pending" and calls == [STRONG]


def test_waits_at_most_live_wait(monkeypatch):
    monkeypatch.setattr(service, "LIVE_WAIT_S", 0.2)
    probe, _ = prober(delay=5.0)
    loop_t = asyncio.new_event_loop()
    try:
        t0 = loop_t.time()
        loop_t.run_until_complete(service.handle(f"audit {STRONG}", Client("strong"), probe=probe))
        assert loop_t.time() - t0 < 2.0
    finally:
        loop_t.close()


def test_per_sender_hourly_cap(monkeypatch):
    monkeypatch.setattr(scout, "AUDIT_CAPS", scout.Caps(per_hour=2, shared=scout.CAPS))
    probe, calls = prober()
    texts = [audit(f"audit {STRONG}", probe, sender_key="s1").text for _ in range(3)]
    assert len(calls) == 2
    assert "Live test skipped (hourly limit)" in texts[2]
    audit(f"audit {STRONG}", probe, sender_key="s2")  # other sender: own budget
    assert len(calls) == 3


def test_global_budget_shared_with_scout():
    for _ in range(scout.GLOBAL_PROBES_PER_MIN // 2):  # scout uses it all (2 per search)
        assert scout.CAPS.allow(f"scout{_}", 2)
    probe, calls = prober()
    res = audit(f"audit {STRONG}", probe, sender_key="new")
    assert calls == [] and res.live == service.LIVE_CAPPED


def test_live_line_wording_has_no_at_sign():
    # On ASI:One "@other" routes the message to that agent.
    for st in ("pending", "capped", "multi"):
        line = report.live_line(st, "weather-bot")
        assert "@" not in line and '"is weather-bot live?"' in line
    assert report.live_line("unknown-status") == "" and report.live_line(None) == ""


def test_report_with_live_line_stays_short():
    lk = load("weak")
    out = report.format_report(lk, score(lk), live=ProbeResult(lk.address, "unreachable"))
    assert len(out) <= 1100 and out.count("How:") == 1
