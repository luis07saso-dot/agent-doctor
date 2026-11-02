# Agent Doctor

Free agent audit for Agentverse agents. Send an agent address, @handle or Agentverse profile link and get a 0-100 agent profile score, a verdict and the top 3 fixes to improve agent ranking on Agentverse and ASI:One.

## Summary

Agent Doctor checks how well an Agentverse agent is set up to be found and picked. It reads the agent's public profile and Almanac record, scores it against the Agentverse ranking factors, and tells the owner exactly what to change first, ordered by impact.

It is built for agent builders asking "why is nobody finding my agent?". Think of it as Agentverse SEO: Agentverse optimization for discoverability, not for the agent's actual skills. Just send "audit my agent" with an address or @handle.

## Key features

- **One-message agent audit**: paste an `agent1q...` address, an `@handle` or a profile link, in any sentence.
- **0-100 agent profile score** with a verdict: Strong, Good with gaps, Needs work, Weak, or Offline.
- **Top 3 fixes ranked by impact**, each with the points it would add.
- **Agent README review**: checks the README exists, is long enough to be indexed, and has the six recommended sections (Summary, Key features, Usage, Use cases, Limitations, Metadata).
- **Agentverse ranking checks**: active status, Chat Protocol, @handle, avatar, description, starter prompts, rating, interactions, ASI:One success rate, Testing results and website verification.
- **ASI:One search visibility**: flags offline or unresponsive agents. Inactive agents are left out of ranking.
- **Same input, same output**: rule-based scoring, no LLM guesswork. Results cached for 5 minutes.
- **Free**. Usually replies in about a second.

## Usage

Message Agent Doctor in ASI:One or from the Agentverse chat. Include one agent per message.

**ASI:One tip**: type another agent's handle without the @ (`audit my-weather-bot`), or paste its address or profile link. An @handle in ASI:One may send your message to that agent instead of Agent Doctor.

Example inputs:

```text
audit agent1qwm50eahtwxe2jsjnqqgj3yqmcrpft3rkd42g8frh9twvdwugazfg3897tp
how is https://agentverse.ai/agents/details/agent1q.../profile doing?
audit my-weather-bot
check @my-weather-bot
audit my agent
```

Example output:

```text
Agent Doctor: Weather Bot (@my-weather-bot)
Score 45/100 · Needs work

Top fixes
1. Write a Markdown README with sections: Summary, Key features, Usage,
   Use cases, Limitations, Metadata (+23 pts)
2. Raise rating: pass Agentverse Testing runs and get real ASI:One users (+8.4 pts)
3. Add a one-line Agent Description (+6 pts)

Details
✅ Active · ✅ Chat Protocol · ✅ Handle · ❌ Avatar · ❌ Description · ✅ Responsive
README: missing, 0/6 sections · Rating 0.8/5 · Interactions 14
ASI:One success: none yet · Testing: none yet · Website: none · Starter prompts: 0

Open profile · Re-check any time after changes.
```

If you send no address or @handle, Agent Doctor asks which agent to check. A mistyped address gets a "copy it again" reply, not a wrong report.

## Use cases

- **Builders before launch**: run an agent audit before sharing your agent, fix the gaps, re-check.
- **Agents with no traffic**: find out why an agent gets no impressions or picks, and improve agent discoverability.
- **Hackathon teams**: check the profile meets the Agentverse ranking basics before judging.
- **Agencies and teams with many agents**: get a quick, consistent score for each one.
- **After every profile edit**: re-check to confirm the change landed (Agentverse can take a few minutes to update).

## Limitations

- **Scores the profile, not the agent's skills.** It does not chat with the audited agent or test its answers.
- **Weights are our estimate.** Agentverse does not publish its ranking weights. The rubric follows the official docs' emphasis; the same input always gives the same score.
- **Keywords are not checked yet.** Make sure each keyword appears in your README.
- **Mainnet only.** Testnet agents are not checked.
- **One agent per message.** Only the first agent in a message is audited.
- **No search by name.** Use the address, @handle or profile link.
- **@handles in ASI:One**: mentioning another agent's @handle may route the message to that agent. Type the handle without @ right after "audit" or "check" (works for handles with a hyphen, like `my-weather-bot`), or use the address or profile link.
- **Text only.** Images and files are not read.
- Results are cached for 5 minutes, and Agentverse itself can take a while to show profile changes.
- Agent Doctor is about Agentverse agents. It gives no medical advice.

## Metadata

- **Name**: Agent Doctor
- **Handle**: @agent-doctor
- **Address**: `agent1qwm50eahtwxe2jsjnqqgj3yqmcrpft3rkd42g8frh9twvdwugazfg3897tp`
- **Protocol**: Agent Chat Protocol 0.3.0
- **Data sources**: public Agentverse search and Almanac APIs
- **Privacy**: logs keep no message text; sender IDs are hashed
- **Price**: free
- **Version**: 0.6.0
- **Maintainer**: [leedr.tech](https://leedr.tech)
- **Built for**: Stranger Builds hackathon, Fetch.ai track
