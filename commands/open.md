Push an acquired PDF into Papers.app for reading and annotating (§7).

Parse `$ARGUMENTS` for:
- `<pmid>` — required.

Steps:
1. Resolve the library root from `~/.config/ref-manager/config.json` (fail
   loudly, pointing at `/ref:init`, if missing).
2. Print, then run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/open_in_papers.py" <pmid> --repo <library_root>
   ```
3. Print the script's output verbatim. If no PDF has been acquired yet
   (`status: no_pdf_acquired`), say so plainly and point at `/ref:fetch` or
   `/ref:attach` rather than treating it as an error.

This is the only ref-manager command that touches Papers.app itself — and
only via `open -a Papers <pdf>`, never the database.
