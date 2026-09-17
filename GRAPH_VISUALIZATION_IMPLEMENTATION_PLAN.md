# Graph Visualization Implementation Plan

Date: 2026-09-17
Status: Implemented — Phases 1–5, including the optional cluster map (see "Implementation notes" at the end)
Area: Dashboard Insights tab — graph, claim-network and gap views
Mockup: https://claude.ai/artifact/6WF6r3SCwc8iqBdpFogWjD (sample data)

## What changed from v1

v1 proposed a new Graph tab, new `/api/graph/*` endpoints, new concept
extraction, a new contradiction model and a new gap summarizer. Review found
most of that already exists or conflicts with committed semantics:

| v1 proposal | Reality in the repo | v2 decision |
|---|---|---|
| New Graph tab | Insights tab (`app.js` `INSIGHT_VIEWS`) already has Evidence map, Gaps, Topic timeline, Knowledge graph (Concepts / Papers & authors / Claim network), Clusters, Synthesis draft | Extend the Insights tab; no new tab |
| `/api/graph/summary`, `/neighborhood`, `/concepts`, `/claims`, `/gaps` | `/api/knowledge` (`dashboard_insights.knowledge()`) already ships papers (MeSH, authors), active claims, concepts, relations; static builds inline the same payload | No new endpoints. Extend the `knowledge()` payload; keep all derivation client-side so static mode keeps working |
| Concept extraction from titles/abstracts/MeSH + new clustering | `graph/concepts.jsonl` (`concept.py`) holds human-confirmed concepts with aliases; `topicIndex()` + `labelPropagation()` already cluster MeSH, concepts and claim fields | Reuse. Concept identity always resolves through the concept registry and its aliases |
| Claim ↔ claim `contradicts` edges, green/red coding | Relations are concept ↔ concept (`subject_concept_id`, `object_concept_id`) with `supporting_claims`; types `supports`, `potential_conflict`, `contradicts`, `extends`, `replicates`; `contradicts` only via reviewed `/ref:weave review` with rationale; `stale` flag | Encode all five types plus review state and staleness; never show an unreviewed `potential_conflict` as a contradiction |
| "Sparse cell" gap heatmap | `gaps.py` defines four deterministic gap types; `population_outcome_gap` = uncovered population × outcome for one intervention concept, citing backing claim_ids. The Insights Gaps view uses a different heuristic (`findGaps` score) | Add the `gaps.py` definition as the primary gap grid; keep the heuristic list, labelled as a heuristic |
| Colour by "evidence strength" (`evidence_tier`) | `evidence_tier` is `abstract` or `full` — extraction depth, not study quality. Quality lives in `appraise.py` reviews (RoB 2 / NOS / AMSTAR 2, GRADE) under `reviews/<batch>/` | Label tier as "extraction: abstract / full text". Appraisal overlay is a later, optional phase |
| Phase 1 = graph + summary cards + cluster summaries + insight cards | Several insight cards need Phase 2–4 data | Phase 1 = neighborhood mode + selection panel + insight cards computed only from data already in the payload |
| Maturity scorecard, no formula | — | Deferred; explicit formula below, components shown, not a single opaque score |
| Accessibility: keyboard "where practical" | Graph nodes are already focusable; no non-visual equivalent of the graph | Every graph mode gets a "Table" toggle listing nodes and edges |
| Cached graph summaries | `/api/knowledge` re-reads every paper on each request (`Cache-Control: no-store`, no server memo) | Add a server-side memo with explicit invalidation |

---

## Current state (shipped in 5783b81)

All in `skills/ref-manager/scripts/dashboard_assets/app.js`, data from
`dashboard_insights.knowledge()`:

- **Scope**: `insightScope()` — Papers-tab filters (when "follow" is on) plus a year range.
- **Knowledge graph** (`buildGraph`, `forceLayout`, `renderGraph`): top-N (20–200) nodes,
  deterministic Fruchterman–Reingold layout, zoom buttons, click/Enter selects a node and
  the side panel lists its neighbours and papers.
  - *Concepts*: co-occurrence of terms, coloured by label-propagation cluster.
  - *Papers & authors*: papers ↔ top terms, authors with ≥2 papers.
  - *Claim network*: intervention / outcome / population nodes; intervention→outcome edges
    coloured by dominant direction; relations overlaid — all `supports`/`extends`/`replicates`
    share one green dashed style, `potential_conflict` and `contradicts` share one red dashed style.
