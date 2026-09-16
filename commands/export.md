Export citations for a selected set of papers as BibTeX and CSL-JSON (D10, D14).

Parse `$ARGUMENTS` for the §5c selector — `<pmid...>`, `--project [--question]`,
`--screened`, `--read`/`--queue`, `--query [--run]`, `--search`, `--from-file`,
refined by `--tier`/`--exclude` — plus:
- `--batch <label>` — required. Names this export batch on disk
  (`exports/<label>/`). Re-running with the same label and no `--refresh` reuses the
  already-frozen resolution rather than re-resolving live. `--refresh` re-resolves
  and reports added/removed against the prior freeze.

Steps:
1. Resolve the library root (fail loudly, pointing at `/ref:init`, if unconfigured).
2. Print, then run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/export.py" --repo <library_root> --batch <label> [selector flags...] [--refresh]
   ```
3. Print the script's own output verbatim, including the resolved-set report (counts
   by extraction tier / human-verification state / retraction-errata status — the
   latter two read "not_yet_tracked" until phases 4 and 11 exist) and, on refresh,
   the added/removed PMIDs.
4. Point the user at `exports/<label>/references.bib` and `references.csl.json`.
