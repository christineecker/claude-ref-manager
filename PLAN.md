# ref-manager — Claude Code plugin for scientific reference management

Status: **revised design; implement and validate the first working slice.** Data ownership and recovery contracts are in §3a; claim provenance in §4a; measurable gates in §8. Converter and integration assumptions require fixture validation before their phases ship.

## 0. Decisions made

| # | Decision | Consequence |
|---|---|---|
| D1 | **Standalone OKF bundle.** ref-manager does not write into wiki-manager's bundle. | Own `okf/` under the library root. OKF v0.2 semantics are re-read from the spec, not inherited from wiki-manager. `okf` plugin MCP + validate/visualize skills still apply to the bundle since they are bundle-generic. |
| D2 | **Library path chosen at init.** `/ref:init [path]` asks for the library root and records it in config; the plugin never hardcodes a location. | Needs a config file resolving the active library, plus a guard so every command fails loudly when no library is configured. |
| D3 | **No embeddings in v1.** Retrieval = SQLite FTS5 + OKF concept graph. | Embeddings remain deferred; graph phases remain core. Retrieval design must not assume a vector store exists. |
| D4 | **Tiered extraction.** Every paper gets an abstract-level record; full atomic-claim extraction only on demand. | The active extraction manifest carries `extraction_tier` (`abstract` / `full`), promotable; missing abstracts remain explicitly metadata-only. Retrieval and synthesis must state which tier backed each cited claim. |
| D5 | **Papers.app: push + *selective* pull.** No bulk import. | The library starts empty and grows only by your explicit choice. Papers is a reading target, plus an opportunistic full-text and annotation source for papers you have already chosen to add. |
| D6 | **Scale: 500–5k papers, ongoing multi-topic.** | FTS5 holds. OKF concept graph becomes the primary navigation surface, not a nicety. Extraction template must cover several study designs, not one. |
| D8 | **Mixed field — template detected per paper.** | The extractor first classifies study type (RCT / cohort / case-control / meta-analysis / molecular / imaging / review), then applies the matching extraction template. No fixed-field assumption; `study_type` becomes a first-class queryable key. |
| D9 | **Discovery is manual and explicit.** | `/ref:add <PMID>` and PubMed search are the ways in. No scheduled jobs, no background ingest. Standing queries exist but are re-run manually (`/ref:update-queries`), never on a schedule. Clipping in the browser still files a paper in Papers for reading; it enters the repo only when you add it. |
| D10 | **Citations: BibTeX + CSL-JSON stored; style chosen at output; default APA 7.** | `meta.json` is the bibliographic authority; CSL-JSON is its generated interchange representation and feeds BibTeX export. Rendering via CSL style files at export time, so any style works without re-ingesting. |
| D11 | **PubMed only in v1.** | Every paper must resolve to a PMID. No non-PubMed source ingestion in v1; a local PDF may be attached to an existing PMID. Keep typed source references extensible for future DOI-only or other records; do not require PMID identifiers on projects, studies, methods, or datasets. |
| D12 | **Library starts empty.** Papers are added deliberately, one decision at a time. | No seeding, no backfill. Growth is curated rather than inherited, so every record in the repo is there because you put it there. |
| D13 | **Knowledge graph is core, not compounding value.** Gap analysis and hypothesis generation (Swanson ABC literature-based discovery) are first-class outputs. | OKF weaving follows the comparison and writing workflow; it remains required product scope. Claim extraction must produce context-rich, provenance-backed records (§4a), with the schema designed in phase 0 before the extractor. Structured graph records back regenerable OKF views; opposite directions produce potential conflicts, not automatic contradictions. New commands `/ref:gaps` and `/ref:hypothesize`. |
| D14 | **Stable citekeys + single export path.** Citekey `authorYearFirstword` assigned at ingest, recorded in `meta.json`, never regenerated. | Generated CSL-JSON (D10) feeds every target: `/ref:export` emits BibTeX (`--bib`) and CSL-JSON (`--csl`); pandoc and quarto both consume `.bib`/CSL + `@citekey`, so one exporter covers LaTeX, Word/Zotero, and markdown writing. |
| D15 | **Systematic-review machinery built, but staged.** Project-scoped screening and basic evidence tables land early; GRADE certainty and risk-of-bias checklists come later. | `/ref:search-pubmed` parses questions into PICO and preserves search runs in `queries/*.yaml` and logs project-specific include/exclude decisions with reasons under `projects/<slug>/`. Full-tier extraction templates later gain RoB 2 (RCT), Newcastle-Ottawa (cohort/case-control), AMSTAR-2 (meta-analysis); `/ref:review` gains GRADE-style certainty ratings and evidence tables. |
| D16 | **Conversion toolchain: JATS-first, anydoc for PDFs, trafilatura for HTML.** `pandoc -f jats -t gfm` when reusable JATS is available (a PMCID alone is insufficient; validate conversion fidelity); **anydoc** (`@firecrawl/anydoc`, local Rust, LaTeX equations, hosted OCR fallback for scans) replaces pdf2md; publisher HTML via **trafilatura**, falling back to firecrawl scrape for JS-rendered pages. anydoc takes no HTML input — it is the PDF/Office leg only. | Three converters, one output contract: versioned GFM `source.md`, available assets, source locators, and completeness diagnostics. Preserve raw inputs; manifests record converter versions, options, and hashes. Verify tool capabilities against fixtures before adoption. |
| D17 | **Figures are first-class knowledge.** Each conversion path extracts available figures and captions and reports omissions; captions are FTS-indexed. Vision descriptions are selective, requested during promotion or for a question, and cached per figure. | `figures/` and `figures.json` retain IDs, captions, source locators, and hashes. Vision output is labeled model interpretation, separate from reported results, with provenance. Raw acquisitions stay immutable; figures are regenerable. |
| D18 | **Explicit ownership and resumable stages.** | Files hold authoritative records; SQLite and OKF are rebuildable projections. Separate user content from generated views; use atomic generation commits, locks, and stage checkpoints (§3a). |
| D19 | **Passage retrieval and incremental enrichment.** | Retrieve source-linked sections and captions, diversify by paper, rerank within a token budget, and cache expensive work by input and toolchain versions. |
| D20 | **Research projects organize daily work.** | Projects own questions, paper relevance, reading queues, screening decisions, evidence tables, arguments, and saved briefs. A paper can belong to multiple projects without duplication. |
| D21 | **Human review is independent of extraction.** | Reading status and claim verification are explicit. Authoritative correction overlays survive regeneration and become pending review when their evidence context changes. |
| D22 | **Study-aware evidence and writing before discovery.** | Model studies, cohorts/datasets, and methods separately from publications. Build comparison tables, reproducible briefs, and paragraph citation checks before hypothesis exploration. |
| D23 | **PI reporting uses structured, auditable records.** | Researcher identity, ordered authorship, grants, and publication–grant links support deterministic filters and counts. Model extraction proposes evidence-backed matches; ambiguous matches require review. |
| D24 | **Reporting scope and evidence are explicit.** | Curated reading collections are not complete publication portfolios. Author/grant discovery is manual and selected additions remain explicit. Reports snapshot coverage, date/counting rules, evidence, and unresolved records. |

