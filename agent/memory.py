"""Q15: what Doctor remembers, on disk so it survives restarts (spec docs/specs/q15-memory.md).

- chats: chat_key -> last audit shown (for "how do I fix #N" and "why this score?"). 24 h.
- seen:  key -> target address -> last score + per-check pass/fail (re-check diff). 30 days.

Not uagents' ctx.storage: it rewrites its JSON in place, and a truncated file makes Agent()
raise on every start. Here: atomic replace (tmp + fsync + rename + dir fsync), tolerant load
(a bad file is deleted, never crashes), debounced writes off the event loop, bounded size.
Stored: hashed keys, public agent names/addresses, scores. Never message text or raw senders.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import OrderedDict
from dataclasses import asdict
from typing import Any, Callable, Optional

from agent.scorer import Check

CHAT_TTL_S = 24 * 3600.0
CHAT_MAX = 500
SEEN_TTL_S = 30 * 86400.0
SEEN_MAX_SENDERS = 2000
SEEN_MAX_TARGETS = 20
SAVE_DELAY_S = 0.5
VERSION = 1

log = logging.getLogger("agent-doctor.memory")


# ---------- Shown <-> dict ----------

def shown_to_dict(shown: Any) -> dict:
    return {"name": shown.name, "address": shown.address, "total": shown.total,
            "verdict": shown.verdict, "fixes": [asdict(c) for c in shown.fixes],
            "rows": [asdict(r) for r in shown.rows], "facts": [list(p) for p in shown.facts]}


def shown_from_dict(d: dict) -> Any:
    from agent.evidence import Row
    from agent.guides import Shown
    return Shown(str(d["name"]), str(d["address"]), tuple(Check(**c) for c in d["fixes"]),
                 int(d.get("total", 0)), str(d.get("verdict", "")),
                 tuple(Row(**r) for r in d.get("rows", ())),
                 tuple((str(k), v) for k, v in d.get("facts", ())))


class Memory:
    def __init__(self, path: Optional[str] = None, clock: Callable[[], float] = time.time,
                 chat_ttl: float = CHAT_TTL_S, chat_max: int = CHAT_MAX) -> None:
        self.clock = clock
        self.chat_ttl = chat_ttl
        self.chat_max = chat_max
        self._chats: OrderedDict[str, tuple[float, str, Any]] = OrderedDict()  # key -> (at, s, Shown)
        self._seen: dict[str, dict[str, dict]] = {}
        self.path: Optional[str] = None
        self._pending: Optional[asyncio.Task] = None
        self._lock: Optional[asyncio.Lock] = None
        self._logged: set[str] = set()
        if path:
            self.attach(path)

    # ---------- chats ----------

    def put_chat(self, key: str, shown: Any, sender_key: str = "") -> None:
        if not key:
            return
        self._chats.pop(key, None)
        self._chats[key] = (self.clock(), sender_key or "", shown)
        self._prune_chats()
        self._changed()

    def get_chat(self, key: str) -> Any:
        item = self._chats.get(key) if key else None
        if item is None:
            return None
        if self.clock() - item[0] > self.chat_ttl:
            self._chats.pop(key, None)
            return None
        return item[2]

    def latest_for_sender(self, sender_key: str) -> Any:
        """Q17: the newest unexpired audit shown to `sender_key` in any chat, or None."""
        if not sender_key:
            return None
        now = self.clock()
        for at, s, shown in reversed(list(self._chats.values())):  # newest put last
            if s == sender_key and now - at <= self.chat_ttl:
                return shown
        return None

    def _prune_chats(self) -> None:
        now = self.clock()
        for k in [k for k, (at, _, _) in self._chats.items() if now - at > self.chat_ttl]:
            self._chats.pop(k, None)
        while len(self._chats) > self.chat_max:
            self._chats.popitem(last=False)

    # ---------- seen (re-check diff) ----------

    def seen_get(self, key: str, address: str) -> Optional[dict]:
        rec = self._seen.get(key, {}).get(address) if key and address else None
        if rec is None:
            return None
        if self.clock() - float(rec.get("at", 0)) > SEEN_TTL_S:
            self._seen.get(key, {}).pop(address, None)
            return None
        return rec

    def seen_put(self, key: str, address: str, rec: dict) -> None:
        if not key or not address:
            return
        targets = self._seen.setdefault(key, {})
        targets.pop(address, None)
        targets[address] = rec
        self._prune_seen()
        self._changed()

    def _prune_seen(self) -> None:
        now = self.clock()
        for key in list(self._seen):
            targets = {a: r for a, r in self._seen[key].items()
                       if now - float(r.get("at", 0)) <= SEEN_TTL_S}
            if len(targets) > SEEN_MAX_TARGETS:
                keep = sorted(targets, key=lambda a: targets[a].get("at", 0))[-SEEN_MAX_TARGETS:]
                targets = {a: targets[a] for a in keep}
            if targets:
                self._seen[key] = targets
            else:
                self._seen.pop(key, None)
        if len(self._seen) > SEEN_MAX_SENDERS:
            newest = {k: max(r.get("at", 0) for r in t.values()) for k, t in self._seen.items()}
            for k in sorted(newest, key=newest.get)[: len(self._seen) - SEEN_MAX_SENDERS]:
                self._seen.pop(k, None)

    # ---------- forget ----------

    async def forget(self, key: str, chat_key: str = "", sender_key: str = "") -> bool:
        """Delete re-check history under `key`, every chat of `sender_key`, and `chat_key`.
        True if the saved copy was updated too."""
        if key:
            self._seen.pop(key, None)
        for k in [k for k, (_, s, _) in self._chats.items()
                  if k == chat_key or (sender_key and s == sender_key)]:
            self._chats.pop(k, None)
        return await self.flush()

    # ---------- disk ----------

    def attach(self, path: str) -> None:
        self.path = path
        self._load()

    def _load(self) -> None:
        if not self.path or not os.path.exists(self.path):
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            if not (isinstance(data, dict) and isinstance(data.get("chats"), dict)
                    and isinstance(data.get("seen"), dict)):
                raise ValueError("bad shape")
        except Exception as e:
            log.error(f"memory load failed: {type(e).__name__}")
            try:
                os.remove(self.path)  # may hold old data forget can't reach; never re-read it
            except OSError:
                pass
            return
        chats = []
        for k, v in data["chats"].items():
            try:
                chats.append((float(v["at"]), str(k), str(v.get("s") or ""),
                              shown_from_dict(v["shown"])))
            except Exception:
                continue  # one broken entry never costs the rest
        for at, k, s, shown in sorted(chats, key=lambda c: c[0]):
            self._chats[k] = (at, s, shown)
        for key, targets in data["seen"].items():
            if isinstance(targets, dict):
                good = {str(a): r for a, r in targets.items()
                        if isinstance(r, dict) and isinstance(r.get("checks"), dict)}
                if good:
                    self._seen[str(key)] = good
        self._prune_chats()
        self._prune_seen()

    def _snapshot(self) -> str:
        self._prune_chats()
        self._prune_seen()
        chats = {k: {"at": at, "s": s, "shown": shown_to_dict(sh)}
                 for k, (at, s, sh) in self._chats.items()}
        return json.dumps({"v": VERSION, "chats": chats, "seen": self._seen},
                          ensure_ascii=False, separators=(",", ":"))

    def _write(self, text: str) -> None:
        path = self.path or ""
        tmp = f"{path}.{os.getpid()}.tmp"
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
            dfd = os.open(os.path.dirname(os.path.abspath(path)), os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        except BaseException:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise

    def _fail(self, e: BaseException) -> None:
        name = type(e).__name__
        if name not in self._logged:  # once per type: no log flood on a full disk
            self._logged.add(name)
            log.error(f"memory save failed: {name}")

    def _changed(self) -> None:
        if not self.path:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # no loop (sync callers, tests): save now
            try:
                self._write(self._snapshot())
            except Exception as e:
                self._fail(e)
            return
        if self._pending is None or self._pending.done():
            self._pending = loop.create_task(self._delayed_save())

    async def _delayed_save(self) -> None:
        await asyncio.sleep(SAVE_DELAY_S)
        await self.flush()

    async def flush(self) -> bool:
        """Save now. True if it reached disk (or there is no file). Never raises."""
        if not self.path:
            return True
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            try:
                await asyncio.to_thread(self._write, self._snapshot())
                return True
            except Exception as e:
                self._fail(e)
                return False
