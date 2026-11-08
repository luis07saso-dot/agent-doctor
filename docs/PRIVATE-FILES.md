# Files referenced but not published

Some code comments and test docstrings point to files that stay private: planning notes
(`HYDRATE.md`, `SCOPE.md`, `ROADMAP.md`), raw third-party feedback (`FEEDBACK.md`), design specs
(`docs/specs/`), smoke-test logs (`docs/smoke-test.md`), VPS deploy scripts (`deploy/`, except the
log collector) and `scripts/metrics_exclude.json` (hashed sender IDs excluded from usage counts).
They hold working notes, third-party text, hosting details or outreach data.
The judge-facing summary of all of it is `docs/evidence.md`.
The test that reads `metrics_exclude.json` skips when the file is absent.
