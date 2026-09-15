Retrieve protocols, instruments, controls, datasets, software/analysis
choices for a selected set of papers, per paper or grouped by recorded
study (PLAN.md §5a).

Parse `$ARGUMENTS` for the §5c selector (same grammar as `/ref:compare`).

Steps:
1. Resolve the library root (fail loudly, pointing at `/ref:init`, if unconfigured).
2. Run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/methods.py" --repo <library_root> [<pmid...>] [--project <slug>] [--study <id>] [...other selector flags]
   ```
3. Print the script's output verbatim.

Notes:
- `study_design`/`adjustment_context`/`cohort_identity` come from phase 4's
  claim extraction; `linked_methods`/`linked_datasets` come from explicit
  `/ref:study create-method`/`create-dataset` records. `instruments`,
  `software`, and `controls` are not covered by the current claim schema
  and always report `"not_reported"` — full protocol extraction is a later
  extension, not something this command reconstructs from context.
- An unstated method detail is `"not_reported"`, never inferred from what
  similar papers typically do.
