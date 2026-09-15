Prose narrative across a §5c-selected set of papers, or a single-paper summary
when the set is one paper (PLAN.md §5a's "Division of labour" — this is what
distinguishes `/ref:summarize` from `/ref:compare`'s structured matrix and
`/ref:review`'s appraised synthesis: plain narrative, no appraisal machinery).

Reuses `agents/ref-synthesizer.md` unchanged — its contract ("N retrieved
evidence candidates -> one grounded answer") already fits; no new subagent
invented. The difference from `/ref:ask`: the candidate set here is NOT
retrieved/ranked search results, it's every active claim for the selector-
resolved PMIDs, full stop — the selector already fixed the set (§5c: "the
resolved list is reported and persisted before work runs").

Parse `$ARGUMENTS` for:
- a §5c selector (`<pmid...>`, `--project`, `--study`, `--search`, `--from-file`,
  etc.) — required, resolves the paper set.
- `--batch <label>` — required, names this saved summary (frozen artifact,
  reused unless `--refresh`, same idiom as `/ref:compare`).
- `--refresh` — re-resolve the selector and regenerate.

Steps:
1. Resolve the library root (fail loudly, pointing at `/ref:init`, if unconfigured).
2. Print, then run, to get the candidate evidence set and the selector's
   resolution report (tier/verification/retraction counts) BEFORE writing anything:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/summarize.py" --repo <library_root> [selector args] --batch <label> --show
   ```
   (`--show` alone, with no `--answer-file`, just resolves+reports without
   persisting — if this errors because no summary exists yet and you haven't
   supplied `--answer-file`, that's expected on first run; proceed to step 3.)
3. If the resolution is wholly abstract-tier or thin, you may still summarize —
   unlike `/ref:review`'s appraisal mode, a prose summary of abstract-only
   evidence is legitimate, just say so in the summary's own text (don't
   overstate confidence a full-tier set would earn).
4. Build the candidate list yourself by calling `summarize.py`'s
   `build_candidates()` logic conceptually — in practice, just let the script
   build it: the `--show`/persist path already does this internally. What you
   need from the calling side is the RESOLVED CANDIDATE LIST to hand to the
   `ref-synthesizer` subagent, so first run:
   ```
   python3 -c "import sys; sys.path.insert(0,'${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts'); import json,summarize; print(json.dumps(summarize.build_candidates(sys.argv[1], sys.argv[2].split(','))))" <library_root> <comma-separated-resolved-pmids>
   ```
   (or resolve PMIDs yourself via `lib_selector.py` and call `build_candidates`
   the same way — the point is you need the actual candidate list, not just
   the count, before invoking the subagent).
5. Spawn ONE `ref-synthesizer` subagent (not one per paper) with:
   `question`: "Produce a narrative summary of what these papers establish,
   covering population(s)/intervention(s)/outcome(s)/direction of effect and
   any notable disagreement across them. Note evidence tier and any
   retraction/errata status where relevant."
   `candidates`: the list from step 4.
6. Write the returned `answer` to a temp file, then print and run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/summarize.py" --repo <library_root> [same selector args] --batch <label> --answer-file <temp-file> [--coverage-note "<from the subagent>"] [--unresolved "<q1>" "<q2>" ...] [--refresh]
   ```
7. Print the script's own output verbatim. On refresh, relay `added_pmids`/
   `removed_pmids`/`withdrawn_evidence` plainly — a saved summary never
   silently changes membership or quietly drops evidence that backed the
   prior version.

This command works identically for a one-paper selector and a many-paper
selector — there is no special single-paper branch; the summary is just
shorter and the subagent naturally writes single-paper prose when given one
paper's claims.
