Search the library (§5). Before phase 3 there is no full-text conversion and no
populated passage index, so "evidence" search here is title/abstract/journal only —
say this plainly if the user expects passage-level search.

Parse `$ARGUMENTS` for:
- `--scope evidence|notes|all` — default `evidence`.
- `--q "<text>"` — required, a substring query.

Steps:
1. Resolve the library root (fail loudly, pointing at `/ref:init`, if unconfigured).
2. Print, then run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/search.py" --repo <library_root> --scope <scope> --q "<text>"
   ```
3. Print the script's own output verbatim. With `--scope all`, each result is tagged
   `"kind": "evidence"`, `"personal_note"`, or `"project_relevance"` — never present a
   personal note or project relevance comment as a published finding (§5).
