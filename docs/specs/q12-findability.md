# Q12 spec — Findability test

Status: **spec v2** (2026-11-04), after Sonnet review (12 points, all addressed). On top of Q10 (`4502bc3`). Brief: `docs/build-brief-q10-q16.md` → Q12. User decisions 2026-11-03: **every audit, deadline-capped, info only (not scored)**; **API default search mode (keyword)**.

## 1. Goal
Each audit tells the owner whether people typing the agent's own starter prompts find it in Agentverse search. Example:
`🔍 Agentverse search (top 50): "audit my agent" #1 · "how do I improve my agent's…" not found`

## 2. Verified facts
| # | Fact | Source |
|---|---|---|
| F1 | `POST /v1/search/agents` body fields: `search_text`, `limit` (max 50, default 30), `offset`, `sort` (default `relevancy`), `semantic_search` (default false → "a keywords-based search is performed instead"), `rerank`, `cutoff` (default `none`), `filters`, `source`, `search_id`. | OpenAPI `docs.agentverse.ai/openapi/api-reference-2.json` → `AgentSearchRequest` (fetched 2026-11-03) |
| F2 | Response: `agents[]` (incl. `address`, `handle`), `offset`, `limit`, `num_hits`, `total`, `search_id`. | same → `AgentSearchResponse` |
| F3 | `source`: "The source where the request is sent from. Used by semantic search to ensure consistent results per user". `search_id` can go to `/v1/search/agents/click` (analytics). | same |
| F4 | Docs don't say whether API searches count as Discovery "Impressions". | discovery-insights page |
| F5 | Docs don't say search order = ASI:One picks or marketplace order. Keyword vs semantic differ (Doctor "audit my agent": #1 vs #8). | live 2026-11-03 |
| F6 | Latency (local, via proxy): 0.5–4.7 s sequential, 4.3–6.2 s with 6 in parallel; bodies 90–500 KB. VPS unmeasured. | live 2026-11-03 |
| F7 | `handle` can be null → match by `address`. | F2 |
| F8 | `_call` caps every call at `CALL_TIMEOUT_S = 4.0` (agentverse.py `_call`); lookup cache max 512 shared entries. | `agent/agentverse.py` |
| F9 | **Description phrases are trivial:** first 6 words of the agent's own description → the agent ranks #1 in 11 of 12 sampled active agents (#3 once). **First starter prompt** → #1, #16, #17, #1, not found ×4 (8 agents). So only starter prompts carry signal. | live 2026-11-04 |

## 3. Design

### 3.1 Phrases (new `agent/findability.py`, pure)
`phrases(profile) -> tuple[str, ...]`: from `starter_prompts` only (F9), max 3, in list order. Per prompt, in this order:
1. Skip if it has a placeholder: `<…>`, `{…}`, `[…]`.
2. Remove agent addresses (`agent1…`), URLs, emails, `@handles`.
3. `report.clean(…, 120)`, then remove `"`, collapse spaces, trim end punctuation/spaces.
4. Skip if generic (case-insensitive exact): what can you do, what do you do, who are you, help, hi, hello, hey, start, menu, test.
5. Length: has spaces → 2–12 words; no spaces (e.g. CJK) → 4–60 chars. Else skip.
6. Dedupe case-insensitively.
No prompts left → no findability block (the starter-prompts check already covers "add prompts").

