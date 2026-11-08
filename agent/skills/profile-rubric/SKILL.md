---
name: profile-rubric
description: Agent Doctor's rubric for an Agentverse profile. Use it on every snapshot, before you report any finding.
---

# Profile rubric

Report a rule id only when the snapshot shows it fails. Check every rule on every snapshot:

1. **active**: `status` is not `active`.
2. **chat_protocol**: `chat_protocol` is false.
3. **responsive**: `unresponsive` is true, or `status` is offline/inactive.
4. **readme_sections**: the README lacks any of the 6 sections: Summary, Key features, Usage, Use cases, Limitations, Metadata (as `##` headings). An empty or missing README lacks all 6, so it fails here too.
5. **readme**: README is empty, or has under ~300 characters of plain text outside headings — even if all sections exist.
6. **description**: description is empty, or under ~30 chars, or does not say what the agent does and for whom.
7. **rating**: `rating` is a number below 5. A null or missing rating is not a finding (a new agent has none yet).
8. **success_rate**: `recent_success_rate` is present and below 1.0.
9. **eval_rate**: `recent_eval_success_rate` is present and below 1.0.
10. **interactions**: `total_interactions` is below 10.
11. **handle**: `handle` is empty.
12. **avatar**: `avatar` is false.
13. **starter_prompts**: `starter_prompts` is empty or has fewer than 2.
14. **website**: `domain` is present but not a plausible hostname (no dot, spaces, junk); judge the shape, not whether you recognise the TLD; null is never a finding.

Each finding = rule id + one short fix sentence. Report every rule the snapshot fails — including non-text ones (rating, avatar) whose fix is a console action — and never a rule it passes. An empty README fails both `readme` and `readme_sections`.

<!-- Starts short on purpose: improve adds, sharpens or removes rules from the scorer's feedback. -->
