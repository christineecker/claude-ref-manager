Import papers from multiple source types, then add and optionally fetch them.

This is the source-aware front door for intake. Use it when you have a mix of
PMIDs, article URLs, local PDFs, or bibliography files and do not want to run
the source-specific commands one by one.

Parse `$ARGUMENTS` for:
- `<item...>` — one or more inputs. Supported forms:
  - PMID tokens like `40691132`
  - article URLs
  - local PDF paths or folders containing PDFs
  - BibTeX (`.bib`) or CSL-JSON (`.csl.json`) files
  - bare DOI strings like `10.1038/s41586-026-00001-2`
- `--no-fetch` — add metadata only; skip full-text acquisition.

Steps:
1. Resolve the library root (fail loudly, pointing at `/ref:init`, if unconfigured).
2. Split the inputs by type:
   - URL-like inputs go through the `/ref:add-url` identification flow.
   - Existing `.pdf` paths go through the `/ref:add-pdf` identification flow.
   - Directory inputs are expanded to the PDFs they contain and then treated
     like local PDF paths.
   - `.bib` and `.csl.json` files are read as citation files and resolved to
     PMIDs before the add stage.
   - Bare DOI strings are resolved through PubMed MCP, with confirmation when
     the DOI maps to zero or multiple PMIDs.
   - Bare PMID tokens are treated as direct PMIDs.
3. For URL and PDF inputs, use the existing identification helpers:
   - `url_identify.py` extracts PMID/PMCID/DOI clues from URLs.
   - `pdf_identify.py` extracts PMID/PMCID/DOI clues from local PDFs.
4. Resolve non-PMID clues to PMIDs using PubMed MCP, asking for confirmation when
   a DOI/PMCID lookup is ambiguous, a title clue is weak, a bibliography
   entry cannot be matched uniquely, or a DOI resolves ambiguously.
5. Call PubMed MCP `get_article_metadata` once for all resolved PMIDs and
   normalize the returned articles into the standard `/ref:add` envelope.
6. Write the metadata array to a temp file, then run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/add.py" add --repo <library_root> --metadata-file <temp-file>
   ```
7. Unless `--no-fetch` was passed, fetch full text for every PMID that now has a
   `papers/<pmid>/meta.json`, using the same `/ref:fetch` priority ladder:
   PMC JATS, PubMed plain text, Unpaywall, publisher HTML, otherwise abstract-only.
8. Print all stage output verbatim under headers so the user can see where each
   paper came from and whether it was added, already present, attached, or fetched.

Suggested output shape:
```text
identify:
<input>: pmid|doi|pmcid|manual -> <pmid>

add:
...

fetch:
...
```

Notes:
- PMID remains the identity key. DOI/URL/PDF clues only resolve a candidate PMID;
  they never merge records.
- This command is a dispatcher, not a new storage path. It reuses the existing
  add, fetch, attach, url-identify, and pdf-identify flows.
- Bibliography files are treated as source material, not as authoritative IDs;
  PMIDs still have to be resolved before the add stage.
- DOI-only input is a convenience for users who copied a DOI from a paper or
  reference list but do not have the PMID yet.
- One input's failure must not block the rest.