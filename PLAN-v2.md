# ref-manager v2 — knowledge layer (phases 12–18)

Status: **draft plan, not started.** Extends [`PLAN.md`](PLAN.md), which stays authoritative for phases 0–11 and every contract it defines (§3a ownership, §3d identifiers, §4a claim/relation, §5c selectors). Nothing here relaxes those contracts; where this plan changes a record shape it says so and states the migration.

Origin: comparison of phases 0–11 against the "Scientific Knowledge Graph Reference Manager" framework (atomic facts, typed graph, ontology, evidence strength, gap/contradiction/hypothesis engines, graph explorer), then a design review of each phase (2026-09-15). Overview figure: [`docs/figures/knowledge-layer-v2.html`](docs/figures/knowledge-layer-v2.html).

---

## 0. Decisions made

Numbering continues from `PLAN.md` §0.

| # | Decision | Consequence |
|---|---|---|
| D29 | **Graph built from library claims only.** No import of external knowledge bases (DrugBank, AHBA, DisGeNET). | Every node and edge traces to a PMID passage; D11 holds. Multi-hop mechanistic chains will be sparse, and presentation must not imply otherwise. |
| D30 | **Small generic entity-type core.** `population`, `condition`, `phenotype_measure`, `intervention_exposure`, `outcome`, `method`, `modality`, `biological_entity`, `anatomical_entity`, `dataset`, plus `unknown`. | Extending the list is an explicit schema bump with a migration note, never an extractor invention. |
| D31 | **Closed predicate list with `associated_with` fallback.** Out-of-vocabulary relationships map to `associated_with` and retain the original verb. | Predicate queries stay reliable. The fallback share is a watched metric (§6): a high share means the list is wrong, not the papers. |
| D32 | **One primary triple per claim, plus typed context entities.** Population, method, modality, and dataset attach as context links, not as extra findings. | Support counts are not inflated by compound sentences. Claim IDs keep their phase-4 stability rules. |
| D33 | **`claim_role` on every claim; `cited` claims are pointers only.** Roles: `own_result`, `background`, `interpretation`, `cited`, `method`. | Cited claims are searchable and resolve to the cited PMID when possible, but never count toward support, replication, or consistency. |
| D34 | **Extraction confidence = deterministic checks + LLM label.** Checks: evidence span found verbatim, locator resolves, share of normalized fields known, direction consistent with span. The model's `high/medium/low` label is displayed separately. | The LLM label never enters evidence scoring, ranking, or bands. |
| D35 | **Inferred edges are never persisted.** `relations.jsonl` holds only reported and reviewed edges; paths and hypotheses are computed on demand. | A saved artifact freezes the inferred paths it showed, with index version IDs, so it stays reproducible without polluting the graph. |
| D36 | **Lazy v1→v2 claim migration.** Existing claims are marked `schema_version: 1`; new extractions write v2; `/ref:extract --upgrade <selector>` re-extracts chosen papers. | Graph views label v1-backed edges as untyped. No library-wide re-extraction cost; overlays follow phase-4 pending rules where spans shift. |
| D37 | **MeSH hierarchy from a pinned local descriptor file.** NLM's yearly MeSH XML is downloaded once per chosen year and recorded in config. MeSH headings are captured per paper as dated observations. | Offline, reproducible tree lookups. A yearly refresh is an explicit command. MeSH indexing that arrives after ingest is a new observation, not a `meta.json` edit (D25 reasoning). |
| D38 | **Only exact reuse applies automatically.** Reusing an existing concept on an exact alias or MeSH-ID match is automatic; new concepts, aliases, parent links, merges, and splits are proposals reviewed in `/ref:verify`. | Safest growth; review load scales with the library, so `/ref:verify` gains per-project batch review (§6 risk 1). |
| D39 | **Merge re-points edges and resets reviews to pending.** The merged-away ID becomes a redirect; duplicate edges are listed, never collapsed silently. | Reviewed `contradicts` decisions survive a merge but must be reconfirmed, because context may differ. |
| D40 | **Ambiguous aliases are allowed and flagged.** One alias may belong to several concepts (CT: cortical thickness / computed tomography). A match on an ambiguous alias never auto-resolves. | The mapper decides with entity type and claim context; the decision is recorded with provenance. Supersedes phase 8's one-alias-one-concept rule. |
| D41 | **Evidence profiles are deterministic and never collapse to one number.** Independence is reported as a min–max range (ungrouped papers widen it); study weights come from a versioned rule table in config; abstract-tier contributions are shown separately; the summary is a rule-derived band (`high/moderate/low/very_low`). | Profiles are rebuildable projections, never stored in `meta.json`. Every displayed profile names its rule-table version. |
| D42 | **Discovery stays evidence-first.** Conflict explanation is a deterministic split by context fields, with an optional LLM moderator hypothesis labelled `hypothesis_generating`; gap-matrix axes are declared per project; hypothesis paths go up to 3 hops, each hop from different PMIDs, within a candidate budget; opportunities reuse existing dataset/method/person records flagged as available to you; feasibility is an explicit match, never a model score. | No output reads as "novel" or "unstudied"; empty cells read "none in this library". |
| D43 | **The graph explorer is a local static HTML file.** Generated under `exports/graph/<id>/`, opened with `file://`, no network, no upload. Personal content (notes, screening, grant links) is excluded unless `--include-personal`. | The file can be shared deliberately without leaking personal records by default. |
| D44 | **Embeddings are gated by a measured recall trigger.** A labelled question set and baseline run are built at the start of phase 12, before any retrieval change; embeddings are added only if recall at the candidate budget falls below a configured threshold. | D3 becomes a measured decision instead of a permanent one. |
| D45 | **Extraction feedback is opt-in and versioned.** Reviewed corrections are curated into a versioned example set; activating one changes the prompt version, so caches miss and re-extraction is explicit. | Existing claims never change silently. Paper→paper `cites` edges come from resolved JATS references, not similarity. |

