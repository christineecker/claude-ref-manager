Resolve and ingest one or more PMIDs (pipeline [1] RESOLVE + [2] DEDUP, PLAN.md §4). PMID
is the identity key (D11) — every paper resolves to a PMID before anything else happens.

Parse `$ARGUMENTS` for:
- `<pmid...>` — one or more PubMed IDs, required.

Steps:
1. Resolve the library root from `~/.config/ref-manager/config.json` (fail loudly,
   pointing at `/ref:init`, if it's missing).
2. Call the PubMed MCP tool `mcp__claude_ai_PubMed__get_article_metadata` with all the
   given PMIDs in one call.
3. For each returned article, normalize it into this envelope (this script does not call
   PubMed itself — it only consumes already-resolved JSON):
   ```json
   {
     "pmid": "<string>",
     "title": "<string>",
     "abstract": "<string, or null if none was returned>",
     "authors": [{"last": "<string>", "first": "<string>", "raw": "<string as PubMed gave it>"}],
     "journal": "<string or null>",
     "year": "<string or null>",
     "doi": "<string or null>",
     "pmcid": "<string or null>",
     "grants": [{"agency": "<string>", "grant_id": "<string>", "raw": "<string>"}]
   }
   ```
   Preserve author order exactly as PubMed returned it — this is the raw published order
   (§3c), not something to re-sort. If a PMID the tool returned nothing for, still include
   it as `{"pmid": "<id>", "title": "", "abstract": null, "authors": []}` so it's reported
   as a per-PMID failure rather than silently dropped.
4. Write the JSON array to a temp file, then print and run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/add.py" add --repo <library_root> --metadata-file <temp-file>
   ```
5. Print the script's own output verbatim — it reports one line per PMID
   (`added` / `already_present` / `failed`), each independent of the others (one paper's
   failure never blocks the rest). A paper with no abstract is still `added`, flagged as
   metadata-only — this is expected, not an error.

If the new record conflicts with an existing paper's DOI/title identity, the
script also emits warnings. Relay those warnings verbatim so the user can see
the mismatch before treating the record as settled.
