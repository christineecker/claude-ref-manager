Find structural gaps in the graph over a selected set of papers (PLAN.md §5b): fragile
single-study claims, unresolved conflicts, ungrouped co-mentions, and population/outcome
coverage gaps for one intervention. Purely deterministic — no LLM judgment, unlike
`/ref:extract`/`/ref:ask`/`/ref:weave`.

Parse `$ARGUMENTS` for:
- a §5c selector (`--project`, `--study`, `--search`, `--from-file`, or a bare `<pmid...>`
  list) — required, same as every other set-valued command.
- `--intervention-concept <slug>` — required only for the population/outcome query; omit
  to skip that query. Populations/outcomes that exactly match (case-insensitively) a
  concept's name or alias are grouped under that concept's name; other values are kept
  as written, and placeholders like "unknown"/"not reported" are ignored.
- `--types <type...>` — restrict to specific gap types (`single_study_fragile`,
  `unresolved_conflicts`, `co_mentioned_ungrouped`, `population_outcome_gap`); default
  runs all applicable to the given arguments.

Steps:
1. Resolve the library root (fail loudly, pointing at `/ref:init`, if unconfigured).
2. Print, then run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/gaps.py" --repo <library_root> <selector...> [--intervention-concept <slug>] [--types <type...>]
   ```
3. Print the script's own output verbatim, grouped by gap type. Every finding cites the
   specific `claim_id`/`relation_id`/`pmid` it rests on — never present a gap as an
   unevidenced summary. Missing edges describe this library's coverage, not an
   established gap in the literature (§5b) — say so when presenting results.
