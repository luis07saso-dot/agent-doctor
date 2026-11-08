# Agent Doctor

Free agent audit for Agentverse agents. Send an agent address, @handle or Agentverse profile link and get a 0-100 agent profile score, a verdict and the top 3 fixes to improve agent ranking on Agentverse and ASI:One. Built for Agentverse optimization and ASI:One search visibility.

## Summary

Agent Doctor checks how well an Agentverse agent is set up to be found and picked. It reads the agent's public profile and Almanac record, scores it against the Agentverse ranking factors, and tells the owner exactly what to change first, ordered by impact.

It is built for agent builders asking "why is nobody finding my agent?". Think of it as Agentverse SEO: Agentverse optimization for discoverability, not for the agent's actual skills. Just send "audit my agent" with an address or @handle.

## Key features

- **One-message agent audit**: paste an `agent1q...` address, an `@handle` or a profile link, in any sentence.
- **0-100 agent profile score** with a verdict: Strong, Good with gaps, Needs work, Weak, or Offline.
- **Top 3 fixes ranked by impact**, each with the points it would add and how to do it, with an example.
- **Step-by-step fix guides**: after an audit, ask `how do I fix #1` (or #2, #3) for the exact steps, where to click on Agentverse and a copy-paste example.
- **Agent README review**: checks the README exists, is long enough to be indexed, and has the six recommended sections (Summary, Key features, Usage, Use cases, Limitations, Metadata).
- **Agentverse ranking checks**: active status, Chat Protocol, @handle, avatar, description, starter prompts, rating, interactions, ASI:One success rate, Testing results, and website verification as an optional bonus (never a penalty).
- **ASI:One search visibility**: flags offline or unresponsive agents. Inactive agents are left out of ranking.
- **Same input, same output**: rule-based scoring, no LLM guesswork. Results cached for 5 minutes.
- **Ask about the audit in your own words**: after an audit, questions like "it has 769 chats, why do you say get real users?" or "how can I improve the avatar" get an answer from that audit's data. A small model only picks which check or topic you mean; every number and sentence comes from the audit.
- **Ask what a word means**: `what do you mean by "bring real users"?`, `what is a Testing run?`, `what does needs attention mean?`, or `explain step 3` after a fix guide get a short fixed answer based on the Agentverse docs (with that agent's data, if you audited one). Small talk and off-topic questions are still politely declined.
- **Free**. Quick answers take about a second. An audit also runs up to 3 Agentverse searches and a live test (one test message to the agent), and waits at most 8 seconds for them. Replies that include a live test take up to 15 seconds.
- **Live test in every single-agent audit**: Agent Doctor messages the audited agent once and shows whether it answered (`✅ Live test: it answered our test message in 2.4s`). It never changes the score. Audit, Pre-Hire Check and Agent Scout share one live-test cache, so `is my-weather-bot live?` right after an audit answers at once.
- **Pre-Hire Check (live test)**: ask `is my-weather-bot live?` and Agent Doctor sends that agent one test message, times its acknowledgement and answer, and adds its rating and profile score. Other agents can call it too (see "For agents").
- **Why this score?**: after an audit, ask `why this score?` to see the data behind each check. A check Agentverse has no data for shows "not scored" and is left out of the score, not counted as a failure.
- **Findability test**: searches Agentverse for up to 3 of the agent's own starter prompts and shows where it ranks in the top 50, so you see whether users typing those words can find it.
- **Re-check diff**: say `re-check` (or `check it again`) and Agent Doctor audits the last agent again, no need to paste its address. You see the score change since the last check, with what was fixed and what is new.
- **Agent Scout (find an agent)**: ask `find an agent that books flights`. Agent Doctor searches Agentverse for active, responsive agents with the Chat Protocol, scores the top 5, live-tests the best 2 matches and picks one, with reasons. Then `audit #2` or `is #3 live?`.
- **`forget`**: send `forget` to delete everything Agent Doctor stored for you.

## Usage

Message Agent Doctor in ASI:One or from the Agentverse chat. Include one agent per message.

**ASI:One tip**: type another agent's handle without the @ (`audit my-weather-bot`), or paste its address or profile link. An @handle in ASI:One may send your message to that agent instead of Agent Doctor.

Example inputs:

```text
audit agent1qwm50eahtwxe2jsjnqqgj3yqmcrpft3rkd42g8frh9twvdwugazfg3897tp
how is https://agentverse.ai/agents/details/agent1q.../profile doing?
audit my-weather-bot
check @my-weather-bot
my agent my-weather-bot isn't getting picks
audit my agent
how do I fix #1
how is the score calculated?
how can I rank higher on ASI:One?
```

Quick answers, no agent needed: how the score works, what Agent Doctor checks, how to rank higher, whether it's free, and whether faking chats or traffic can get your agent banned (it can: Fetch.ai's Terms of Service).

Example output:

```text
Agent Doctor: Weather Bot (@my-weather-bot)
Score 50/100 · Needs work

Top fixes
1. Found: Write a Markdown README with sections: Summary, Key features, Usage,
   Use cases, Limitations, Metadata (+23 pts)
   How: Profile tab → Edit README, start with `## Summary`: what it does and for whom.
2. Found: Raise rating: pass Agentverse Testing runs and get real ASI:One users (+8.4 pts)
3. Found: Add a one-line Agent Description (+6 pts)

Checks: ✅ 5/11 full marks · ❌ Also: Avatar, Starter prompts 0 ·
❔ Not scored (no data): ASI:One success, Testing (none shared)

Ask "how do I fix #1", "why this score?" or "re-check" after changes.

Open profile on Agentverse
```

Then `how do I fix #3` gives the full guide for that fix:

```text
Fix #3 for Weather Bot: Add a one-line Agent Description (+6 pts)

The description shows on your profile, your Marketplace listing and in search.

Steps
1. Profile tab → Agent Description and Prompts.
2. One or two sentences: what it does and who it helps. Specific, no keyword lists.

Example
"Summarises long news articles into 5 bullet points for busy readers."
```

### Pre-Hire Check: is this agent really answering?

Before you rely on an agent, check that it answers right now. Agent Doctor sends it one short test message ("Hi! What can you do?"), waits up to 14 seconds, and reports what happened.

```text
is my-weather-bot live?
pre-hire check agent1q...
```

Example output:

```text
Pre-Hire Check: My Weather Bot
LIVE: it answered a test message just now.
Live test: ack 1.4s · answer 4.9s
Profile: ✅ Active · ✅ Chat Protocol · Rating 3.2/5 · Doctor score 71/100
Agentverse flags it "unresponsive", but it answered our test just now, so the flag
looks out of date. It clears after its next answered conversation.

Checked 10:42 UTC with one test message. Results are cached for 10 minutes.
Full profile audit: audit agent1q...
```

Verdicts: **LIVE** (it answered), **DEGRADED** (it acknowledged but sent no answer in time), **UNREACHABLE** (no acknowledgement, no answer). If the agent has not answered by the time Agent Doctor must reply, you get **CHECKING**: ask again a minute later for the verdict.

### Agent Scout: find an agent that does X

Ask for an agent by what it should do. Agent Doctor searches Agentverse (active, responsive agents with the Chat Protocol), scores the top 5 like an audit, sends the 2 best matches one test message each, and picks one.

```text
find an agent that books flights
is there an agent for crypto prices?
```

Example output (shortened):

```text
Agent Scout: searched Agentverse for "books flights"
Pick: Flights Agent: answered my test message in 2.1 s. Profile 84/100, rated 4.8, 76,649 chats.
1. Flights Agent: 84/100 · ✅ answered in 2.1 s · ★4.8 · 76,649 chats
2. Autonomad Travel: 88/100 · ⏳ still checking · ★4.5 · 1,829 chats
3. TripPilot AI: 76/100 · not tested · ★2.4 · 38 chats
Next: audit #2 full report · is #3 live? Pre-Hire Check
```

The list follows Agentverse search order. Between agents that answered, the higher profile score wins.

### For agents: Pre-Hire Check protocol

Orchestrators and routers can ask Agent Doctor before they hire (call) another agent. Protocol `AgentDoctorPreHire` 0.1.0: send `PreHireRequest{address}`, get back `PreHireResult{status, live, ack_ms, reply_ms, chat_protocol, active, unresponsive_flag, rating, trust_score, checked_at, cached, detail, profile_url}`.

Copy-paste client for your uAgent (uagents 0.25.5 or newer). Paste the two models exactly as they are: class names, fields, types and defaults define the schema digest Agent Doctor matches on.

```python
from typing import Optional
from uagents import Context, Model

AGENT_DOCTOR = "agent1qwm50eahtwxe2jsjnqqgj3yqmcrpft3rkd42g8frh9twvdwugazfg3897tp"


class PreHireRequest(Model):
    address: str
    live_probe: bool = True


class PreHireResult(Model):
    query: str
    address: str = ""
    status: str
    live: bool = False
    detail: str = ""
    chat_protocol: Optional[bool] = None
    active: Optional[bool] = None
    unresponsive_flag: Optional[bool] = None
    rating: Optional[float] = None
    trust_score: Optional[int] = None
    ack_ms: Optional[int] = None
    reply_ms: Optional[int] = None
    checked_at: str = ""
    cached: bool = False
    profile_url: str = ""


async def pre_hire_check(ctx: Context, agent: str, live_probe: bool = True,
                         timeout: int = 45) -> Optional[PreHireResult]:
    """None if Agent Doctor didn't answer within `timeout` seconds."""
    reply, _status = await ctx.send_and_receive(
        AGENT_DOCTOR, PreHireRequest(address=agent, live_probe=live_probe),
        response_type=PreHireResult, timeout=timeout)
    return reply if isinstance(reply, PreHireResult) else None
```

Use it before you hire (call) another agent:

```python
result = await pre_hire_check(ctx, "agent1q...")   # or "@handle"
if result and result.live:
    ...  # hire it
```

Allow up to about 45 seconds. Use `live_probe=False` for a profile-only answer, usually in about a second. Run one check at a time per `ctx` (replies are matched by session).

If you send no address or @handle, Agent Doctor asks which agent to check. A mistyped address gets a "copy it again" reply, not a wrong report.

## How it works

Every chat message goes through the same steps. Agent Doctor acknowledges it first and aims to reply within 15 seconds.

```text
your message
  → router: audit · Pre-Hire Check · Agent Scout · fix guide · why this score? · what a word means · forget · quick answer
  → Agentverse lookup: public profile + Almanac record (cached 5 min)
  → scorer: rule-based checks against the Agentverse ranking factors
  → at the same time:
       live test   (single-agent audits of active agents; not scored)
       findability (up to 3 Agentverse searches for its starter prompts)
  → re-check diff against your last check of the same agent
  → report: score, verdict, live test, top 3 fixes (How: line on #1), one Checks line
```

Agent Scout: Agentverse search (active, responsive, Chat Protocol) → top 5 → audit score each (an agent the Almanac shows offline is dropped) → live test of the first 2 → pick.

- **Rules decide; AI only picks the topic.** The score, the fixes and every answer come from fixed rules and Agentverse data, so the same agent always gets the same score. A question the rules don't recognise goes to a small model (ASI:One `asi1-mini`) that only chooses which check, topic or explainer it is about, from fixed lists, or says it is off-topic. It never writes the answer, a number or a verdict. If it is off, slow (over 3.5 s) or failing, you get the rules answer.
- **Agents hiring agents.** Agent Doctor speaks the Agent Chat Protocol and its own `AgentDoctorPreHire` protocol. For a live test it messages the other agent over Agentverse, like any agent would, and times the reply.
- **Data used**: public Agentverse endpoints only (agent search, agent profile, Almanac registration and handles). No private data, no logins.
- **Privacy**: logs keep no message text, and sender IDs are hashed. A question the rules don't recognise is sent to the ASI:One API (Fetch.ai) with agent addresses, links, emails and long tokens removed, only to pick the topic; with it goes the text of the fix guide you last saw, if any, so "that step" can be understood. Nothing else is sent. Agent Scout sends your search words (not your message) to Agentverse search and keeps the last list per chat for 24 hours in memory, so `audit #2` works. To power fix guides, `why this score?` and the re-check diff, Agent Doctor stores the last agent audited or checked in a chat (24 hours) and the last score and pass/fail of each check per agent you checked (30 days, up to 20 agents). Keys are hashed; only public agent data (name, address, score, check results) is kept. Send `forget` to delete it.
- **Reliability**: an error gets a short "try again" reply, never silence or a crash. Rate limits and a loop guard stop runaway agent-to-agent loops (a conversation that keeps flooding is paused for 24 hours). Runs 24/7 on a dedicated server with a watchdog and one-step rollback.
- **Tested**: 1,458 automated tests, plus live checks on ASI:One.

## Use cases

- **Builders before launch**: run an agent audit before sharing your agent, fix the gaps, re-check.
- **Agents with no traffic**: wondering "why is my agent not getting interactions?" Send its address or handle to see why it gets no impressions or picks, and improve agent discoverability.
- **Agent not responding?** Ask `is my-weather-bot live?` (or just "my-weather-bot not responding"). One test message tells you LIVE, DEGRADED or UNREACHABLE, so you know whether to fix it or hire another agent.
- **Hackathon teams**: check the profile meets the Agentverse ranking basics before judging.
- **Hiring an agent**: ask Agent Scout for an agent by what it should do and get one that answered a live test, not just the first search hit.
- **Agencies and teams with many agents**: get a quick, consistent score for each one.
- **After every profile edit**: re-check to confirm the change landed (Agentverse can take a few minutes to update).

## Limitations

- **Scores the profile, not the agent's skills.** A single-agent audit of an active agent sends it one test message and reports the result next to the score, never in it; audits of several agents at once, and offline agents, are not messaged (unless Agentverse flags them "unresponsive": then the audit tests the first one to confirm or overturn the flag). Pre-Hire Check sends one on request. Either way: one short test message, at most once per agent every 10 minutes, with hourly limits. Agentverse counts conversations started by other agents in an agent's success rate, so a test message the agent ignores counts like any unanswered chat.
- **Pre-Hire Check tests availability, not answer quality.** LIVE means the agent answered within 14 seconds; it does not judge the answer. An agent that acknowledges but answers after 14s shows as DEGRADED; one that does not even acknowledge shows as UNREACHABLE.
- **Fix guides follow the last audit in the same chat.** `how do I fix #2` and `why this score?` need an audit earlier in that chat; it is kept for 24 hours, also across restarts. Guides follow the Agentverse docs; the Agentverse UI may change.
- **Findability is information, not score.** It uses Agentverse search; ASI:One may rank agents differently. Agents without usable starter prompts get no findability line. A search that is slow shows "not checked": re-check a minute later.
- **`re-check` remembers the last agent for 24 hours.** It uses the last agent audited or Pre-Hire checked in the same chat (right after an Agent Scout list, `audit it` asks which one; `audit the autonomad agent` picks it by name); `re-check`, `same agent` or `again` also reach your latest audit from an earlier chat. Naming it works too (`is that same tavily agent live?`): if the name doesn't match the agent I remember, I say so instead of guessing. To check a different agent, send its address or handle.
- **Re-check diff needs an earlier check.** It compares with your last complete check of the same agent in the past 30 days.
- **Follow-up questions about an agent's data need an audit in the same chat.** Questions about Agentverse words (Testing runs, real users, success rate…) work without one. A one-word message gets the standard reply. The model can pick the wrong check or explainer; the answer is then about that one, never invented facts. `explain step 2` follows the last fix guide in the chat.
- **No health or medical answers.** Agent Doctor checks AI agents, not people. Health and medicine questions get a fixed reply that points to a health professional (and to Agent Scout for health agents on Agentverse).
- **Website verification is optional.** Agentverse lists it as an "other signal", not a core ranking factor. A verified domain adds points; no domain costs nothing.
- **Weights are our estimate.** Agentverse does not publish its ranking weights. Score = points won / points possible, so checks with no data are left out. The rubric follows the official docs' emphasis; the same input always gives the same score.
- **Testing results: only what Agentverse shares.** Its public data often has no recent Testing result, even when the owner has runs in the Testing tab. A missing result is not scored (left out of the score), never shown as "not found". Same for any other check Agentverse has no data for.
- **Keywords are not checked yet.** Make sure each keyword appears in your README.
- **Mainnet only.** Testnet agents are not checked.
- **One agent per message.** Only the first agent in a message is audited.
- **No search by name.** Use the address, @handle or profile link. Agent Scout searches by what an agent does, not by its name.
- **Agent Scout tests at most 2 agents per search.** The others show "not tested": ask `is #3 live?`. The profile score is not answer quality. Results depend on Agentverse keyword search; few or exact words work best. Live tests pause for a while after many searches in a short time.
- **@handles in ASI:One**: mentioning another agent's @handle may route the message to that agent. Type the handle without @ (works for handles with a hyphen, like `my-weather-bot`, anywhere in the message), or use the address or profile link. A hyphenless handle needs the @ or the address. If a hyphenated word isn't a known handle, Agent Doctor answers the rest of the message instead.
- **Text only.** Images and files are not read.
- Results are cached for 5 minutes, and Agentverse itself can take a while to show profile changes.
- Agent Doctor is about Agentverse agents. It gives no medical advice.

## Metadata

- **Name**: Agent Doctor
- **Handle**: @agent-doctor
- **Address**: `agent1qwm50eahtwxe2jsjnqqgj3yqmcrpft3rkd42g8frh9twvdwugazfg3897tp`
- **Protocols**: Agent Chat Protocol 0.3.0, AgentDoctorPreHire 0.1.0
- **Data sources**: public Agentverse search and Almanac APIs
- **Privacy**: logs keep no message text; sender IDs are hashed; `forget` deletes stored audits
- **Price**: free
- **Version**: 0.14.0
- **Maintainer**: [leedr.tech](https://leedr.tech)
- **Built for**: Stranger Builds hackathon, Fetch.ai track

## Agent Doctor on TrueForge

The same Agent Doctor, rebuilt as a **self-improving agent on [TrueForge](https://trueforge.dev)** for the Stranger Builds TrueForge challenge. It checks one Agentverse listing snapshot, reports which Agent Doctor rubric rules fail, and rewrites the listing text (description, README, keywords, starter prompts). It scores itself on a fixed task set, rewrites its own skills and instructions from its failures, and runs again.

How it uses TrueForge:

- **Subagents:** for every listing, the root agent calls `create_sub_agent` twice: a `diagnose` subagent (which rules fail) and a `rewrite` subagent (new listing text). The root merges both into one JSON reply.
- **Git skills:** two TrueForge skills live in this repo, `agent/skills/profile-rubric` (the rubric) and `agent/skills/listing-rewrite` (how to write the listing). They are registered in `git` mode, pinned to the commit that runs, and read from the sandbox.
- **Sandbox:** skills need it; the agent also saves its rewrite there (`fixed/README.md`, `fixed/listing.json`).
- **SDK:** `scripts/*.ts` drive TrueForge through `@truefoundry/trueforge-sdk`: sync the agent, one session per eval run, export every session to `runs/`.

The eval: 6 synthetic listings in `evals/tasks/` (4 training, 2 holdout that `improve` never sees). Each task's expected findings are generated from Agent Doctor's own scorer (`agent/scorer.py`), never hand-written. `evals/score.ts` is deterministic: half diagnosis (rules caught, minus a penalty for rules that did not fail), half rewrite (README sections and length, description length, keywords that appear in the text, the owner's terms kept, starter prompts).

The skills **start short on purpose**: the agent grows them from the scorer's feedback. That is the point of the challenge.

## Run 1 vs run N

- **Task and score:** 6 fixed Agentverse listings (4 train, 2 holdout). Score = 50% diagnosis (the failing rule ids must match Agent Doctor's own production scorer, `agent/scorer.py`) + 50% rewrite (6 checks from the Agentverse README guidelines). Same tasks, same scorer, every run.
- **Run 1 → run N:** 51.44 → 97.81 → 99.17 (run 01 at `d7c4ab6`, run 02 at `b0bfd0a`, run 03 at `5fdb323`). Diagnosis 0.31 → 0.98, rewrite 0.72 → 1.00. Holdouts: 0.56 → 0.95 and 0.46 → 1.00. Tasks fully passed: 0/6 → 3/6 → 5/6.
- **The change that did it:** `5942593` (`Agent-Session` commit after run 01): the agent rewrote its two skills and its instructions with an explicit threshold per rubric rule, the 6 exact README headings, and keywords taken word-for-word from the text. Two rounds (`8f709e2`, `b0bfd0a`, learned from counted attempts that failed the gate) removed false findings and made the reply always end with the JSON block. The last round (`5fdb323`, from run 02) fixed a rule it had broken itself: count the whole README, headings included.
- **What the agent learned:** false findings cost score too. It added a step: for each finding, name the snapshot field and value that fails the rule, or drop it. And it corrected its own earlier README-length rule once the scorer flagged it.
- **What still fails:** one holdout task (05) is not fully passed: a short starter-prompt list is flagged where Doctor only fails an empty one. The agent never sees holdout feedback, so it can't learn this. Tokens grew about 2.3× (177.8k → 404.8k) and run time about 2.7× (170 s → 453 s). ASI:One sometimes returns HTTP 500 (hit 3 of 5 gate-failed run-02 attempts); since run 03 the harness retries such turns (none needed in run 03).

Four improve rounds in total, every one an `Agent-Session` commit that changes only `agent/` (plus, when learned from a counted run, that run's improve session export): `5942593` (from run 01), `8f709e2` and `b0bfd0a` (from two run-02 attempts that failed the evidence gate and were not counted), `5fdb323` (from run 02). `evals/` has not changed since run 01. The scorer is Agent Doctor's own production rubric plus the Agentverse README guidelines, so a higher score means a better Doctor, not a gamed metric — and the two holdout tasks improved as much as the training ones.

Retries: asi1 sometimes returns HTTP 500, and TrueForge 0.184.2 doesn't retry 500s. So `run-evals` re-runs a task when its turn dies on a provider 429/5xx error, at most twice, as ASI:One's docs advise. Retried turns stay in `session.json`, are listed in `results.json` `retried`, and are checked by the evidence gate. Bad or unparsed answers are never retried. Runs 01 and 02 ran before this change and had no retries.

## How to run

You need Node.js 22.18+, git, and a model on TrueForge. We use ASI:One (`asi1`) as an OpenAI-compatible custom provider.

1. Start TrueForge in its own terminal and keep it running: `npx @truefoundry/trueforge@<version>` (we pin server version 0.184.2; opens http://localhost:8790). Add your model under **Settings → Models**; the key stays in TrueForge, never in this repo.
2. Install and configure: `npm install`, then `cp .env.example .env` and set `TF_MODEL` (ours: `asi1/asi-1`) and `SKILL_REPO_URL` (this repo's public URL). TrueForge needs no secrets in `.env`: the Agent Doctor keys in `.env.example` can stay blank, and the model key lives only in TrueForge.
3. Create the agent: `npm run setup`.
4. Run the evals: `npm run run-evals` (one TrueForge session; saves `runs/run-NN/` and a row in `runs/summary.csv`). Skills are cloned at the commit that runs, so push first.
5. Let the agent improve itself: `npm run improve` (it rewrites `agent/` from its failed training tasks and commits with `Agent-Session: <id>`), review with `git show`, push, then `npm run run-evals` again.

Checks that need no model: `npm run score -- --selftest`, `npm run typecheck`.

## Credits

- TrueForge scripts, eval loop and repo layout are adapted from the TrueForge starter (`nerdconf/trueforge-starter` on GitHub, MIT). Its license is in `LICENSES/trueforge-starter-MIT.txt`.
- What existed before the TrueForge work: the Agent Doctor uAgent (the Python code in `agent/*.py`, `tests/`, `deploy/`), built since 2026-11-03 for the Fetch.ai track.
- New for TrueForge: `agent/agent.json`, `agent/instructions.md`, `agent/skills/`, `evals/`, `scripts/*.ts`, `runs/`.
