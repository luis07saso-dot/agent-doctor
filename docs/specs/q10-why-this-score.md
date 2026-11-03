# Q10 spec — "Why this score?" (FB-2 change)

Status: **spec v2** (2026-11-03), after Sonnet review (16 points, all addressed below). Brief: `docs/build-brief-q10-q16.md` → Q10. User decisions 2026-11-03: no-data checks = **0 pts, labelled "no data", tagged Tip, listed after Found fixes**.

## 1. Problem (FB-2, `FEEDBACK.md`)
- (a) No evidence behind recommendations.
- (b) "No data" looks like zero.
- (c) General advice looks like a detected problem.
- (d) Questions about an audit re-run the audit.

## 2. Verified facts (sources)
| # | Fact | Source |
|---|---|---|
| F1 | `_rate()` gives 0 pts + "Get real users…" when the value is `None`. `_rating`/`_interactions` also give 0 for `None`. | `agent/scorer.py` |
| F2 | In 317 sampled live agents: `recent_success_rate` is null in all 278 with `recent_verified_interactions` = 0; in all 39 others it **equals exactly** (err < 1e-16) the 95% Wilson lower bound of `recent_success_verified_interactions / recent_verified_interactions`. Sample, not a documented rule. | Live `POST /v1/search/agents`, 2026-11-03 (this session) |
| F3 | Docs: success rate = "a rolling last-30-day Wilson-score interval over your Agent's recent conversations"; "counts every conversation your Agent takes part in over ASI:One - including conversations initiated by other Agents". Empty display, minimum count: not stated. | docs.agentverse.ai/documentation/agent-optimization/growth-metrics |
| F4 | Profile JSON fields exist: `recent_interactions`, `recent_verified_interactions`, `recent_success_verified_interactions`, `total_interactions`, `rating`, `recent_success_rate`, `recent_eval_success_rate`. Field meanings beyond F2: not documented. `recent_interactions` ≠ verified (strong fixture: 7,179 vs 0). | `tests/fixtures/*.json` |
| F5 | Eval rate: docs don't define it or say when it's empty. | Testing docs |
| F6 | No unique-user field in public profile data. | F4; OpenAPI `Agent` schema |
| F7 | Rating = recent + total interactions, successful ASI:One conversations, successful agent evaluations. No formula. | ranking docs (`SCOPE.md` Score rules) |
| F8 | A message with a target and no Pre-Hire wording routes to `audit`. | `agent/router.py` `classify` (l.264-267) |
| F9 | Effect of missing data on ranking (penalty vs neutral): not stated. | ranking docs |

**Wording rule from F2–F4:** per-agent counts are shown as Agentverse's field names in plain words ("verified chats"), never "ASI:One chats" or "30 days" (not proven per field). Only the rate *definition* quotes F3.

## 3. Design

### 3.1 Scorer (`agent/scorer.py`)
- `Check` gains `kind: str = "found"` (last field, default). Values: `ok` (full marks), `found` (data shows a gap), `no_data` (Agentverse gave no value).
- `_mk(rule, frac, detail, fix, kind="found")` → `kind="ok"` when full marks, else the given kind.
- `no_data` cases (all still 0 pts → **every total unchanged**):
  - `success_rate` not a number → detail `no data`, fix `No success rate from Agentverse yet (0 verified chats): bring real users via ASI:One` if `recent_verified_interactions == 0`, else `No success rate from Agentverse yet: bring real users via ASI:One`. `_rate` gets the profile's verified count as an extra arg (signature change).
  - `eval_rate` not a number → detail `no data`, fix `No Testing score from Agentverse yet: run Agentverse Testing with real in-scope questions`.
  - `rating` not a number → detail `no data`, today's fix.
  - `interactions` not an int → detail `no data`, today's fix.
- **Not indexed** (`indexed=False`: profile missing/failed): every failing check is `found` (the missing profile is the detected gap; no Tips).
- Measured values (incl. 0.0) keep today's fix text, `found`.
- README merge check in `Score.fixes` → `kind="found"`.
- `Score.fixes` sort: `(rule != "active", kind == "no_data", -lost, rubric order)`.

### 3.2 Report (`agent/report.py` `format_report`)
- Fix line: `1. Found: <fix> (+N pts)` / `1. Tip: <fix> (+N pts)`.
- Details: `ASI:One success: no data` / `Testing: no data` (was `none yet`).
- Footnote shortened to keep length: `_Weights are our estimate (Agentverse doesn't publish them). Keywords are private, so not scored._`
- Legend line only if a Tip is in Top fixes: `_Tip = no data from Agentverse, general advice._`
- Tail with fixes: `Ask "how do I fix #1" for step-by-step help, or "why this score?" for the evidence. Re-check any time after changes.` Without fixes: `Ask "why this score?" for the evidence. Re-check any time after changes.`
- **Constraint (test):** all 4 fixtures keep all 3 "How:" lines and stay ≤ 1500. If a fixture fails, shorten text, never the how-to.
- Update `README.md` sample output (l.~65) and `tests/test_scorer.py:210` ("none yet").

