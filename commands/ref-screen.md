Record a project-specific screening decision (§3b), feeding the §5c
`--screened included|excluded|pending` selector.

Parse `$ARGUMENTS` for:
- `--project <slug>` — required.
- `--pmid <pmid>` — required.
- `--decision included|excluded|pending` — required.
- `--reason "<text>"` — required.
- `--run <query-run-id>` — optional, links the decision to the saved search run it
  came from.

Steps:
1. Resolve the library root.
2. Print, then run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/screen.py" decide --repo <library_root> --project <slug> --pmid <pmid> --decision <decision> --reason "<text>" [--run <run-id>]
   ```
3. Print the script's own output verbatim. Screening a PMID that isn't yet a
   project member adds it as a member with no relevance note yet — screen first,
   annotate later is fine.
