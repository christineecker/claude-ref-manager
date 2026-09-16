Library-hygiene sweep: re-check retraction/errata status, and (`--citations`)
record dated PMC cited-by observations — PLAN.md §1, D25, §3c, §4a's closing
paragraph. Unlike every other §5c-selector command, **no selector at all
means the whole library**, not an error — this is a maintenance sweep, not
a set-scoped artifact. Pass a selector to scope a re-check if you don't want
the whole library.

Parse `$ARGUMENTS` for:
- an optional §5c selector (`<pmid...>`, `--project`, `--study`, `--search`,
  `--from-file`, etc.) to scope the sweep; omit entirely for the whole library.
- `--citations` — record citation observations instead of (or alongside)
  retraction-status checks; run the two modes separately, see below.
- `show-citations` (as the action, not a flag) — print each resolved PMID's
  latest real citation observation plus its staleness, without checking
  anything new.

**Read this before running `--citations`**: no PubMed MCP tool has a real
cited-by/citing-article COUNT source — `search_articles`,
`get_article_metadata`, `get_full_text_article`, `find_related_articles`
(only `pubmed_pubmed` word-similarity, no citation graph — confirmed live in
phase 9's `/ref:related` work), `convert_article_ids`,
`lookup_article_by_citation`, `get_copyright_status` were all checked. The
wired source is instead a direct NCBI E-utilities ELink call over WebFetch
(see step 3 below) — a real, public "cited in PMC" count, not a fabricated
one. Its `coverage` is intentionally narrow: it only counts citing articles
that are themselves indexed in PMC, so it undercounts total literature
citations. Never fabricate a count from `pubmed_pubmed` similarity results —
those are NOT citations.

Steps for the default (retraction-status) mode:
1. Resolve the library root (fail loudly, pointing at `/ref:init`, if unconfigured).
2. Resolve the selector (or, with none given, every PMID in the library).
3. For each PMID, call `mcp__claude_ai_PubMed__get_article_metadata` again and
   check `article_types` for a retraction/erratum/correction marker — the
   IDENTICAL check `/ref:extract`'s command doc already runs once at
   ingestion (`commands/ref-extract.md` step 4's `retraction_status` section
   — reuse that logic verbatim, don't invent a second approach). On success,
   normalize to `{"status": "retracted"|"erratum"|"none"|"unknown", "source":
   "pubmed", "checked_at": "<iso8601>"}`. On any failure or ambiguity, record
   `{"pmid": ..., "error": "<what went wrong>"}` instead — **never** guess
   `"none"` or silently downgrade a prior `"retracted"` finding.
4. Write the per-PMID results (a JSON array, each either `{"pmid",
   "result": {...}}` or `{"pmid", "error": "..."}`) to a temp file, then
   print and run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/audit.py" retraction --repo <library_root> --results-file <temp-file> [selector args]
   ```
5. Print the script's output verbatim, including `changed_pmids`. If any
   PMID's status changed, also run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/audit.py" propagate --repo <library_root> --results-file <changed-pmids-json-array>
   ```
   and relay `potentially_stale_artifacts` to the user plainly — a saved
   `/ref:brief`/`/ref:compare`/`/ref:summarize` that used a now-retracted
   paper needs an explicit `--refresh` to surface that (never auto-refreshed
   silently; the artifact's prior frozen version is never overwritten).

Steps for `--citations` mode:
1-2. Same as above.
3. For each PMID, first check `meta.json`/`convert_article_ids` for a PMCID.
   No PMCID → `{"pmid": ..., "no_pmcid": true}`. Otherwise, strip any `PMC`
   prefix to get the bare numeric PMC id and fetch (via WebFetch, one PMID at
   a time — do not batch multiple `id=` params into one call, so a single
   malformed response never blocks the rest of the sweep):
   ```
   https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi?dbfrom=pmc&linkname=pmc_pmc_citedby&id=<pmcid-numeric>&retmode=json
   ```
   This is `pmc_pmc_citedby` — NCBI's "Cited By" link for a PMC record: other
   PMC articles that cite it. Parse the response:
   ```json
   {"linksets": [{"linksetdbs": [{"dbto": "pmc", "linkname": "pmc_pmc_citedby", "links": ["<pmcid>", ...]}]}]}
   ```
   `count` is `len(links)`. If `linksets[0]` has no `linksetdbs` entry (the
   key is simply absent when there are zero citing links — NCBI omits empty
   linksetdbs rather than returning an empty list), treat that as a real
   `count: 0`, not a failure. A non-2xx response, unparseable JSON, or a
   missing `linksets` key is a failed lookup, not a zero.
   Wrap a successful result under the literal key `"observation"` — this is
   the one field name `audit.py` actually reads for a successful result,
   verified live:
   ```json
   {"pmid": "...", "observation": {"source": "pmc_elink",
     "query": "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi?dbfrom=pmc&linkname=pmc_pmc_citedby&id=<pmcid-numeric>&retmode=json",
     "count": <int>, "coverage": "citing articles indexed in PMC; not a total citation count"}}
   ```
   A failed lookup → `{"pmid": ..., "error": "..."}` — never a fabricated zero.
   A record with none of `observation`/`no_pmcid`/`error` is refused by the
   script as malformed input, not silently treated as a failed lookup.
4. Write results, then print and run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/audit.py" citations --repo <library_root> --results-file <temp-file> [selector args]
   ```
   Every call appends a new dated observation — `papers/<pmid>/citations.json`
   never has a prior entry overwritten (D25).
5. Print the output verbatim.

`show-citations` (no MCP call, no `--results-file`):
```
python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/audit.py" show-citations --repo <library_root> [--stale-days N] [selector args]
```
Prints each resolved PMID's most recent REAL observation (skipping any
`check_failed`/`no_pmcid` markers) plus whether it's past the staleness
threshold (default 180 days). A PMID with no real observation shows `null`
— relay this as "no observation available," never as zero.
