# Files referenced but not published

Some code comments and specs point to planning files that stay private: `HYDRATE.md`, `SCOPE.md`,
`ROADMAP.md`, `FEEDBACK.md` (raw feedback, FB-1/FB-2), `docs/smoke-test.md` and
`scripts/metrics_exclude.json` (hashed sender IDs excluded from usage counts). They hold
working notes, raw third-party feedback and outreach data, so they are not in this repo.
The test that reads `metrics_exclude.json` skips when the file is absent.