---

## 1. Framework coverage

| Framework component | Phases 0–11 | Added here |
|---|---|---|
| Reference library, identifiers, notes | done | MeSH observations (13) |
| Document processing with structure | done | `claim_role` separates own results from background/cited (12) |
| Atomic fact store | claims with PICO fields, locator, span | typed triple, context entities, extraction checks (12) |
| Knowledge graph nodes | untyped concepts; people/grants graph | entity types (12), hierarchy + MeSH mapping (13) |
| Relationships with metadata | 5 evidential edge types | controlled semantic predicates, `origin` (12); `cites` edges (18) |
| Provenance, versioning, human review | done | ontology proposals, merge/split review, batch review (13) |
| Confidence & evidence status | study grouping confidence only | evidence profile + bands (14) |
| Contradiction detection | `potential_conflict` / reviewed `contradicts` | null results counted; conflict explanation (14, 15) |
| Gap detection | 4 structural gap types | project gap matrix (15) |
| Hypothesis generation | 2-hop ABC + PubMed check | ≤3 hops, independent routes, convergence, output labels (15) |
| Opportunity engine | — | `/ref:opportunities` over your available resources (15) |
| Graph explorer / Knowledge view | OKF views only | local HTML explorer, hubs/communities/bridges (16) |
| Semantic vector index | deferred (D3) | eval-gated hybrid retrieval (12 baseline, 17) |
| Corrections inform processing | — | versioned extraction examples (18) |

Out of scope by decision: external KB import (D29), Zotero integration, automatic/background ingestion (D9), non-PubMed sources (D11).

---

## 2. Layout additions