### 3.2 Client (`agent/agentverse.py`)
- `_call`/`_post` gain an optional `timeout` override (default `self._call_timeout`).
- `async search_addresses(phrase) -> tuple[str, tuple[str, ...]]`: `(status, addresses)`; status `ok | timeout | api_down`. Body `{"search_text": phrase, "limit": 50, "offset": 0, "source": "agent-doctor-findability"}`, other fields default (keyword, relevancy). Never calls `/click`.
- Own timeout `SEARCH_TIMEOUT_S = 8.0`, **no caller deadline**: callers only cap how long they wait.
- Own cache dict (not the lookup cache, F8): key = phrase lowercased, spaces collapsed; value = addresses (lowercased); TTL `SEARCH_CACHE_TTL_S = 300` (same as lookups, so a re-check after fixing the README isn't stale long); max `SEARCH_CACHE_MAX = 256` (drop oldest). Only `ok` results cached.
- In-flight: dict phrase-key → `asyncio.Task`. Awaiters use `asyncio.shield(task)`. Done-callback pops the entry and calls `task.exception()` (no "never retrieved" warning).
- Global `asyncio.Semaphore(SEARCH_CONCURRENCY = 6)` around the HTTP call.
- Never raises (catches `Exception`; `CancelledError` of an awaiter doesn't cancel the task).

### 3.3 Check (`findability.check`)
`async check(client, address, phrases, wait_s) -> Find`:
- One task per phrase (`client.search_addresses`), then `asyncio.wait(tasks, timeout=wait_s)`. Done → rank = 1-based index of `address` in results or None; not done or not ok → `not checked`. Tasks keep running and fill the cache.
- `Find(items=((phrase, status, rank), …))`, `status` ∈ `ok | not_checked`.

### 3.4 Service (`agent/service.py`)
- Runs after a successful audit lookup when: intent is `audit`, profile indexed, phrases non-empty, env `FINDABILITY` (`.strip() != "0"`, same as `AUDIT_CARDS`).
- Not for explain, pre-hire, card fix rebuild.
- Wait = `min(FIND_WAIT_S, started + REPLY_BUDGET_S - FIND_MARGIN_S - now)`; `FIND_WAIT_S = 7.0`, `FIND_MARGIN_S = 0.5`. If wait < `MIN_FIND_S = 1.0`: start the tasks (warm cache), don't wait, all `not checked`.
- The Q2 live probe wait and the findability wait run concurrently (`asyncio.gather` of two never-raising coroutines). The probe keeps its existing budget (unchanged Q2 behaviour).
- `Result` gains `find: str = ""` (`"<checked>/<total>"`) and `find_top50: int = -1`; `chat.py` adds `find`, `find_top50` to the log extras when set. Phrases never logged.
- Tests patch `FIND_WAIT_S` / fake client delays (no fake clock needed).

### 3.5 Report (`agent/report.py`)
- `format_report(..., find=None)`. Block sits **after Details, before the tail** (its own paragraph):
  `🔍 Agentverse search (top 50): "audit my agent" #1 · "how do I improve…" not found · "x" not checked`
  + advice ` Use those words in your README.` only if ≥1 `ok` phrase not found **and** the agent is active.
- Phrases shown ≤ 28 chars (`…`). Block ≤ ~150 chars at the short level.
- Trimming order (keeps Top-fix how-tos first): full block (40-char phrases + advice) → no advice → 28-char phrases → no block → existing how-drop loop → `fit`.
- Not scored: no effect on totals, `Score.fixes`, cards, Q10 rows/explain, rubric.
- Test: all 4 fixtures with a 3-phrase worst-case `Find` keep 3 "How:" lines and ≤ 1500.

### 3.6 FAQ
- `FAQ["checks"]` gains its own paragraph (outside the scored list): "I also test findability: where the agent ranks in Agentverse search for its own starter prompts. Info only, not scored."

## 4. Tests (TDD)
- phrases: placeholders skipped; address/URL/email/handle stripped; quotes removed; generic + 1-word skipped; CJK char rule; dedupe; max 3; Doctor's `STARTER_PROMPTS` → ("Audit my agent", "How do I improve my agent's ranking on ASI:One"); no prompts → ().
- client (fake fetch): body (`source`, limit 50, no semantic); 8 s own timeout; status mapping; cache hit (1 fetch for 2 calls), non-ok not cached, separate from lookup cache; in-flight shared (2 concurrent callers → 1 fetch); awaiter cancel doesn't cancel the task; never raises.
- check: partial results (fast phrase ranked, slow one `not checked`); rank by address, case-insensitive.
- service: block in audit; slow search → `not checked`, reply within wait; `FINDABILITY=0` / `" 0 "` → no searches; explain/prehire → no searches; unindexed/no prompts → none; low remaining budget → no wait.
- report: block format, advice rule (inactive → no advice), trimming levels, 4 fixtures keep 3 hows.
- Full suite green.

## 5. Risks
- F4 (impressions): `source` label, cache 5 min, ≤3 searches per audit, semaphore, no background runs. README Limitations (Q16).
- F5: label says "Agentverse search", never "ASI:One rank".
- F6: VPS latency unmeasured → check log `find` after deploy.
