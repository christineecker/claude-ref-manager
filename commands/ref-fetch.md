Acquire full text for one or more already-added PMIDs, in priority order:
PMC OA JATS → Unpaywall → publisher HTML → abstract-only (PLAN.md §4, §6).

Parse `$ARGUMENTS` for:
- `<pmid...>` — one or more PubMed IDs, required. Each must already have a
  `papers/<pmid>/meta.json` from `/ref:add` — fetch augments a record, it
  doesn't create one.

Steps:
1. Resolve the library root (fail loudly, pointing at `/ref:init`, if unconfigured).
2. For each PMID, try in order, stopping at the first that succeeds:
   a. Call `mcp__claude_ai_PubMed__get_full_text_article` for a reusable PMC OA
      JATS full text. A PMCID alone does not guarantee availability (D16) — if the
      tool returns nothing usable, move on.
   b. Otherwise leave `jats_xml` null — the script itself checks Unpaywall directly
      (a single deterministic REST call needing no judgment, §6 point 2) using the
      paper's DOI and the `unpaywall_email` recorded in `config.json` at `/ref:init`.
      If Unpaywall finds an OA PDF location, the script records it on the paper and
      reports `oa_location_found` — download it yourself (WebFetch or similar) and
      hand it to `/ref:attach` to actually convert it, or leave it for a future
      auto-download step. Do not treat `oa_location_found` as failure.
   c. Otherwise, fetch the publisher's article HTML yourself (WebFetch or the
      `firecrawl` skill) and pass it as `publisher_html`. This script does not
      fetch URLs itself beyond the Unpaywall API call.
   d. If none of the above produced anything, leave both `jats_xml` and
      `publisher_html` null — the script will record `full_text: false` and report
      `abstract_only`. This is expected, not a failure (§6 closing line).
3. Normalize into this envelope (one object per PMID):
   ```json
   {
     "pmid": "<string>",
     "doi": "<string or null>",
     "jats_xml": "<string or null>",
     "publisher_html": "<string or null>"
   }
   ```
4. Write the JSON array to a temp file, then print and run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/fetch.py" --repo <library_root> --input-file <temp-file>
   ```
5. Print the script's own output verbatim — it reports one line per PMID
   (`acquired` / `oa_location_found` / `abstract_only` / `failed`), each independent;
   one paper's failure never blocks the rest. Print any `diagnostic:` lines too —
   these flag incomplete conversion (missing tables/math/figure assets) without
   failing the whole fetch.
