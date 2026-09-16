# /ref:repair-fulltext

Batch-repair full-text gaps found by `/ref:lint`: work through the
`metadata_only`, `abstract_only`, and `oa_pending` PMID buckets and run the
same acquisition workflow as `/ref:fetch` for each, bounded by `--limit` and
resume-safe across runs. This is an orchestration wrapper; it must not
replace `/ref:lint` or `/ref:fetch`.

Parse `$ARGUMENTS` for:

- `--limit <N>` — optional, default `20`. Max PMIDs attempted this run.
- `--stale-days <N>` — optional, default `180`. Passed to `/ref:lint` for
  bucket selection (does not affect which papers count as needing full text).
- `--retry-failed` — optional. Without this flag, PMIDs marked `failed` or
  `abstract_only` in the state file within the last 24h are skipped; with it,
  they're retried this run.
- `[selector]` — optional. Restrict the candidate set to PMIDs matching a
  `/ref:search`-style selector before batching (defaults to whole library).

Steps:

1. Resolve the library root from `~/.config/ref-manager/config.json` (fail
   loudly, pointing at `/ref:init`, if unconfigured).
2. Run:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/lint.py" run --repo <library_root> --stale-days <N> --json
   ```
   and read `issues.metadata_only`, `issues.abstract_only`,
   `issues.oa_pending` from the JSON report. Union these three buckets,
   de-duplicated, preserving first-seen order (`metadata_only` first, then
   `abstract_only`, then `oa_pending`).
3. If `[selector]` was given, intersect the candidate PMIDs with the
   selector's matches (evaluate the selector the same way `/ref:search` does).
4. Load resume state by running:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/repair_state.py" read --repo <library_root>
   ```
   This returns a JSON object keyed by PMID:
   `{"<pmid>": {"result": "acquired|oa_location_found|abstract_only|failed", "attempted_at": "<ISO8601>"}}`
   (`{}` if no state file exists yet). Never read or write
   `maintenance/repair-fulltext-state.json` directly — `repair_state.py` is
   the only owner of that file.
5. Build this run's batch:
   - Drop any candidate PMID whose full text is already present (`meta.json`
     now shows `full_text: true`) — the lint report may be slightly stale.
   - Unless `--retry-failed` is passed, drop candidates whose state entry has
     `result` in `{failed, abstract_only}` and `attempted_at` within the last
     24 hours. Always retry `oa_location_found` entries — a follow-up
     Unpaywall/publisher check may now succeed.
   - Take the first `--limit` PMIDs of what remains, in the order from step 2.
   - If the batch is empty, print `nothing to repair` (with a one-line reason:
     all candidates recently attempted, or no candidates found) and stop.
6. Run the `/ref:fetch` acquisition workflow (see `/ref:fetch` for the
   per-PMID source priority: JATS XML via PMC efetch, then
   `mcp__claude_ai_PubMed__get_full_text_article`, then Unpaywall via
   `fetch.py`'s own DOI lookup, then publisher HTML) for exactly this batch,
   independently per PMID — one failure must not block the rest.
7. After `fetch.py` reports per-PMID results, build a JSON object of every
   attempted PMID's entry (result + current UTC timestamp) and merge it in
   with:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/repair_state.py" merge --repo <library_root> --entries '<json>'
   ```
   `repair_state.py` does the read-modify-write atomically under the
   library lock, so a crash mid-run or a concurrent repair run against the
   same library can't corrupt or drop entries.
8. Print a summary:
   ```text
   repair-fulltext:
   candidates: <N> (after resume-skip: <M>)
   attempted: <count>
   acquired: <count>
   oa_location_found: <count>
   abstract_only: <count>
   failed: <count>
   remaining: <count of candidates not attempted this run>

   next:
   - /ref:repair-fulltext --limit <N>   (if remaining > 0)
   - /ref:repair-fulltext --retry-failed   (if failed > 0)
   ```

Notes:

- Resume-safety means re-running with the same `--limit` after an interrupted
  or partial run makes forward progress instead of re-attempting the same
  PMIDs that just failed or came back abstract-only.
- Do not fabricate `full_text` success. A PMID that legitimately has no OA
  full text stays `abstract_only` or `oa_location_found` across runs; that is
  expected, not a bug in this command.
- The state file is repair-run bookkeeping, not paper data — never write to
  `papers/<pmid>/`. All paper mutations still flow through `fetch.py`.
