# Q15 spec — Persistent memory + re-check diff + `forget`

Status: **spec v2** (2026-11-04), after Sonnet review (13 points, all addressed). On top of Q10 (`4502bc3`) + Q12 (`f2c1267`). Brief: `docs/build-brief-q10-q16.md` → Q15. User decision 2026-11-03: **re-check diff keyed per hashed sender**.

## 1. Goal
- "how do I fix #N" and "why this score?" survive restarts and redeploys (open bug in HYDRATE).
- Re-audit of the same agent shows what changed: `_Since the last check (2 d ago): 68 → 76 (+8) · Fixed: Avatar · New: Responsive_`.
- `forget` deletes what we stored for that sender.

## 2. Verified facts
| # | Fact | Source |
|---|---|---|
| F1 | uagents 0.26.1 `KeyValueStore(name)` writes `{name}_data.json` in cwd (`name = address[0:16]`). `_save` rewrites the file in place; `_load` is a bare `json.load` in `Agent.__init__` (truncated file → raise at every start). | `uagents/storage/__init__.py:90-96`, `uagents/agent.py:404` |
| F2 | uagents writes that store only with `store_message_history=True` (default False) or experimental dialogues/health. We use neither. | `uagents/agent.py:324,418` |
| F3 | `WORKDIR /data`, owned by `doctor` (uid 10001) at image build; volume `agent-data:/data` survives restart + redeploy. A volume created earlier under another owner could be unwritable → must fall back, log ERROR. | `Dockerfile:19-20`, `docker-compose.yml` |
| F4 | One asyncio loop (`handle_messages_concurrently=True` interleaves handlers). | `agent/main.py` |
| F5 | `chat_key = hash_id(f"{sender}|{session}")`; `hash_id(sender)` (sha256, 12 hex) already in every REQ log. | `agent/chat.py` |
| F6 | Guard: identical text `LOOP_REPEAT=4` times in 600 s → `REPEATED`. Lookup cache 300 s. | `agent/guard.py:33-34`, `agent/agentverse.py` |
| F7 | `main.build` runs in tests (`tests/test_prehire.py:132,150`) → no persistence in `build` by default. `__main__` is `build(...).run()`. | tests, `agent/main.py:61-62` |
| F8 | One `container_name` + `compose up -d`: old and new containers don't overlap on deploy. The only restart path is watchdog `restart` (same container). Atomic replace is enough. | `deploy/remote_install.sh:24`, compose |
| F9 | **Unverified:** whether ASI:One relays many users under one sender address. Smoke test: one user = one sender hash across 4 chats, new session per chat (`docs/smoke-test.md:55-62`). Others: unknown (VPS log check not run this session). | `agent/guard.py:3-5`, smoke test |

Decision from F1: own file, atomic write, tolerant load (not `ctx.storage`).
Decision from F9: wording never says "your" history; `DIFF_KEY=chat` env switches the diff/forget key to the chat (session) without a rebuild.

## 3. Design

### 3.1 Store (new `agent/memory.py`)
- `Memory(path: str | None = None, clock=time.time)`. `path=None` = in-memory only (default; tests).
- Data `{"v": 1, "chats": {...}, "seen": {...}}`:
  - `chats[chat_key] = {"at": ts, "s": sender_key, "shown": <Shown dict>}` — TTL `CHAT_TTL_S = 24 h`, max `CHAT_MAX = 500`.
  - `seen[sender_key][address] = {"at": ts, "w": weights_hash, "total": int, "checks": {rule: bool}}` — TTL `SEEN_TTL_S = 30 d`, max `SEEN_MAX_SENDERS = 2000` (evict sender with oldest newest-`at`), max `SEEN_MAX_TARGETS = 20` per sender (evict oldest `at`). `at` refreshed on each record.
