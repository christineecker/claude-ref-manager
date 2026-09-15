# Graph Report - .  (2026-09-15)

## Corpus Check
- 147 files · ~151,380 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1391 nodes · 3284 edges · 58 communities (50 shown, 8 thin omitted)
- Extraction: 91% EXTRACTED · 9% INFERRED · 0% AMBIGUOUS · INFERRED: 301 edges (avg confidence: 0.69)
- Token cost: 1,186,832 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Ingestion & OKF Emit Pipeline|Ingestion & OKF Emit Pipeline]]
- [[_COMMUNITY_Selector, Audit & Export Pipeline|Selector, Audit & Export Pipeline]]
- [[_COMMUNITY_People, Grants & Identifiers|People, Grants & Identifiers]]
- [[_COMMUNITY_Repo Init, Schema & Screening|Repo Init, Schema & Screening]]
- [[_COMMUNITY_Core Design Docs & Extraction Concepts|Core Design Docs & Extraction Concepts]]
- [[_COMMUNITY_Papers.app Export & Handoff|Papers.app Export & Handoff]]
- [[_COMMUNITY_Appraisal & Claim Verification|Appraisal & Claim Verification]]
- [[_COMMUNITY_Acquisition Tests (Phase 3)|Acquisition Tests (Phase 3)]]
- [[_COMMUNITY_SummarizeReview Tests (Phase 10)|Summarize/Review Tests (Phase 10)]]
- [[_COMMUNITY_Concept Graph & GapHypothesis Discovery|Concept Graph & Gap/Hypothesis Discovery]]
- [[_COMMUNITY_Extraction Tests (Phase 4)|Extraction Tests (Phase 4)]]
- [[_COMMUNITY_OKF & Related-Papers Tests|OKF & Related-Papers Tests]]
- [[_COMMUNITY_Compare Tests (Phase 5)|Compare Tests (Phase 5)]]
- [[_COMMUNITY_Gaps Tests (Phase 9)|Gaps Tests (Phase 9)]]
- [[_COMMUNITY_Annotation & Vision Cache Tests|Annotation & Vision Cache Tests]]
- [[_COMMUNITY_Brief & Compare Scripts|Brief & Compare Scripts]]
- [[_COMMUNITY_AskRetrieve Tests (Phase 6)|Ask/Retrieve Tests (Phase 6)]]
- [[_COMMUNITY_Audit Tests (Phase 11)|Audit Tests (Phase 11)]]
- [[_COMMUNITY_Concept Graph Tests (Phase 8)|Concept Graph Tests (Phase 8)]]
- [[_COMMUNITY_Check-Citations Tests (Phase 7)|Check-Citations Tests (Phase 7)]]
- [[_COMMUNITY_Papers.app Tests (Phase 3)|Papers.app Tests (Phase 3)]]
- [[_COMMUNITY_InitCatalog Tests (Phase 0)|Init/Catalog Tests (Phase 0)]]
- [[_COMMUNITY_PRISMA Tests (Phase 5)|PRISMA Tests (Phase 5)]]
- [[_COMMUNITY_Methods & Study Records|Methods & Study Records]]
- [[_COMMUNITY_Docs AcquireAPI Command Reference|Docs: Acquire/API Command Reference]]
- [[_COMMUNITY_Docs People & Maintenance Commands|Docs: People & Maintenance Commands]]
- [[_COMMUNITY_Docs Knowledge Layer v2 & Extraction Fan-out|Docs: Knowledge Layer v2 & Extraction Fan-out]]
- [[_COMMUNITY_PRISMA Flow Script|PRISMA Flow Script]]
- [[_COMMUNITY_Docs Appraisal & Synthesis Commands|Docs: Appraisal & Synthesis Commands]]
- [[_COMMUNITY_Docs Systematic Review Tutorials|Docs: Systematic Review Tutorials]]
- [[_COMMUNITY_Docs Knowledge Graph & OKF Bundle|Docs: Knowledge Graph & OKF Bundle]]
- [[_COMMUNITY_Docs Command Index Cross-links|Docs: Command Index Cross-links]]
- [[_COMMUNITY_Docs Skill Definition & Maintenance|Docs: Skill Definition & Maintenance]]
- [[_COMMUNITY_Docs Papers.app Handoff Tutorial|Docs: Papers.app Handoff Tutorial]]
- [[_COMMUNITY_Publications & Authorship Script|Publications & Authorship Script]]
- [[_COMMUNITY_Related-Papers Script|Related-Papers Script]]
- [[_COMMUNITY_Docs Getting Started & Project Commands|Docs: Getting Started & Project Commands]]
- [[_COMMUNITY_Figure Vision Cache|Figure Vision Cache]]
- [[_COMMUNITY_Docs Selector Grammar & Organize Scripts|Docs: Selector Grammar & Organize Scripts]]
- [[_COMMUNITY_Docs Ingest & Ownership Workflows|Docs: Ingest & Ownership Workflows]]
- [[_COMMUNITY_Docs Design Decisions & Identifier Contract|Docs: Design Decisions & Identifier Contract]]
- [[_COMMUNITY_Plugin Marketplace Manifest Fields|Plugin Marketplace Manifest Fields]]
- [[_COMMUNITY_Docs AskBriefSummarize Commands|Docs: Ask/Brief/Summarize Commands]]
- [[_COMMUNITY_Docs Search & PubMed Query Commands|Docs: Search & PubMed Query Commands]]
- [[_COMMUNITY_Docs Notes & Papers.app Sync|Docs: Notes & Papers.app Sync]]
- [[_COMMUNITY_Search Script|Search Script]]
- [[_COMMUNITY_Note Script|Note Script]]
- [[_COMMUNITY_App Icon (SVG Source)|App Icon (SVG Source)]]
- [[_COMMUNITY_App Icon (128px)|App Icon (128px)]]
- [[_COMMUNITY_Plugin Manifest Files|Plugin Manifest Files]]
- [[_COMMUNITY_Unpaywall Fetch Link|Unpaywall Fetch Link]]
- [[_COMMUNITY_App Icon (512px)|App Icon (512px)]]
- [[_COMMUNITY_FreezeRefresh Manifest Contract|Freeze/Refresh Manifest Contract]]
- [[_COMMUNITY_List Datasets Function|List Datasets Function]]
- [[_COMMUNITY_List Methods Function|List Methods Function]]
- [[_COMMUNITY_List Studies Function|List Studies Function]]
- [[_COMMUNITY_Show Summary Function|Show Summary Function]]

