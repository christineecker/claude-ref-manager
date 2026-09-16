Build/review the concept and relation graph, then regenerate the derived OKF bundle
and researcher/grant graph relationships — PLAN.md §4 pipeline step [5] WEAVE:
"structured concepts/relations -> generated OKF views" is one step, so this command
covers both halves. No dedicated subagent exists for concept mapping (PLAN.md §3
names only `ref-extractor`/`ref-synthesizer`, neither fits) — do the mapping inline
in this session, same pattern `/ref:check-citations` already established for a
different judgment task.

Parse `$ARGUMENTS` for:
- `<pmid...>` or a §5c selector — the papers whose claims to weave into the graph.
  Omit entirely to skip straight to step 5 (regenerate derived views only).
- `review <relation-id> <type> --rationale "..."` — promote/demote a relation
  (e.g. `potential_conflict` → `contradicts`); `contradicts` is refused without a
  non-empty rationale.
- `neighbors <concept-slug>` — "what supports/conflicts with/contradicts X" (§5's
  structural retrieval layer).
- `--regenerate-only` — skip claim-comparison entirely and just rerun step 5 (useful
  after a `/ref:verify` correction or `/ref:extract` rerun changes underlying data
  without adding new claims to weave).

Steps (for the default weave mode, when a selector is given):
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
   Never mark an edge `contradicts` here — that's always a separate, explicit
   `review` action with a rationale.
   `propose`/`create` only ever produce `potential_conflict` (the deterministic
   opposite-direction comparability check can't derive `supports`/`extends`/
   `replicates` from PICO fields alone). When *you* read two papers and judge that
   one genuinely extends or replicates another — a judgment call, not something to
   automate — use `relation.py create-manual --type supports|extends|replicates
   --subject-concept <slug> --object-concept <slug> --claim-a-file <claim.json>`
   directly; state your reasoning when you report the edge to the user.

5. **Regenerate the derived views** — always run this step (it's also the entirety of
   `--regenerate-only`/no-selector mode), since concepts/relations may have changed:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/okf_emit.py" --repo <library_root>
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/graph_people.py" --repo <library_root>
   ```
   - `okf/` — a conformant OKF v0.2 bundle (Concept/Entity/Reference views), readable
     by the `okf` plugin's `search_concepts`/`read_concept`/`get_neighbors` MCP tools.
     Never hand-edit anything under `okf/` — edit the source JSONL/JSON and re-run
     this command. To confirm conformance, the `okf:validate` skill can check the
     generated `okf/` directory directly.
   - `graph/people_relations.jsonl` — `researcher_authored_publication` and
     `publication_acknowledges_grant` edges, built from data phases 1-3 already
     committed (confirmed person-publication links, funding observations matched
     against grant records). This is a **separate file from `graph/relations.jsonl`**
     (the scientific concept/claim comparison graph built in steps 1-4) — kept apart
     because the two were designed independently and merging their schemas wasn't
     worth the risk. `publication_supports_aim` and `researcher_lab_membership` are
     schema-ready but unpopulated: nothing in this plugin currently links a
     publication to a specific grant aim or lab membership record, and the script
     reports this plainly rather than fabricating a link.

Print each created/proposed edge and any concept created/aliased along the way in
step 4, then both regeneration scripts' output verbatim from step 5.

For `review`/`neighbors`, just run the matching `relation.py` subcommand and print
its output verbatim (skip steps 3-5 entirely).

**Scope note**: comparing every claim pair across a whole library is expensive and
usually pointless — the weave-mode steps above only compare claims already mapped to
the same concept pair, and only within the papers the selector resolved to. A
library-wide sweep is an explicit, separate operation the calling agent should batch
by selector (e.g. one project at a time), not something this command does unprompted.
