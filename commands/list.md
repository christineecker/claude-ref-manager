# /ref:list

Filterable browse/report over the paper library: metadata, source coverage,
lint issues, project/reading state, and a coverage matrix. Read-only, built
on the same `lib_inventory.rows()` every other view uses. No filters at all
lists every paper; a filter combination that matches nothing prints an
explicit "no papers matched" message rather than nothing.

Parse `$ARGUMENTS` for:

- `--source <badge,...>` — subset of `pdf-backed,full-text,oa-pending,abstract-only,metadata-only`
- `--has <key,...>` / `--missing <key,...>` — presence filters (ANDed),
  subset of `pdf,fulltext,claims,figures,notes`
- `--tier <abstract|full|unavailable>` — `meta.json.extraction_tier`
- `--year <YYYY|YYYY..YYYY>`
- `--journal <substring>` — case-insensitive
- `--retracted` — `retraction_status` is `retracted` or `erratum`
- `--stale-days <N>` — only papers whose `checked_at` is older than `N` days
- `--issue <lint-bucket>` — one of the buckets `/ref:lint` reports
- `--project <slug>`, `--reading-status <state>`, `--query <slug>`, `--from-file <path>` —
  reuse the shared selector grammar (`lib_selector.resolve()`); `--reading-status`
  requires `--project`, matching every other project-scoped state filter
- `--sort <year|added|title|checked|claims>`
- `--columns <col,...>` — projection for `table`/`csv`/`json`; run without it
  for the default column set
- `--format <table|csv|json|pmids>` — default `table`. `pmids` prints a bare
  space-separated PMID list with no other output, meant to be piped straight
  into `/ref:fetch` / `/ref:extract`
- `--matrix` — paper x `{meta, abstract, fulltext, pdf, figures, claims, indexed, retraction}`
  coverage grid instead of `--columns`

Steps:

1. Resolve the library root from `~/.config/ref-manager/config.json` (fail
   loudly, pointing at `/ref:init`, if unconfigured).
2. Print, then run:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/list.py" --repo <library_root> [flags above]
   ```

3. Print the script output verbatim.

Suggested follow-up:

- `/ref:list --format pmids <filters>` to build a PMID list for `/ref:fetch`
  or `/ref:extract`.
- `/ref:list --matrix` for a quick source/claims/indexing coverage overview.