---

## 1. What it does

| Capability | Mechanism |
|---|---|
| Search PubMed by criteria / question / PMID list | PubMed MCP (`search_articles`, `get_article_metadata`, `find_related_articles`, `convert_article_ids`); questions parsed into PICO → boolean MeSH + free-text query (D15) |
| Snowball from a known paper | `/ref:related <pmid>` — backward (reference list from full text) + forward (`find_related_articles`, ELink cited-by); stays within D11 |
| Cite in any style | `meta.json` → CSL-JSON → BibTeX export; rendered at output, default APA 7; stable citekeys (D14); `/ref:export` for `.bib`/CSL files, `/ref:cite` for inline `@citekey` while writing |
| Acquire full text | PMC OA JATS XML (`get_full_text_article`) → Unpaywall OA PDF → publisher HTML ; Papers' extracted fulltext tried first once the phase 4 adapter is available |
| Convert to markdown | JATS → `pandoc -f jats -t gfm` ; PDF → **anydoc** (local, OCR fallback) ; HTML → **trafilatura** → firecrawl scrape for JS-rendered pages (D16) |
| Extract & index figures | each converter path emits available assets in `figures/` + `figures.json` (caption, label, sha256); captions FTS-indexed; selective cached vision descriptions (D17) |
| Normalize to a central repo | one directory per paper, immutable source + derived extraction |
| Structured extraction | OKF v0.2 `Reference` note per paper, paper-specific keys on top |
| Search the repo | SQLite FTS5 over passages (lexical) + OKF concept graph (structural); no vectors in v1 |
| Answer scientific questions | retrieval → grounded synthesis with `[^pmid]` citations, contradiction surfacing |
| Find gaps & generate hypotheses | `/ref:gaps` (single-study claims, unresolved contradictions, untested concept pairs) and `/ref:hypothesize` (Swanson ABC traversal over the OKF graph, candidates checked against PubMed) — D13 |
| Summaries / reviews | per-paper, per-topic, and evidence-table outputs; GRADE certainty + risk-of-bias appraisal at full tier (D15) |
| Library hygiene | `/ref:audit` — re-check retraction/errata status for all PMIDs; `/ref:note <pmid>` — your own free-text thoughts, kept distinct from model extraction |
| Read in ReadCube Papers | push PDF into Papers; selectively pull full text and annotations for chosen PMIDs |
| Organize research | `/ref:project` manages questions, chapter/experiment scope, memberships, relevance notes, and project-specific screening |
| Manage reading | `/ref:queue` tracks to-screen / to-read / reading / read, priority, and why saved; separate from extraction tier |
| Attach acquired PDFs | `/ref:attach <pmid> <path>` verifies identity and preserves a local PDF as an immutable acquisition |
| Review extraction | `/ref:verify` accepts, edits, or rejects claims and concept mappings with evidence-backed correction overlays |
| Search personal thinking | `/ref:search --scope notes` searches notes, annotations, and project relevance comments with explicit personal-content labels |
| Compare evidence | `/ref:compare` builds project-scoped, editable evidence tables with source-linked cells and study-level grouping |
| Reuse methods | `/ref:methods` retrieves protocols, datasets, software, instruments, controls, and analysis choices with evidence locators |
| Support writing | `/ref:check-citations` checks a paragraph's assertions against supplied/library evidence; flags unsupported wording and conflicting results |
| Save research briefs | `/ref:brief` saves answers, evidence snapshots, user revisions, and unresolved questions; explicit refresh shows evidence changes |
| Export to Papers | `/ref:export --papers` packages selected references as BibTeX plus available PDFs with readable filenames |
| Identify researchers | `/ref:person` manages name variants, ORCID, affiliation history, and confirmed publication matches |
| Query authorship | `/ref:publications --person <id> --role <role>` filters complete ordered author lists with independently evidenced shared/corresponding roles |
| Track grants | `/ref:grant` manages funders, awards, approved aliases, aims, and evidence-backed publication links |
| Discover portfolio candidates | `/ref:discover --person <id>` or `--grant <id>` runs an explicit PubMed search and queues candidate matches for confirmation |
| Produce PI reports | `/ref:report` exports publication lists by period, researcher, lab, author role, or grant, with evidence and unresolved-match appendices |
| Review reporting evidence | `/ref:verify` also resolves researcher matches, grant aliases/links, and author contribution statements |


