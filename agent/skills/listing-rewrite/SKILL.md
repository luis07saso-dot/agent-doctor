---
name: listing-rewrite
description: How to rewrite an Agentverse listing (README, description, keywords, starter prompts). Use it before you write any listing text.
---

# Listing rewrite

1. **Description**: one line saying what the agent does and for whom; 60-120 chars.
2. **README**: Markdown with exactly these 6 `##` sections, in order: Summary, Key features, Usage, Use cases, Limitations, Metadata.
   - Use these exact heading names; never swap in a synonym (`## Features` or `## How to use` are wrong), even if the old profile used one.
   - Summary: 2-3 sentences on what it does and for whom.
   - Key features: 3-5 bullets.
   - Usage: how to use, with one indented example exchange (indent each line 4 spaces; no code fences).
   - Use cases: who benefits and when.
   - Limitations: honest limits (input formats, scope, approximations).
   - Metadata: version, category, source of data if any.
   - At least ~300 characters of plain prose outside headings — aim for 400+ so the length check clears with margin; the README is the main search document.
   - Cover every capability in the owner's note; drop nothing. If the current profile is blank, write it all from the note.
3. **Keywords**: 4-6 short phrases users would type; each must appear word-for-word in the README or description. Build them from words already in the owner's note or your README — no invented compounds — then check each against the text before returning.
4. **Starter prompts**: 2-4 concrete questions a first-time user could send, each ending in "?", matching the README's examples.
5. **Self-check before returning**: all four fields filled; count the `##` lines — exactly 6, exact names, in order; every keyword found word-for-word; 2-4 question-form prompts; no triple backticks in any field (the rewrite travels inside a JSON string).
