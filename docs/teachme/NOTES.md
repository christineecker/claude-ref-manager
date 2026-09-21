# Teaching notes

- User's mission: contribute to claude-ref-manager as OSS + learn general paper-repo/ref-manager maintenance concepts (not just this codebase). See MISSION.md.
- Session runs under caveman-mode chat responses, but lessons themselves are written as normal prose artifacts — caveman mode is a chat-tone thing, not a lesson-content thing.
- Ground lessons in this repo's real docs/code (docs/concepts.html, docs/workflows.html, commands/*.md, skills/ref-manager/scripts/*.py) rather than generic reference-manager theory — mission explicitly prefers this.
- Use `graphify query/path/explain` to orient before reading raw files (project convention, also faster).
- Watch out: graphify-out/ can lag a rename. It still indexed `commands/ref-weave.md`; after the 2026-09-18 rename commit the real path is `commands/weave.md`. If a graphify hit doesn't exist on disk, fall back to `find`/`grep` before concluding the concept moved.