```
<LIBRARY>/
  papers/<pmid>/
    mesh.json              # dated MeSH heading observations: descriptor UI, qualifiers,
                           #   major flag, indexing status, retrieved_at, raw source hash
  ontology/
    mesh/<year>/           # pinned NLM descriptor download; never edited
    mappings.jsonl         # concept <-> MeSH descriptor: match type, MeSH year, review state
    hierarchy.jsonl        # broader/narrower links between local concepts, provenance, review
    proposals.jsonl        # pending/accepted/rejected ontology proposals with evidence
    redirects.jsonl        # merged/split/renamed concept IDs -> targets (§3d alias rule)
  graph/
    concepts.jsonl         # + entity_type, per-alias ambiguity flags
    relations.jsonl        # + kind (evidential|semantic), predicate, origin
    references.jsonl       # paper -> paper cites edges from resolved references (phase 18)
  projects/<slug>/
    project.yaml           # + matrix_axes
    analyses/<id>/         # frozen gap matrix / conflict explanation / hypothesis runs
    opportunities/<id>/    # frozen opportunity report: inputs, resources matched, versions
  eval/
    questions.jsonl        # labelled question -> expected PMIDs / claim IDs
    runs/<id>.json         # recall at candidate budget, config + index versions
  extraction/examples/<version>/
    examples.jsonl         # curated reviewed corrections used as few-shot examples
  exports/graph/<id>/
    index.html             # self-contained explorer; manifest.json beside it
  index/
    catalog.sqlite         # + concept_types, mesh_tree, mappings, evidence_profiles tables
```

Everything under `index/` and `exports/` stays rebuildable (§3a). `ontology/*.jsonl` except `mesh/` are authoritative user-reviewed records and follow the atomic-write and library-lock rules.

---

## 3. Contracts

### 3a. Claim v2

Adds to the §4a claim (all v1 fields unchanged):

| Field | Shape | Rule |
|---|---|---|
| `schema_version` | `1` \| `2` | v1 claims lack every field below; readers treat them as untyped |
| `claim_role` | `own_result` \| `background` \| `interpretation` \| `cited` \| `method` | only `own_result` feeds evidence counts (D33) |
| `triple` | `{subject_text, subject_concept_id, predicate, object_text, object_concept_id, original_verb}` | concept IDs may be `null` until mapped; `predicate` from the closed list |
| `context_entities` | `[{text, entity_type, concept_id, role}]` | role ∈ `population`, `method`, `modality`, `dataset`, `anatomical`, `other` |
| `cited_pmid` | string \| `null` | set only for `claim_role: cited` when resolvable |
| `extraction_checks` | `{span_verbatim, locator_resolves, known_field_share, direction_consistent}` | computed in code after the model returns |
| `model_confidence_label` | `high` \| `medium` \| `low` | display only; never read by scoring (D34) |

Predicates (closed list, D31): `increases`, `decreases`, `no_effect_on`, `associated_with`, `predicts`, `mediates`, `moderates`, `measures`, `uses_method`, `uses_dataset`, `targets`, `part_of`, `located_in`, `expressed_in`, `derived_from`.

Direction mapping for evidence: `increase` → +1, `decrease` → −1, `no significant difference` → 0 (null, counted), `not reported` → excluded and counted as missing.

### 3b. Concepts, mappings, proposals

- `concepts.jsonl` gains `entity_type` (D30) and `alias_flags: {<alias>: {"ambiguous": bool}}`. An alias present on two concepts is `ambiguous` on both.
- `mappings.jsonl` row: `mapping_id`, `concept_id`, `mesh_ui`, `match` (`exact|broader|narrower|none`), `mesh_year`, `source` (`auto_exact|proposal:<id>|manual`), `review_state`, timestamps. A MeSH UI is an alias-level attribute, never a concept key (§3d).
- `proposals.jsonl` row: `proposal_id`, `kind` (`new_concept|add_alias|parent|merge|split|mapping|disambiguation`), payload, evidence (claim IDs / passages), proposer (`extractor|weave|manual`), `status` (`pending|accepted|rejected`), reviewer, rationale. Rejected proposals are retained to suppress repeats.
- Merge: under the library lock, re-point relations and mappings to the target, write a redirect, set every affected reviewed relation to `review_state: pending` with the prior decision retained, and report duplicate edges (D39). Split mirrors this with explicit claim reassignment.