## God Nodes (most connected - your core abstractions)
1. `SchemaError` - 76 edges
2. `atomic_write_json()` - 56 edges
3. `SlugError` - 50 edges
4. `SelectorError` - 43 edges
5. `lib_atomic module` - 41 edges
6. `Commands index doc page` - 40 edges
7. `atomic_write_text()` - 23 edges
8. `lib_ids module` - 21 edges
9. `run_export_papers()` - 20 edges
10. `lib_schema module` - 20 edges

## Surprising Connections (you probably didn't know these)
- `Evidence profile (D41)` --semantically_similar_to--> `Citation observations (D25)`  [INFERRED] [semantically similar]
  PLAN-v2.md → PLAN.md
- `/ref:review command` --semantically_similar_to--> `/ref:compare command`  [INFERRED] [semantically similar]
  commands/ref-review.md → docs/commands/index.html
- `lib_schema.py` --semantically_similar_to--> `lib_schema.py`  [INFERRED] [semantically similar]
  skills/ref-manager/SKILL.md → docs/concepts.html
- `/ref:ask command` --calls--> `ref-synthesizer subagent`  [EXTRACTED]
  docs/commands/find.html → skills/ref-manager/scripts/summarize.py
- `/ref:summarize command` --calls--> `ref-synthesizer subagent`  [EXTRACTED]
  commands/ref-summarize.md → skills/ref-manager/scripts/summarize.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Freeze/Refresh Manifest Contract (§5c)** — scripts_export_run_export, scripts_compare_run_compare, scripts_brief_save_brief, scripts_appraise_run_review [EXTRACTED 1.00]
