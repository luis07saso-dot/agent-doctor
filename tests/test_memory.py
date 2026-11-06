"""Q15: persistent memory, re-check diff, forget. Spec: docs/specs/q15-memory.md."""
import asyncio
import json
import os
import stat
from dataclasses import replace
from pathlib import Path

import pytest

from agent import agentverse as av
from agent import guides, main, memory, recheck, router, service
from agent import rubric as R
from agent.report import MAX_CHARS, format_report
from agent.scorer import score

FIX = Path(__file__).parent / "fixtures"
FIXTURES = ["strong", "weak", "dead", "flagged"]
STRONG = "agent1qfvydlgcxrvga2kqjxhj3hpngegtysm2c7uk48ywdue0kgvtc2f5cwhyffv"


def load(name) -> av.Lookup:
    d = json.loads((FIX / f"{name}.json").read_text())
    d.pop("captured_at", None)
    d["notes"] = tuple(d.get("notes") or ())
    return av.Lookup(**d)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.setattr(guides, "LAST", guides.LastAudit())
    monkeypatch.setenv("FINDABILITY", "0")
    monkeypatch.delenv("DIFF_KEY", raising=False)


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def shown(name="strong"):
    lk = load(name)
    return service.shown_for(lk, score(lk), "Weather")


# ---------- store ----------

def test_restart_round_trip(tmp_path):
    p = str(tmp_path / "m.json")
    m = memory.Memory(p)
    s = shown()
    m.put_chat("k", s, "snd")
    m.seen_put("snd", STRONG, {"at": __import__("time").time(), "w": "x", "total": 1, "checks": {"active": True}})
    assert run(m.flush())
    m2 = memory.Memory(p)
    got = m2.get_chat("k")
    assert got == s and got.rows == s.rows and got.facts_dict == s.facts_dict
    assert m2.seen_get("snd", STRONG)["total"] == 1


def test_file_mode_and_no_tmp_left(tmp_path):
    p = tmp_path / "m.json"
    m = memory.Memory(str(p))
    m.put_chat("k", shown(), "s")
    run(m.flush())
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o600
    assert [f.name for f in tmp_path.iterdir()] == ["m.json"]


def test_sync_save_without_loop(tmp_path):
    p = tmp_path / "m.json"
    m = memory.Memory(str(p))
    m.put_chat("k", shown(), "s")  # no running loop: saved at once
    assert memory.Memory(str(p)).get_chat("k") is not None


def test_debounced_save_once(tmp_path, monkeypatch):
    p = str(tmp_path / "m.json")
    m = memory.Memory(p)
    writes = []
    real = m._write
    monkeypatch.setattr(m, "_write", lambda text: (writes.append(1), real(text)))
    monkeypatch.setattr(memory, "SAVE_DELAY_S", 0.01)

    async def go():
        for i in range(5):
            m.put_chat(f"k{i}", shown(), "s")
        await asyncio.sleep(0.1)
    run(go())
    assert len(writes) == 1 and memory.Memory(p).get_chat("k4") is not None


def test_corrupt_file_deleted(tmp_path):
    p = tmp_path / "m.json"
    p.write_text('{"v": 1, "chats": {"k": ')
    m = memory.Memory(str(p))
    assert m.get_chat("k") is None and not p.exists()
    p.write_text('["not", "a", "dict"]')
    memory.Memory(str(p))
    assert not p.exists()


def test_broken_entry_skipped(tmp_path):
    p = tmp_path / "m.json"
    good = memory.Memory(str(p))
    good.put_chat("ok", shown(), "s")
    data = json.loads(p.read_text())
    data["chats"]["bad"] = {"at": 1e12, "s": "", "shown": {"name": "x", "fixes": [{"nope": 1}]}}
    p.write_text(json.dumps(data))
    m = memory.Memory(str(p))
    assert m.get_chat("ok") is not None and m.get_chat("bad") is None


def test_unwritable_never_raises(tmp_path):
    d = tmp_path / "ro"
    d.mkdir()
    os.chmod(d, 0o500)
    try:
        m = memory.Memory(str(d / "m.json"))
        m.put_chat("k", shown(), "s")
        assert m.get_chat("k") is not None
        assert run(m.flush()) is False
    finally:
        os.chmod(d, 0o700)


def test_path_none_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    m = memory.Memory(None)
    m.put_chat("k", shown(), "s")
    assert run(m.flush()) is True and list(tmp_path.iterdir()) == []


