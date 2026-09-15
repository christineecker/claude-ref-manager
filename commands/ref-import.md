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
2. Print, then run the shared resolver on the raw inputs as given (URLs, PDF
   paths/dirs, bib/CSL files, bare DOIs, bare PMIDs all go in one call — it
   classifies each and expands any directory into the PDFs it contains):
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/lib_intake.py" classify --repo <library_root> <item...>
   ```
   This replaces doing type-dispatch by hand — the script is local and
   deterministic (no network/MCP), and each result item carries `kind`
   (`pmid`/`doi`/`url`/`pdf`/`bib_file`/`csl_file`/`unknown`), whatever
   clues it found, and a `status` when the item is a duplicate:
   - `duplicate_in_batch` — an earlier item in this same call already claimed
     the same identity (e.g. a bare PMID and a PubMed URL for the same
     paper). Skip it; report it against the first occurrence, don't resolve
     it twice.
   - `already_imported` — the resolved identity (pmid/doi/pmcid) matches a
     paper already in the library (`existing_pmid` names it). Skip
     resolution/add for it and report `already imported as <pmid>` — this is
     the friendly duplicate message, not a failure.
   - `bib_file`/`csl_file` results come back `"result": "unparsed"` —
     parsing bibliography file contents isn't implemented yet. Tell the user
     to extract PMIDs/DOIs from it another way for now, or skip it; don't
     silently drop it from the report.
3. For every remaining item (not a batch/library duplicate), resolve to a PMID:
   - `kind: "pmid"` — use it directly.
   - `kind: "doi"` or a `doi` clue on a `url`/`pdf` item — call PubMed MCP
     `search_articles` using the DOI. Accept exactly one PMID result; ask the
     user to pick/provide a PMID on zero or multiple matches.
   - a `pmcid` clue with no `doi`/`pmid` — resolve it to a PMID via PubMed MCP.
   - `kind: "url"` or `"pdf"` with no clues at all — for a `url`, fetch the
     page HTML and extract `citation_doi`/`DC.Identifier`/schema.org
     JSON-LD/`citation_pmid`/`citation_pmcid`, then repeat the DOI/PMID/PMCID
     resolution above; for a `pdf`, show its `title_guess` and ask the user
     to pick/provide a PMID or skip it.
   - `kind: "unknown"` — show the raw input and ask the user to provide a
     PMID/DOI/URL/path, or skip it.
4. Call PubMed MCP `get_article_metadata` once for all resolved PMIDs and
   normalize the returned articles into the standard `/ref:add` envelope.
5. Write the metadata array to a temp file, then run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/add.py" add --repo <library_root> --metadata-file <temp-file>
   ```
6. Unless `--no-fetch` was passed, fetch full text for every PMID that now has a
   `papers/<pmid>/meta.json`, using the same `/ref:fetch` priority ladder:
   PMC JATS, PubMed plain text, Unpaywall, publisher HTML, otherwise abstract-only.
7. Print all stage output verbatim under headers so the user can see where each
   paper came from and whether it was added, already imported, attached, or fetched.

Suggested output shape:
```text
classify:
<input>: pmid|doi|url|pdf|bib_file|csl_file|unknown [already imported as <pmid> | duplicate of <input>]

add:
...

fetch:
...
```

Notes:
- PMID remains the identity key. DOI/URL/PDF clues only resolve a candidate PMID;
  they never merge records.
- This command is a dispatcher, not a new storage path. It reuses the existing
  add, fetch, attach, and lib_intake classification.
- DOI-only input is a convenience for users who copied a DOI from a paper or
  reference list but do not have the PMID yet.
- One input's failure must not block the rest.