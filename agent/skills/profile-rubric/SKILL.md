---
name: profile-rubric
description: Agent Doctor's rubric for an Agentverse profile. Use it on every snapshot, before you report any finding.
---

# Profile rubric

Report a rule id only when the snapshot clearly fails it. Judge every rule on every snapshot; each rule names the field it reads:

1. **active**: `status` is not `active`.
2. **chat_protocol**: `chat_protocol` is false.
3. **responsive**: `unresponsive` is true, or `status` is offline/inactive.
4. **readme_sections**: the README lacks any of the 6 sections: Summary, Key features, Usage, Use cases, Limitations, Metadata (as `##` headings). An empty or missing README lacks all 6, so it fails here too.
5. **readme**: README is empty or near-empty — hardly more text than headings, well under ~300 characters in total (count headings too). A short but real README passes even though it is brief, and a count near the threshold passes; it still fails here even when all 6 sections exist, if there is almost no text.
6. **description**: empty, under ~30 chars, or does not say what the agent does. A clear what-it-does line passes even when it names no audience; a missing "for whom" alone is never a finding.
7. **rating**: `rating` is a number below 5. Null or missing passes (a new agent has none yet).
8. **success_rate**: `recent_success_rate` is a number below 1.0. Null or missing passes.
9. **eval_rate**: `recent_eval_success_rate` is a number below 1.0. Null or missing passes.
10. **interactions**: `total_interactions` is a number below 10. Null or missing passes.
11. **handle**: `handle` is empty or missing.
12. **avatar**: `avatar` is false.
13. **starter_prompts**: `starter_prompts` is missing or has fewer than 2 items; exactly 2 passes.
14. **website**: `domain` is a non-null string that is not a plausible hostname (no dot, spaces, junk); judge the shape, not whether you recognise the TLD; null or missing is never a finding.

Discipline:

- For every candidate finding, name the snapshot field and value that fails the rule; if you cannot, drop it.
- Borderline values pass: a count or number near a rule's threshold is a pass, not a finding.
- Report only clear failures — a short but clear description, plain wording, or a missing audience is a pass.
- An empty or near-empty README fails both `readme` and `readme_sections`.
- Never skip the field rules: responsive, handle, avatar, rating, success_rate, eval_rate, interactions are findings even though the fix is a console action.
- Return every failing rule id and never a passing one.

Each finding = rule id + one short fix sentence.