- **Unified Conversion Backend Contract (D16/D17)** — scripts_convert_convert_jats, scripts_convert_convert_html, scripts_convert_convert_plain_text, scripts_convert_convert_pdf [EXTRACTED 1.00]
- **Study-Type-to-Checklist Dispatch** — scripts_appraise_rob2_appraisal, scripts_appraise_nos_appraisal, scripts_appraise_amstar2_appraisal, scripts_appraise_draft_appraisal_for_pmid [EXTRACTED 1.00]
- **Atomic write + library/PMID lock persistence pattern** — scripts_lib_atomic_atomic_write_json, scripts_lib_ids_allocate_slug, scripts_relation_create_relation, scripts_person_create, scripts_project_create [INFERRED 0.85]
- **Selector-resolve-then-work command flow** — scripts_lib_selector_resolve, scripts_methods_main, scripts_queue_set_state [INFERRED 0.75]
- **Concept-relation graph traversal and rendering** — scripts_relation_neighbors, scripts_hypothesize_candidates, scripts_okf_emit_write_concept [INFERRED 0.85]
- **verify.py's six-target-type review/correction dispatch** — verify_review_claim, verify_review_grant_link, verify_review_author_contribution, verify_review_person_identity, verify_review_appraisal, verify_corrections_json [EXTRACTED 1.00]
- **summarize.py's freeze/refresh evidence lifecycle over candidates and manifest** — summarize_build_candidates, summarize_run_summarize, summarize__withdrawn_evidence, lib_verify_link [EXTRACTED 0.90]
- **study/dataset/method three distinct but related grouping relationships** — study_studies_jsonl, study_datasets_jsonl, study_methods_jsonl [EXTRACTED 0.90]
- **Commands sharing the §5c selector grammar** — concept_selector_grammar, commands_ref_ask, commands_ref_compare, commands_ref_export, commands_ref_gaps, commands_ref_audit [EXTRACTED 1.00]
- **ReadCube Papers export handoff** — commands_ref_export_papers, scripts_export_papers, concept_papers_app, concept_citekey [EXTRACTED 1.00]
- **Claim extraction pipeline** — commands_ref_extract, agents_ref_extractor, scripts_extract, concept_extraction_tiers [EXTRACTED 1.00]
- **Concept mapping and relation review flow** — ref_weave, ref_manager_concept_py, ref_manager_relation_py, graph_concepts_jsonl, graph_relations_jsonl [EXTRACTED 1.00]
- **Appraisal draft-review-confirm flow** — ref_review, ref_manager_appraise_py, ref_verify, ref_manager_verify_py [EXTRACTED 1.00]
- **PRISMA flow count derivation from queries and screening** — ref_review, ref_manager_prisma_py, ref_search_pubmed, ref_screen [INFERRED 0.75]
- **Frozen-selector artifact pattern** — docs_concepts_selectorgrammar, commands_write_refcompare, commands_write_refsummarize, commands_write_refbrief, commands_write_refexport [INFERRED 0.85]
- **Papers.app round-trip handoff** — commands_maintain_refopen, commands_write_refexportpapers, commands_maintain_refpullannotations, figures_paperrepoanatomy_papershandoff [EXTRACTED 1.00]
- **PI identity-to-report evidence chain** — commands_people_refperson, commands_people_refdiscover, commands_organize_refverify, commands_people_refpublications, commands_people_refreport [EXTRACTED 1.00]

## Communities (58 total, 8 thin omitted)

### Community 0 - "Ingestion & OKF Emit Pipeline"
Cohesion: 0.05
Nodes (82): audit module, lib_atomic module, publications module, attach_one(), _check_identity(), main(), _normalize(), _pdf_head_text() (+74 more)

### Community 1 - "Selector, Audit & Export Pipeline"
Cohesion: 0.05
Nodes (70): cite module, export module, lib_selector module, lib_status_check module, lib_verify_link module, report module, audit_citation_observation(), audit_retraction_status() (+62 more)

### Community 2 - "People, Grants & Identifiers"
Cohesion: 0.06
Nodes (62): /ref:discover command, /ref:grant command, note module, person module, queue module, main(), add_alias(), create() (+54 more)

### Community 3 - "Repo Init, Schema & Screening"
Cohesion: 0.06
Nodes (64): /ref:init command, ref-synthesizer Subagent, lib_schema module, add_one(), _first_author_lastname(), _first_title_word(), _flag_doi_title_conflicts(), main() (+56 more)

### Community 4 - "Core Design Docs & Extraction Concepts"
Cohesion: 0.05
Nodes (60): ref-extractor agent, ref-synthesizer agent, /ref:ask command, /ref:attach command, /ref:audit command, /ref:brief command, /ref:check-citations command, /ref:cite command (+52 more)

### Community 5 - "Papers.app Export & Handoff"
Cohesion: 0.07
Nodes (55): Exception, export_papers module, papers_snapshot module, _allocate_path(), _escape_bibtex(), _is_foreign(), _last_author_lastname(), layout_relative_path() (+47 more)

### Community 6 - "Appraisal & Claim Verification"
Cohesion: 0.08
Nodes (55): AMSTAR-2 Checklist, GRADE Certainty Rating, Newcastle-Ottawa Scale, ref-extractor Subagent, RoB 2 Risk-of-Bias Checklist, _active_claims(), amstar2_appraisal(), _batch_dir() (+47 more)

