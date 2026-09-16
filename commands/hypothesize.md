Swanson ABC literature-based discovery over the concept graph (PLAN.md §5b, D13):
two-hop traversal from concept A finds untested A-C pairs, each checked against PubMed
to distinguish "untested in this library" from "untested in the literature."

Parse `$ARGUMENTS` for:
- `--concept <slug>` — the starting concept A, required.

Steps:
1. Resolve the library root (fail loudly, pointing at `/ref:init`, if unconfigured).
2. Print, then run the pure graph traversal (no network yet):
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/hypothesize.py" candidates --repo <library_root> --concept <slug>
   ```
   This returns ranked A-C candidates (ranked by count of independent A-B/B-C chains,
   ties broken alphabetically), each with its full supporting evidence chain
   (`claim_id`s, `pmid`s, relation IDs) and no PubMed data yet.
3. If there are no candidates, say so and stop — nothing to check.
4. **For each candidate**, call `mcp__claude_ai_PubMed__search_articles` with a query
   combining concept A's and concept C's names/aliases (e.g. `"<A name>" AND "<C name>"`).
   Record the exact query text, an ISO 8601 timestamp, and the resulting PMIDs (may be
   empty). A nonzero result is NOT a reason to drop the candidate — it means the
   connection may already be studied in the wider literature, which is itself useful
   information; report it, don't discard it.
5. Write a JSON object mapping each checked candidate's `concept_c` to its check result
   (`{"query": "...", "retrieved_at": "...", "result_pmids": [...]}`) to a temp file, then
   print and run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/hypothesize.py" finalize --repo <library_root> --concept <slug> --checks-file <temp-file>
   ```
6. Print the script's own output verbatim: ranked hypotheses, each with its full A-B/B-C
   evidence chain, the exact PubMed query/timestamp/results, and a limitations note. A
   zero-result check reads "not found by this search" — present it exactly that way,
   never as "novel" or "confirmed gap." This output is a ranked reading list of
   candidates worth investigating, not a set of validated claims.