### 3c. Relation v2

Adds `kind` (`evidential|semantic`), `predicate` (semantic only; from §3a list), and `origin` (`reported|reviewed`). Existing rows migrate to `kind: evidential, origin: reported|reviewed` from their `review_state`. `supporting_claims` stays mandatory and must reference `claim_role: own_result` claims. Inferred paths have no row (D35). `review_state` gains `pending` for merge/stale reconfirmation.

### 3d. Evidence profile

Computed per relation or concept pair, over active, non-rejected, `own_result` claims:

| Component | Computation |
|---|---|
| Volume | claims, papers, and independent-source range |
| Independence | `min`: papers collapsed by studies **and** shared datasets; `max`: grouped studies + every ungrouped paper; ungrouped count shown |
| Consistency | `C = Σwᵢdᵢ / Σwᵢ` per independent source, plus heterogeneity (share of opposing mass); null counted as 0 |
| Replication | independent sources agreeing in direction under comparable context (§4a comparability) |
| Quality | from reviewed/draft appraisal (`appraise.py`), labelled draft vs reviewed |
| Statistics | share of sources reporting effect + interval; share whose interval excludes null |
| Modality convergence | distinct `modality` context entities among agreeing sources |
| Tier split | every component shown for full-tier vs abstract-tier contributions |

Weights `wᵢ` = rule table in config (`evidence.rules`, versioned): design tier × appraisal result × extraction tier. Bands come from explicit threshold rules in the same table. No 0–100 score (D41). Profiles live in `index/catalog.sqlite` and are frozen into any artifact that displays them.

### 3e. Output classification

Every discovery, synthesis, and explorer output labels each statement: `directly_reported`, `multi_source`, `replicated`, `contradictory`, `computationally_inferred`, `hypothesis_generating`. `computationally_inferred` and `hypothesis_generating` never appear without their evidence chain.

### 3f. Hypotheses and opportunities

A hypothesis candidate carries: path(s) with per-hop PMIDs and relation IDs, independent route count, modality convergence across routes, absence of a direct edge, PubMed check (query, timestamp, PMIDs), and matched resources. There is no single hypothesis score; ranking sorts lexicographically by a configured key order (default: independent routes, convergence, PubMed check empty, resource match). Opportunities join frozen gap/conflict/hypothesis results to datasets, methods, and people flagged `available`; each row names the resource record that makes it feasible.

---

## 4. Slash commands

### New

| Command | Phase | Purpose |
|---|---|---|
| `/ref:eval add\|run\|compare` | 12 (step 0), 17 | maintain labelled questions in `eval/questions.jsonl`; run recall at the candidate budget; compare runs across index/config versions |
| `/ref:ontology sync-mesh --year <yyyy>` | 13 | download and pin one MeSH descriptor year; build `mesh_tree` in the catalog |
| `/ref:ontology backfill-mesh <selector>` | 13 | parse MeSH headings from preserved `raw/` metadata into `mesh.json`; network only when raw lacks them |
| `/ref:ontology map <concept> --mesh <UI> --match exact\|broader\|narrower\|none` | 13 | propose or record a MeSH mapping |
| `/ref:ontology parent <child> <parent>` | 13 | propose a broader/narrower link |
| `/ref:ontology merge <from> <into> --rationale "..."` | 13 | merge concepts; edges re-pointed, reviews → pending |
| `/ref:ontology split <concept> --into <a,b> --rationale "..."` | 13 | split a concept with explicit claim reassignment |
| `/ref:ontology tree <concept>` / `ambiguous` / `proposals [--project <slug>]` | 13 | inspect hierarchy, ambiguous aliases, pending proposals |
| `/ref:evidence <relation-id> \| --pair <a> <b> \| <selector>` | 14 | show evidence profiles with components, band, independence range, tier split, rule version |
| `/ref:opportunities --project <slug>` | 15 | join frozen gaps/conflicts/hypotheses to your available datasets, methods, collaborators |
| `/ref:explore <selector> \| --concept <id> [--include-personal]` | 16 | write the local static graph explorer to `exports/graph/<id>/` |
| `/ref:examples curate\|list\|activate <version>` | 18 | build and activate versioned extraction example sets |

