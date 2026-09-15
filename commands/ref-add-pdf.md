Identify local PDFs, add their PubMed records, then attach the PDFs.

Parse `$ARGUMENTS` for:
- `<path...>` — one or more local PDF paths.
- `--force` — pass through to `/ref:attach` only when attaching; use only when
  the PDF identity check refuses and the user explicitly accepts the match.

Steps:
1. Resolve the library root (fail loudly, pointing at `/ref:init`, if
   unconfigured).
2. Print, then run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/pdf_identify.py" <path...>
   ```
   This local script extracts DOI, PMID, PMCID, and a title guess from the
   first PDF pages using `pdftotext`. It does not call the network.
3. For each PDF:
   - If `pmid` was found, use it directly.
   - Else if `doi` was found, call PubMed MCP `search_articles` with the query
     `"DOI"[AID]` style when supported, otherwise the DOI string itself. Accept
     exactly one PMID result. If zero or multiple results, show the DOI/title
     guess and ask the user to choose or provide a PMID.
   - Else if only `pmcid` was found, use PubMed/PMC lookup via PubMed MCP to
     resolve it to a PMID if available; otherwise ask the user.
   - Else show the title guess and ask for a PMID, or skip that PDF.
4. Call PubMed MCP `get_article_metadata` once for all resolved PMIDs and
   normalize the returned articles into the same metadata envelope used by
   `/ref:add`.
5. Write the metadata array to a temp file, then run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/add.py" add --repo <library_root> --metadata-file <temp-file>
   ```
6. Attach each PDF to its resolved PMID with the normal attachment pipeline:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/attach.py" --repo <library_root> [--force] <pmid1> <path1> [<pmid2> <path2> ...]
   ```
7. Print all script output verbatim. Per PDF, report the clue used
   (`pmid`, `doi`, `pmcid`, or `manual`) and whether the add/attach step
   succeeded. One PDF's failed identification or refused attachment never blocks
   the rest.

Safety:
- PMID remains the identity key. DOI/title clues only resolve a candidate PMID;
  they never merge records.
- If DOI search returns multiple candidates, or if the metadata title clearly
  disagrees with the PDF title guess, ask for confirmation before adding or
  attaching.
