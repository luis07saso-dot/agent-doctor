# Evidence (judge-facing)

Facts behind each judging criterion, with a source for every number. Times are UTC.
Public copy of a private ledger: sender IDs, contact details and working notes are left out.
**Our own traffic is never counted as outside use** (owner chats, demo client, test agent).
A sender ID is not a person: ASI:One can relay many users under one sender.

Last update: 2026-11-08 08:16 UTC (metrics data 2026-11-02 10:03 – 2026-11-08 08:11).

## 1. Is it useful

| date | claim | source |
|---|---|---|
| 2026-11-02 | One message → 0-100 score, verdict, top 3 fixes, a `How:` line on the first fix, profile link | `agent/report.py`, `tests/agentverse-testing.csv` |
| 2026-11-02 | Step-by-step guide per fix ("how do I fix #1") | `agent/guides.py`, `tests/test_guides.py` |
| 2026-11-03 | Before/after on our own test agent (labelled ours): blank offline agent **12 → 72/100** in ~1 min after following the Doctor's fixes. The remaining points are usage (rating, interactions, success), which can't be faked | `docs/r11/` (before/after audit, API readback) |

## 2. Fetch.ai rails (agents hiring agents)

| date | claim | source |
|---|---|---|
| 2026-11-02 | Agent Chat Protocol + own `AgentDoctorPreHire` 0.1.0 protocol, manifests published | `agent/main.py`, `agent/prehire.py` |
| 2026-11-02 | The Doctor messages other agents itself (live probe: ack + answer timing) | `agent/probe.py`, `scripts/e2e_prehire_local.py` (offline E2E 9/9) |
| 2026-11-03 | Demo: our client agent ran Pre-Hire Check on 3 agents over real Agentverse mailboxes (2 live, 1 unreachable), hired the live one (score 77), job done in 6.9 s. Ours, not outside use | `scripts/p6_hire_demo.py`, `media/demo-v1.mp4` |
| 2026-11-08 | Single-agent audits send the target a live message and show whether it answered within 8 s (info only, not scored) | `agent/service.py`, `tests/test_q20a_audit_live.py` |

## 3. Works every time

| date | claim | source |
|---|---|---|
| 2026-11-08 | **1485 automated tests pass** | `pytest -q` |
| 2026-11-08 | All-time: 444 chat messages, 439 answered (98.9%), **0 errors, 0 handler errors, 0 fallbacks**. The 5 unanswered were rate-limit guard drops on 11-05 (by design) | `docs/metrics.md` → Reliability |
| 2026-11-08 | p95 reply time under 15 s every day since 11-04 | `docs/metrics.md` → Reliability |
| 2026-11-08 | Mailbox: only Agentverse-side 503s, longest streak 3 min, no outage alert. Hourly heartbeat never missed (gap ≤ 1h00m every day) | `docs/metrics.md` → Mailbox and heartbeat |
| 2026-11-08 08:20 | Agentverse public API: `status=active`, `unresponsive=false`, rating 4.3, 749 total interactions | `POST https://agentverse.ai/v1/search/agents` |
| 2026-11-02 | Rate guard, 15 s reply cap, watchdog restart, one-command rollback | `agent/guard.py`, `agent/service.py` |

## 4. What builders said, and what we changed

| date | who | note (short) | what we changed |
|---|---|---|---|
| 2026-11-02 | Fetch.ai rep (hackathon Slack) | false "not responsive" flag, link hidden, suggest fixes | honest unresponsive flag, live check, link on its own line, how-to per fix |
| 2026-11-05 | Builder (Trick or Feedback, 4/5) | only reads README and public data; should actually message the agent | single-agent audits now send a live message and show if it answered (live 2026-11-08) |
| 2026-11-06 | Builder (Trick or Feedback, 4/5) | replies too long; saw "500" errors | audit reply cut to ~750–980 chars (was ~1,250–1,440), `How:` on fix #1 only, help 581 chars (was 1,070). 500s: every message that reached the Doctor was answered with 0 errors, so most likely ASI:One-side (live 2026-11-08) |
| 2026-11-07 | Builder (Trick or Feedback, 3/5) | "test suite not found" lowers score; website should be optional | checks with no public data (Testing, rating, success) are now "not scored" and left out of the total; website is an optional bonus (live 2026-11-08) |

## 5. Real use outside the event

Outside = our own senders removed (`docs/metrics.md` → Use).

| day | outside senders | outside sessions | outside messages | audits | fix guides |
|---|---|---|---|---|---|
| 2026-11-03 | 2 | 3 | 14 | 5 | 6 |
| 2026-11-04 | 2 | 3 | 13 | 8 | 4 |
| 2026-11-05 | 5 | 22 | 162 | 70 | 10 |
| 2026-11-06 | 2 | 2 | 4 | 1 | 1 |
| 2026-11-07 | 3 | 7 | 63 | 23 | 0 |
| 2026-11-08 (to 08:11) | 1 | 1 | 7 | 5 | 0 |
| **total** | – | **38** | **263** | **112** | **21** |

Agentverse Discovery (owner dashboard, 2026-11-04): 359 impressions, 1 pick, 128 interactions.
