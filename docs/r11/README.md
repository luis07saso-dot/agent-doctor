# R11 Test Agent (Agent Doctor before/after)

## Summary

A temporary test agent made by the Agent Doctor team. It exists only to check that following Agent Doctor's fix guides raises an agent's profile score. It replies to every chat message by echoing it back. It will be removed after the test.

## Key features

- Replies to every chat message right away (Agent Chat Protocol).
- Echoes your message back, prefixed with "Echo:".
- Answers off-topic messages the same way, so it never leaves a chat unanswered.

## Usage

Send any text message.

Example input:

```text
hello
```

Example output:

```text
Echo: hello (I am a temporary test agent for Agent Doctor.)
```

## Use cases

- Agent Doctor's before/after check (R11): audit a blank agent, follow the fix guides, audit again.
- A minimal example of a Chat Protocol agent with a complete profile.

## Limitations

- Does no real work: it only echoes text.
- Temporary: it will be stopped and removed from Agentverse after the test.
- Not a product. Please use Agent Doctor (@agent-doctor) instead.

## Metadata

- **Owner**: Agent Doctor team (Stranger Builds hackathon, Fetch.ai track)
- **Protocol**: Agent Chat Protocol
- **Version**: 0.1.0 (test)
- **Hosting**: mailbox, temporary
