---
name: review-checklist
description: The checklist to run on every code review. Use it each time you review code, before you write any finding.
---

# Review checklist

Go through every item. For each one, look at every line where it could apply.

1. **Off-by-one.** Loops and slices: does the range include or skip the last element on purpose?
2. **Injection.** Is user input pasted into SQL, a shell command or HTML?
3. **Errors.** Is an error caught and then ignored?

<!--
This checklist is meant to start short. The improve step (npm run improve) asks the
agent to add, sharpen or remove items here based on what it missed in its last run.
-->