### Community 7 - "Acquisition Tests (Phase 3)"
Cohesion: 0.06
Nodes (21): attach module, convert module, convert_html_worker.main, fetch module, funding_extract module, author(), TempLibrary, TestAttach (+13 more)

### Community 8 - "Summarize/Review Tests (Phase 10)"
Cohesion: 0.11
Nodes (23): appraise module, grant module, author(), claim(), extractor_output(), TempLibrary, TestAppraisalReviewDistinguishable, TestChecklistSelectionByStudyType (+15 more)

### Community 9 - "Concept Graph & Gap/Hypothesis Discovery"
Cohesion: 0.12
Nodes (38): concept module, relation module, _active_claims(), co_mentioned_ungrouped(), main(), population_outcome_gap(), single_study_fragile(), unresolved_conflicts() (+30 more)

### Community 10 - "Extraction Tests (Phase 4)"
Cohesion: 0.13
Nodes (17): author(), claim(), extractor_output(), TempLibrary, TestAuthorContributionRequiresEvidence, TestClaimsResolveToSources, TestCorrectionPendingOnSupersession, TestCorrectionsOnUnchangedEvidence (+9 more)

### Community 11 - "OKF & Related-Papers Tests"
Cohesion: 0.09
Nodes (13): add module, graph_people module, okf_emit module, related module, author(), TempLibrary, TestOkfBasicGeneration, TestOkfConceptDegradesWithoutRelations (+5 more)

### Community 12 - "Compare Tests (Phase 5)"
Cohesion: 0.12
Nodes (13): lib_ids module, methods module, study.create_study, author(), claim(), TempLibrary, TestCompareCellSemantics, TestCompareFreezeAndRefresh (+5 more)

### Community 13 - "Gaps Tests (Phase 9)"
Cohesion: 0.12
Nodes (14): gaps module, hypothesize module, study.create_dataset, datasets.jsonl (dataset identity records), studies.jsonl (study grouping records), study.study_for_pmid, author(), claim() (+6 more)

### Community 14 - "Annotation & Vision Cache Tests"
Cohesion: 0.12
Nodes (16): pull_annotations module, Path, author(), build_synthetic_papers_db(), make_record(), papers_item(), TempLibrary, TestPullAnnotations (+8 more)

### Community 15 - "Brief & Compare Scripts"
Cohesion: 0.17
Nodes (30): edit_brief(), _edits_path(), _evidence_hash(), _key_dir(), _latest_snapshot_id(), _load_edits(), main(), save_brief() (+22 more)

### Community 16 - "Ask/Retrieve Tests (Phase 6)"
Cohesion: 0.14
Nodes (12): ask_retrieve module, author(), claim(), TempLibrary, TestBrief, TestCatalogIndexesClaimsAndPassages, TestCitationValidation, TestRetrieval (+4 more)

### Community 17 - "Audit Tests (Phase 11)"
Cohesion: 0.13
Nodes (10): brief module, compare module, extract module, author(), _now(), TempLibrary, TestCacheInvalidation, TestCitationObservations (+2 more)

### Community 18 - "Concept Graph Tests (Phase 8)"
Cohesion: 0.15
Nodes (8): author(), claim(), TempLibrary, TestConceptAliasResolution, TestConflictProposal, TestContradictsRequiresReview, TestNeighborsResolveToEvidence, TestStaleEdgeInvalidation

### Community 19 - "Check-Citations Tests (Phase 7)"
Cohesion: 0.13
Nodes (12): check_citations module, author(), claim(), TempLibrary, TestBibliographyExportScope, TestCaveat, TestCitedPmidMerge, TestEvidenceRequirements (+4 more)

### Community 20 - "Papers.app Tests (Phase 3)"
Cohesion: 0.18
Nodes (14): init_repo module, open_in_papers module, resolve_from_args(), main(), Path, status.main, _args(), attach_pdf() (+6 more)

### Community 21 - "Init/Catalog Tests (Phase 0)"
Cohesion: 0.09
Nodes (9): catalog module, TempLibrary, TestAtomicWrite, TestCitekey, TestInitAndCatalog, TestQuestionIds, TestRename, TestSlugCollision (+1 more)

### Community 22 - "PRISMA Tests (Phase 5)"
Cohesion: 0.16
Nodes (10): prisma module, project module, pubmed_query module, screen module, author(), TempLibrary, TestFreezeAndRefresh, TestHappyPath (+2 more)

