Parse a research question into a PubMed search and save the run immutably (D15).

Parse `$ARGUMENTS` for:
- `<question text>` or an explicit PubMed query expression.
- `--slug <slug>` — required, names the saved query (`queries/<slug>.yaml`).
- `--create` — pass when this is the first run for a new slug.

Steps:
1. Resolve the library root.
2. If given a natural-language question, translate it into a PICO-framed boolean
   query (MeSH + free-text) yourself, using clinical/scientific judgment — this
   script does not call PubMed and does not parse PICO; it only persists what you
   give it. If given an explicit query expression, use it verbatim.
3. Call the PubMed MCP tool `mcp__claude_ai_PubMed__search_articles` (or
   equivalent) with that exact query and collect the resulting PMIDs.
4. Write the PMIDs to a temp JSON file (`["12345", "67890", ...]`), then print and
   run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/pubmed_query.py" new-run --repo <library_root> --slug <slug> --query-text "<exact query>" --source pubmed --pmids-file <temp-file> [--create]
   ```
5. Print the script's own output verbatim. The saved run is immutable — a later
   `/ref:update-queries <slug>` re-runs this exact stored expression, it does not
   re-derive a new one from the original question.