## 2. Prior art in this environment — reuse, don't rebuild

Discovered on this machine:

- **`wiki-manager` skill** (`~/.agents/skills/wiki-manager/`) already implements OKF v0.2 frontmatter, `op-ingest-paper.md` (PMID/DOI → literature note), dedup protocol, query, lint, merge, audit. Roughly 60–70% conceptual overlap with this request.
- **`okf` plugin** ships `okf_mcp.py` with `search_concepts` / `read_concept` / `get_neighbors`, plus validate/visualize/backfill skills. That is a ready-made knowledge-graph retrieval layer.
- **`firecrawl`**, **`graphify`**, **`deep-research`** skills exist and cover HTML scraping, graph building, and multi-source research. (`pdf2md` also exists but is superseded by anydoc — D16.)
- **Papers.app** (`com.ReadCube.Papers`) is an Electron app with a local SQLite library at
  `~/Library/Application Support/Papers/<uuid>.db` — tables `items`, `collections`, `fulltext`, `fts`, `actions_queue`, `sync_meta`.
  It registers **no custom URL scheme**; it is a PDF document handler.

**Design consequence:** ref-manager should be the *acquisition + extraction + retrieval engine* and delegate knowledge-article maintenance to the OKF/wiki layer, rather than forking a second OKF implementation. Use existing OKF validation and rendering conventions with the authoritative records described in §3a.

## 3. Repository layout

Plugin (this folder, versioned):

```
ref-manager/
  .claude-plugin/plugin.json
  commands/            /ref:init /ref:add /ref:fetch /ref:extract /ref:search
                       /ref:ask /ref:search-pubmed /ref:update-queries /ref:related
                       /ref:gaps /ref:hypothesize /ref:export /ref:cite
                       /ref:summarize /ref:review /ref:audit /ref:note
                       /ref:open /ref:pull-annotations /ref:index /ref:status
                       /ref:project /ref:queue /ref:attach /ref:verify
                       /ref:compare /ref:methods /ref:check-citations /ref:brief
                       /ref:person /ref:publications /ref:grant /ref:discover /ref:report
  skills/ref-manager/
    SKILL.md
    references/op-*.md          # one file per operation, loaded on demand
  agents/
    ref-extractor.md            # 1 paper -> structured extraction (parallel fan-out)
    ref-synthesizer.md          # N extractions -> answer/summary
  scripts/                      # uv PEP-723 single-file python, no venv
    pubmed.py acquire.py convert.py extract.py catalog.py papers_sync.py okf_emit.py
                                  # convert.py wraps pandoc(JATS)/anydoc(PDF)/
                                  # trafilatura(HTML) behind one interface — D16
```

Library (data; root chosen at `/ref:init`, recorded in `~/.config/ref-manager/config.json` — D2):

```
<LIBRARY>/
  papers/<pmid>/      # pure PMID dirs — D11 guarantees every paper has one
    meta.json         # bibliographic authority, stable citekey, status + checked_at
    raw/<sha256>/     # immutable metadata response, PDF, JATS, HTML, or Papers text
    acquisitions.json # origin, URL/item ID, fetched_at, media type, hash, availability
    current.json      # atomic pointer to the active validated generation
    generations/<id>/
      manifest.json   # input hashes, schema/tool/model/prompt versions, completeness
      source.md       # derived full text with source-locator mapping
      claims.json    # persisted extraction records, provenance, evidence tier
      figures/       # derived images
      figures.json   # IDs, captions, locators, hashes, optional vision interpretation
      paper.md       # generated OKF Reference view; no authoritative user content
    notes.md          # user-authored content; never overwritten by extraction
    annotations.json # imported annotations keyed by source/item/annotation ID
    authorship.json   # ordered authors, list completeness, identity links, role evidence
    funding.json      # funding observations, grant links, locators and review states
    corrections.json  # authoritative claim/mapping/identity/funding review overlays
    state.json        # resumable stage checkpoints and errors
  projects/<slug>/
    project.yaml      # scope, questions, chapter/experiment context
    papers.yaml       # PMID membership, relevance, priority, reading status
    screening.jsonl   # project-specific decisions, reasons, associated search run
    arguments.md      # user-authored working arguments and open questions
    tables/<id>/      # generated evidence snapshots plus separate user edits
    briefs/<id>/      # versioned synthesis/evidence manifest plus user revisions
  people/<id>.json    # names, ORCID, affiliations, confirmed/candidate identity matches
  labs/<id>.json      # explicit membership with dates; no inference from coauthorship
  grants/<id>.json    # funder, award, approved aliases, dates, aims and project links
  reports/<id>/
    manifest.json    # filters, date/counting policy, coverage and source snapshot
    publications.csv # one publication per row; grant associations exported separately
    grant-links.csv  # publication–grant associations, evidence and verification state
    report.md        # rendered summary and unresolved-evidence appendix
  studies/
    studies.jsonl     # stable study IDs, linked publications, grouping confidence
    datasets.jsonl    # cohort/dataset identities and reuse relationships
    methods.jsonl     # protocols/tools/controls, context and source provenance
  graph/
    concepts.jsonl    # stable concept IDs, names, aliases and normalization provenance
    relations.jsonl   # typed edges, evidence claim IDs, generation IDs, review state
  okf/                # generated OKF v0.2 Concept/Entity views
  index/
    catalog.sqlite    # rebuildable papers/passages/claims/concepts/relations + FTS5
  queries/<slug>.yaml # saved searches, exact query/date and immutable run histories
  exports/            # generated CSL-JSON and BibTeX
    papers/<batch>/   # references.bib, manifest.json, pdfs/<citekey>.pdf
  log.md              # operation summaries; checkpoints are machine-readable
```

