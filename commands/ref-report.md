Generate a basic reproducible publication report for one researcher and date
window (§3c). No grant/lab grouping yet — that is a later, fuller `/ref:report`.

Parse `$ARGUMENTS` for:
- `--person <id>` — required.
- `--from <date> --to <date>` — required (year granularity at this phase).
- `--label <slug>` — optional; defaults to `<person>-<from>-<to>`.
- `--citations` — include PMC-indexed citing-article counts (D25, phase 11's
  `/ref:audit --citations` observations) alongside each publication.
  `--stale-days N` (default 180) controls when a count is flagged stale.

Steps:
1. Resolve the library root.
2. Print, then run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/report.py" --repo <library_root> --person <id> --from <date> --to <date> [--label <slug>] [--citations [--stale-days N]]
   ```
3. Print the script's own output verbatim, and point the user at
   `reports/<label>/publications.csv` and `report.md`. Re-running with the same
   inputs and no data changes reproduces identical report content.
   The exported rows now include provenance columns (`extraction_tier`,
   `abstract_available`, `full_text`, `checked_at`) so freshness/state travel
   with the report instead of living only in `meta.json`.
4. With `--citations`: every count is labeled with its source and retrieval
   date, and captioned "citing articles indexed in PMC; not a total citation
   count" — relay that caveat, never present the number as "citations."
   A publication with no observation on file shows `unknown`, never `0`.
   Citation data only exists if `/ref:audit --citations` has been run on
   these PMIDs at least once; if none has, every row will show `unknown`.
