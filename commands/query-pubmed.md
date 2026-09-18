Parse a research question into a PubMed search, save the run immutably (D15),
and open the Triage tab so you can screen the results.

Parse `$ARGUMENTS` for:
- `<question text>` or an explicit PubMed query expression.
- `--slug <slug>` — required, names the saved query folder `queries/<slug>/`, which
  holds the query (`query.yaml`) and its triage files.
- `--create` — pass when this is the first run for a new slug.
- `--project <slug>` — optional, link the triage to an existing project so
  decisions also go into that project's screening log. A triage without a
  project is fine for plain topic searches; it can be linked later.
- `--no-triage` — save the run only; don't load metadata or open the dashboard.

Steps:
1. Resolve the library root.
2. If given a natural-language question, translate it into a PICO-framed boolean
   query (MeSH + free-text) yourself, using clinical/scientific judgment — this
   script does not call PubMed and does not parse PICO; it only persists what you
   give it. If given an explicit query expression, use it verbatim.
3. Call the PubMed MCP tool `mcp__claude_ai_PubMed__search_articles` with that
   exact query and collect **all** resulting PMIDs, preserving PubMed's order.
   The tool returns at most 200 per call (`max_results` ≤ 200): page with
   `retstart` = 0, 200, 400, … until `has_more` is false. If `total_count` is
   above 1,000, tell the user the count and ask before collecting more than the
   first 1,000.
4. Write the PMIDs to a temp JSON file (`["12345", "67890", ...]`), then print and
   run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/pubmed_query.py" new-run --repo <library_root> --slug <slug> --query-text "<exact query>" --source pubmed --pmids-file <temp-file> [--create]
   ```
   Print the script's own output verbatim. The saved run is immutable — a later
   `/ref:update-query <slug>` re-runs this exact stored expression (or one
   refined by explicit update terms), it does not re-derive a new one from the
   original question.
5. Unless `--no-triage` was passed:
   a. Print, then run (creates the triage, or reuses an existing one):
      ```
      python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/triage.py" init --repo <library_root> --slug <slug> [--project <project>]
      ```
   b. Load metadata for the first 100 PMIDs from NCBI E-utilities. Print, then run:
      ```
      python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/triage.py" load-batch --repo <library_root> --slug <slug>
      ```
      If it fails because no contact email is configured, relay the error — it
      names the `ncbi_email` key to add to `~/.config/ref-manager/config.json`.
   c. Print one summary line:
      `found: <N> · metadata loaded: <loaded> · remaining: <remaining> (load more from the Triage tab, or /ref:triage <slug> --more)`
   d. Start the dashboard on the Triage tab in the background (it blocks until
      stopped), then print the launch URL line it prints verbatim:
      ```
      python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/dashboard.py" serve --repo <library_root> --open --triage <slug>
      ```
      If a dashboard server from earlier in the session is still running, stop it
      first or tell the user to press the refresh button there instead.