### 3a. Ownership, persistence, and recovery

- `meta.json` owns bibliographic metadata and citekeys. Allocate a collision suffix under a library-level lock; existing citekeys never change during metadata refresh. PMID is the identity key; DOI/title/hash matches only flag inconsistencies and must not silently merge different PMIDs.
- Raw acquisitions are immutable evidence snapshots. Conversions and extractions are versioned derived records retained for reproducibility. `extraction_tier` is derived from the active validated generation; availability and extraction completion are separate states. Missing abstracts produce metadata-only records with an explicit unavailable status, not fabricated claims.
- `notes.md` and `annotations.json` are authoritative user content. Display them alongside generated paper views; regeneration never edits them. Annotation pulls upsert by stable source IDs, preserve provenance, and report source edits/deletions without erasing local notes.
- Structured claim, concept, and relation files back explicit SQLite tables and generated OKF views. Each edge names supporting claims and source generation IDs. Reviewed edge decisions persist in relation records. Re-extraction invalidates affected evidence links and triggers an incremental graph refresh.
- Serialize mutations per PMID; use a library lock for citekey allocation and graph commits. Write each generation into a staging directory, validate it, then atomically replace `current.json`. Write authoritative JSON updates with temporary files and atomic replacement. Record pending/running/complete/failed stage states and diagnostics.
- SQLite updates occur in transactions after file commits. There is no cross-filesystem/SQLite transaction: track indexed generation IDs, detect mismatches on startup, and reconcile before retrieval. `/ref:index --rebuild` reconstructs the catalog from committed records; incomplete staging directories are ignored. Graph views carry generation IDs and are refreshed or reported unavailable when stale.
- Retry interrupted stages from the last valid checkpoint. Cache conversion by source hash + converter/version/options; extraction by source hash + schema/model/prompt/options; vision by figure hash + model/prompt/options. Explicit refresh creates a new generation. Limit retries and concurrent network/model work; retain actionable errors.


### 3b. Projects, review, and research artifacts

- A project has stable question IDs, scope, and optional chapter/experiment links. Membership references a paper once; relevance, priority, screening, and reading state belong to that membership. Preserve screening history with decision, reason, timestamp, and search-run reference. Exclusion from one project does not exclude a paper globally.
- Human reading states are `to_screen`, `to_read`, `reading`, and `read`. Neither acquisition nor model promotion marks a paper read. Show read status, evidence availability, extraction tier, and human verification separately.
- `corrections.json` stores accept/edit/reject decisions for claims and concept mappings, original and replacement values, rationale, reviewer, timestamp, and evidence locator/hash. Apply valid overlays to retrieval, tables, and graph projections. Never overwrite raw extraction. Preserve decisions on unchanged evidence; changed or superseded evidence makes an overlay pending review rather than silently applying or deleting it. Rejected claims are excluded from default synthesis and retained for audit.
- Study records link publications to an underlying investigation; dataset/cohort reuse is a separate relationship and does not automatically establish that publications describe the same study. Store grouping evidence, confidence, and review state. Summaries report publication counts and identified independent-study counts with uncertain groupings visible.
- Table and brief artifacts have a generated snapshot and a separate authoritative user-edit layer. A manifest records project/question, selected PMIDs, source generations, correction versions, and model/prompt versions. Explicit refresh creates a new snapshot and a change report; preserve prior versions and user text, flagging edits whose evidence changed. Research briefs retain unresolved questions and selected evidence, not only rendered prose.
- Typed source references initially resolve to PMID-backed papers; project, question, study, dataset, method, and claim IDs are independent. A future non-PubMed adapter can add identifier types without redesigning all relationships. Non-PubMed ingestion remains outside v1.


### 3c. PI identity, funding, and reporting contract

**Researcher identity and authorship.** Researcher IDs are independent of paper IDs. Profiles retain name variants, ORCID when supplied, dated affiliations, and confirmed/rejected/candidate matches to specific author entries. Name similarity alone cannot establish identity. Preserve the complete ordered published author list, raw metadata provenance, person/group author distinctions, and source completeness. If the list is incomplete or consortium structure makes position ambiguous, mark the role unresolved.

