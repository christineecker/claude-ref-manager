Translate a research prompt into a PubMed query, run the search, save the run,
then add and fetch a bounded set of results.

Parse `$ARGUMENTS` for:
- `<question or PICO>` — required. Can also be an explicit PubMed query.
- `--slug <slug>` — required. Names the saved search run under
  `queries/<slug>/query.yaml`.
- `--create` — pass for the first run of a new slug.
- `--limit <N>` — optional cap on PMIDs to ingest. Default `20`. Refuse values
  above `100` unless the user explicitly confirms.
- `--broad` / `--specific` — query-construction bias, same meaning as
  `/ref:pubmed-query`.

Steps:
1. Resolve the library root (fail loudly, pointing at `/ref:init`, if
   unconfigured).
2. Build the exact PubMed query:
   - If the input is already an explicit PubMed expression, use it verbatim.
   - Otherwise translate the prompt/PICO as `/ref:pubmed-query` would.
3. Call PubMed MCP `search_articles` with that exact query. Preserve the
   returned PMID order.
4. Save the complete search run before ingesting:
   a. Write all returned PMIDs to a temp JSON file.
   b. Print and run:
      ```
      python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/pubmed_query.py" new-run --repo <library_root> --slug <slug> --query-text "<exact query>" --source pubmed --pmids-file <temp-file> [--create]
      ```
5. Select the first `N` PMIDs from the returned list, where `N` is `--limit`
   or the default `20`. Print the total found and selected count.
6. Add selected PMIDs using the same `/ref:add` workflow:
   a. Call PubMed MCP `get_article_metadata` once for selected PMIDs.
   b. Normalize each article into the standard add envelope.
   c. Run:
      ```
      python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/add.py" add --repo <library_root> --metadata-file <temp-file>
      ```
7. Fetch full text for selected PMIDs that have `papers/<pmid>/meta.json` after
   the add stage, using the same `/ref:fetch` priority ladder:
   PMC E-utilities JATS, PubMed MCP plain text, Unpaywall, publisher HTML,
   otherwise abstract-only.
8. Run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/fetch.py" --repo <library_root> --input-file <temp-file>
   ```
9. Print all stage output verbatim under headers:
   ```text
   search:
   query: ...
   found: <all_pmids_count>
   selected: <N>

   save-run:
   ...

   add:
   ...

   fetch:
   ...
   ```

Safety:
- Default `--limit 20` prevents accidental ingestion of very large searches.
- The full search run is saved before limiting, so the search remains
  reproducible even when only the first results are ingested.
- PMID remains the identity key. DOI/title never merge records.
- One PMID's add/fetch failure must not block the rest.
