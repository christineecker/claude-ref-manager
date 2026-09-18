Manually update a saved query: re-run it, optionally with refined terms, and
append a new run (D9 — explicit manual re-run only, never scheduled; §5c —
prior runs are never mutated).

Parse `$ARGUMENTS` for:
- `<slug>` (or `--slug <slug>`) — required, an existing saved query.
- `<update terms>` — optional free text after the slug describing how to refine
  the query (e.g. `add fMRI`, `limit to 2020 onwards`, `drop the ASD[tiab] term`).

Steps:
1. Resolve the library root.
2. Read the query's current expression:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/pubmed_query.py" show --repo <library_root> --slug <slug>
   ```
   Print the `query` field from the most recent run.
3. If no update terms were given, ask with `AskUserQuestion` (header
   `Update`), showing the current query in the question:
   - **Enter update terms** — the user types the terms (via "Other"); continue
     to step 4 with them.
   - **Re-run unchanged** — skip step 4 and use the stored expression verbatim.
   - **Exit** — print `update-query: no changes, exiting` and stop. Nothing is
     searched or written.
4. With update terms: apply them to the stored expression, changing only what
   the terms ask for (same rules as `/ref:pubmed-query` for MeSH, `[tiab]`,
   `[dp]`, `[pt]`, `[au]`). Print the old and new expressions, then confirm with
   `AskUserQuestion` (**Run refined query** / **Edit terms** / **Exit**). Loop on
   **Edit terms**; stop on **Exit**.
5. Call the PubMed MCP search tool with the exact final expression. Collect all
   PMIDs, paging with `retstart` in steps of 200 as `/ref:query-pubmed` does.
6. Write the resulting PMIDs to a temp JSON file, then print and run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/pubmed_query.py" rerun --repo <library_root> --slug <slug> --pmids-file <temp-file> [--query-text "<refined expression>"]
   ```
   Pass `--query-text` only when the expression was refined; later updates
   start from it, since it is now the most recent run.
7. Print the script's own output verbatim, including the added/removed PMIDs
   against the prior run.
8. If `queries/<slug>/triage.json` exists (one triage per saved search), merge the
   new run into it. Print, then run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/triage.py" sync --repo <library_root> --slug <slug>
   ```
   - If `new_pmids` has 1–100 entries, load their metadata straight away: write
     them to a temp JSON file and run `triage.py load-batch --repo <library_root> --slug <slug> --pmids-file <temp-file>`.
   - If it has more than 100, tell the user the count and ask before loading the
     first 100 the same way.
   - Tell the user they show under **New since last run** in the Triage tab, and
     that decisions on PMIDs the new run dropped are kept (marked "not in latest run").

Notes:
- A refinement that changes the question's scope belongs in a new slug
  (`/ref:query-pubmed ... --slug <new-slug> --create`), so one saved query's
  run history stays comparable. Say so when the update terms change the
  population, intervention, or outcome rather than narrowing/widening them.