For a verified complete list, the mutually exclusive reporting categories are `sole` (one author), `first` (first of multiple), `last` (last of multiple), and `middle`. A sole author is not counted again as first and last. Preserve literal position and total author count separately. Shared-first, shared-senior, and corresponding authorship are independent flags requiring explicit contribution/correspondence evidence; do not infer seniority or correspondence from last position. Equal-contribution metadata alone does not identify a shared-senior role. Retain statement text, locator, source hash, and review state. See [NLM author metadata](https://www.ncbi.nlm.nih.gov/books/NBK3828/).

**Grant identities and evidence.** A grant has a stable ID, funder identity, award number, approved aliases, title, dates, optional PI links, and aims. Preserve raw award strings beside normalized identifiers; normalization is funder-specific and must not collapse distinct awards or award periods without a reviewed rule. A publication can link to multiple grants. The link records the reported funder/award, exact funding statement or metadata evidence, source locator/hash, match method, timestamp, and review decision.

Preserve distinct funding observations: `explicit_acknowledgement_verified`, `indexed_funding_association`, `user_assigned_output`, `possible_match`, and `unknown`. These can coexist as separate evidence records for the same pair. An article's relevance to a grant aim or membership in a funded project does not prove an acknowledgement. Missing metadata, unavailable full text, or an unsuccessful text search must not become a definitive negative. Where checked, report “not found in the inspected sources” with coverage. Extract structured PubMed grants at ingest; inspect JATS funding elements and funding/acknowledgement passages during conversion, independently of scientific-claim promotion. PubMed normalizes some award numbers, so retain its raw response and original article wording when available. Sources: [PubMed GrantList](https://dtd.nlm.nih.gov/ncbi/pubmed/doc/out/250101/el-GrantList.html), [PMC funding markup](https://pmc.ncbi.nlm.nih.gov/tagging-guidelines/article/tags/), [NLM funding metadata](https://www.nlm.nih.gov/databases/download/pubmed_medline.html).

**Portfolio discovery and lab scope.** `/ref:discover` performs a manually initiated person/grant search, saves exact query, retrieval date, pagination/completion status, and candidates. User confirmation is required for ambiguous identity and explicit selection for library additions. Confirming a publication identity does not automatically verify every funding or author-role assertion. Retain rejected matches to prevent repeated suggestions. Lab reports use explicit dated memberships and a declared policy (membership at publication date versus selected roster), not inferred affiliation from coauthorship. Projects can link to grants and aims without changing acknowledgement evidence.

**Reproducible reports.** `/ref:report --person <id> --from <date> --to <date>` supports role filters and optional grant/lab grouping. Persist the chosen date basis (online publication or issue date), missing-date handling, publication types, identity review policy, funding evidence threshold, and deduplication policy. Never silently substitute dates. Report unique-publication totals; grant subtotals may overlap and must be labeled. Export citations, PMID/DOI, dates, author position/category and independent flags, award identifiers, funding evidence, verification status, and source references. CSV plus Markdown is the first export scope; Office-specific formatting can follow later.

Report snapshots retain selected records and metadata/evidence/correction versions, unresolved candidates, unavailable acknowledgement coverage, and the data cutoff. Frozen reports are reproducible; refresh produces a new version with a change summary. By default label scope “confirmed publications in this library,” with PubMed-only coverage and whether portfolio completeness has been reviewed. No report may imply that the curated reading collection is a complete career or lab bibliography. `/ref:verify` reviews identity, grant, and author-role evidence using the same persistent-overlay rules as claim correction.


## 4. Pipeline

```
  explicit PMID list | explicitly selected PubMed search results
            |
    [1] RESOLVE    metadata + ordered authors + indexed grants + abstract + initial status
    [2] DEDUP      PMID identity; stable citekey allocation; preserve raw response
    [3] EXTRACT    abstract evidence when available; provenance-backed claims
    [4] COMMIT    validated generation -> metadata/passages/claims FTS -> citation export
            |
            +-- /ref:fetch (optional)
            |     Papers text when integration is available -> reusable PMC JATS
            |     -> Unpaywall PDF -> publisher HTML -> retain abstract-only availability
            |     preserve raw input -> convert -> available figures/captions + diagnostics
            |
            +-- /ref:extract (on demand, requires adequate converted full text)
                  full claim extraction + selective cached figure interpretation
                  -> commit new generation -> refresh index and affected graph edges
            |
    [5] WEAVE     structured concepts/relations -> generated OKF views
                  supports | potential_conflict | contradicts | extends | replicates
```

Acquisition failures do not prevent metadata/abstract ingestion. Conversion success alone does not promote the extraction tier. Agent outputs are nondeterministic: persist and validate them before commit. Graph construction is core, built after comparison and writing workflows, and shares the provenance schema established in phase 0.

### 4a. Claim and relation contract

Each claim has a stable `claim_id`, PMID, generation ID, evidence tier, source hash, section/page/table/figure locator, and supporting evidence span. Retain IDs for unchanged claims across reruns; materially changed claims receive new IDs with supersession links. Record schema, extractor, model, and prompt versions.

Normalize population, intervention/exposure, **comparator**, outcome definition, **timepoint**, direction, effect value, **effect measure and units**, uncertainty interval, study design, cohort identity, and adjustment context. Unknown fields stay explicitly unknown. Preserve original wording and normalization provenance. Classify study type with an unknown/mixed fallback rather than forcing a template.

Opposite directions under comparable contexts create `potential_conflict` edges. Mismatched measures, comparators, follow-up periods, or populations do not establish contradiction; missing context lowers comparability. `contradicts` requires a recorded review decision and rationale. Model interpretation of a figure is a separate evidence kind and cannot silently become an author-reported finding.

Store retraction/errata status, source, and `checked_at` on ingestion; failures yield unknown status. Retrieval and synthesis display status and its age. Later `/ref:audit` refreshes status and invalidates affected answer caches and graph projections.

## 5. Retrieval — cheapest layer first

1. **Lexical** — SQLite FTS5 over source-linked abstract/body sections and captions, with separate fields for title, authors, and normalized terms. Rank passages with BM25; exclude duplicated rendered claims and user notes from the scientific-evidence index. Tune field weights against fixtures.
2. **Structural** — OKF concept graph traversal (`get_neighbors`) for "what contradicts X", "what else came out of this cohort".
3. ~~Semantic (embeddings)~~ — **deferred, D3.** Design constraint: nothing in retrieval may assume a vector store. To compensate for FTS's literal matching, `/ref:ask` expands queries first — MeSH terms, synonyms, gene/drug aliases from the resolved metadata — before hitting FTS.

`/ref:ask` expands terms, retrieves passage candidates from FTS and evidence linked by the graph, deduplicates overlapping passages, and diversifies across PMIDs. Start with a configurable 30-passage candidate budget, include relevant potential-conflict evidence, then rerank within a configurable context-token budget rather than a fixed eight-paper cutoff. Report truncation or insufficient coverage.

Synthesis requires `[^pmid]` citations backed by claim IDs or passage locators and source hashes, with the actual evidence tier and retraction/errata status visible. Validate that every citation resolves to committed evidence supplied to the model; evaluate whether evidence supports each assertion separately. PICO framing is used when appropriate; non-PICO questions retain their own concepts. Graph retrieval joins once phase 8 ships; earlier `/ref:ask` uses passages alone. Project filters constrain retrieval before ranking; cross-project expansion must be explicit. `/ref:search --scope notes` uses a separate personal-content index; `--scope all` labels evidence and personal commentary distinctly and never treats a personal note as a published finding.

### 5a. Compare, write, and revisit

- `/ref:compare --project <slug>` produces an evidence matrix for selected papers: population/model, design, methods, sample size, comparator, results, uncertainty, limitations, and relevance to the question. Cells link to source passages or reviewed claims, distinguish not reported from not extracted, and retain extraction/verification status. Basic comparison does not depend on advanced risk-of-bias or certainty appraisal.
- `/ref:methods` extracts or retrieves protocols, instruments, controls, datasets, software/version, and analysis choices with the setting and source locator. Do not reconstruct unreported procedural details; link supplements when acquired and indicate when unavailable.
- `/ref:check-citations` accepts a paragraph and optional project/bibliography. Split it into checkable assertions and report supporting, conflicting, insufficient, or unavailable evidence; flag overstatement and mismatched citations. Suggestions preserve user prose until applied. Export selected references and the evidence report; available library coverage does not establish a comprehensive literature check.
- `/ref:brief` persists a research answer, its evidence and user revisions. Explicit refresh after additions or corrections reports new support, conflicts, withdrawn evidence, and unresolved questions. No scheduled monitoring or automatic ingestion is introduced.
- Initial graph views answer practical questions: which evidence supports a thesis argument; which publications share a study/dataset; why results differ; which claims lack checked full text; and which methods were used in comparable settings. Use typed project/question/study/dataset/method/claim relationships with provenance; extend these with researcher-authored-publication, publication-acknowledges-grant, publication-supports-aim, and dated researcher-lab membership relationships. Acknowledgement and aim support remain distinct. For scientific relationships, co-occurrence is distinct from evidential support.

### 5b. Gap analysis & hypothesis generation (D13)

Both commands consume structured graph evidence; `/ref:hypothesize` also needs the PubMed search adapter for candidate checking. Missing edges describe library coverage, not established gaps in the literature.

- **`/ref:gaps [topic]`** — structural queries over the indexed concept, relation, and claim tables, with OKF views for navigation:
  - claims supported by a single study (fragile evidence)
  - `potential_conflict` and reviewed `contradicts` edges without a recorded resolution
  - concept pairs co-mentioned in text but never directly studied together
  - populations/outcomes absent for an intervention that has them elsewhere
- **`/ref:hypothesize [concept]`** — Swanson ABC literature-based discovery: two-hop `get_neighbors` traversal (A–B edges from some papers, B–C from others), keep A–C pairs with no direct edge, then **check each candidate against PubMed** (`search_articles`) — untested in the library ≠ untested in the literature. Output: ranked hypotheses, each with its supporting A–B / B–C chains and the PubMed check result, exact search query, timestamp, and limitations. Zero results means “not found by this search,” not proof of novelty.

## 6. Full-text acquisition — scope and limits

`/ref:attach <pmid> <path>` supports a PDF the user has already acquired. Match embedded identifiers and bibliographic metadata to the existing record; refuse silent attachment on conflict, and request resolution for ambiguous identity. Store verified bytes under `raw/<sha256>/source.pdf` with attachment provenance, then use the same conversion and promotion pipeline. Duplicate content is a no-op. This works before Papers integration and does not add identifier-less records.

Clean and legal, in priority order:

1. **PMC Open Access subset** — free full text via the PubMed MCP / OA service. Check reusable full-text availability explicitly; a PMCID alone does not guarantee it. Prefer **JATS XML** over PDF when available. Preserve XML and linked assets, then convert with `pandoc -f jats -t gfm`; test tables, math, references, and figure links on fixtures. Record missing assets and conversion losses. See [PMC API availability](https://pmc.ncbi.nlm.nih.gov/tools/oai/).
2. **Unpaywall** (`api.unpaywall.org`, needs an email as API key — recorded in `config.json` at `/ref:init`, never prompted per fetch) — locates author manuscripts and publisher OA copies.
3. **Publisher HTML** for openly readable articles — fetched + converted with **trafilatura** first (local, free, article-aware boilerplate removal), **firecrawl scrape** as fallback for JS-rendered publisher SPAs. `<figure>` elements yield images + captions where present (D16, D17).
4. **Everything else stays paywalled.** ref-manager will record the paper with abstract + metadata only, set `full_text: false`, and hand the DOI to Papers.app, which holds the institutional credentials and is the appropriate place to fetch it. The plugin will not attempt to bypass paywalls or proxy authentication.

Abstract-only records stay first-class and visibly flagged, so a synthesis never silently treats an abstract as a read paper.

## 7. ReadCube Papers integration — selective, not bulk

**The library starts empty (D12).** No bulk import from Papers. The confirmed schema below is used for *targeted lookups* of papers you have already decided to add — never for a sweep.

Schema confirmed by reading a copy of the live library at `~/Library/Application Support/Papers/<uuid>.db`:

```
items(id TEXT PK, collection_id TEXT, json TEXT)
  $.ext_ids.pmid | .doi | .pmcid
  $.article.title | .abstract | .authors[] | .journal | .year | .volume | .issue
                 | .pagination | .issn | .eissn | .url
  $.user_data.notes                                   -- free-text note
  $.user_data.tags                                    -- user tags
  $.user_data.annotations[]                           -- {type: highlight|note, text, note}
  $.files[].sha256 | $.primary_file_hash | $.primary_file_type
  $.deleted
fulltext(sha256 -> extracted text)                    -- Papers' own extraction
collections, lists, actions_queue, sync_meta
```

Interaction points, all initiated by you:

- **Batch export** — `/ref:export --papers` takes explicitly selected PMIDs or a project selection and emits `exports/papers/<batch>/references.bib`, available PDFs under readable citekey filenames, and a manifest listing included/missing PDFs and source hashes. Copies leave originals unchanged. Import the bibliography and PDFs through Papers' import UI; verify matching and duplicates. Claims, graph records, and Markdown notes are not transferred by this export. No live database writes or automatic import are required.
- **Push** — `/ref:open <pmid>`: `open -a Papers <pdf>` sends a PDF ref-manager acquired into Papers for reading and annotating.
- **Opportunistic full text** — during `/ref:fetch` for a paper you added, check whether Papers already holds it (match on PMID, else DOI) and reuse its extracted `fulltext` instead of re-downloading. Preserve the text snapshot and item/hash provenance; report missing figures and source locators. Skip when absent, and continue acquisition when richer source material is needed.
- **Annotation pull** — `/ref:pull-annotations <pmid>`: bring your highlights and margin notes for *that* paper into its record. Annotations persist in `annotations.json` and appear under **Your annotations** in the composed display. `/ref:note` writes `notes.md`. Neither is overwritten by generated views or blended with extracted evidence.

Snapshot and access contract:

- Query only a consistent snapshot. Create it using the [SQLite backup API](https://www.sqlite.org/backup.html) with a read-only source connection; the only live-database access is the snapshot read. Never copy an active `.db` file alone or discard its WAL. If a consistent snapshot cannot be obtained, warn and skip integration.
- **Never write** to it. `actions_queue` is a live ReadCube sync queue; writing risks corrupting your sync.
- The schema is undocumented and vendor-owned. Every read validates the paths it expects and warns-and-skips per field rather than failing the run.


## 8. Build order

| Phase | Deliverable | Gate |
|---|---|---|
| 0 | Scaffold/init/status; authority, project, researcher/authorship, grant/funding, claim/correction and study schemas; atomic commits, migrations, locks, rebuild contract | Empty library works; interrupted commit recovers; typed identities do not require PMID for non-paper entities |
| 1 | `/ref:add`, `/ref:project`, `/ref:queue`, `/ref:note`, `/ref:person`, `/ref:grant`; ordered authors, indexed grants, stable citekeys and initial status checks | Fixtures cover missing abstracts, duplicate adds and citekey collisions; one paper belongs to two projects with independent relevance/screening/reading states; raw author order and grant strings survive ingest |
| 2 | Passage and personal-note search; `/ref:export --bib/--csl`, `/ref:cite`; PubMed discovery, saved query runs and project screening; `/ref:discover`, `/ref:publications`, basic `/ref:report` | Search finds evidence and personal comments with distinct labels; citation exports render correctly; manual rerun preserves history and requires explicit selection to add; index rebuild preserves results; same-name candidates remain unresolved, sole authors count once, incomplete lists do not yield confident roles, and frozen reports reproduce |
| 3 | `/ref:attach`, `/ref:fetch`, source preservation and conversion, funding/acknowledgement and contribution-statement extraction; `/ref:open`, `/ref:export --papers` | Local PDF identity conflicts are caught; incomplete conversion remains visible; retries preserve evidence; export includes selected references and available PDFs without altering originals; funding locators resolve even without full claim promotion; missing acknowledgement sources remain unknown |
| 4 | `/ref:extract`, `/ref:verify`; full extraction, selective vision, correction overlays including author/grant evidence review; targeted Papers snapshot/annotation pull | Claims resolve to sources; rejected claims leave default synthesis; corrections survive unchanged reruns and become pending on changed evidence; notes survive promotion; snapshot and repeat annotation pulls are consistent; grant aliases preserve distinct awards, shared-role flags require explicit statements, and report counts respect reviewed evidence |
| 5 | `/ref:compare`, `/ref:methods`; study/dataset grouping and basic evidence tables | Table cells resolve to evidence; missing values are explicit; multiple papers from one study are grouped without treating all dataset reuse as the same study; methods retain source/context |
| 6 | Project-scoped `/ref:ask`, saved `/ref:brief`; passage diversification and citation validation | Expected-evidence recall and assertion support are measured; project filters work; evidence tiers/status are visible; explicit brief refresh shows changes and preserves user edits |
| 7 | `/ref:check-citations`; argument support, selected bibliography/evidence export | Test paragraph includes supported, overstated, conflicting, and unsupported assertions; findings link to evidence and do not rewrite user text automatically |
| 8 | Structured graph + OKF views across questions/studies/datasets/methods/claims and researchers/grants/labs; conflict review | Practical graph questions resolve to source evidence; mismatched contexts do not become contradictions; stale edges invalidate; reviewed decisions survive rebuilding |
| 9 | `/ref:gaps`, `/ref:hypothesize`, `/ref:related`; PubMed candidate checking and snowballing | Candidates retain evidence chains and search query/date; missing edges or zero search results are not presented as proof of novelty |
| 10 | `/ref:summarize`, advanced `/ref:review`; certainty and risk-of-bias appraisal | Appraisal traces judgments to evidence, flags missing inputs, and distinguishes model drafts from human-reviewed assessments |
| 11 | `/ref:audit` refresh and library maintenance | Changed status propagates to subsequent answers/views; saved artifacts expose stale evidence without overwriting their history; failed checks retain prior status with diagnostics |

**Collect and organize: phases 0–2. Read and verify: phases 3–4. Compare and write: phases 5–7. Connect and discover: phases 8–9.** Graph discovery remains required scope, while advanced appraisal follows the daily research workflow. Papers database integration is optional at runtime and must not block local attachment, export, or verification.

The PhD workflow acceptance test is: **take 20 papers for one thesis question, identify what they establish, inspect disagreements, and produce a paragraph whose citations can be verified.** Exercise project membership, local attachment, extraction correction, evidence comparison, and bibliography export along that path.

The PI workflow acceptance test is: **generate an annual publication report grouped by grant and authorship role, with every inclusion traceable and every unresolved match visible.** Fixtures cover name collisions, sole/first/middle/last positions, incomplete/group author lists, explicit shared contributions, multiple grants per paper, award aliases, funding metadata without full text, an acknowledgement absent from indexed metadata, uncertain identity, date-boundary cases, and cross-grant totals without double counting. Report generation queries structured reviewed records and must not need a synthesis-model call.

Keep a small versioned fixture set and a labeled retrieval/answer evaluation set. Track recall at the candidate budget, conflicting-evidence inclusion, citation resolution, and manually assessed assertion support. Require all fixture citations to resolve and no user-content loss; record a retrieval baseline and reject regressions before expanding scope. Measure conversion/extraction cache hits, model-call counts, and latency to guide optimization instead of adding embeddings preemptively.

## 9. Residual assumptions — flagged, not blocking

1. **The repo and your Papers library will diverge.** That is the point of D12, but it is worth saying plainly: papers you read in Papers are not in the repo unless you add them, and `/ref:ask` can only reason over what the repo holds. If that gap becomes annoying, a one-off selective import is easy to add later — the schema work in §7 is already done.

2. **Papers schema is vendor-owned and undocumented.** Confirmed correct today against a real library; a ReadCube update can move fields. The sync script validates expected paths up front and warns-and-skips per field rather than failing the run.

3. **No embeddings (D3) means FTS misses paraphrase.** Mitigated by MeSH/synonym query expansion, not solved by it. If `/ref:ask` starts missing papers you know are in the library, that is the signal to revisit D3 — worth watching deliberately rather than discovering late.

4. **Tiered extraction (D4) means most papers are abstract-only.** Every synthesis must label which tier backed each citation, so thin evidence cannot pass as a read paper.

5. **Paywalled full text stays out of reach.** Acquisition depends on PMC OA, Unpaywall, and whatever Papers happens to hold for papers you add. Local attachment provides another route for user-acquired PDFs; some records may still remain abstract-tier permanently.

6. **ABC hypothesis generation over-generates.** Two-hop co-occurrence produces many spurious A–C candidates; the PubMed novelty check filters known links but not implausible ones. `/ref:hypothesize` output is a ranked *reading list of candidates*, not claims — presentation must say so.

---

## 10. First implementation step

Phases 0 → 2: `/ref:init <path>` to create the library at a location you choose, then `/ref:add <PMID...>` to put the first papers in it deliberately. Target for the first working slice is a handful of papers you actually care about, ingested end to end — resolved, deduped, catalogued, abstract-tier extracted when available, findable via `/ref:search`, and exportable through stable citekeys and CSL-JSON/BibTeX. Define authority, claim provenance, and crash-recovery fixtures before writing the extractor. Include a project/question, relevance notes, reading queue, and project-specific screening in this slice. Finish it before introducing full-text conversion or graph generation.
