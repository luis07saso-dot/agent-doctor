"""Per-sender rate limit + loop guard. Pure, clock-injected, memory-bounded.

Keys: (sender, session) per conversation, plus sender alone for a wider cap. We can't yet
verify whether ASI:One relays many users from one sender address (the REQ log records
hashed sender + session so L8 can check), so the sender cap is generous.

Decisions:
- "ok":     reply normally.
- "warn":   over a rate limit: send one short "slow down" reply (once per window).
- "repeat": same text again and again: send one short "same request" note (once per window).
- "drop":   ack only, no reply (already warned, or a reply loop with another agent).

Loop guard: an auto-replying agent and Doctor can ping-pong forever. Bounded by: identical
text LOOP_REPEAT times in LOOP_WINDOW_S; SESSION_HOURLY_CAP / SESSION_DAILY_CAP replies in
one session; and per-sender warnings so a bot opening a new session per message is still
silenced. Humans don't hit these in normal use.
"""
from __future__ import annotations

import hashlib
import time
from collections import OrderedDict, deque
from typing import Callable, Literal

Decision = Literal["ok", "warn", "repeat", "drop"]

WINDOW_S = 60.0
PER_SESSION_PER_MIN = 8  # covers a human sending 5 rapid messages
PER_SENDER_PER_MIN = 60  # generous: the sender may be a shared ASI:One relay
SESSION_HOURLY_CAP = 20
SESSION_DAILY_CAP = 50  # bounds slow loops that stay under the hourly cap
TRIP_S = 86400.0  # quiet period after a session hits a cap
LOOP_REPEAT = 4  # same text this many times in LOOP_WINDOW_S -> treat as repeat/loop
LOOP_WINDOW_S = 600.0
TEXT_HISTORY = 16  # recent texts kept per session (bounded)
MAX_KEYS = 10_000


class _Bucket:
    __slots__ = ("times", "warned_at", "repeat_noted_at", "texts", "tripped_until")

    def __init__(self) -> None:
        self.times: deque[float] = deque()
        self.warned_at: float | None = None
        self.repeat_noted_at: float | None = None
        self.texts: deque[tuple[float, str]] = deque(maxlen=TEXT_HISTORY)
        self.tripped_until: float | None = None


def _recent(at: float | None, now: float, window: float) -> bool:
    return at is not None and at > now - window


class Guard:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._sessions: OrderedDict[tuple[str, str], _Bucket] = OrderedDict()
        self._senders: OrderedDict[str, _Bucket] = OrderedDict()

    def check(self, sender: str, session: str, text: str) -> Decision:
        now = self._clock()
        sess = self._get(self._sessions, (sender, session))
        snd = self._get(self._senders, sender)
        _trim(sess.times, now - 86400.0)
        _trim(snd.times, now - WINDOW_S)

        # Long-running conversation: almost surely an agent<->agent loop. Once tripped, the
        # session stays quiet for TRIP_S (a loop doesn't get to resume each hour).
        if sess.tripped_until is not None and now < sess.tripped_until:
            return "drop"
        hourly = sum(1 for t in sess.times if t > now - 3600.0)
        if hourly >= SESSION_HOURLY_CAP or len(sess.times) >= SESSION_DAILY_CAP:
            sess.tripped_until = now + TRIP_S
            return "drop"

        # Rate limits. Warn once per window per conversation AND per sender, so a bot that
        # opens a new session per message gets one warning, then silence.
        if len(snd.times) >= PER_SENDER_PER_MIN:
            if _recent(snd.warned_at, now, 3600.0) or _recent(sess.warned_at, now, WINDOW_S):
                return "drop"
            snd.warned_at = sess.warned_at = now
            return "warn"
        per_min = sum(1 for t in sess.times if t > now - WINDOW_S)
        if per_min >= PER_SESSION_PER_MIN:
            if _recent(sess.warned_at, now, WINDOW_S):
                return "drop"
            sess.warned_at = now
            return "warn"

        # Identical text over and over (echo loop, or a user re-sending the same check).
        digest = hashlib.sha256(text.strip().lower().encode()).hexdigest()[:16]
        repeats = sum(1 for t, d in sess.texts if d == digest and t > now - LOOP_WINDOW_S)
        if repeats >= LOOP_REPEAT:
            if _recent(sess.repeat_noted_at, now, LOOP_WINDOW_S):
                return "drop"
            sess.repeat_noted_at = now
            return "repeat"

        # Only messages we actually answer count toward limits and history.
        sess.texts.append((now, digest))
        sess.times.append(now)
        snd.times.append(now)
        return "ok"

    def _get(self, store: OrderedDict, key) -> _Bucket:
        b = store.get(key)
        if b is None:
            b = store[key] = _Bucket()
            while len(store) > MAX_KEYS:
                store.popitem(last=False)
        else:
            store.move_to_end(key)
        return b


def _trim(times: deque[float], cutoff: float) -> None:
    while times and times[0] <= cutoff:
        times.popleft()
