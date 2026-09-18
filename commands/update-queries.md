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
   recent run — do not alter it. Collect all PMIDs, paging with `retstart` in
   steps of 200 as `/ref:search-pubmed` does.
4. Write the resulting PMIDs to a temp JSON file, then print and run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/pubmed_query.py" rerun --repo <library_root> --slug <slug> --pmids-file <temp-file>
   ```
5. Print the script's own output verbatim, including the added/removed PMIDs
   against the prior run.
6. If `triage/<slug>/triage.json` exists (one triage per saved search), merge the
   new run into it. Print, then run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/triage.py" sync --repo <library_root> --slug <slug>
   ```
   - If `new_pmids` has 1–100 entries, load their metadata straight away: write
     them to a temp JSON file and run `triage.py load-batch --repo <library_root> --slug <slug> --pmids-file <temp-file>`.
   - If it has more than 100, tell the user the count and ask before loading the
     first 100 the same way.
   - Tell the user they show under **New since last run** in the Queries section, and
     that decisions on PMIDs the new run dropped are kept (marked "not in latest run").
