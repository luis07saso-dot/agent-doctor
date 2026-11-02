"""R9 metrics + R10 mailbox alert (scripts/metrics.py) and the VPS log collector
(deploy/collect_logs.sh, run against a fake `docker`)."""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("metrics", ROOT / "scripts" / "metrics.py")
m = importlib.util.module_from_spec(_spec)
sys.modules["metrics"] = m  # dataclasses look the module up by name
_spec.loader.exec_module(m)

T0 = datetime(2026, 11, 3, 10, 0, tzinfo=timezone.utc)


def ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond:06d}000Z"


def req(dt, **rec) -> str:
    base = {"input": "address", "outcome": "ok", "latency_ms": 900, "sender": "s1", "session": "a"}
    base.update(rec)
    return f"{ts(dt)} REQ {json.dumps(base)}"


def mb(dt, status="503") -> str:
    return f"{ts(dt)} MAILBOX_ERR status={status}"


# ---------- parsing ----------

def test_parse_ts_nanoseconds_and_order():
    a = m.parse_ts("2026-11-02T10:03:12.157616347Z")
    assert a == datetime(2026, 11, 2, 10, 3, 12, 157616, tzinfo=timezone.utc)
    assert m.parse_ts("2026-11-02T10:03:12Z").second == 12


def test_parse_events_skips_junk_and_sorts():
    lines = [req(T0 + timedelta(minutes=5)), "garbage", "2026-99 REQ {}", f"{ts(T0)} REQ not-json",
             f"{ts(T0)} HEARTBEAT almanac", f"{ts(T0)} UNKNOWN x", mb(T0 + timedelta(minutes=1)), ""]
    ev = m.parse_events(lines)
    assert [e.kind for e in ev] == ["HEARTBEAT", "MAILBOX_ERR", "REQ"]
    assert ev[1].data == {"status": "503"}


def test_pct_nearest_rank():
    assert m.pct([], 95) is None
    assert m.pct([5], 95) == 5
    assert m.pct(list(range(1, 101)), 50) == 50
    assert m.pct(list(range(1, 101)), 95) == 95
    assert m.pct([1, 2, 3, 100], 95) == 100


# ---------- R9 day stats ----------

def test_day_stats_answered_errors_latency():
    lines = [req(T0, latency_ms=100), req(T0, latency_ms=300, outcome="fallback"),
             req(T0, outcome="dropped", latency_ms=1), req(T0, input="control", outcome="no_reply"),
             req(T0, outcome="prehire_pending", latency_ms=15000, input="handle"),
             req(T0, input="prehire_protocol", outcome="live", sender="agentX")]
    s = m.day_stats(m.parse_events(lines), {})
    assert s["chat"] == 4  # control and protocol are not chat messages
    assert s["answered"] == 3 and s["answered_pct"] == 75.0
    assert s["errors"] == 1 and s["fallbacks"] == 1 and s["dropped"] == 1
    assert s["prehire_pending"] == 1
    assert s["p50"] == 300 and s["max"] == 15000  # dropped (1 ms) not in latency
    assert s["proto_calls"] == 1 and s["out_proto_callers"] == 1


def test_exclusions_only_affect_use_counts():
    lines = [req(T0, sender="me", session="x"), req(T0, sender="me", session="y"),
             req(T0, sender="out1"), req(T0, sender="out1", session="b", outcome="fix_guide"),
             req(T0, sender="out2", outcome="prehire_live", click="fix"),
             req(T0, input="prehire_protocol", sender="me", outcome="live")]
    s = m.day_stats(m.parse_events(lines), {"me": "user"})
    assert s["chat"] == 5  # reliability keeps everyone
    assert s["out_senders"] == 2 and s["out_sessions"] == 3 and s["out_msgs"] == 3
    assert s["audits"] == 1 and s["fix_guides"] == 1 and s["prehire_chat"] == 1
    assert s["clicks"] == {"fix": 1}
    assert s["out_proto_callers"] == 0
    assert s["excluded"] == {"user": 3} and s["excluded_sessions"] == 2


# ---------- R10 mailbox streaks + heartbeat ----------

