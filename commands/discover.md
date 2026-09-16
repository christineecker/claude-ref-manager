Run a manually initiated portfolio-discovery search for a researcher (§3c).

Parse `$ARGUMENTS` for:
- `--person <id>` — required (person slug). `--grant <id>` is not implemented in
  phase 2 — say so and stop if given.

Steps:
1. Resolve the library root.
2. Read the person record (`/ref:person show --slug <id>` equivalent:
   `python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/person.py" show --repo <library_root> --slug <id>`)
   and build a PubMed author-search query from their name variants (and ORCID, if
   present).
3. Call the PubMed MCP search tool with that exact query.
4. Write the candidate articles (at least `pmid`, `title`) to a temp JSON file,
   then print and run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/discover.py" --repo <library_root> --person <id> --query-text "<exact query>" --candidates-file <temp-file>
   ```
5. Print the script's own output verbatim. Candidates require explicit
   confirmation (`/ref:person confirm-publication`) before they count as this
   person's publications — do not treat a candidate as confirmed.