### Extended

| Command | Phase | Change |
|---|---|---|
| `/ref:extract --upgrade <selector>` | 12 | re-extract chosen papers to claim v2 |
| `/ref:weave` | 12 | semantic edges from triples; null results recorded; only `own_result` claims |
| `/ref:concept create --type <entity_type>` | 12–13 | typed concepts; `find` reports ambiguous matches instead of picking one |
| `/ref:add` | 13 | captures MeSH headings as a `mesh.json` observation |
| `/ref:verify proposals [--project <slug>] [--batch]` | 13 | review ontology proposals, merges, ambiguous mappings, pending relation reviews |
| `/ref:compare`, `/ref:ask`, `/ref:summarize`, `/ref:review` | 14 | evidence band + profile column; §3e labels |
| `/ref:gaps --explain-conflicts` | 15 | deterministic context split; optional labelled moderator hypothesis |
| `/ref:gaps --matrix [--project <slug>]` | 15 | gap matrix over project-declared axes |
| `/ref:project axes <slug> <axis...>` | 15 | declare matrix axes (entity types or concept subtrees) |
| `/ref:hypothesize --concept <id> --hops 2\|3 --budget <n>` | 15 | multi-hop, independent routes, convergence, resource match |
| `/ref:study create-dataset\|create-method --available`, `/ref:person --collaborator` | 15 | mark resources available to you |
| `/ref:related --cites <pmid...>` | 18 | persist resolved references as `cites` edges |

---

## 5. Build order