- **Clusters** (`computeClusters`, `renderClusters`): cluster cards with term chips and year span.
- **Topic timeline** (`renderTimeline`): up to 8 terms per year.
- **Gaps** (`renderGaps`): heuristic sparse pairs, single-study intervention→outcome pairs,
  unresolved conflicts (same rule as `gaps.unresolved_conflicts`), copyable `/ref:gaps` command.
- **Evidence map**, **Synthesis draft**.

## Gaps this plan closes

1. No view centred on one paper or concept (the graph is always global top-N).
2. No "what is notable" digest at the top of the Insights tab.
3. Relation types and review state are collapsed into two styles; relation rationale is not visible.
4. Gaps view does not use the `gaps.py` definitions the `/ref:gaps` command reports.
5. Clusters have no trend, so "emerging" or "fading" topics are not surfaced.
6. No text equivalent of graph views.
7. `/api/knowledge` has no caching.

---

## Design principles

1. Extend the Insights tab; no separate graph app or tab.
2. One source of truth: claim registries, `graph/concepts.jsonl`, `graph/relations.jsonl`.
   The dashboard never re-derives relations or concept identity.
3. Client-side derivation from the knowledge payload, so `/ref:dashboard --static` renders the same views.
4. Read-only. Review and extraction stay in commands; the dashboard offers copyable commands.
5. Deterministic, no LLM judgment (same rule as the existing Insights code).
6. Local and filtered by default; caps on visible nodes.
7. Every colour meaning also has a text label, line style or glyph.

---

## Data changes (`dashboard_insights.knowledge()`)

Additive fields only; existing consumers ignore unknown keys.

```json
{
  "relations": [{
    "id": "rel-…", "type": "potential_conflict",
    "subject": "parent-mediated-intervention", "object": "parent-stress",
    "pmids": ["…"],
    "claim_ids": ["…"],
    "review_state": "unreviewed", "stale": false,
    "rationale": null, "reviewed_at": null
  }],
  "claims": [{ "…existing fields…": "", "timepoint": "12 months" }],
  "meta": { "cache_key": "…", "generated_at": "…" }
}
```

- `relations[].claim_ids` — from `supporting_claims[].claim_id`, so a relation edge can link to exact claims.
- `relations[].rationale`, `reviewed_at` — shown in the relation detail panel.
- `claims[].timepoint` — needed to explain why a `potential_conflict` is only potential (comparability in `relation.comparable()`).
- `meta.cache_key` — see Performance.

Not added in v2: `evidence_span` (large; `co_mentioned_ungrouped` stays a `/ref:gaps` command result) and appraisal data (Phase 5).

---

## Phases

### Phase 1: Neighborhood mode, insight cards, table fallback

**Goal**: inspect one paper or concept and its local connections.

Scope:
- Add a fourth Knowledge graph mode, **Neighborhood**, centred on a selected paper or concept.
  Entry points: a node's "Center here" action, a paper drawer "Show in graph" action, and the
  `insight=` view URL param (`VIEW_PARAM_KEYS` already includes `insight`).
