Regenerate the OKF knowledge bundle and researcher/grant graph relationships
(PLAN.md §4 pipeline step [5] WEAVE, D1, §5a). Both are entirely derived from
already-committed structured records — never hand-edit anything under `okf/`
or `graph/people_relations.jsonl`; edit the source JSONL/JSON and re-run this
command.

This command owns two independent, non-conflicting outputs:
- `okf/` — a conformant OKF v0.2 bundle (Concept/Entity/Reference views),
  readable by the `okf` plugin's `search_concepts`/`read_concept`/
  `get_neighbors` MCP tools.
- `graph/people_relations.jsonl` — researcher-authored-publication and
  publication-acknowledges-grant edges, built from data phases 1-3 already
  committed (confirmed person-publication links, funding observations
  matched against grant records). `publication_supports_aim` and
  `researcher_lab_membership` are schema-ready but unpopulated — nothing in
  this plugin currently links a publication to a specific grant aim or lab
  membership; the command reports this plainly rather than fabricating a
  link.

Note: `graph/concepts.jsonl` and `graph/relations.jsonl` (the scientific
concept/claim comparison graph — supports/potential_conflict/contradicts/
extends/replicates edges) are a separate phase-8 deliverable with their own
entry point; this command only *consumes* those files if present (for
concept neighbor listings in the OKF output) and degrades cleanly when they
don't exist yet.

Steps:
1. Resolve the library root (fail loudly, pointing at `/ref:init`, if unconfigured).
2. Print, then run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/okf_emit.py" --repo <library_root>
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/graph_people.py" --repo <library_root>
   ```
3. Print both scripts' output verbatim. If you want to confirm OKF conformance,
   the `okf:validate` skill can check the generated `okf/` directory directly.