| Phase | Deliverable | Main files | Gate |
|---|---|---|---|
| 12 | **Step 0:** `/ref:eval` with an initial labelled question set and a recorded baseline run. **Then:** claim v2 schema, `claim_role`, typed triple and context entities, extraction checks + display-only label, entity types, closed predicates, relation v2, v1→v2 lazy migration, `/ref:extract --upgrade`, `/ref:weave` semantic edges | `lib_schema.py`, `extract.py`, `agents/ref-extractor.md`, `concept.py`, `relation.py`, `catalog.py`, `okf_emit.py`, new `eval.py` | Baseline run stored before any retrieval change; a v1 library rebuilds identically after migration; a cited claim never appears in `supporting_claims`; an out-of-vocabulary verb lands as `associated_with` with `original_verb` kept; extraction checks flag a fabricated span; the LLM label changes no count or ranking; no inferred edge is written to `relations.jsonl` |
| 13 | MeSH capture + backfill, pinned MeSH tree, mappings, hierarchy, proposals queue, merge/split/redirects, ambiguous aliases, `/ref:ontology`, `/ref:verify proposals --batch` | `add.py`, new `ontology.py`, `concept.py`, `relation.py`, `verify.py`, `lib_ids.py`, `catalog.py` | Backfill reads MeSH from `raw/` without network when present; later MeSH indexing appends an observation; only exact alias/MeSH-ID reuse applies without review; a merge keeps old IDs resolving, re-points edges, and sets reviewed edges pending; an ambiguous alias never auto-resolves; a rejected proposal is not re-proposed; `/ref:index --rebuild` reproduces mappings and hierarchy |
| 14 | Evidence profile engine, versioned rule table, bands, tier split, `/ref:evidence`, profile columns in compare/ask/summarize/review, §3e labels | new `evidence.py`, `compare.py`, `ask_retrieve.py`, `summarize.py`, `appraise.py`, `catalog.py` | Three papers sharing one dataset yield independence `1–1`, and three ungrouped papers yield `1–3`; "all null" and "half up, half down" produce different consistency/heterogeneity; abstract-only profiles are flagged; changing the rule table changes the version shown and is reproducible; no display contains a single numeric score |
| 15 | `/ref:gaps --explain-conflicts` and `--matrix`, project axes, `/ref:hypothesize --hops 3 --budget`, available-resource flags, `/ref:opportunities`, frozen `analyses/` and `opportunities/` artifacts | `gaps.py`, `hypothesize.py`, `project.py`, `study.py`, `person.py`, new `opportunities.py` | Conflict split names the separating fields or reports "too few to separate"; LLM moderator text is always labelled `hypothesis_generating`; empty matrix cells read "none in this library"; every hop of a 3-hop path has distinct PMIDs; budget truncation is reported; each opportunity names the resource record that makes it feasible; frozen artifacts reproduce |
| 16 | `/ref:explore` static HTML explorer: filter by entity type, predicate, band, date; expand neighbours; evidence drawer to passages; hubs, communities (label propagation), bridges; per-paper Knowledge view; personal content opt-in | new `explore.py`, `okf_emit.py`, `catalog.py` | Opens offline via `file://` with no network requests; every edge reaches a passage locator; stale edges are marked; default export contains no notes, screening, or grant links; community output is stable for a fixed index version |
| 17 | *Conditional.* If `/ref:eval run` recall at budget is below `eval.recall_threshold`: local embeddings as a rebuildable index, hybrid rank fusion in `/ref:ask` | `catalog.py`, `ask_retrieve.py`, `eval.py` | Recall improves over the phase 12 baseline on the same question set with no regression in conflicting-evidence inclusion or citation resolution; the index rebuilds from committed records; otherwise the phase is recorded as not triggered |
| 18 | `/ref:examples` versioned example sets feeding the extractor prompt; `/ref:related --cites` resolved references as `cites` edges | `extract.py`, new `examples.py`, `related.py`, `convert.py` | Activating an example set bumps the prompt version and misses cache; no existing claim changes without explicit re-extraction; unresolved references are listed, not dropped |

Order: **12 → 13 → 14, then re-plan 15–18** after running them on one real thesis question. Phase 17 runs only if triggered; 18 can follow any time after 12.

**Acceptance test (v2).** Take one project question with ~20 papers: upgrade their claims, map concepts with MeSH, review proposals, and produce a comparison whose rows carry evidence bands and independence ranges; explain one disagreement by context; generate hypotheses with frozen evidence chains; open the explorer offline and trace one edge to its passage.

---

## 6. Risks and watched metrics

1. **Review load (D38).** Nearly every ontology change is a proposal. Watch pending-proposal count per project; mitigate with batch review and per-project scoping before relaxing auto-apply.
2. **`associated_with` fallback share (D31).** If it exceeds a threshold you set on real extractions, revise the predicate list with a schema bump rather than accepting a vague graph.
3. **Study grouping coverage (D41).** Independence ranges stay wide and bands low until studies/datasets are grouped. Report ungrouped counts prominently; this is intended pressure, not a defect.
4. **Eval before retrieval changes (D44).** Phase 12 step 0 must land first, or phase 17's trigger has no baseline.
5. **Sparse mechanistic chains (D29).** Claims-only graphs will rarely produce drug → target → region paths; 3-hop results must say how many routes were found and not imply coverage.
6. **MeSH drift (D37).** A new MeSH year can move tree positions; mappings record their year and a year change produces proposals, not silent rewrites.

---

## 7. First step

Build `/ref:eval` and record a baseline on a small labelled question set from a real project. Then implement claim v2 on a three-paper fixture (one own result, one cited finding, one null result), migrate an existing v1 fixture library, and confirm the phase 12 gate before touching the ontology.