- Hop control: 1 or 2 hops. Node types: paper, concept (via `topicIndex` terms resolved through
  concept aliases), author, claim. Edges: mentions, authored, reports, supports-claim,
  potential-conflict (from relations touching the centre's claims).
- Radial layout (centre, hop-1 ring, hop-2 ring) instead of force layout: stable, readable, cheap.
- Insight-card row above the Insights body, **computed only from current payload**:
  most connected paper in scope, open conflicts count (`unresolvedConflicts`), single-study
  findings count, papers in scope with 0 active claims. Clicking a card focuses the node or
  applies the Papers-tab filter chip (`applyPmidFilter`).
- "Graph / Table" toggle for every graph mode: sortable node table (label, type, papers, degree)
  and edge table (from, to, kind, papers).

Acceptance:
- Neighborhood renders for a paper with ≥1 concept or author link; an unlinked paper shows an
  empty state naming the fix (`/ref:extract`, `/ref:weave`).
- ≤100 nodes at 2 hops; the cap is shown when hit.
- Selection panel reuses the existing side panel; "Open paper" opens the existing drawer.
- Table view lists the same nodes/edges as the graph, keyboard reachable.
- Works in static and live mode.

Tasks:
1. `buildNeighborhood(scope, centerId, hops)` in `app.js` next to `buildGraph`.
2. `radialLayout(nodes, centerId)`.
3. Mode button + hop control in `renderGraph`; `ins.center`, `ins.hops` in URL state.
4. `renderInsightCards(scope)` above `ins-body`.
5. `renderGraphTable(graph)` and toggle.
6. Drawer "Show in graph" button.

### Phase 2: Relation-aware claim network

**Goal**: show what the relation graph actually records, including review state.

Scope:
- Encode each relation type distinctly (see Encoding).
- Relation detail in the side panel: type, review state, stale flag, rationale, reviewed date,
  supporting claims (`claim_ids` → claim rows via `claimTable`), and the copyable command
  `/ref:weave review <relation-id> <type> --rationale "…"` for unreviewed or stale relations.
- Legend toggles per relation type and a "reviewed only" filter.
- Direction-inferred conflicts (up and down on the same intervention→outcome edge) keep a
  separate label, "mixed direction", so they are not confused with recorded relations.
- Extraction filter: all / full text only (`tier`).

Acceptance:
- `potential_conflict` (unreviewed) and `contradicts` (reviewed) are visually and textually distinct.
- Stale relations are marked stale.
- A relation edge links to its supporting claims and papers.

Tasks:
1. Payload fields (`claim_ids`, `rationale`, `reviewed_at`, `timepoint`) + tests in `test_dashboard.py`.
2. `edgeStyle()` per relation type and state; legend update.
3. Relation detail panel + command copy.
4. Filters.

### Phase 3: Gap grid aligned with `gaps.py`

**Goal**: the dashboard and `/ref:gaps` agree on what a gap is.

Scope:
- New Gaps sub-view **Population × outcome**: pick an intervention concept (concept registry);
  rows/columns are the populations and outcomes of that intervention's own claims, exactly as
  in `gaps.population_outcome_gap()`. Every uncovered cell is a gap; the detail panel lists
  `population_evidenced_by` / `outcome_evidenced_by` claim ids.
- Port the rule to JS; guard with a shared fixture test so JS and Python outputs match.
- Keep the existing sparse-pair list, renamed "Sparse pairs (heuristic)" with its scoring line.
- Gap detail offers `/ref:search-pubmed` and `/ref:gaps --project <slug>` commands (existing `gapActions`).

Acceptance:
- For the same library and selector, the grid's gap cells equal `/ref:gaps` `population_outcome_gap` findings.
- Heuristic and rule-based gaps are labelled differently.

Tasks:
1. `populationOutcomeGaps(claims, concept)` in `app.js`, matching intervention names/aliases case-insensitively.
2. Grid rendering (reuse evidence-map cell styles; hatched gap cells with a text "gap" label).
3. Fixture test: Python finding set vs JS output (run the JS via the existing test harness, or
   compare against a JSON snapshot generated from `gaps.py`).

### Phase 4: Cluster trends

**Goal**: surface growing and fading topics.

Scope:
- Per-cluster papers-per-year series in cluster cards (sparkline) from `BY_PMID[].year`.
- Trend label from papers in the last 5 years vs the previous 5 (ratio last/previous):
  "growing" ≥ 1.25×, "fading" ≤ 0.8×, otherwise "stable"; shown only when both windows
  have ≥3 papers. The detail panel shows both counts and the ratio.
- Optional cluster map: clusters as nodes, edges = shared papers (≥2).
- Insight cards gain "growing topic" / "fading topic".

Acceptance:
- Trend labels are reproducible from the displayed counts.
- Small clusters show counts without a trend label.

### Phase 5 (deferred): Maturity and appraisal overlay

Only after Phases 1–4 ship and are used.

- **Maturity components**, shown individually per intervention concept (no single blended score in v1 of this phase):
  - Volume: papers with active claims.
  - Outcome breadth: distinct outcomes / outcomes seen for any intervention in scope.
  - Coverage: covered population × outcome cells / all cells (Phase 3 grid).
  - Full-text share: claims with `tier = full` / all claims.
  - Open conflicts: unreviewed `potential_conflict` + stale `contradicts`.
- **Appraisal overlay**: if a `reviews/<batch>/grade.json` exists for the scope, show GRADE
  certainty per outcome; requires a new optional `reviews` block in the knowledge payload.

---

## Encoding

| Element | Encoding |
|---|---|
| Paper / concept / author / claim node | colour **and** shape (circle, filled circle sized by papers, ring, diamond) |
| intervention → outcome edge | colour by dominant direction + glyph ↑ ↓ → in labels; "mixed direction" label when up and down |
| `supports` | solid green |
| `replicates` | solid green, double line |
| `extends` | solid blue |
| `potential_conflict` (unreviewed) | dashed amber, label "potential conflict — unreviewed" |
| `contradicts` (reviewed) | solid red, label "contradicts — reviewed" |
| stale relation | any of the above at reduced opacity + "stale" tag |
| Extraction tier | chip "abstract" / "full text" (never called evidence strength) |
| Gap cell | hatched + text "gap" |

Colours come from existing tokens (`--good`, `--warn`, `--crit`, `--c5`); no new palette.

---

## Performance

- Server: memoise `knowledge()` per server process, keyed by a cheap signature — mtimes of
  `graph/concepts.jsonl`, `graph/relations.jsonl`, and the newest `claim_registry.json` mtime
  from `lib_inventory.rows()` (already loaded). Recompute on key change; the existing refresh
  button forces recompute. Keep `Cache-Control: no-store` (the token model stays unchanged).
- Client: neighborhood cap 100 nodes; global graph keeps the existing 20–200 slider;
  radial layout is O(n); force layout stays O(n²) and only runs for global modes.
- Recompute derived structures on scope change, not on hover.

## Accessibility

- Graph/Table toggle on every graph mode (Phase 1).
- Nodes stay focusable with Enter/Space to select (existing); add arrow-key moves between
  neighbours of the selected node in Neighborhood mode.
- Legends list every encoding in text; no colour-only meaning.
- `prefers-reduced-motion`: no animated layout transitions.

## Testing

- `tests/test_dashboard.py`: new payload fields, cache key changes when relations/concepts/claims change.
- `tests/test_dashboard_serve.py`: `/api/knowledge` still token-protected; memo returns fresh data after a relation review.
- `tests/test_phase9_gaps.py` fixtures reused for the JS/Python gap parity check.
- Manual: static build renders Neighborhood, Claim network and Gap grid; a 1,000+ paper library
  keeps the Insights tab responsive; unreviewed vs reviewed conflicts are distinguishable in
  greyscale.

## Risks

- **Concept coverage is thin** (concepts only exist after `/ref:weave`): Neighborhood and gap
  grid show an empty state naming `/ref:weave`; MeSH terms still populate Concepts mode.
- **Free-text claim fields fragment rows/columns** ("preschool ASD" vs "preschool children with autism"):
  resolve through concept aliases where mapped; show unmapped values as-is, never guess merges.
- **JS/Python gap drift**: parity test in CI.
- **`app.js` size** (4.6k lines): put new code in clearly delimited sections next to the existing
  Insights code; split into a separate asset only if the file passes ~6k lines.

## Implementation order

1. Phase 1 — Neighborhood mode, insight cards, table fallback.
2. Phase 2 — payload fields + relation-aware claim network.
3. Phase 3 — gap grid with `gaps.py` parity.
4. Phase 4 — cluster trends.
5. Phase 5 — maturity components and appraisal overlay (only if needed).
6. `/api/knowledge` memo can land with Phase 1 or independently.
7. Update `commands/dashboard.md` Insights bullet and `docs/tutorials/library-viewer.html` per phase.

---

## Implementation notes (2026-09-17)

Deviations and additions made while implementing:

- **GRADE is per review batch, not per outcome.** `appraise.grade_certainty()` writes one
  certainty for a batch's whole paper set (`reviews/<batch>/grade.json`), so the Phase 5
  overlay shows certainty per batch and never relabels it per outcome. The knowledge payload
  carries a `reviews` block (manifest, grade, per-paper appraisal summary re-merged with
  current appraisal corrections); `appraise.appraisal_signal()` is the shared per-paper
  risk-of-bias reading.
- **Placeholder claim values.** `lib_schema.clean_claim_value()` is the single definition of
  "no value"; `gaps.population_outcome_gap()` and the dashboard both use it, so the JS/Python
  parity test also covers "not reported"-style values and whitespace variants.
- **Clustering links terms only above chance** (≥ 1.5× the expected co-occurrence, scopes of
  20+ papers). Plain counts merged every topic into one cluster through terms present in most
  papers.
- **Interactive graphs.** Knowledge graph and cluster map share one SVG renderer: nodes drag
  (positions persist until "Re-layout"), the background pans, ⌘/Ctrl + wheel zooms, Shift +
  arrows move a focused node.
- **Entry by URL** uses `center` / `hops` params alongside `insight`.
- **Alias folding (Risks).** `gaps.population_outcome_gap()` and the dashboard grid both fold a
  population/outcome that exactly matches a concept's name or alias onto that concept; other
  values stay as written. The JS/Python parity test covers it.
- **CI.** `.github/workflows/tests.yml` runs the full suite on Python 3.11 and 3.12 with node 20;
  `REF_REQUIRE_NODE=1` turns the node-based JS tests from skip into fail if node is missing.
- **Split.** The Insights tab moved to `dashboard_assets/insights.js` (a `RefDashInsights(ctx)`
  factory loaded before `app.js`); `app.js` passes it the shared page state, with getters for
  values refresh reassigns. Both files are served, copied into static builds and syntax-checked
  in CI.
