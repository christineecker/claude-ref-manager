Manually re-run a saved query's exact stored expression and append a new run (D9 —
explicit manual re-run only, never scheduled; §5c — prior runs are never mutated).

Parse `$ARGUMENTS` for:
- `<slug>` — required, an existing saved query.

Steps:
1. Resolve the library root.
2. Read the query's current expression:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/pubmed_query.py" show --repo <library_root> --slug <slug>
   ```
3. Call the PubMed MCP search tool with the exact `query` field from the most
   recent run — do not alter it.
4. Write the resulting PMIDs to a temp JSON file, then print and run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/pubmed_query.py" rerun --repo <library_root> --slug <slug> --pmids-file <temp-file>
   ```
5. Print the script's own output verbatim, including the added/removed PMIDs
   against the prior run.
