# Maintaining the claude-ref-manager paper repo — Resources

## Knowledge

- [docs/concepts.html](../concepts.html) — "Concepts" page
  Canonical description of the data model, claim contract, extraction tiers, identifier contract, atomic writes, locks, corrections overlay. Use for: anything about *what the data looks like and why*.
- [docs/workflows.html](../workflows.html) — "Workflows" page
  Figures for the command map, ingest & commit flow, extraction fan-out (ref-extractor subagent). Use for: *how a paper moves through the pipeline*.
- [docs/getting-started.html](../getting-started.html)
  Entry-level tutorial; good for orientation before diving into concepts.html.
- [docs/figures/paper-repo-anatomy.html](../figures/paper-repo-anatomy.html)
  Visual breakdown of a `papers/<pmid>/` directory. Use for: understanding on-disk layout.
- [docs/figures/knowledge-layer-v2.html](../figures/knowledge-layer-v2.html)
  Claim v2 schema (phase 12). Use for: the current claim/graph data shape.
- [reference/maintenance-commands.html](reference/maintenance-commands.html) (this workspace)
  Cheat sheet: `/ref:status`, `/ref:lint`, `/ref:audit`, `/ref:repair-fulltext`, `/ref:maintain` — purpose, reads/writes, flags.
- [reference/pipeline-commands.html](reference/pipeline-commands.html) (this workspace)
  Cheat sheet: `/ref:init` → `/ref:add` → `/ref:fetch` → `/ref:extract` — requires, writes, result lines, fetch's source priority.
- [agents/ref-extractor.md](../../agents/ref-extractor.md)
  The subagent contract `/ref:extract` fans out per-PMID: study-type classification, PICO+ claim normalization, output JSON shape. Use for: exactly what a claim looks like right after extraction, before any correction overlay.
- [docs/concepts.html#claims](../concepts.html#claims) — "The claim contract"
  Authoritative field-by-field claim schema, a real worked example claim, and the stable-claim-ID/supersession algorithm (`assign_claim_ids`). Use for: anything about what a claim *is*, as opposed to how it got extracted.
- [reference/claim-schema.html](reference/claim-schema.html) (this workspace)
  Cheat sheet: every claim field, the retrieval invariant (`status='active' AND excluded_from_synthesis=0`), the three-case supersession rule.
- [commands/*.md](../../commands/) (e.g. `add.md`, `extract.md`, `ask.md`, `audit.md`)
  Each file is the spec for one `/ref:*` slash command — the primary/authoritative source for command behavior, since these are what actually ship.
- [skills/ref-manager/scripts/triage.py](../../skills/ref-manager/scripts/triage.py) and [skills/ref-manager/scripts/okf_emit.py](../../skills/ref-manager/scripts/okf_emit.py)
  Reference implementations of acquisition triage and OKF-note emission (concepts/papers/people/grants). Use for: ground-truth behavior when docs are ambiguous.
- `graphify query` / `graphify path` / `graphify explain` (this repo's own graphify-out/ graph)
  Fastest way to find where a concept lives in code before reading raw files. Use for: every "where is X" or "how does X connect to Y" question in this repo.

## Wisdom (Communities)

None yet — claude-ref-manager is a personal/small-project plugin, not a large open-source community with an active forum. If it grows a GitHub Discussions or issue tracker with real traffic, add it here.

## Gaps

- No external resource yet on "OKF" note format conventions beyond what's in this repo (docs/concepts.html + okf_emit.py are currently the only source of truth).
- No resource yet on Claude Code plugin/skill authoring conventions specifically — would help when a lesson touches how commands/skills are wired up (commands/*.md -> skills/ref-manager/scripts/*.py).