### Community 23 - "Methods & Study Records"
Cohesion: 0.25
Nodes (21): _active_claims(), main(), methods_for_pmid(), run(), _append_row(), create_dataset(), create_method(), create_study() (+13 more)

### Community 24 - "Docs: Acquire/API Command Reference"
Cohesion: 0.15
Nodes (19): catalog.py module, ~/.config/ref-manager/config.json, Acquire commands doc page, API docs page, find_related_articles MCP tool, /ref:add command, /ref:attach command, /ref:audit command (+11 more)

### Community 25 - "Docs: People & Maintenance Commands"
Cohesion: 0.20
Nodes (18): audit.py, /ref:audit, /ref:verify, verify.py, discover.py, grant.py, graph_people.py, person.py (+10 more)

### Community 26 - "Docs: Knowledge Layer v2 & Extraction Fan-out"
Cohesion: 0.14
Nodes (18): mcp__claude_ai_PubMed__get_article_metadata, The claim contract, Corrections overlay lifecycle, Extraction tiers, Relations & edges, Extraction fan-out (figure 4), ref-extractor subagent, Claim v2 (phase 12) (+10 more)

### Community 27 - "PRISMA Flow Script"
Cohesion: 0.29
Nodes (16): build_flow(), _identified(), _included_studies(), _latest_snapshot_id(), _load_json(), _load_query_run(), main(), _project_dir() (+8 more)

### Community 28 - "Docs: Appraisal & Synthesis Commands"
Cohesion: 0.14
Nodes (16): AMSTAR-2 checklist, catalog.sqlite FTS5 index, corrections.json record, GRADE certainty rating, Newcastle-Ottawa scale, PRISMA 2020 flow diagram, /ref:ask command, /ref:compare command (+8 more)

### Community 29 - "Docs: Systematic Review Tutorials"
Cohesion: 0.21
Nodes (16): /ref:screen, /ref:study, screen.py, study.py, appraise.py, compare.py, methods.py, prisma.py (+8 more)

### Community 30 - "Docs: Knowledge Graph & OKF Bundle"
Cohesion: 0.15
Nodes (16): Graph commands doc page, graph/concepts.jsonl, graph/people_relations.jsonl, graph/relations.jsonl, OKF v0.2 bundle, okf plugin, /ref:check-citations command, /ref:concept command (+8 more)

### Community 31 - "Docs: Command Index Cross-links"
Cohesion: 0.16
Nodes (15): Commands index doc page, /ref:brief command, /ref:cite command, /ref:discover command, /ref:export command, /ref:export-papers command, /ref:grant command, /ref:index command (+7 more)

### Community 32 - "Docs: Skill Definition & Maintenance"
Cohesion: 0.15
Nodes (13): catalog.py, /ref:index, /ref:status, status.py, lib_schema.py, catalog.py, init_repo.py, lib_atomic.py (+5 more)

### Community 33 - "Docs: Papers.app Handoff Tutorial"
Cohesion: 0.30
Nodes (12): open_in_papers.py, Papers.app, papers_snapshot.py, pull_annotations.py, /ref:open, /ref:pull-annotations, note.py, /ref:note (+4 more)

### Community 34 - "Publications & Authorship Script"
Cohesion: 0.47
Nodes (11): _all_people(), _authorship(), classify_role(), coauthors(), _find_ambiguous_name_person(), _find_confirmed_identity(), main(), _meta() (+3 more)

### Community 35 - "Related-Papers Script"
Cohesion: 0.44
Nodes (11): _already_in_library(), backward(), forward(), _load(), main(), _now(), persist(), Extract raw reference-list candidates from this paper's committed     full text, (+3 more)

### Community 36 - "Docs: Getting Started & Project Commands"
Cohesion: 0.24
Nodes (11): project.py, queue.py, /ref:project, /ref:queue, cite.py, export.py, lib_cite.py, /ref:cite (+3 more)

### Community 37 - "Figure Vision Cache"
Cohesion: 0.49
Nodes (9): /ref:describe-figure command, _figures_path(), _find_cached(), _find_figure(), _load_figures(), main(), request(), store() (+1 more)

### Community 38 - "Docs: Selector Grammar & Organize Scripts"
Cohesion: 0.22
Nodes (10): lib_selector.py module, project.py script, queue.py script, screen.py script, study.py script, /ref:project command, /ref:queue command, /ref:screen command (+2 more)

### Community 39 - "Docs: Ingest & Ownership Workflows"
Cohesion: 0.28
Nodes (9): add.py, /ref:add, lib_atomic.py, Ownership & recovery, Command map (figure 1), Full-text acquisition (figure 3), Ingest & commit (figure 2), Paper directory anatomy (+1 more)

