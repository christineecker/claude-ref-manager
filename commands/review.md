Two independent modes, selected by whether `$ARGUMENTS` includes `--prisma`. If
`$ARGUMENTS` is neither `--prisma` nor a §5c selector, say so and stop rather than
guessing what else `/ref:review` might mean.

## `--prisma`

Render a [PRISMA 2020](https://www.prisma-statement.org/prisma-2020-flow-diagram)
flow record for one project's search — counts only, no appraisal.

Parse `$ARGUMENTS` for:
- `--project <slug>` — required.
- `--query <slug>` — the saved query (PLAN.md §5c/§5a) whose run history feeds this
  project's "identified" count. Repeatable. Optionally `--query <slug>:<run_id>` to
  pin one run rather than using the query's latest; omit `:run_id` to use the latest
  run. If you omit `--query`, the saved searches whose triage is linked to the
  project (`/ref:triage <slug> --project <project>`) are used, and the output's
  `query_source` says `linked_triages`. With no `--query` and no linked triage,
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
   committed state (`queries/*/query.yaml` run histories, `screening.jsonl`,
   `meta.json`'s `full_text` flag, `studies/studies.jsonl` if present) — nothing is
   re-run or estimated. `unresolved_query_specs` and `unevidenced_*` fields in the
   output name counts that have no committed evidence; these read `"unknown"`
   rather than being folded into the arithmetic to make it balance. `included.
   studies_count` and `included.publications_count` are reported separately —
   multiple publications can belong to one study, and the flow never collapses
   that distinction. On `--refresh`, print `included_added`/`included_removed`
   against the prior snapshot.

## Appraised synthesis (default mode, a §5c selector instead of `--prisma`)

GRADE-style certainty and per-paper risk-of-bias appraisal (RoB 2 for RCTs,
Newcastle-Ottawa for cohort/case-control, AMSTAR-2 for meta-analyses), plus
evidence tables (D15, phase 10). No LLM judgment is needed for this command —
`appraise.py` derives every domain rating deterministically from already-committed
claim fields (this is genuinely more limited than a human appraiser using the full
paper text, and the tool is honest about that: most domains the claim schema
doesn't capture land on `insufficient_information`, never a guessed rating).

Parse `$ARGUMENTS` for:
- a §5c selector (`<pmid...>`, `--project`, `--study`, `--search`, `--from-file`,
  etc.) — required, resolves the paper set to appraise.
- `--batch <label>` — required, names this saved review (frozen, reused unless
  `--refresh`, same idiom as `/ref:compare`/`/ref:summarize`).
- `--refresh` — re-resolve the selector and regenerate.

Steps:
1. Resolve the library root (fail loudly, pointing at `/ref:init`, if unconfigured).
2. Print, then run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/appraise.py" --repo <library_root> [selector args] --batch <label> [--refresh]
   ```
3. **If the result's `status` is `"refused"`** (the resolved set is wholly
   abstract-tier), relay the `reason` plainly and stop — do not attempt to
   construct an appraisal by hand from abstracts alone; full-text detail is what
   RoB2/NOS/AMSTAR-2/GRADE actually need.
4. Otherwise print the script's own output verbatim: per-PMID `appraisals` (each
   domain/item carries a `rating` or `stars_awarded`, the `claim_ids` backing it,
   a `note` explaining the signal or its absence, and a `review_status` of
   `model_draft` unless a human has already reviewed it via `/ref:verify
   review-appraisal`), and the set-level `grade` certainty rating with its
   baseline and each downgrading factor's `downgrade`/`not_assessed`/`reason`
   shown explicitly — never silently omitted. A paper whose own appraisal is
   `{"insufficient_information": true, ...}` (abstract-tier within an otherwise
   full-tier set) is reported as such, not silently dropped from the table.
   The same content is saved as `review.md` in the batch directory (the result's
   `markdown` path) — tell the user where it is.
5. Present every domain rating as a DRAFT — label it plainly as machine-derived.
   To record a human review decision on one domain (accept/edit/reject with a
   rationale), run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/verify.py" review-appraisal --repo <library_root> --pmid <pmid> --checklist <RoB2|Newcastle-Ottawa|AMSTAR-2> --domain-key <domain_or_item_key> --decision accept|edit|reject --reviewer <name> --rationale "<why>" [--replacement-file <path>]
   ```
   Re-running `/ref:review` for the same batch (with `--refresh`) picks up any
   recorded reviews and shows them as `human_confirmed`/`human_edited`/
   `human_rejected` instead of `model_draft`.
6. The set-level GRADE certainty rating has no per-PMID home to review through
   `/ref:verify` — it's a judgment about the whole appraised set, not one paper,
   and is persisted directly in the review artifact (`grade.json`), the same way
   phase 8's relation review lives on the relation record itself rather than in
   any single paper's `corrections.json`.
