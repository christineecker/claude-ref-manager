# /ref:search

Search the library (§5). Before phase 3 there is no full-text conversion and no
populated passage index, so `evidence` search here is still metadata-only, but it
now matches title, abstract, journal, DOI, PMCID, citekey, author names, grant
metadata, and saved-query context where present. Say this plainly if the user
expects passage-level search.

Parse `$ARGUMENTS` for:

- `--scope evidence|notes|all` - default `evidence`.
- `--q "<text>"` - required, a substring query.

Steps:

1. Resolve the library root (fail loudly, pointing at `/ref:init`, if unconfigured).
2. Print, then run:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/search.py" --repo <library_root> --scope <scope> --q "<text>"
   ```

3. Print the script's own output verbatim. With `--scope all`, each result is tagged
   `"kind": "evidence"`, `"personal_note"`, `"project_relevance"`, or `"saved_query"` -
   never present a personal note or project relevance comment as a published finding (§5).
   Evidence hits now also report which structured field matched and a lifecycle
   state (`metadata-only`, `abstract-only`, `full-text`, `pdf-backed`, or
   `oa-pending`) when available.
