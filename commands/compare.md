Build an evidence matrix over a selected set of papers (PLAN.md §5a, §5c).
Columns: population/model, design, methods, sample size, comparator,
results, uncertainty, limitations, relevance to the question. Cells link to
the claims backing them, or state explicitly why a value is missing.

Parse `$ARGUMENTS` for the §5c selector (`<pmid...>`, `--project`
[`--question`], `--screened`, `--read`/`--queue`, `--query` [`--run`],
`--study`, `--search`, `--from-file`, refined by `--tier`/`--exclude`) plus:
- `--batch <label>` — required. Identifies this table; re-running without
  `--refresh` reuses the frozen resolution (§5c: "a saved comparison never
  silently changes membership underneath its conclusions").
- `--refresh` — re-resolve the selector and report added/removed papers.
- `--edit <pmid> <column> <value>` — record a user override for one cell.
  Survives a later `--refresh` if that cell's underlying evidence hasn't
  changed; flagged `stale` (not silently discarded or silently reapplied)
  if it has.

Steps:
1. Resolve the library root (fail loudly, pointing at `/ref:init`, if unconfigured).
2. Run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/compare.py" --repo <library_root> [<pmid...>] [--project <slug>] [--study <id>] [...other selector flags] --batch <label> [--refresh]
   ```
   To edit a cell:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/compare.py" --repo <library_root> --batch <label> [--project <slug>] --edit-pmid <pmid> --edit-column <column> --edit-value "<text>"
   ```
3. Print the script's output verbatim.

Notes:
- A cell's value is `"not_extracted"` when no claim covers that dimension
  for this paper at all (including columns the extractor never captures,
  like sample size and limitations — those stay `not_extracted` until a
  later phase adds that extraction, never guessed). It's `"not_reported"`
  when a claim exists but its normalized field is the extractor's own
  explicit "unknown" — these are deliberately different states, don't
  collapse them when presenting the table.
- Each row also carries a `provenance` block keyed by PMID with paper-state
  metadata such as extraction tier, last checked timestamp, and whether the
  record currently has abstract/full-text material available.
- Papers sharing a recorded study (`/ref:study create-study`) group into
  one row; papers merely sharing a dataset do not. An uncertain-confidence
  study grouping is shown as uncertain, not presented as equally solid as a
  confirmed one.
- A bare PMID list and an equivalent `--project` selector produce the same
  table for the same resolved papers — the selector syntax used to build a
  batch is recorded in the manifest, but never changes the table content
  itself.
- The table is saved under `projects/<slug>/tables/<batch>/` when built
  with `--project`, else `tables/<batch>/` at the library root.