- Ages: `max(0, now - at)` (clock steps back → never negative).
- Load (attach): missing → empty. Unreadable / bad JSON / wrong shape → empty, **corrupt file deleted** (it may hold old data `forget` can't reach), log `ERROR memory load failed: <ExcType>`. Never raises.
- Save: JSON serialized on the loop (small), then `<path>.<pid>.tmp` via `os.open(..., O_WRONLY|O_CREAT|O_TRUNC, 0o600)`, write, `fsync`, `os.replace`, fsync the directory. Done in `asyncio.to_thread` under an `asyncio.Lock` when a loop runs; debounced (`SAVE_DELAY_S = 0.5`: one pending save task). No running loop → synchronous save. Prune before saving.
- Failure → log `ERROR memory save failed: <ExcType>` once per type, stay in memory, never raise.
- `async flush() -> bool`: save now, True if it reached disk (or path None).
- Stored: hashed keys, cleaned public agent names, target addresses (public), scores, check rows. No message text, no raw sender addresses, no session ids.

### 3.2 Serialization
`Shown` ↔ dict: `name, address, total, verdict, fixes: [Check fields], rows: [Row fields], facts: [[k, v]]`. Rebuild `Check(**d)`, `Row(**d)`. Any error → entry skipped.

### 3.3 Wiring
- `guides.LastAudit(ttl_s=CHAT_TTL_S, max_items=CHAT_MAX, clock=time.time)` keeps `put/get`, gains `put(key, shown, sender_key="")`, `.memory` (the `Memory`), `attach(path)`. `put` with `sender_key=""` stores `s=""`.
- Existing test monkeypatching `guides.time.monotonic` (`tests/test_guides.py:276`) → updated to the `clock` param.
- `agent/main.py` `__main__`: `agent = build(settings); guides.LAST.attach(memory_path(agent.address)); agent.run()`. `build` never attaches (F7).
- `memory_path(address)`: `MEMORY=0` → None (in-memory). `MEMORY_PATH` if set. Else `os.path.join(os.getcwd(), f"doctor_memory_{address[:16]}.json")` (prod cwd `/data`; dev agent → own file).
- `.gitignore`: `doctor_memory_*`.
- `service.handle(..., sender_key="")` and `service.handle_card(..., sender_key="")`; passed to `_handle` and every `LAST.put` (audit, explain-with-target, card FIX rebuild, card RECHECK via `_handle`). `chat.py` passes `hash_id(sender)` in `common`.
- `diff_key(sender_key, chat_key)`: env `DIFF_KEY` `.strip().lower() == "chat"` → `chat_key`, else `sender_key` (read per reply).

### 3.4 Re-check diff
- Record only on an **audit** whose `lk.outcome == "ok"` and `lk.notes` empty (no partial data → no false Fixed/New) and key non-empty and `lk.address`. Cached lookups record too (same data).
- `prev = memory.seen_get(key, address)` read before recording.
- `weights_hash = sha256(json.dumps(R.WEIGHTS, sort_keys=True))[:8]`.
- Compare only rules in both records. Fixed = was False, now True. New = was True, now False. Labels `router.RULE_NAMES`, max 3 each + `+N more`.
- Line (under the score line):
  - hash differs → `_Since the last check (<age> ago): scoring changed, so points aren't comparable. Fixed: … · New: …_` (lists only if any).
  - else lists empty and same total → `_Same score as the last check (<age> ago)._`
  - else `_Since the last check (<age> ago): 68 → 76 (+8) · Fixed: A · New: B_` (`±0` if same total).
- Age: `just now` (<60 s), `N min`, `N h`, `N d`.
- Levels: 0 full, 1 short (`_Since the last check (<age> ago): 68 → 76 (+8)._` / scoring-changed short / same-score), 2 none.
- `format_report(..., diff=None)`; `diff` = a small object with `.line(level)`. Search order: for how-count (all → 0): for diff level (0, 1, 2): for find level (0..4): first fit. Fallback `fit(build(0, …), tail)` unchanged.

### 3.5 `forget`
- Checked after the self-mention strip, before `fix_number`/FAQ/soft handles; only when there are **no targets**.
- Rule (case-insensitive, whole message, after stripping a leading `please` and trailing `please|now|thanks|thank you` and punctuation):
  - `forget`, `forget me|us|everything|it all` → forget.
  - `<verb> [all] [of] [my|our|the|this] [stored|saved|audit|chat] <noun>` with verb ∈ forget, delete, erase, wipe, clear, remove and noun ∈ data, history, memory, record(s), info, information, audit(s), everything → forget.
  - A verb alone or with a non-noun (`delete`, `clear`, `delete this`, `delete my-agent`) → not forget.
- Service: `ok = await memory.forget(key)` where key = `diff_key(...)`; deletes `seen[key]`, every chat with `s == sender_key` (sender mode) and the current `chat_key`; then `flush()`.
- Reply ok: "Done. I deleted what I stored for this ASI:One sender: recent audits and re-check history. Request logs keep only hashed IDs and no message text; this doesn't change them."
- Reply not saved to disk: "I removed it from memory, but couldn't update the saved copy. Please try `forget` again in a minute."
- Outcome `forget` / `forget_error`. HELP gains `Send "forget" to delete what I stored for you.`

## 4. Tests (TDD)
- memory: restart round-trip; TTL + caps + eviction rules; corrupt → empty + file deleted; unwritable dir → no raise, in-memory works, flush False; no `.tmp` left; file mode 0o600; `path=None` writes nothing; negative age clamped; debounced save runs once for many changes.
- serialization: Shown with Q10 rows round-trips; broken entry skipped.
- service: audit → new LastAudit from same file → "how do I fix #1" + "why this score?" work; diff on 2nd audit by same sender (changed avatar → "Fixed: Avatar"); other sender → none; `DIFF_KEY=chat` → per chat; partial/notes → not recorded; weights hash differs → "scoring changed"; cancel-out → lists shown with ±0; explain/prehire don't record; card RECHECK shows diff; sender_key threaded to card FIX rebuild.
- report: diff levels + find levels; 4 fixtures + longest diff + worst `Find` keep 3 hows and ≤ 1500.
- router: forget ✓ `forget`, `forget me`, `@agent-doctor forget me`, `delete my data`, `delete all my data`, `erase my audit history`, `remove my data`, `forget my data please`, `please wipe my history`; ✗ `delete`, `clear`, `delete this`, `delete my-agent`, `forget it, audit weather-bot`, `how do I delete an agent?`, `delete agent1q…`.
- forget: removes only that key's data; flush failure → `forget_error` text.
- main: `build()` never attaches; `memory_path` honours `MEMORY=0` / `MEMORY_PATH`.
- Full suite green.

## 5. Risks
- F9 shared relay: neutral wording; `DIFF_KEY=chat` switch; 👤 verify with `scripts/metrics.py --pull --sessions` (sandbox off) — if distinct people share a sender hash, set `DIFF_KEY=chat`.
- Disk/permission → ERROR log, in-memory fallback.
- 12-hex sender hash is pseudonymous (brute-forceable from public addresses): README privacy (Q16).