def test_streak_joins_errors_within_gap_and_splits_after():
    ev = m.parse_events([mb(T0), mb(T0 + timedelta(seconds=300)), mb(T0 + timedelta(seconds=620)),
                         mb(T0 + timedelta(seconds=1000), "connect")])
    st = m.mailbox_streaks(ev)
    assert len(st) == 2  # 620 -> 1000 is a 380 s quiet gap (> 330 s)
    assert st[0].errors == 3 and st[0].seconds == 620
    assert st[1].statuses == {"connect": 1}


def continuous(start, minutes, step_s=2):
    return [mb(start + timedelta(seconds=i)) for i in range(0, minutes * 60 + 1, step_s)]


def test_alert_on_30_min_streak_not_on_shorter():
    long = m.parse_events(continuous(T0, 30) + [f"{ts(T0 + timedelta(hours=1))} HEARTBEAT almanac"])
    al = m.alerts(long)
    assert len(al) == 1 and al[0][1].startswith("ALERT mailbox: errors 2026-11-03 10:00–10:30 UTC (30m")
    assert "still failing" not in al[0][1]
    assert m.alerts(m.parse_events(continuous(T0, 29))) == []


def test_alert_marks_ongoing_streak():
    al = m.alerts(m.parse_events(continuous(T0, 40, step_s=60)))
    assert al and "still failing at the last collected line" in al[0][1]


def test_heartbeat_gap_alert_and_now():
    beats = [f"{ts(T0)} START", f"{ts(T0 + timedelta(hours=1))} HEARTBEAT almanac",
             f"{ts(T0 + timedelta(hours=3))} HEARTBEAT almanac"]
    ev = m.parse_events(beats)
    al = m.alerts(ev)
    assert [t for _, t in al] == ["ALERT heartbeat: none from 2026-11-03 11:00 UTC to 2026-11-03 13:00 UTC (2h00m)"]
    al_now = m.alerts(ev, now=T0 + timedelta(hours=5))
    assert any("to now (2h00m)" in t for _, t in al_now)
    assert len(m.alerts(ev, now=T0 + timedelta(hours=3, minutes=30))) == 1  # 30 min since last: fine


def test_target_alerts():
    lines = [req(T0, latency_ms=16000)] * 19 + [req(T0, outcome="dropped")]
    texts = [t for _, t in m.alerts(m.parse_events(lines))]
    assert "TARGET missed: 95.0% answered (< 99%)" in texts
    assert "TARGET missed: p95 16000 ms (>= 15000 ms)" in texts


# ---------- doc rendering ----------

def test_render_and_update_doc_idempotent(tmp_path):
    lines = [f"{ts(T0)} START", req(T0 + timedelta(minutes=1)), mb(T0 + timedelta(minutes=2)),
             req(T0 + timedelta(days=1), sender="me")]
    ev = m.parse_events(lines)
    block = m.render(ev, {"me": "user"}, now=T0 + timedelta(days=1, minutes=5))
    assert "| 2026-11-03 | 1 | 1 | 100.0 |" in block and "| 2026-11-04 |" in block
    assert "user 1" in block and "503 1" in block
    doc = tmp_path / "metrics.md"
    doc.write_text("# Metrics\n\nHand-written intro.\n\n" + m.START_MARK + "\nold\n" + m.END_MARK + "\n\nNotes.\n")
    m.update_doc(doc, block)
    m.update_doc(doc, block)
    text = doc.read_text()
    assert text.count(m.START_MARK) == 1 and "old" not in text
    assert text.startswith("# Metrics\n\nHand-written intro.") and text.endswith("Notes.\n")


def test_render_empty():
    assert "no events yet" in m.render([], {})
    assert "- none" in m.render([], {})


def test_update_doc_creates_file(tmp_path):
    doc = tmp_path / "new.md"
    m.update_doc(doc, "BODY")
    assert m.START_MARK + "\nBODY\n" + m.END_MARK in doc.read_text()


def test_main_exit_codes(tmp_path):
    doc, f = tmp_path / "m.md", tmp_path / "events.log"
    assert m.main(["--file", str(f), "--doc", str(doc)]) == 1  # no file
    f.write_text("\n".join([req(T0)]) + "\n")
    assert m.main(["--file", str(f), "--doc", str(doc), "--exclude", str(tmp_path / "none")]) == 0
    f.write_text("\n".join(continuous(T0, 31, step_s=30)) + "\n")
    assert m.main(["--file", str(f), "--doc", str(doc)]) == 2


