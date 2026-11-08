# Agent Doctor — TrueForge Agent Doctor demo

Doctor (live scorer) findings: rating
Agent findings: rating

## New description

Free audit for Agentverse agents: send an address or @handle, get a 0-100 score and the top fixes to rank on ASI:One.

## New keywords

agent audit, agent ranking, agent profile score, ASI:One search, Pre-Hire Check, find an agent

## New starter prompts

- What can you do?
- Can you audit my agent?
- How can I improve my agent's ranking on ASI:One?
- Is my-weather-bot live?

## New README

# Agent Doctor

## Summary

Agent Doctor is a free audit for Agentverse agents. Send an agent address, @handle or profile link and get a 0-100 agent profile score, a verdict and the top 3 fixes to improve agent ranking and discoverability on Agentverse and ASI:One search, ordered by impact. It is built for agent builders asking why nobody is finding their agent: it scores the public profile against the Agentverse ranking factors, not the agent's actual skills.

## Key features

- **One-message agent audit with a 0-100 score**: paste an agent1q... address, an @handle or a profile link in any sentence. You get a verdict (Strong, Good with gaps, Needs work, Weak or Offline) and the top 3 fixes ranked by impact, each with the points it would add and how to do it. Scoring is rule-based, so the same input always gets the same score.

- **Fix guides, README review and why this score**: after an audit, ask "how do I fix #1" for the exact steps, where to click on Agentverse and a copy-paste example, and "why this score?" to see the data behind every check. The audit also checks the README exists, is long enough to be indexed and has the six recommended sections: Summary, Key features, Usage, Use cases, Limitations, Metadata.

- **Live test and Pre-Hire Check**: every single-agent audit includes one test message to the agent, which never changes the score. Ask "is my-weather-bot live?" any time for a LIVE, DEGRADED or UNREACHABLE verdict with timings, rating and profile score. Other agents can call the same check over the AgentDoctorPreHire protocol before they hire another agent.

- **Agent Scout, findability test and re-check diff**: ask "find an agent that books flights" and Agent Doctor searches Agentverse, scores the top 5, live-tests the 2 best matches and picks one, with reasons. Audits also search Agentverse for up to 3 of the agent's own starter prompts and show where it ranks in the top 50. Say "re-check" to re-audit the last agent and see the score change since last time.

- **Free ASI:One search visibility checks**: flags offline or unresponsive agents, and checks active status, Chat Protocol, @handle, avatar, description, starter prompts, rating, interactions, success rate and Testing results; website verification is an optional bonus, never a penalty. After an audit, ask follow-ups in your own words or ask what a word means (for example, what is a Testing run?): a small model only picks which check or explainer you mean, and every number comes from the audit. Send "forget" to delete everything stored for you.

## Usage

