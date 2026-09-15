Download free PMC Open Access PDFs for one or more already-added PMIDs and
attach them through the normal PDF attachment pipeline.

Parse `$ARGUMENTS` for:
- `<pmid...>` — one or more PubMed IDs. Each must already have a
  `papers/<pmid>/meta.json` from `/ref:add`.
- `--force` — attach even if the PDF identity check fails; refused otherwise.

Steps:
1. Resolve the library root (fail loudly, pointing at `/ref:init`, if
   unconfigured).
2. For each PMID, read `papers/<pmid>/meta.json` and require a `pmcid`.
   A PMCID is necessary but not sufficient: some PMC records have JATS/full
   text but no downloadable PDF in the OA subset.
3. Print, then run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/fetch_pmc_pdf.py" --repo <library_root> [--force] <pmid...>
   ```
4. Print the script's own output verbatim. Per PMID:
   - `attached` — PMC OA PDF bytes were downloaded, identity-checked, stored as
     `raw/<sha256>/source.pdf`, and converted through `convert_pdf`.
   - `duplicate_noop` — identical PDF bytes were already stored.
   - `no_pmcid` — the paper has no PMCID.
   - `no_pdf` — PMC OA lookup succeeded but no downloadable PDF link was
     available. When PMC E-utilities JATS is available, the output will say so
     and point back to `/ref:fetch`.
   - `refused` — PDF identity check failed.
   - `failed` — lookup/download/attachment error.

Notes:
- This command uses the documented PMC OA Web Service to discover downloadable
  PDF resources. It does not scrape the PMC PDF viewer and does not bypass
  access controls.
- For structured full text and figure locators, `/ref:fetch` remains the
  better default because it prefers PMC JATS XML. Use `/ref:fetch-pdf` when
  you specifically want a PDF stored for reading/export/Papers handoff.
- Some papers, including PMC-hosted Wiley articles, expose public HTML/JATS
  full text while the PDF route is a browser-check page or absent from the PMC
  OA Web Service. Treat that as "PDF unavailable", not "full text unavailable".