def test_exclude_file_in_repo_is_valid():
    ex = m.load_exclude()
    assert ex and all(len(k) == 12 and int(k, 16) >= 0 for k in ex)


def test_load_exclude_missing_or_bad(tmp_path):
    assert m.load_exclude(tmp_path / "nope.json") == {}
    (tmp_path / "bad.json").write_text("{")
    assert m.load_exclude(tmp_path / "bad.json") == {}


# ---------- collector (deploy/collect_logs.sh) ----------

DOCKER_LINES = """\
2026-11-02T10:03:12.157616347Z INFO:     [Agent Doctor]: Starting agent with address: agent1qx
2026-11-02T10:03:12.383464887Z INFO:     [uagents.registration]: Registration on Almanac API successful
2026-11-02T10:05:00.100000000Z INFO:     [Agent Doctor]: REQ {"input":"address","outcome":"ok"}
2026-11-02T10:06:00.100000000Z ERROR:    [Agent Doctor]: Failed to retrieve messages: 503:<html>Service Unavailable</html>
2026-11-02T10:06:01.200000000Z WARNING:  [Agent Doctor]: Failed to connect to mailbox server: Cannot connect
2026-11-02T10:06:02.200000000Z ERROR:    [Agent Doctor]: Got exception while checking mailbox: boom
2026-11-02T10:06:03.200000000Z WARNING:  [Agent Doctor]: Agent mailbox not found: create one using the agent inspector
2026-11-02T10:07:00.000000000Z ERROR:    [Agent Doctor]: chat handler failed: TypeError
2026-11-02T10:08:00.000000000Z INFO:     [Agent Doctor]: something else
"""


@pytest.fixture
def collector(tmp_path):
    if shutil.which("bash") is None or shutil.which("awk") is None:
        pytest.skip("needs bash + awk")
    bin_dir, vps = tmp_path / "bin", tmp_path / "vps"
    bin_dir.mkdir()
    vps.mkdir()
    shutil.copy(ROOT / "deploy" / "collect_logs.sh", vps / "collect_logs.sh")
    logs = tmp_path / "docker.txt"
    logs.write_text(DOCKER_LINES)
    (bin_dir / "docker").write_text(
        "#!/usr/bin/env bash\n"
        "if [ \"$1\" = inspect ]; then exit 0; fi\n"
        "since=''; while [ $# -gt 0 ]; do [ \"$1\" = --since ] && since=\"$2\"; shift; done\n"
        f"if [ -n \"$since\" ]; then awk -v s=\"$since\" '$1 >= s' {logs}; else cat {logs}; fi\n")
    (bin_dir / "flock").write_text("#!/bin/sh\nexit 0\n")  # macOS has no flock
    for p in bin_dir.iterdir():
        p.chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}

    def run():
        subprocess.run(["bash", str(vps / "collect_logs.sh")], env=env, check=True, timeout=20)
        return (vps / "logs" / "events.log").read_text().splitlines()
    return run, logs


def test_collector_extracts_and_never_duplicates(collector):
    run, logs = collector
    first = run()
    assert first == [
        "2026-11-02T10:03:12.157616347Z START",
        "2026-11-02T10:03:12.383464887Z HEARTBEAT almanac",
        '2026-11-02T10:05:00.100000000Z REQ {"input":"address","outcome":"ok"}',
        "2026-11-02T10:06:00.100000000Z MAILBOX_ERR status=503",
        "2026-11-02T10:06:01.200000000Z MAILBOX_ERR status=connect",
        "2026-11-02T10:06:02.200000000Z MAILBOX_ERR status=exception",
        "2026-11-02T10:06:03.200000000Z MAILBOX_ERR status=404",
        "2026-11-02T10:07:00.000000000Z HANDLER_ERR",
    ]
    assert run() == first  # inclusive --since: last line not copied twice
    with logs.open("a") as f:
        f.write("2026-11-02T11:03:12.000000000Z INFO:     [uagents.registration]: "
                "Registration on Almanac API successful\n")
    assert run() == first + ["2026-11-02T11:03:12.000000000Z HEARTBEAT almanac"]


def test_collector_output_parses(collector):
    run, _ = collector
    ev = m.parse_events(run())
    assert [e.kind for e in ev].count("MAILBOX_ERR") == 4 and ev[2].data["outcome"] == "ok"