def test_ttl_caps_and_eviction(monkeypatch):
    clock = Clock()
    m = memory.Memory(None, clock=clock, chat_ttl=10, chat_max=2)
    s = shown()
    m.put_chat("a", s, ""), m.put_chat("b", s, ""), m.put_chat("c", s, "")
    assert m.get_chat("a") is None and m.get_chat("c") is s
    clock.t += 11
    assert m.get_chat("c") is None
    monkeypatch.setattr(memory, "SEEN_MAX_TARGETS", 2)
    monkeypatch.setattr(memory, "SEEN_MAX_SENDERS", 2)
    for i, addr in enumerate(("a1", "a2", "a3")):
        clock.t += 1
        m.seen_put("s1", addr, {"at": clock.t, "w": "", "total": i, "checks": {}})
    assert m.seen_get("s1", "a1") is None and m.seen_get("s1", "a3") is not None
    clock.t += 1
    m.seen_put("s2", "x", {"at": clock.t, "w": "", "total": 0, "checks": {}})
    clock.t += 1
    m.seen_put("s3", "x", {"at": clock.t, "w": "", "total": 0, "checks": {}})
    assert m.seen_get("s1", "a3") is None and m.seen_get("s3", "x") is not None
    clock.t += memory.SEEN_TTL_S + 1
    assert m.seen_get("s3", "x") is None


def test_lastaudit_api_unchanged():
    mem = guides.LastAudit(ttl_s=10, max_items=2, clock=Clock())
    s = guides.Shown("A", "", ())
    mem.put("a", s)
    assert mem.get("a") is s and mem.get("") is None
    mem.put("", s)
    assert mem.get("") is None


# ---------- diff ----------

def record(lk):
    return recheck.record(score(lk), 1_000_000.0)


def test_diff_fixed_new_and_delta():
    before = replace(load("strong"), profile={**load("strong").profile, "avatar_href": None})
    prev = record(before)
    now = score(load("strong"))
    d = recheck.compare(prev, now, 1_000_000.0 + 2 * 86400)
    line = d.line(0)
    assert "Since the last check (2 d ago)" in line and "→" in line and "Fixed: Avatar" in line
    assert "your" not in line.lower()


def test_diff_same_and_cancel_out():
    lk = load("strong")
    d = recheck.compare(record(lk), score(lk), 1_000_030.0)
    assert d.line(0) == "_Same score as the last check (just now)._"
    prev = record(lk)
    prev["checks"]["avatar"], prev["checks"]["handle"] = False, True  # swap: totals may differ
    prev["total"] = score(lk).total
    line = recheck.compare(prev, score(lk), 1_000_030.0).line(0)
    assert "±0" in line and "Fixed: Avatar" in line and "New: Custom @handle" in line


def test_diff_scoring_changed_and_new_rules_ignored():
    prev = record(load("strong"))
    prev["w"] = "different"
    line = recheck.compare(prev, score(load("strong")), 1_000_000.0).line(0)
    assert "scoring changed" in line and "→" not in line
    prev = record(load("strong"))
    del prev["checks"]["avatar"]  # rule unknown to the old record: never "Fixed"
    prev["checks"]["avatar_old"] = False
    line = recheck.compare(prev, score(load("strong")), 1_000_000.0).line(0)
    assert "Fixed" not in line


def test_diff_negative_age_clamped():
    lk = load("strong")
    assert "just now" in recheck.compare(record(lk), score(lk), 999_000.0).line(0)


def test_diff_lists_capped():
    prev = record(load("dead"))
    prev["checks"] = {r: False for r in R.WEIGHTS}
    line = recheck.compare(prev, score(load("strong")), 1_000_000.0).line(0)
    assert "more" in line


@pytest.mark.parametrize("name", FIXTURES)
def test_report_with_diff_and_find_keeps_hows(name):
    from tests.test_findability import WORST
    lk = load(name)
    prev = record(lk)
    prev["checks"] = {r: not v for r, v in prev["checks"].items()}
    prev["total"] = 0
    d = recheck.compare(prev, score(lk), 1_000_000.0 + 3600)
    out = format_report(lk, score(lk), diff=d, find=WORST)
    assert len(out) <= MAX_CHARS and out.count("How:") == 1 and "Since the last check" in out


# ---------- service ----------

class Client:
    def __init__(self, fixture="strong"):
        self.fixture = fixture

    async def lookup(self, a):
        return replace(load(self.fixture), address=STRONG)  # same agent, changed profile

    async def lookup_handle(self, h):
        return replace(load(self.fixture), address=STRONG)


def audit(client, chat="c1", sender="s1"):
    return run(service.handle(f"audit {STRONG}", client, chat_key=chat, sender_key=sender))


