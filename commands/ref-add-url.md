Identify article URLs, add their PubMed records, then fetch available full text.

Parse `$ARGUMENTS` for:
- `<url...>` — one or more article URLs. Supported best-effort clues include
  PubMed URLs, PMC URLs, DOI URLs, and publisher URLs containing a DOI.
- `--no-fetch` — add metadata only; skip the fetch stage.

Steps:
1. Resolve the library root (fail loudly, pointing at `/ref:init`, if
   unconfigured).
2. Print, then run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/url_identify.py" <url...>
   ```
   This local script extracts obvious DOI, PMID, or PMCID clues from the URL
   itself. It does not call the network.
3. For each URL:
   - If `pmid` was found, use it directly.
   - Else if `doi` was found, call PubMed MCP `search_articles` using the DOI
     as an article identifier query. Accept exactly one PMID result.
   - Else if `pmcid` was found, resolve it to a PMID through PubMed/PMC lookup
     via PubMed MCP.
   - Else fetch the page HTML using an appropriate web fetcher, extract
     citation metadata from common tags (`citation_doi`, `DC.Identifier`,
     schema.org JSON-LD, DOI-looking text, `citation_pmid`, `citation_pmcid`),
     then repeat the DOI/PMID/PMCID resolution.
   - If zero or multiple candidates remain, show the URL, extracted title/DOI
     clues, and ask the user to pick/provide a PMID or skip.
4. Confirm against PubMed before adding:
   - Call PubMed MCP `get_article_metadata` once for all resolved PMIDs.
   - If URL/page DOI exists, it should match PubMed DOI when PubMed has one.
   - If page title exists, it should be compatible with PubMed title. Ambiguous
     or weak matches require user confirmation.
5. Normalize PubMed metadata into the standard `/ref:add` envelope, write it to
   a temp file, then run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/add.py" add --repo <library_root> --metadata-file <temp-file>
   ```
6. Unless `--no-fetch` was passed, fetch full text for successfully
   added/already-present PMIDs using the same `/ref:fetch` priority ladder:
   PMC E-utilities JATS, PubMed MCP plain text, Unpaywall, publisher HTML,
   otherwise abstract-only.
7. Print all stage output verbatim under headers:
   ```text
   identify:
   <url>: doi|pmid|pmcid|page_meta|manual -> <pmid>

   add:
   ...

   fetch:
   ...
   ```

Safety:
- PMID remains the identity key. URL/DOI/title clues only resolve candidate
  PMIDs; they never merge records.
- Do not treat publisher page access as permission to bypass paywalls. Fetching
  full text still follows the `/ref:fetch` legal/available-source ladder.
- One URL's failed identification must not block the rest.