### 3.3 Evidence (new `agent/evidence.py`, pure)
- `facts(profile) -> dict`: ints (or None) for `total_interactions`, `recent_interactions`, `recent_verified_interactions`, `recent_success_verified_interactions`; floats (or None) for `recent_success_rate`, `recent_eval_success_rate`, `rating`. Non-numbers and bools → None. None is shown as "no data", never 0.
- `rows(lookup, score) -> tuple[Row, ...]`, `Row(rule, label, points, max_points, kind, value)`; `value` examples:
  - active `active (profile + Almanac)` / `not registered in the Almanac` / `offline`.
  - readme_sections `4/6, missing Usage, Limitations`; readme `812 chars`.
  - success_rate `no data (0 verified chats)` / `85% (107 of 117 verified chats succeeded)`.
  - eval_rate `no data` / `60%`. rating `2.5/5`. interactions `352 total, 7 recent`.
  - others: the check's detail.
- Labels from `router.RULE_NAMES` (single source).

### 3.4 Explain reply (`evidence.format_explain(shown, text) -> str`)
Body (trimmed from the end by `report.fit`) + footer (always kept, passed as `fit`'s footer):
```
**Why <name> scored <total>/100 · <verdict>**
Data: Agentverse public profile + Almanac. Points are our estimate (weights not published).

<topic paragraphs the question asks about>

❌ README sections 10/15: 4/6, missing Usage, Limitations (found)
❔ Success rate 0/4: no data (0 verified chats) (tip)
…one line per check that lost points: found first, then no data, rubric order…
✅ Full marks: Active, Chat Protocol, Handle, …
```
Footer: `\n\nFound = the data shows a gap. Tip = no data, general advice. Ask "how do I fix #1" for steps.` (+ profile link if address).
Topics (case-insensitive on the user's text):
- users (`unique users?`, `how many (users|people)`): "Agentverse's public data has no unique-user count. It shows <total> total interactions, <recent> recent, and <verified> verified chats (<ok> succeeded)."
- interactions (`interactions?|chats?|conversations?`): same counts sentence, without the unique-user part (skip if users topic already shown).
- success (`success`, `asi:?one`, `asi1`): "Success rate: Agentverse docs call it a rolling 30-day Wilson score over the agent's ASI:One conversations (chats started by other agents count). Its value matches <ok> succeeded of <verified> verified chats. <Rate X% | No rate yet: 0 verified chats.>"
- rating (`rating|rated|stars?`): "Rating <r>/5 is Agentverse's own value from recent and total interactions, successful ASI:One chats and evaluations. Agentverse doesn't publish the formula."
- testing (`test(ing)?|evals?|evaluation`): "Testing score: <X% | no data from Agentverse>. Agentverse doesn't say when it's empty."
All numbers from `facts`; missing → "no data".

### 3.5 Memory (`agent/guides.py`)
- `Shown` gains defaulted fields: `total: int = 0`, `verdict: str = ""`, `rows: tuple = ()`, `facts: tuple = ()` (pairs; `facts_dict` property). Old call sites unchanged.
- Stored by the audit path, the explain-with-target path, and the card "fix" rebuild path.

### 3.6 Router (`agent/router.py`)
New kinds `explain`, `explain_none`.
```
_EXPLAIN = (any of, re.I|re.S)
  \bwhy\b.{0,40}\b(?:scor\w*|rated|rating|points?|recommend\w*|suggest\w*|tips?|found|so low|so high)\b
  \b(?:this|that|my|the|its|their) score\b.{0,20}\?|\bthis score\b
  \bevidence\b
  \bexplain\b.{0,30}\b(?:score|scoring|rating|points|audit|result|this|that)\b
  \bbreak\s?down\b
  \bunique users?\b | \bhow many (?:unique )?(?:users|people|chats|conversations|interactions)\b
  \bsuccess (?:rate|metrics?)\b
  \bwhat(?:'s|s| is| was| are)\b.{0,30}\b(?:rating|success|interactions)\b
  \bhow\b.{0,30}\b(?:you|it|this|that|they)\b.{0,20}\b(?:scor\w*|calculat\w*|rated|rating|measur\w*|got)\b
  \bwhere\b.{0,30}\b(?:data|numbers?)\b.{0,20}\bcome\b
_AUDIT_CMD = \baudit\w*|\bre-?check\w*|\bscan\b
_STRONG_EXPLAIN = \bthis score\b | \bwhy\b.{0,40}\bscor\w* | \bunique users?\b
```
`explain_wanted(text) = _EXPLAIN.search(text) and not _AUDIT_CMD.search(text) and not prehire wording and fix_number(text, True) == 0`.
Order in `classify`:
1. Targets: prehire wording → `prehire` (unchanged). `explain_wanted` → `explain` with targets. Else `audit` (unchanged; incl. "how do I fix #2 for weather-bot").
2. bad address, self-mention strip, empty → unchanged.
3. `fix_number` → `fix_guide` (unchanged).
4. `has_audit` and `faq_key(text) in ("", "score")` and (`explain_wanted` or `faq_key == "score"`) → `explain` (last audit). FAQ `rank`/`free`/`checks` always win.
5. Soft handle and `explain_wanted`: `explain` with that target, `soft=True`, fallback = `Intent("explain")` if `has_audit` else today's base intent.
6. Unchanged base (`_no_target`: prehire_need_target → faq → need_target → help → off_scope), **except** when base would be `need_target`/`help`/`off_scope`, no audit, and `_STRONG_EXPLAIN` matches → `explain_none`.
- Card RECHECK sends `audit <addr>` → `_AUDIT_CMD` keeps it an audit (test).
- `EXPLAIN_NONE`: "I don't have an audit in this chat yet, so there's no score to explain. Send an agent address or handle first (e.g. `audit weather-bot`, no @), then ask `why this score?`."
- HELP gains: `Ask "why this score?" to see the data behind each check.`

Expected routing (tests):
| Text | has_audit | → |
|---|---|---|
| how many unique users does weather-bot have? | any | explain (soft weather-bot) |
| what's agent1q…'s success rate and how did you score it? | any | explain (target) |
| how many interactions does weather-bot have? | any | explain (soft) |
| why this score? / how did you calculate that? / why did you recommend real users? | yes | explain |
| why this score? | no | explain_none |
| how is this score calculated? / how is the score calculated? | no | faq score |
| how is the score calculated? | yes | explain |
| what evidence do you check? | no | faq checks |
| why is ticketlens-agent not showing up? | no | audit, soft (unchanged, `test_faq_soft.py:100`) |
| why isn't weather-bot ranking? / why is my agent not ranking? (has_audit) | any | unchanged (audit soft / faq rank) |
| is weather-bot open-source? / show weather-bot metrics / my-bot is based on gpt | any | audit (unchanged) |
| explain fix #2 for weather-bot / how do I fix #2 | any | unchanged (fix_guide: soft handle, fix_number first) |
| audit weather-bot and explain the score | any | audit |
| is weather-bot live? | any | prehire |

### 3.7 Service (`agent/service.py`)
- `explain` no targets → `_explain(chat_key, text)`: LAST has rows → `format_explain`, outcome `explain`; else `EXPLAIN_NONE`, outcome `explain_none`. No I/O.
- `explain` with target → audit's lookup path (cache, errors, soft miss → fallback intent) → score → rows → store Shown → explain reply. No probe, no card. Outcome `explain`.
- Soft explain miss with fallback `explain` → `_explain` on last audit.
- Docstring outcome list gains `explain`, `explain_none`.

### 3.8 Guides
- `short_how`/`full_guide` for `success_rate`/`eval_rate` when `kind == "no_data"`: "Agentverse has no value yet" variant. Success: users reach it through ASI:One; Agentverse judges those chats (F3); keep `_NO_FAKE`. No other claims.

## 4. Tests (TDD, write first)
- scorer: kind per rule (None / number / bool / 0.0); fixtures: strong success → no_data, flagged → found; **all 4 fixture totals equal today's**; found before tip; offline first; unindexed → no Tips.
- report: Found/Tip prefixes; "no data" for null (never "0%"/"none yet"); legend only with a Tip; **4 fixtures keep 3 hows, ≤1500**; no-fix tail.
- evidence: facts None handling; row values; each topic; "0%" never for null; ≤1500; footer kept when trimmed.
- router: every row of the §3.6 table; all existing router tests unchanged.
- service: explain from LAST (0 client calls); explain with target (1 lookup, then "#1" works); explain_none; soft miss → last-audit explain; card RECHECK still audit; never raises.
- Full suite green.

## 5. Out of scope
LLM (Q11), persistence (Q15), findability (Q12), profile publish (Q16), weight changes.

## 6. Risks
- Router steals audits → narrow regex + `_AUDIT_CMD` + regression table.
- Length → shortened footnote, conditional legend, test on hows.
