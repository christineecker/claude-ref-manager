Resolve and ingest one or more PMIDs, then immediately try to acquire full
text for every PMID that now has a library record. This is a convenience
wrapper around `/ref:add` followed by `/ref:fetch`; it must not replace either
command's underlying contract.

Parse `$ARGUMENTS` for:
- `<pmid...>` — one or more PubMed IDs, required. PMID remains the identity
  key. This wrapper creates missing records with `/ref:add` semantics, then
  augments existing/added records with `/ref:fetch` semantics.

Steps:
1. Resolve the library root from `~/.config/ref-manager/config.json` (fail
   loudly, pointing at `/ref:init`, if it's missing).
2. Run the `/ref:add` workflow for all requested PMIDs:
   a. Call the PubMed MCP tool `mcp__claude_ai_PubMed__get_article_metadata`
      with all given PMIDs in one call.
   b. Normalize each returned article into the same envelope used by
      `/ref:add`:
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
      Preserve author order exactly as PubMed returned it. If the PubMed MCP
      tool returned nothing for a PMID, still include it as
      `{"pmid": "<id>", "title": "", "abstract": null, "authors": []}` so it
      is reported as a per-PMID failure rather than silently dropped.
   c. Write the JSON array to a temp file, then print and run:
      ```
      python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/add.py" add --repo <library_root> --metadata-file <temp-file>
      ```
   d. Print the script's own output verbatim. This is the `add:` stage and
      reports `added` / `already_present` / `failed`, one line per PMID.
3. Determine which requested PMIDs should continue to fetch:
   - Include every requested PMID for which `papers/<pmid>/meta.json` exists
     after step 2, whether the add stage reported `added` or `already_present`.
   - Exclude PMIDs with no `meta.json`; they failed to add and `/ref:fetch`
     would only repeat `run /ref:add first`.
   - If no PMIDs remain, stop after printing the add output.
4. Run the `/ref:fetch` acquisition workflow for the remaining PMIDs, in the
   same priority order and with the same per-PMID independence:
   a. First attempt genuine JATS XML directly: if `papers/<pmid>/meta.json`
      has a `pmcid`, fetch
      ```
      https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pmc&id=<pmcid>&rettype=full&retmode=xml
      ```
      via WebFetch. Validate it's well-formed XML. If it parses, pass it as
      `jats_xml`.
   b. Otherwise call `mcp__claude_ai_PubMed__get_full_text_article` for PMC OA
      full text. Treat returned `articles[].full_text` as `plain_text`, not
      `jats_xml`, because the live tool returns pre-extracted plain text.
   c. Otherwise leave `jats_xml` null so `fetch.py` can check Unpaywall using
      DOI + `unpaywall_email` from config. If it reports `oa_location_found`,
      do not treat that as failure.
   d. Otherwise fetch publisher HTML yourself (WebFetch or firecrawl skill)
      and pass it as `publisher_html`.
   e. If none of the above produced content, leave `jats_xml`,
      `publisher_html`, and `plain_text` null; the script will report
      `abstract_only`.
5. Normalize the fetch input into the standard envelope:
   ```json
   {
     "pmid": "<string>",
     "doi": "<string or null>",
     "pmcid": "<string or null>",
     "jats_xml": "<string or null>",
     "publisher_html": "<string or null>",
     "plain_text": "<string or null>"
   }
   ```
   Include `pmcid` when known so JATS figure assets can be downloaded from
   PMC OA asset URLs.
6. Write the fetch JSON array to a temp file, then print and run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/fetch.py" --repo <library_root> --input-file <temp-file>
   ```
7. Print the script's own output verbatim under a `fetch:` stage header. It
   reports `acquired` / `duplicate_noop` / `oa_location_found` /
   `abstract_only` / `failed`, each independent; one paper's failure never
   blocks the rest.

Output shape:
```text
add:
<pmid>: added|already_present|failed ...

fetch:
<pmid>: acquired|duplicate_noop|oa_location_found|abstract_only|failed ...
```

Notes:
- This wrapper is intentionally orchestration only. Do not merge `add.py` and
  `fetch.py`; the split keeps "create metadata record" separate from "acquire
  full text".
- Do not skip the fetch stage for `already_present` records. This command is
  useful for "make sure these PMIDs are in the library and fetch whatever full
  text is legally available."
