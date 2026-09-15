Currently supports only `--prisma` (PLAN.md §5a: "`--prisma` is a separate mode
reporting the search itself rather than the papers"). Appraised synthesis
(GRADE certainty, risk-of-bias) is phase 10 and not implemented yet — if
`$ARGUMENTS` doesn't include `--prisma`, say so and stop rather than guessing
what else `/ref:review` might mean.

## `--prisma`

Render a [PRISMA 2020](https://www.prisma-statement.org/prisma-2020-flow-diagram)
flow record for one project's search — counts only, no appraisal.

Parse `$ARGUMENTS` for:
- `--project <slug>` — required.
- `--query <slug>` — the saved query (PLAN.md §5c/§5a) whose run history feeds this
  project's "identified" count. Repeatable. Optionally `--query <slug>:<run_id>` to
  pin one run rather than using the query's latest; omit `:run_id` to use the latest
  run. **PLAN.md does not specify how a project associates its saved queries** —
  `project.yaml` has no such field — so this command takes them explicitly on each
  invocation rather than assuming an implicit link. If you omit `--query` entirely,
  the identified/duplicates-removed counts are reported as `"unknown"`, not zero —
  every other section (screening, sought/retrieved, included) still renders from
  what's committed.
- `--refresh` — re-derive the flow from current state instead of reusing the frozen
  snapshot. Without it, a repeat call reuses the last snapshot verbatim.

Steps:
1. Resolve the library root (fail loudly, pointing at `/ref:init`, if unconfigured).
2. Print, then run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/prisma.py" --repo <library_root> --project <slug> [--query <slug>[:<run_id>] ...] [--refresh]
   ```
3. Print the script's own output verbatim. Every count is a query over already-
   committed state (`queries/*.yaml` run histories, `screening.jsonl`,
   `meta.json`'s `full_text` flag, `studies/studies.jsonl` if present) — nothing is
   re-run or estimated. `unresolved_query_specs` and `unevidenced_*` fields in the
   output name counts that have no committed evidence; these read `"unknown"`
   rather than being folded into the arithmetic to make it balance. `included.
   studies_count` and `included.publications_count` are reported separately —
   multiple publications can belong to one study, and the flow never collapses
   that distinction. On `--refresh`, print `included_added`/`included_removed`
   against the prior snapshot.