def test_restart_keeps_fix_guide_and_explain(tmp_path, monkeypatch):
    p = str(tmp_path / "m.json")
    guides.LAST.attach(p)
    audit(Client())
    run(guides.LAST.memory.flush())
    monkeypatch.setattr(guides, "LAST", guides.LastAudit())  # "restart"
    guides.LAST.attach(p)
    r = run(service.handle("how do I fix #1", Client(), chat_key="c1", sender_key="s1"))
    assert r.outcome == "fix_guide"
    r = run(service.handle("why this score?", Client(), chat_key="c1", sender_key="s1"))
    assert r.outcome == "explain"


def test_diff_on_second_audit_same_sender_only():
    assert "Since the last check" not in audit(Client("weak")).text
    r = audit(Client("strong"), chat="c2")  # new chat, same sender
    assert "Since the last check" in r.text and "→" in r.text
    assert "last check" not in audit(Client("strong"), chat="c3", sender="s2").text


def test_diff_key_chat(monkeypatch):
    monkeypatch.setenv("DIFF_KEY", " Chat ")
    audit(Client("weak"))
    assert "last check" not in audit(Client("strong"), chat="c2").text
    assert "last check" in audit(Client("strong"), chat="c2").text


def test_partial_or_notes_not_recorded():
    class Partial(Client):
        async def lookup(self, a):
            return replace(load("strong"), outcome="partial", notes=("almanac timeout",))
    audit(Partial())
    assert "last check" not in audit(Client()).text


def test_explain_and_prehire_do_not_record():
    run(service.handle(f"why is {STRONG} rated so low?", Client(), chat_key="c", sender_key="s1"))
    assert "last check" not in audit(Client()).text


def test_card_recheck_shows_diff_and_fix_rebuild_threads_sender():
    from agent import cards
    audit(Client("weak"))
    sel = cards.Selection(cards.RECHECK, 0, STRONG)
    r = run(service.handle_card(sel, Client(), chat_key="c9", sender_key="s1"))
    assert "Since the last check" in r.text
    sel = cards.Selection(cards.FIX, 1, STRONG)
    run(service.handle_card(sel, Client(), chat_key="new", sender_key="s7"))
    assert guides.LAST.memory._chats["new"][1] == "s7"


# ---------- forget ----------

@pytest.mark.parametrize("text", ["forget", "forget me", "@agent-doctor forget me", "delete my data",
                                  "delete all my data", "erase my audit history", "remove my data",
                                  "forget my data please", "please wipe my history", "Forget me."])
def test_forget_routes(text):
    assert router.classify(text, ("agent-doctor",), (), True).kind == "forget"


@pytest.mark.parametrize("text", ["delete", "clear", "delete this", "delete my-agent",
                                  "forget it, audit weather-bot", "how do I delete an agent?",
                                  f"delete {STRONG}", "forget #2"])
def test_not_forget(text):
    assert router.classify(text, ("agent-doctor",), (), True).kind != "forget"


def test_forget_removes_only_that_sender():
    audit(Client(), chat="c1", sender="s1")
    audit(Client(), chat="c2", sender="s1")
    audit(Client(), chat="c3", sender="s2")
    r = run(service.handle("forget me", Client(), chat_key="c1", sender_key="s1"))
    assert r.outcome == "forget" and "this ASI:One sender" in r.text
    m = guides.LAST.memory
    assert m.get_chat("c1") is None and m.get_chat("c2") is None and m.get_chat("c3") is not None
    assert m.seen_get("s1", STRONG) is None and m.seen_get("s2", STRONG) is not None


def test_forget_disk_failure_reply(monkeypatch):
    async def fail():
        return False
    monkeypatch.setattr(guides.LAST.memory, "flush", fail)
    r = run(service.handle("forget", Client(), chat_key="c1", sender_key="s1"))
    assert r.outcome == "forget_error" and "try `forget` again" in r.text


def test_help_mentions_forget():
    assert "forget" in router.HELP


# ---------- main ----------

def test_memory_path(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MEMORY_PATH", raising=False)
    monkeypatch.delenv("MEMORY", raising=False)
    assert main.memory_path(STRONG) == str(tmp_path / f"doctor_memory_{STRONG[:16]}.json")
    monkeypatch.setenv("MEMORY_PATH", "/x/y.json")
    assert main.memory_path(STRONG) == "/x/y.json"
    monkeypatch.setenv("MEMORY", " 0 ")
    assert main.memory_path(STRONG) is None
