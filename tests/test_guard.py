from agent import guard, router


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def g():
    clk = Clock()
    return guard.Guard(clk), clk


def test_window_resets():
    gd, clk = g()
    for i in range(guard.PER_SESSION_PER_MIN):
        assert gd.check("a", "s", f"m{i}") == "ok"
    assert gd.check("a", "s", "x") == "warn"
    assert gd.check("a", "s", "y") == "drop"
    clk.t += guard.WINDOW_S + 1
    assert gd.check("a", "s", "z") == "ok"


def test_sessions_independent_but_sender_capped():
    gd, _ = g()
    ok = sum(gd.check("asi1", f"s{i}", "hi") == "ok" for i in range(guard.PER_SENDER_PER_MIN))
    assert ok == guard.PER_SENDER_PER_MIN
    assert gd.check("asi1", "new", "hi") == "warn"
    assert gd.check("other", "s", "hi") == "ok"


def test_new_session_per_message_bot_warned_once_then_silenced():
    gd, clk = g()
    out = []
    for i in range(300):
        out.append(gd.check("bot", f"sess{i}", f"msg {i}"))
        clk.t += 0.5  # 120/min
    assert out.count("warn") == 1
    assert out.count("ok") <= guard.PER_SENDER_PER_MIN * 3  # one window per 60s, ~150s run


def test_user_rechecking_same_target_gets_answers_then_one_note():
    gd, clk = g()
    out = []
    for _ in range(6):
        out.append(gd.check("user", "s", "check @my-agent"))
        clk.t += 50
    assert out[: guard.LOOP_REPEAT] == ["ok"] * guard.LOOP_REPEAT
    assert out[guard.LOOP_REPEAT] == "repeat"  # a reply, not silence
    assert out[guard.LOOP_REPEAT + 1] == "drop"
    clk.t += guard.LOOP_WINDOW_S + 1  # quiet period over: answered again
    assert gd.check("user", "s", "check @my-agent") == "ok"


def test_echo_loop_goes_quiet():
    gd, clk = g()
    out = []
    for _ in range(20):
        out.append(gd.check("bot", "s", router.HELP))
        clk.t += 20
    assert out.count("ok") == guard.LOOP_REPEAT and out.count("repeat") == 1


def test_varied_text_loop_hits_hourly_cap():
    gd, clk = g()
    out = []
    for i in range(100):  # "hi #N" every 120s: stays under per-minute limits
        out.append(gd.check("bot", "s", f"hi #{i}"))
        clk.t += 120
    assert out.count("ok") == guard.SESSION_HOURLY_CAP  # tripped: no resuming next hour
    assert out[-1] == "drop"


def test_slow_loop_hits_daily_cap():
    gd, clk = g()
    out = []
    for i in range(250):  # ~21h
        out.append(gd.check("bot", "s", f"m{i}"))
        clk.t += 300  # 12/hour, under the hourly cap
    assert out.count("ok") == guard.SESSION_DAILY_CAP


def test_text_history_bounded_and_drops_not_recorded():
    gd, clk = g()
    for i in range(5000):
        gd.check("bot", "s", "same")
        clk.t += 1
    b = gd._sessions[("bot", "s")]
    assert len(b.texts) <= guard.TEXT_HISTORY


def test_memory_bounded(monkeypatch):
    monkeypatch.setattr(guard, "MAX_KEYS", 50)
    gd, _ = g()
    for i in range(200):
        gd.check(f"s{i}", "x", "hi")
    assert len(gd._sessions) <= 50 and len(gd._senders) <= 50