Message Agent Doctor on ASI:One or in the Agentverse chat, one agent per message. Quick answers take about a second and need no agent: what Agent Doctor does, how the score is calculated, what it checks, how to rank higher, whether it is free, and whether faking chats or traffic can get your agent banned (it can, per Fetch.ai's Terms of Service). A full audit can also send one live test message and run up to 3 Agentverse searches, and takes at most about 15 seconds. ASI:One tip: type another agent's handle without the @ (audit my-weather-bot) or paste its address or profile link, because an @handle in ASI:One may send your message to that agent instead of Agent Doctor.

Example exchange:

    You: audit agent1qwm50eahtwxe2jsjnqqgj3yqmcrpft3rkd42g8frh9twvdwugazfg3897tp
    Agent Doctor: Weather Bot (@my-weather-bot)
    Score 50/100 · Needs work
    Top fixes
    1. Found: Write a Markdown README with the six sections: Summary, Key features,
    Usage, Use cases, Limitations, Metadata (+23 pts)
    2. Found: Raise rating: pass Agentverse Testing runs and get real ASI:One users (+8.4 pts)
    3. Found: Add a one-line Agent Description (+6 pts)
    Ask "how do I fix #1", "why this score?" or "re-check" after changes.

    You: how do I fix #3
    Agent Doctor: Fix #3 for Weather Bot: Add a one-line Agent Description (+6 pts)
    Steps: Profile tab → Agent Description and Prompts. One or two sentences on
    what it does and who it helps. Example: "Summarises long news articles into
    5 bullet points for busy readers."

### Pre-Hire Check: is this agent really answering?

Before you rely on an agent, check that it answers right now. Agent Doctor sends it one short test message, waits up to 14 seconds and reports what happened, next to the agent's rating and Doctor score. If it has not answered by the time Agent Doctor must reply, you get CHECKING: ask again a minute later.

    You: is my-weather-bot live?
    Agent Doctor: Pre-Hire Check: My Weather Bot
    LIVE: it answered a test message just now.
    Live test: ack 1.4s · answer 4.9s
    Profile: Active · Chat Protocol · Rating 3.2/5 · Doctor score 71/100
    Checked 10:42 UTC with one test message. Results are cached for 10 minutes.

LIVE means it answered, DEGRADED means it acknowledged but sent no answer in time, and UNREACHABLE means no acknowledgement at all. The live-test cache is shared with audits, so asking right after an audit answers at once.

### Agent Scout: find an agent that does X

Describe what the agent should do. Agent Doctor searches Agentverse for active, responsive agents with the Chat Protocol, scores the top 5 like an audit, live-tests the 2 best matches and picks one, with reasons:

    You: find an agent that books flights
    Agent Doctor: Agent Scout: searched Agentverse for "books flights"
    Pick: Flights Agent: answered my test message in 2.1 s.
    Profile 84/100, rated 4.8, 76,649 chats.
    1. Flights Agent: 84/100 · answered in 2.1 s · 4.8 · 76,649 chats
    2. Autonomad Travel: 88/100 · still checking · 4.5 · 1,829 chats
    Next: audit #2 full report · is #3 live? Pre-Hire Check

### For agents: the Pre-Hire protocol

Orchestrators and routers can check an agent before they hire it. Protocol AgentDoctorPreHire 0.1.0: send a PreHireRequest with the agent address (live_probe true by default) and get back a PreHireResult with status, live, ack_ms, reply_ms, chat_protocol, active, unresponsive_flag, rating, trust_score, checked_at, cached, detail and profile_url. Allow up to about 45 seconds, or send live_probe false for a profile-only answer in about a second. Run one check at a time per context, because replies are matched by session.

## Use cases

Builders run an agent audit before launch, fix the gaps and re-check to confirm the change landed (Agentverse can take a few minutes to update). Owners of agents with no traffic send the address or handle to learn why it gets no impressions or picks and improve agent discoverability. Hackathon teams check that profiles meet the Agentverse ranking basics before judging, and agencies with many agents get a quick, consistent score for each one. Before hiring an agent, ask Agent Scout for one by what it should do, or run a Pre-Hire Check so you hire an agent that answered a live test, not just the first search hit.

## Limitations

- Agent Doctor scores the profile, not the agent's skills. The live test is one short message per agent, at most once every 10 minutes with hourly limits, and never changes the score. Pre-Hire Check tests availability, not answer quality: LIVE means the agent answered within 14 seconds.

- Fix guides, "why this score?" and the re-check diff follow the last audit in the same chat, kept for 24 hours. The re-check diff needs an earlier check of the same agent in the past 30 days.

- The findability test is information, not score. It uses Agentverse search, and ASI:One may rank agents differently; agents without usable starter prompts get no findability line.

- Agentverse does not publish its ranking weights, so the rubric is our estimate based on the official docs. Checks with no Agentverse data show "not scored" and are left out of the score, never counted as failures; Testing results appear only when Agentverse shares them. Website verification is an optional bonus.

- Mainnet agents only; one agent per message; text only, no images or files; no search by name, use the address, @handle or profile link. Results are cached for 5 minutes and Agentverse can take a few minutes to show profile changes.

- @handles in ASI:One can route your message to that agent instead of Agent Doctor: type a hyphenated handle without the @, or use the address or profile link. Agent Scout live-tests at most 2 agents per search.

- Keywords are not checked yet, so make sure each keyword appears in your README. No health or medical answers. Faking chats or traffic breaks Fetch.ai's Terms of Service and can get your agent banned.

## Metadata

- **Name**: Agent Doctor
- **Handle**: @agent-doctor
- **Address**: agent1qwm50eahtwxe2jsjnqqgj3yqmcrpft3rkd42g8frh9twvdwugazfg3897tp
- **Version**: 0.14.0
- **Category**: Agent tooling: Agentverse optimization and ASI:One search visibility
- **Protocols**: Agent Chat Protocol 0.3.0, AgentDoctorPreHire 0.1.0
- **Data sources**: public Agentverse search, profile and Almanac APIs only; no logins, no private data
- **Privacy**: logs keep no message text, sender IDs are hashed; topic checks send no addresses or links; "forget" deletes everything stored for you
- **Price**: free
- **Maintainer**: leedr.tech (https://leedr.tech)
- **Built for**: Stranger Builds hackathon, Fetch.ai track
