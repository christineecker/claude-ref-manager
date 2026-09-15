Build/review `graph/relations.jsonl` — typed edges between concepts, evidenced by
claims (PLAN.md §4a, §4 pipeline step [5] WEAVE). No dedicated subagent exists for
concept mapping (PLAN.md §3 names only `ref-extractor`/`ref-synthesizer`, neither
fits) — do the mapping inline in this session, same pattern `/ref:check-citations`
already established for a different judgment task.

Parse `$ARGUMENTS` for:
- `<pmid...>` or a §5c selector — the papers whose claims to weave into the graph.
- `review <relation-id> <type> --rationale "..."` — promote/demote a relation
  (e.g. `potential_conflict` → `contradicts`); `contradicts` is refused without a
  non-empty rationale.
- `neighbors <concept-slug>` — "what supports/conflicts with/contradicts X" (§5's
  structural retrieval layer).

Steps (for the default weave mode):
1. Resolve the library root (fail loudly, pointing at `/ref:init`, if unconfigured).
2. Resolve the selector to a PMID list (reuse `lib_selector.py`, same as every other
   set-valued command).
3. For each active claim across the resolved papers, map its `intervention`/`outcome`
   (or whichever normalized fields the claim is really about) to concept IDs:
   - **Always call `concept.py find` first.** Only call `concept.py create` when no
     existing concept/alias matches.
   - If a near-match exists under a different name (e.g. claim says "myocardial
     infarction", an existing concept is named "MI"), add the claim's wording as an
     alias via `concept.py add-alias` rather than minting a new concept.
4. For every pair of claims that map to the SAME concept pair (subject + object)
   across DIFFERENT papers, propose an edge:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/relation.py" propose --repo <library_root> \
     --claim-a-file <tmp-claim-a.json> --claim-b-file <tmp-claim-b.json> \
     --subject-concept <slug> --object-concept <slug>
   ```
   This returns `null` unless the two claims have opposite directions (`increase` vs
   `decrease` specifically) AND matching comparator/effect_measure/timepoint/population
   — never invent a conflict from a mismatched or missing context (§4a). Only pairs
   from DIFFERENT PMIDs are candidates; don't weave a paper's claims against themselves.
   When it returns a proposal, persist it with the `create` action instead of `propose`.
5. Print each created/proposed edge and any concept created/aliased along the way.
   Never mark an edge `contradicts` here — that's always a separate, explicit
   `review` action with a rationale.

For `review`/`neighbors`, just run the matching `relation.py` subcommand and print
its output verbatim.

**Scope note**: comparing every claim pair across a whole library is expensive and
usually pointless — this command only compares claims already mapped to the same
concept pair, and only within the papers the selector resolved to. A library-wide
sweep is an explicit, separate operation the calling agent should batch by selector
(e.g. one project at a time), not something this command does unprompted.
