Acquire full text for one or more already-added PMIDs, in priority order:
PMC OA JATS → Unpaywall → publisher HTML → abstract-only (PLAN.md §4, §6).

Parse `$ARGUMENTS` for:
- `<pmid...>` — one or more PubMed IDs. Each must already have a
  `papers/<pmid>/meta.json` from `/ref:add` — fetch augments a record, it
  doesn't create one.
- If no PMID/selector is given at all: run
  ```
  python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/lib_selector.py" recent --repo <library_root> --limit 15
  ```
  and present the results via `AskUserQuestion` (multiSelect, one option per
  paper labeled `<title> (<citekey>, <year>)`) instead of failing or asking
  the user to recall PMIDs from memory. Resolve the ticked papers' `pmid`
  fields and proceed with those as `<pmid...>`.

Steps:
1. Resolve the library root (fail loudly, pointing at `/ref:init`, if unconfigured).
2. For each PMID, try in order, stopping at the first that succeeds:
   a. First attempt genuine JATS XML directly: if `papers/<pmid>/meta.json`
      has a `pmcid`, fetch
      ```
      https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pmc&id=<pmcid>&rettype=full&retmode=xml
      ```
      via WebFetch. Validate it's well-formed XML (`convert.py` refuses
      non-well-formed input rather than mangling it — pandoc's JATS reader
      silently falls back to plain-text parsing on bad input and destroys
      section/heading structure with no error). If it parses, pass it as
      `jats_xml`. This is strictly better full-text fidelity than plain text
      (section headings, tables, math markup, and figure locators/captions
      all survive JATS conversion) and is the only path that yields
      `figures.json` at all, so try it before falling back to (b).
   b. Otherwise (no PMCID, the efetch call failed/timed out, or the XML
      wasn't well-formed), call `mcp__claude_ai_PubMed__get_full_text_article`
      for a reusable PMC OA full text. A PMCID alone does not guarantee
      availability (D16) — if the tool returns nothing usable, move on.
      **Verified against the live tool: it returns pre-extracted plain text
      in `articles[].full_text`, not raw JATS XML** — do not put that string
      into `jats_xml`. Pass it as `plain_text` instead (not `publisher_html`
      — verified live that trafilatura returns an EMPTY document on
      non-HTML plain text, which would silently discard the content;
      `plain_text` is written through as-is by a dedicated no-markup path,
      with the structure/figure loss stated as a diagnostic rather than
      hidden).
   c. Otherwise leave `jats_xml` null — the script itself checks Unpaywall directly
      (a single deterministic REST call needing no judgment, §6 point 2) using the
      paper's DOI and the `unpaywall_email` recorded in `config.json` at `/ref:init`.
      If Unpaywall finds an OA PDF location, the script records it on the paper and
      reports `oa_location_found` — download it yourself (WebFetch or similar) and
      hand it to `/ref:attach` to actually convert it, or leave it for a future
      auto-download step. Do not treat `oa_location_found` as failure.
   d. Otherwise, fetch the publisher's article HTML yourself (WebFetch or the
      `firecrawl` skill) and pass it as `publisher_html`. This script does not
      fetch URLs itself beyond the Unpaywall API call.
   e. If none of the above produced anything, leave both `jats_xml` and
      `publisher_html` null — the script will record `full_text: false` and report
      `abstract_only`. This is expected, not a failure (§6 closing line).
3. Normalize into this envelope (one object per PMID):
   ```json
   {
     "pmid": "<string>",
     "doi": "<string or null>",
     "jats_xml": "<string or null>",
     "publisher_html": "<string or null>",
     "plain_text": "<string or null>"
   }
   ```
4. Write the JSON array to a temp file, then print and run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/fetch.py" --repo <library_root> --input-file <temp-file>
   ```
5. Print the script's own output verbatim — it reports one line per PMID
   (`acquired` / `duplicate_noop` / `oa_location_found` / `abstract_only` /
   `failed`), each independent; one paper's failure never blocks the rest.
   `duplicate_noop` means the current fetched full-text version already has
   the same source kind and raw hash, so no new version was created. When a
   changed fetch is committed, older complete fetch-created version
   directories are pruned so only the final current full-text acquisition
   version remains; content-addressed `raw/<sha256>/...` evidence is
   preserved. For a JATS acquisition it also reports `figures=<N>,
   images=<K>/<N>` — the script auto-downloads figure image bytes right after
   a successful JATS conversion, using PMC OA asset URLs when a PMCID is known
   and known publisher URL patterns keyed by DOI otherwise (currently Springer
   Nature, `10.1038/...`; other publishers degrade to a diagnostic, not a
   failure). Print any `diagnostic:` lines too — these flag incomplete
   conversion (missing tables/math) or per-figure asset-download failures
   without failing the whole fetch.
6. If figures remain `asset_available: false` after step 5 (unrecognized
   publisher, or a version fetched before this auto-download step existed),
   and you can obtain the image bytes another way (manual download,
   `firecrawl`, etc.), attach them post-hoc without re-fetching:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/attach_figures.py" --repo <library_root> --pmid <pmid> --asset <figure-id> <local-path>
   ```
   (repeatable `--asset`), or point at a directory whose filenames match each
   figure's `source_locator`:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/attach_figures.py" --repo <library_root> --pmid <pmid> --figures-dir <dir>
   ```
   Optional — only needed when `/ref:describe-figure` reports
   `asset_unavailable` and you have a way to get real bytes.
