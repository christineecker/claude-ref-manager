Check a paragraph's assertions against library evidence (PLAN.md §5a). Splits the
paragraph into checkable assertions and judges each against retrieved evidence — never
rewrites the paragraph itself; findings are a separate report.

No dedicated subagent exists for this (PLAN.md §3 names exactly two: `ref-extractor` and
`ref-synthesizer`, neither of which fits — this verifies existing text rather than writing
new text). Do the assertion-splitting and evidence-judgment yourself, inline, in this same
session — the same pattern `/ref:add`'s metadata normalization already uses.

Parse `$ARGUMENTS` for:
- `<paragraph>` or `--file <path>` — the text to check, required.
- an optional §5c selector (`--project`, `--study`, `--search`, `--from-file`, or a bare
  `<pmid...>` list) to scope retrieval.
- `--export-bib` — also export a BibTeX/CSL-JSON bibliography of every PMID the report
  actually references as evidence.

Steps:
1. Resolve the library root (fail loudly, pointing at `/ref:init`, if unconfigured).
2. Note any `[^pmid]` markers already present in the paragraph — these are existing
   citations you must verify, not just candidates a search might surface.
3. **Query expansion + retrieval**, same as `/ref:ask` (steps 2-3 of `commands/ref-ask.md`):
   think of 2-4 expansion terms, then run `ask_retrieve.py` with the paragraph text as
   the question (optionally selector-scoped). This rebuilds the FTS catalog and returns
   candidates.
4. If any `[^pmid]` markers were found in step 2 for PMIDs NOT already in the retrieved
   candidates, fetch those PMIDs' active claims directly too (a citation check must verify
   what's already cited, not only what search would find on its own — see
   `check_citations.py`'s `merge_cited_pmid_candidates` for the exact merge logic; you can
   either replicate it inline or just make sure every already-cited PMID's evidence ends up
   in the candidate list you use next).
5. **Split the paragraph into assertions** — one per sentence/clause making a factual
   claim. For each assertion, using ONLY the retrieved candidates:
   - `supported` — evidence directly backs it, with evidence refs (`pmid` + `claim_id`)
   - `overstated` — evidence exists but is weaker/more hedged than the assertion claims
     (e.g. assertion says "causes", evidence says "associated with")
   - `conflicting` — evidence contradicts it
   - `insufficient` — relevant evidence exists but doesn't clearly resolve it
   - `unavailable` — no relevant evidence among the candidates (leave `evidence: []`)
   If the assertion already had a `[^pmid]` citation attached, check whether that specific
   PMID's evidence actually supports it — if not, set `"citation_mismatch": true` and
   `"existing_citation_pmid": "<pmid>"` on the finding, distinct from an assertion that
   simply has no citation at all.
   Each finding's `assertion_text` must be an exact substring of the input paragraph —
   never paraphrase or invent one.
6. Write the paragraph, your findings (a JSON array matching the shape above), the
   candidates, and the selector resolution (if any) to temp files, then print and run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/check_citations.py" check --repo <library_root> [--project <slug>] --paragraph-file <temp-file> --findings-file <findings-temp-file> --candidates-file <candidates-temp-file> [--resolution-file <resolution-temp-file>] [--export-bib]
   ```
7. Print the script's own output verbatim, including its `caveat` line — always relay it to
   the user: available library coverage does not establish a comprehensive literature
   check. Present the findings grouped by verdict; never present an edited version of the
   user's paragraph as if it were their original text.
