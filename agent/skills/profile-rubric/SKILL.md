---
name: profile-rubric
description: Agent Doctor's rubric for an Agentverse profile. Use it on every snapshot, before you report any finding.
---

# Profile rubric

Report a rule id only when the snapshot shows it fails. Use these thresholds:

1. **active**: `status` is not `active`.
2. **chat_protocol**: `chat_protocol` is false.
3. **responsive**: `unresponsive` is true, or `status` is offline/inactive.
4. **readme_sections**: the README lacks any of the 6 sections: Summary, Key features, Usage, Use cases, Limitations, Metadata (as `##` headings).
5. **readme**: README is empty or only a line or two (even if it has sections).
6. **description**: description is empty, or under ~30 chars, or does not say what the agent does and for whom.
7. **rating**: `rating` is null or below 5.
8. **success_rate**: `recent_success_rate` is present and below 1.0.
9. **eval_rate**: `recent_eval_success_rate` is present and below 1.0.
10. **interactions**: `total_interactions` is below 10.
11. **handle**: `handle` is empty.
12. **avatar**: `avatar` is false.
13. **starter_prompts**: `starter_prompts` is empty or has fewer than 2.
14. **website**: `domain` is present but invalid; do not report when it is simply null.

Each finding = rule id + one short fix sentence. Never report a rule the snapshot passes.

<!-- Starts short on purpose: improve adds, sharpens or removes rules from the scorer's feedback. -->
