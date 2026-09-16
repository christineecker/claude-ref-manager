# Maintenance Feature Implementation Plan

## Goals

- Add a first-class maintenance loop for paper repositories.
- Detect incomplete paper records early.
- Keep search/index/retraction state trustworthy.
- Make maintenance workflows tutorial-first and reproducible.

## Existing Maintenance Tools (current)

- `/ref:status`: health summary and next actions.
- `/ref:index --rebuild`: rebuilds catalog projection and relation staleness refresh.
- `/ref:audit`: retraction/errata checks; citation observation plumbing.
- `/ref:open`, `/ref:pull-annotations`: reading workflow maintenance.
- `/ref:verify`, `/ref:queue`, `/ref:check-citations`: quality control overlays.

## Gaps Identified (original, now closed — see Phase 4)

- No dedicated lint command for incomplete/fragile paper records.
- No single report listing PMIDs by maintenance issue class.
- ~~Bib/CSL intake parsing still unimplemented in shared intake classification.~~ closed Phase 4.
- ~~Citation-count audit mode lacks a wired real cited-by source.~~ closed Phase 4.

## New Tooling Introduced (this iteration)

- `/ref:lint`
  - Backed by `skills/ref-manager/scripts/lint.py`.
  - Read-only repo lint report with issue buckets:
    - missing metadata fields
    - metadata-only / abstract-only / OA-pending
    - missing current version pointer
    - missing claim registry
    - stale status checks
    - index presence signal
  - Emits actionable follow-up command suggestions.

## Proposed Tool Set (next)

- `/ref:maintain` (orchestration wrapper)
  - Run: status -> lint -> index -> audit -> summary.
  - Optional flags: `--fix-index`, `--audit`, `--json`.
- `/ref:repair-fulltext`
  - Consume lint buckets (`metadata_only`, `abstract_only`, `oa_pending`) and run bounded fetch/add-fetch batches.
- `/ref:lint --format table|json|markdown`
  - Add machine-readable output mode for CI and reports.
- `/ref:audit --since <days>`
  - Restrict re-check to stale records first.

## Implementation Phases

### Phase 1 (done)

- Add `/ref:lint` command spec.
- Add `lint.py` script.
- Add maintenance tutorial page with diagram-first flow.

### Phase 2 (done)

- Integrate `/ref:lint` into docs command reference pages.
- Add `/ref:maintain` command with non-destructive default.
- Add PMIDs-per-issue export option (`--json`) for scripting.

### Phase 3 (done)

- [done] Add structured maintenance snapshots under `maintenance/` with
  timestamps (`lint.py --snapshot`, wired as default in `/ref:maintain`'s
  lint stage).
- [done] Add regression checks for lint output shape and status transitions
  (`skills/ref-manager/scripts/tests/test_lint.py`).
- [done] Add auto-batching for repair commands (`--limit`, resume-safe
  behavior): `/ref:repair-fulltext` consumes `metadata_only`/
  `abstract_only`/`oa_pending` lint buckets, tracks attempts in
  `maintenance/repair-fulltext-state.json`, and skips recently-attempted
  PMIDs unless `--retry-failed`.

### Phase 4 (done)

- [done] Implement bibliography-file parsing for `.bib` and `.csl.json` in
  intake: `skills/ref-manager/scripts/lib_bibparse.py` (stdlib-only,
  brace-aware BibTeX parser + CSL-JSON parser), wired into
  `lib_intake.py`'s `classify_item`/`classify_all` so a `.bib`/`.csl.json`
  file expands into one `bib_entry`/`csl_entry` result per record (same
  pattern as `pdf_dir` expanding into `pdf` items), each carrying whatever
  `doi`/`pmid`/`title`/`year`/`journal` clues it found. `/ref:import`
  resolves each entry the same way it resolves a URL/PDF clue.
- [done] Wire a real citation-count backend for `/ref:audit --citations`:
  NCBI E-utilities ELink (`dbfrom=pmc&linkname=pmc_pmc_citedby`) called
  directly over WebFetch, since no PubMed MCP tool exposes a citation-graph
  count. Coverage is PMC-only (undercounts total literature citations) —
  documented as such everywhere the count is shown, never presented as a
  total.
- [done] Add scheduled maintenance profile docs (weekly/monthly/quarterly)
  — `docs/tutorials/maintenance.html` "Suggested cadence" section.

## Tutorial/Docs Plan

- Add `docs/tutorials/maintenance.html` (diagram-first, minimal text).
- Add Tutorials index card linking to maintenance tutorial.
- Add command reference entry for `/ref:lint` in maintain section.

## Acceptance Criteria

- User can run one command to identify incomplete papers by PMID.
- User can map each lint bucket to a concrete follow-up command.
- Maintenance tutorial shows complete loop visually with minimal prose.
- No maintenance command silently mutates history without explicit action.

## Risks

- False positives for missing fields on legitimately sparse PubMed entries.
- Over-triggering stale checks if timestamp semantics differ across commands.
- User confusion between metadata completeness and evidence quality.

## Mitigations

- Keep lint read-only and transparent.
- Include issue counts and PMIDs in every report.
- Pair each issue bucket with recommended command-level remediation.
- Keep `/ref:audit` as explicit re-check gate.
