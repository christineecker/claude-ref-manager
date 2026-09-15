Generate a basic reproducible publication report for one researcher and date
window (§3c). No grant/lab grouping yet — that is a later, fuller `/ref:report`.

Parse `$ARGUMENTS` for:
- `--person <id>` — required.
- `--from <date> --to <date>` — required (year granularity at this phase).
- `--label <slug>` — optional; defaults to `<person>-<from>-<to>`.

Steps:
1. Resolve the library root.
2. Print, then run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/report.py" --repo <library_root> --person <id> --from <date> --to <date> [--label <slug>]
   ```
3. Print the script's own output verbatim, and point the user at
   `reports/<label>/publications.csv` and `report.md`. Re-running with the same
   inputs and no data changes reproduces identical report content.
