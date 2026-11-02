"""Q2: live check inside the audit, only for agents Agentverse flags unresponsive."""
import asyncio
import json
from pathlib import Path

import pytest

from agent import agentverse as av
from agent import probe as probe_mod
from agent import report, service
from agent.probe import ProbeResult
from agent.report import MAX_CHARS, format_report
from agent.scorer import score

FIX = Path(__file__).parent / "fixtures"
NOW = "2026-11-02T10:00:00Z"


def load(name) -> av.Lookup:
    d = json.loads((FIX / f"{name}.json").read_text())
    d.pop("captured_at", None)
    d["notes"] = tuple(d.get("notes") or ())
    return av.Lookup(**d)


class Client:
    def __init__(self, name):
        self.lk = load(name)

    async def lookup(self, address):
        return self.lk

    async def lookup_handle(self, handle):
        return self.lk


def prober(status="live", reply_ms=2400, delay=0.0):
    calls = []

    async def probe(address):
        calls.append(address)
        await asyncio.sleep(delay)
        return ProbeResult(address, status, 900, reply_ms if status == "live" else None, NOW)
    return probe, calls


def run(name, probe):
    return asyncio.run(service.handle(f"audit {load(name).address}", Client(name), probe=probe))


def test_wording_constant_matches_probe_timeout():
    assert report.PROBE_WAIT_S == int(probe_mod.PROBE_TIMEOUT_S)


@pytest.mark.parametrize("status,phrase", [
    ("live", "Our live check just got a reply in 2.4s, so the flag looks out of date"),
    ("degraded", "acknowledged but sent no answer within 14s"),
    ("unreachable", "no reply within 14s, so the flag looks right"),
])
def test_flagged_agent_gets_live_verdict(status, phrase):
    probe, calls = prober(status)
    res = run("flagged", probe)
    lk = load("flagged")
    assert calls == [lk.address] and res.live == status and res.outcome == "ok"
    assert phrase in res.text and "We did not test it" not in res.text
    assert "Recent ASI:One success rate: 0%" in res.text
    assert len(res.text) <= MAX_CHARS


@pytest.mark.parametrize("name", ["strong", "weak", "dead"])
def test_unflagged_or_offline_agents_are_never_probed(name):
    probe, calls = prober()
    res = run(name, probe)
    assert calls == [] and res.live == ""


def test_slow_probe_reports_pending_within_budget(monkeypatch):
    monkeypatch.setattr(service, "AUDIT_BUDGET_S", 0.2)
    monkeypatch.setattr(service, "MIN_PROBE_S", 0.05)
    probe, calls = prober(delay=1.0)
    res = run("flagged", probe)
    assert res.live == "pending" and len(calls) == 1
    assert 'Our live check is still running: ask "is ticketlens-agent live?"' in res.text
    assert "@ticketlens-agent live" not in res.text  # "@x" would route to the other agent


def test_no_budget_left_skips_waiting(monkeypatch):
    monkeypatch.setattr(service, "AUDIT_BUDGET_S", 0.0)
    probe, calls = prober()
    res = run("flagged", probe)
    assert res.live == "pending" and calls == []


def test_probe_error_falls_back_to_q1_note():
    async def broken(address):
        raise RuntimeError("boom")
    res = run("flagged", broken)
    assert "We did not test it" in res.text and res.outcome == "ok"


def test_probe_skipped_or_busy_falls_back_to_q1_note():
    for status in ("skipped", "error"):
        probe, _ = prober(status)
        res = run("flagged", probe)
        assert "We did not test it" in res.text and res.live == status


def test_no_probe_injected_keeps_q1_report():
    lk = load("flagged")
    res = asyncio.run(service.handle(f"audit {lk.address}", Client("flagged")))
    assert res.text == format_report(lk, score(lk)) and res.live == ""