### Community 40 - "Docs: Design Decisions & Identifier Contract"
Cohesion: 0.22
Nodes (9): Key design decisions (D1-D28), Identifier contract, lib_ids.py, Library layout, lib_selector.py, Selector grammar, ref-manager overview page, Selecting papers (selector table) (+1 more)

### Community 41 - "Plugin Marketplace Manifest Fields"
Cohesion: 0.25
Nodes (7): metadata, description, name, owner, name, plugins, $schema

### Community 42 - "Docs: Ask/Brief/Summarize Commands"
Cohesion: 0.29
Nodes (8): ask_retrieve.py, brief.py, check_citations.py, /ref:brief, /ref:check-citations, /ref:summarize, ref-synthesizer subagent, summarize.py

### Community 43 - "Docs: Search & PubMed Query Commands"
Cohesion: 0.43
Nodes (7): Find commands doc page, pubmed_query.py script, search.py script, /ref:search command, /ref:search-pubmed command, /ref:update-queries command, search_articles MCP tool

### Community 44 - "Docs: Notes & Papers.app Sync"
Cohesion: 0.33
Nodes (7): notes.md file, Papers.app, note.py script, open_in_papers.py script, pull_annotations.py script, /ref:note command, /ref:pull-annotations command

### Community 45 - "Search Script"
Cohesion: 0.67
Nodes (6): _evidence_hits(), main(), _notes_hits(), _paper_abstract(), run(), Path

### Community 46 - "Note Script"
Cohesion: 0.80
Nodes (5): append(), main(), notes_path(), show(), Path

### Community 47 - "App Icon (SVG Source)"
Cohesion: 0.60
Nodes (5): ref-manager App Icon (SVG), Book Stack Motif, Coral Burst Reader Mascot, Open Book with Knowledge Graph Motif, Teal Tile Color Palette

### Community 48 - "App Icon (128px)"
Cohesion: 1.00
Nodes (3): App Icon (icon-128.png), Teal Reader Mascot Character, claude-ref-manager Project

## Ambiguous Edges - Review These
- `audit.py` → `/ref:verify`  [AMBIGUOUS]
  docs/commands/organize.html · relation: references

## Knowledge Gaps
- **114 isolated node(s):** `$schema`, `name`, `name`, `description`, `plugins` (+109 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **8 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What is the exact relationship between `audit.py` and `/ref:verify`?**
  _Edge tagged AMBIGUOUS (relation: references) - confidence is low._
- **Why does `lib_atomic module` connect `Ingestion & OKF Emit Pipeline` to `Selector, Audit & Export Pipeline`, `People, Grants & Identifiers`, `Repo Init, Schema & Screening`, `Related-Papers Script`, `Papers.app Export & Handoff`, `Appraisal & Claim Verification`, `Figure Vision Cache`, `Acquisition Tests (Phase 3)`, `Concept Graph & Gap/Hypothesis Discovery`, `OKF & Related-Papers Tests`, `Annotation & Vision Cache Tests`, `Brief & Compare Scripts`, `Init/Catalog Tests (Phase 0)`, `Methods & Study Records`, `PRISMA Flow Script`?**
  _High betweenness centrality (0.187) - this node is a cross-community bridge._
- **Why does `summarize.run_summarize` connect `Selector, Audit & Export Pipeline` to `Summarize/Review Tests (Phase 10)`, `Audit Tests (Phase 11)`, `Docs: Appraisal & Synthesis Commands`?**
  _High betweenness centrality (0.114) - this node is a cross-community bridge._
- **Why does `ref-synthesizer subagent` connect `Docs: Appraisal & Synthesis Commands` to `Selector, Audit & Export Pipeline`?**
  _High betweenness centrality (0.110) - this node is a cross-community bridge._
- **Are the 64 inferred relationships involving `SchemaError` (e.g. with `main()` and `persist_check()`) actually correct?**
  _`SchemaError` has 64 INFERRED edges - model-reasoned connections that need verification._
- **Are the 30 inferred relationships involving `atomic_write_json()` (e.g. with `run_review()` and `attach_one()`) actually correct?**
  _`atomic_write_json()` has 30 INFERRED edges - model-reasoned connections that need verification._
- **Are the 43 inferred relationships involving `SlugError` (e.g. with `add_alias()` and `create_concept()`) actually correct?**
  _`SlugError` has 43 INFERRED edges - model-reasoned connections that need verification._