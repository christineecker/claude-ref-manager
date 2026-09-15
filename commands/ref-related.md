Snowball from a known paper — backward (reference list) and forward
(computational similarity via PubMed) — PLAN.md §1, D11.

Parse `$ARGUMENTS` for:
- `<pmid>` — required, must already have a `papers/<pmid>/meta.json` from `/ref:add`.
- `--direction backward|forward|both` — default `both`.
- `--link-type pubmed_pubmed|pubmed_pmc|pubmed_gene|pubmed_protein|pubmed_nucleotide`
  — default `pubmed_pubmed`, passed through to `find_related_articles`.

**Honesty note, read before running**: the live PubMed MCP's `find_related_articles`
tool has no true "cited-by" link_type — `pubmed_pubmed` (the default) is
word-weighted title/abstract/MeSH *similarity*, not a citation graph. Every forward
candidate this command persists records exactly which `link_type` produced it
(`method: "find_related_articles:<link_type>"`), so this is never presented as
citation data it isn't. If genuine ELint cited-by tracking is needed, that's a
later phase's `/ref:audit --citations` (D25), not this command.

Steps:
1. Resolve the library root (fail loudly, pointing at `/ref:init`, if unconfigured).

2. **Backward** (if `--direction backward` or `both`): just run and print —
   this needs no MCP call, it reads already-committed full text:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/related.py" backward --repo <library_root> --pmid <pmid>
   ```
   If `available: false`, relay the stated `reason` plainly (no full text, or no
   References section found) — never imply the paper has no references, only that
   this library can't currently extract them. Extracted candidates are raw citation
   text, not resolved PMIDs — most reference-list entries don't embed one. If a
   candidate looks resolvable and it's useful to the user, you may look it up
   yourself (e.g. `search_articles` on the citation text) as a separate, explicit
   step, but do not silently auto-resolve every candidate — that's expensive and
   usually not wanted for a full reference list.

3. **Forward** (if `--direction forward` or `both`): call
   `mcp__claude_ai_PubMed__find_related_articles` with `pmids: [<pmid>]` and the
   requested `link_type`. Write the returned PMIDs (just the ID list, e.g. from
   `identifiers.pmid` per result) to a temp JSON file, then print and run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/related.py" forward --repo <library_root> --pmid <pmid> --link-type <link_type> --results-file <temp-file>
   ```
   A zero-result response is printed plainly as `zero_results: true` with its note
   — never phrased as "no related work exists."

4. Print each script's output verbatim, including the `persisted` summary
   (`already_in_library` vs `not_yet_added` counts). Never auto-add a candidate to
   the library — `/ref:related` only surfaces candidates; `/ref:add <pmid>` remains
   the explicit, deliberate way something enters the library (D12).

`show` (no arguments needed beyond `--pmid`) just prints the persisted
`related.json` for a PMID without querying anything new:
```
python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/related.py" show --repo <library_root> --pmid <pmid>
```
