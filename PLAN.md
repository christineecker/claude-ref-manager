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
| D7 | **Mixed field — template detected per paper.** | The extractor first classifies study type (RCT / cohort / case-control / meta-analysis / molecular / imaging / review), then applies the matching extraction template. No fixed-field assumption; `study_type` becomes a first-class queryable key. |
| D8 | **Discovery is manual and explicit.** | `/ref:add <PMID...>` and PubMed search are the ways in. No scheduled jobs, no background ingest. Standing queries exist but are re-run manually (`/ref:update-queries`), never on a schedule. Clipping in the browser still files a paper in Papers for reading; it enters the repo only when you add it. |
| D9 | **Citations: BibTeX + CSL-JSON stored; style chosen at output; default APA 7.** | `meta.json` is the bibliographic authority; CSL-JSON is its generated interchange representation and feeds BibTeX export. Rendering via CSL style files at export time, so any style works without re-ingesting. |
| D10 | **PubMed only in v1.** | Every paper must resolve to a PMID. No non-PubMed source ingestion in v1; a local PDF may be attached to an existing PMID. Keep typed source references extensible for future DOI-only or other records; do not require PMID identifiers on projects, studies, methods, or datasets. |
| D11 | **Library starts empty.** Papers are added deliberately, one decision at a time. | No seeding, no backfill. Growth is curated rather than inherited, so every record in the repo is there because you put it there. |
| D12 | **Knowledge graph is core, not compounding value.** Gap analysis and hypothesis generation (Swanson ABC literature-based discovery) are first-class outputs. | OKF weaving follows the comparison and writing workflow; it remains required product scope. Claim extraction must produce context-rich, provenance-backed records (§4a), with the schema designed in phase 0 before the extractor. Structured graph records back regenerable OKF views; opposite directions produce potential conflicts, not automatic contradictions. New commands `/ref:gaps` and `/ref:hypothesize`. |
| D13 | **Stable citekeys + single export path.** Citekey `authorYearFirstword` assigned at ingest, recorded in `meta.json`, never regenerated. | Generated CSL-JSON (D9) feeds every target: `/ref:export` emits BibTeX (`--bib`) and CSL-JSON (`--csl`); pandoc and quarto both consume `.bib`/CSL + `@citekey`, so one exporter covers LaTeX, Word/Zotero, and markdown writing. |
| D14 | **Systematic-review machinery built, but staged.** Project-scoped screening and basic evidence tables land early; GRADE certainty and risk-of-bias checklists come later. | `/ref:search-pubmed` parses questions into PICO and preserves search runs in `queries/*.yaml` and logs project-specific include/exclude decisions with reasons under `projects/<slug>/`. `/ref:review --prisma` renders a PRISMA 2020 flow record from committed screening, acquisition, and study-grouping state and needs no appraisal machinery. Full-tier extraction templates later gain RoB 2 (RCT), Newcastle-Ottawa (cohort/case-control), AMSTAR-2 (meta-analysis); `/ref:review` gains GRADE-style certainty ratings and evidence tables. |
| D15 | **Conversion toolchain: JATS-first, anydoc for PDFs, trafilatura for HTML.** `pandoc -f jats -t gfm` when reusable JATS is available (a PMCID alone is insufficient; validate conversion fidelity); **anydoc** (`@firecrawl/anydoc`, local Rust, LaTeX equations, hosted OCR fallback for scans) replaces pdf2md; publisher HTML via **trafilatura**, falling back to firecrawl scrape for JS-rendered pages. anydoc takes no HTML input — it is the PDF/Office leg only. | Three converters, one output contract: versioned GFM `source.md`, available assets, source locators, and completeness diagnostics. Preserve raw inputs; manifests record converter versions, options, and hashes. Verify tool capabilities against fixtures before adoption. |
| D16 | **Figures are first-class knowledge.** Each conversion path extracts available figures and captions and reports omissions; captions are FTS-indexed. Vision descriptions are selective, requested during promotion or for a question, and cached per figure. | `figures/` and `figures.json` retain IDs, captions, source locators, and hashes. Vision output is labeled model interpretation, separate from reported results, with provenance. Raw acquisitions stay immutable; figures are regenerable. |
| D17 | **Explicit ownership and resumable stages.** | Files hold authoritative records; SQLite and OKF are rebuildable projections. Separate user content from generated views; use atomic version commits, locks, and stage checkpoints (§3a). |
| D18 | **Passage retrieval and incremental enrichment.** | Retrieve source-linked sections and captions, diversify by paper, rerank within a token budget, and cache expensive work by input and toolchain versions. |
| D19 | **Research projects organize daily work.** | Projects own questions, paper relevance, reading queues, screening decisions, evidence tables, arguments, and saved briefs. A paper can belong to multiple projects without duplication. |
| D20 | **Human review is independent of extraction.** | Reading status and claim verification are explicit. Authoritative correction overlays survive regeneration and become pending review when their evidence context changes. |
| D21 | **Study-aware evidence and writing before discovery.** | Model studies, cohorts/datasets, and methods separately from publications. Build comparison tables, reproducible briefs, and paragraph citation checks before hypothesis exploration. |
| D22 | **PI reporting uses structured, auditable records.** | Researcher identity, ordered authorship, grants, and publication–grant links support deterministic filters and counts. Model extraction proposes evidence-backed matches; ambiguous matches require review. |
| D23 | **Reporting scope and evidence are explicit.** | Curated reading collections are not complete publication portfolios. Author/grant discovery is manual and selected additions remain explicit. Reports snapshot coverage, date/counting rules, evidence, and unresolved records. |
| D24 | **Citation counts are dated observations from a named source, never "the" citation count.** | PMC cited-by (ELink, the adapter `/ref:related` already needs) is systematically incomplete against Scopus/Web of Science and must be labelled as such at every display. Counts persist per paper as observations with source, query, and retrieval date — never in `meta.json`, which holds only facts that do not change under the library's feet. No derived index (h-index, field-normalized score) is computed from an incomplete source. |
| D25 | **One selector grammar; no free-text topic argument.** Every set-valued command selects papers the same way, and the resolved PMID list is frozen into the artifact (§5c). | A bare topic would re-resolve on each run, so a saved comparison would silently change membership underneath its conclusions. Durable subjects are project questions or graph concepts; free text goes through `--search` and is resolved once. Selection reports tier, verification, and retraction counts before expensive work runs. |
| D26 | **Two ID classes: typed slugs and opaque tokens (§3d).** | IDs you type into a selector are user-minted slugs with refused collisions and explicit renames; IDs the system references are opaque and never constructed by a caller. External codes (MeSH, ORCID, DOI, award numbers) are aliases, never primary keys. Formats are fixed in phase 0, since changing one later migrates every record that references it. |
| D27 | **The Papers handoff is a one-way file export, and only the item note travels with it.** `/ref:export --papers` writes a BibTeX batch plus PDF copies into a folder Papers imports from (§7a); `note`/`keywords` carry `notes.md` and tags into `$.user_data` (§7b); highlights never travel outbound. | The live database stays read-only (§7), so the app's own export dialect — including `local-url` PDF attachment — is the contract to reproduce. Since annotations and notes flow *in* via `/ref:pull-annotations`, an outbound note push may only happen on a paper's first export; afterwards it is refused unless forced, and the export manifest records the pushed-note hash that makes that check possible. |

---

## 1. What it does

| Capability | Mechanism |
|---|---|
| Search PubMed by criteria / question / PMID list | PubMed MCP (`search_articles`, `get_article_metadata`, `find_related_articles`, `convert_article_ids`); questions parsed into PICO → boolean MeSH + free-text query (D14) |
| Snowball from a known paper | `/ref:related <pmid>` — backward (reference list from full text) + forward (`find_related_articles`, ELink cited-by); stays within D10 |
| Cite in any style | `meta.json` → CSL-JSON → BibTeX export; rendered at output, default APA 7; stable citekeys (D13); `/ref:export` for `.bib`/CSL files, `/ref:cite` for inline `@citekey` while writing |
| Acquire full text | PMC OA JATS XML (`get_full_text_article`) → Unpaywall OA PDF → publisher HTML ; Papers' extracted fulltext tried first once the phase 4 adapter is available |
| Convert to markdown | JATS → `pandoc -f jats -t gfm` ; PDF → **anydoc** (local, OCR fallback) ; HTML → **trafilatura** → firecrawl scrape for JS-rendered pages (D15) |
| Extract & index figures | each converter path emits available assets in `figures/` + `figures.json` (caption, label, sha256); captions FTS-indexed; selective cached vision descriptions (D16) |
| Normalize to a central repo | one directory per paper, immutable source + derived extraction |
| Structured extraction | OKF v0.2 `Reference` note per paper, paper-specific keys on top |
| Search the repo | SQLite FTS5 over passages (lexical) + OKF concept graph (structural); no vectors in v1 |
| Answer scientific questions | retrieval → grounded synthesis with `[^pmid]` citations, contradiction surfacing |
| Find gaps & generate hypotheses | `/ref:gaps` (single-study claims, unresolved contradictions, untested concept pairs) and `/ref:hypothesize` (Swanson ABC traversal over the OKF graph, candidates checked against PubMed) — D12 |
| Summaries / reviews | `/ref:summarize` writes prose across a selected set; `/ref:review` adds GRADE certainty and risk-of-bias appraisal at full tier; both take the §5c selectors (D14) |
| Report a systematic search | `/ref:review --prisma` renders a PRISMA 2020 flow record — identified, screened, excluded with reasons, sought, retrieved, included — from saved query runs, project screening decisions, and acquisition availability (D14) |
| Library hygiene | `/ref:audit` — re-check retraction/errata status for all PMIDs; `/ref:note <pmid>` — your own free-text thoughts, kept distinct from model extraction |
| Read in ReadCube Papers | push PDF into Papers; selectively pull full text and annotations for chosen PMIDs; notes and annotations flow inbound only (§7b) |
| Organize research | `/ref:project` manages questions, chapter/experiment scope, memberships, relevance notes, and project-specific screening |
| Manage reading | `/ref:queue` tracks to-screen / to-read / reading / read, priority, and why saved; separate from extraction tier |
| Attach acquired PDFs | `/ref:attach <pmid> <path>` verifies identity and preserves a local PDF as an immutable acquisition |
| Review extraction | `/ref:verify` accepts, edits, or rejects claims and concept mappings with evidence-backed correction overlays |
| Search personal thinking | `/ref:search --scope notes` searches notes, annotations, and project relevance comments with explicit personal-content labels |
| Compare evidence | `/ref:compare` builds editable evidence tables with source-linked cells and study-level grouping over any selected set |
| Select papers to work on | one selector grammar across every set-valued command — explicit `<pmid...>`, project/question, screening state, saved query run, study, concept, or frozen search; the resolved list is reported and persisted before work runs (§5c, D25) |
| Reuse methods | `/ref:methods` retrieves protocols, datasets, software, instruments, controls, and analysis choices with evidence locators |
| Support writing | `/ref:check-citations` checks a paragraph's assertions against supplied/library evidence; flags unsupported wording and conflicting results |
| Save research briefs | `/ref:brief` saves answers, evidence snapshots, user revisions, and unresolved questions; explicit refresh shows evidence changes |
| Export to Papers | `/ref:export --papers <selector>` writes Papers' own BibTeX dialect plus PDF copies into a folder the app imports from, `local-url` attaching each PDF; `--notes`/`--tags` carry `notes.md` and tags into the app's Notes and Tags fields; duplicates checked against a read-only snapshot; foreign files never overwritten (§7a, §7b, D27) |
| Identify researchers | `/ref:person` manages name variants, ORCID, affiliation history, and confirmed publication matches |
| Query authorship | `/ref:publications --person <id> --role <role>` filters complete ordered author lists with independently evidenced shared/corresponding roles |
| Track grants | `/ref:grant` manages funders, awards, approved aliases, aims, and evidence-backed publication links |
| Discover portfolio candidates | `/ref:discover --person <id>` or `--grant <id>` runs an explicit PubMed search and queues candidate matches for confirmation |
| Produce PI reports | `/ref:report` exports publication lists by period, researcher, lab, author role, or grant, with evidence and unresolved-match appendices |
| Track citation counts | `/ref:audit --citations` records dated PMC cited-by observations per paper; `/ref:report --citations` includes them with their source and retrieval date, labelled as PMC-indexed coverage rather than total citations (D24) |
| Declare collaborators | `/ref:publications --coauthors --person <id> --since <date>` derives a de-duplicated coauthor list with affiliation at publication time for NSF COA / NIH conflict forms, flagging any paper whose author list is incomplete |
| Review reporting evidence | `/ref:verify` also resolves researcher matches, grant aliases/links, and author contribution statements |


## 2. Prior art in this environment — reuse, don't rebuild

Discovered on this machine:

- **`wiki-manager` skill** (`~/.agents/skills/wiki-manager/`) already implements OKF v0.2 frontmatter, `op-ingest-paper.md` (PMID/DOI → literature note), dedup protocol, query, lint, merge, audit. Roughly 60–70% conceptual overlap with this request.
- **`okf` plugin** ships `okf_mcp.py` with `search_concepts` / `read_concept` / `get_neighbors`, plus validate/visualize/backfill skills. That is a ready-made knowledge-graph retrieval layer.
- **`firecrawl`**, **`graphify`**, **`deep-research`** skills exist and cover HTML scraping, graph building, and multi-source research. (`pdf2md` also exists but is superseded by anydoc — D15.)
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
                                  # trafilatura(HTML) behind one interface — D15
```

Library (data; root chosen at `/ref:init`, recorded in `~/.config/ref-manager/config.json` — D2):

```
<LIBRARY>/
  papers/<pmid>/      # pure PMID dirs — D10 guarantees every paper has one
    meta.json         # bibliographic authority, stable citekey, status + checked_at
    raw/<sha256>/     # immutable metadata response, PDF, JATS, HTML, or Papers text
    acquisitions.json # origin, URL/item ID, fetched_at, media type, hash, availability
    current.json      # atomic pointer to the active validated version
    versions/<id>/
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
    citations.json    # dated cited-by observations: source, query, count, coverage (D24)
    corrections.json  # authoritative claim/mapping/identity/funding review overlays
    state.json        # resumable stage checkpoints and errors
  projects/<slug>/
    project.yaml      # scope, questions, chapter/experiment context
    papers.yaml       # PMID membership, relevance, priority, reading status
    screening.jsonl   # project-specific decisions, reasons, associated search run
    arguments.md      # user-authored working arguments and open questions
    tables/<id>/      # generated evidence snapshots plus separate user edits
    briefs/<id>/      # versioned synthesis/evidence manifest plus user revisions
    prisma/<id>/      # frozen PRISMA flow snapshot: counts, source run IDs, data cutoff
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
    relations.jsonl   # typed edges, evidence claim IDs, version IDs, review state
  okf/                # generated OKF v0.2 Concept/Entity views
  index/
    catalog.sqlite    # rebuildable papers/passages/claims/concepts/relations + FTS5
  queries/<slug>.yaml # saved searches, exact query/date and immutable run histories
  exports/            # generated CSL-JSON and BibTeX
    papers/<batch>/   # references.bib in Papers' dialect + manifest.json
                      #   --layout flat   -> <citekey>.pdf  (self-contained batch)
                      #   --layout papers -> <LastAuthor>/<Journal>-<Year>.pdf, mirroring
                      #     the app's own export convention when writing into the
                      #     configured papers_export_dir (D2 config key, §7a)
  log.md              # operation summaries; checkpoints are machine-readable
```

### 3a. Ownership, persistence, and recovery

- `meta.json` owns bibliographic metadata and citekeys. Allocate a collision suffix under a library-level lock; existing citekeys never change during metadata refresh. PMID is the identity key; DOI/title/hash matches only flag inconsistencies and must not silently merge different PMIDs.
- Raw acquisitions are immutable evidence snapshots. Conversions and extractions are versioned derived records retained for reproducibility. `extraction_tier` is derived from the active validated version; availability and extraction completion are separate states. Missing abstracts produce metadata-only records with an explicit unavailable status, not fabricated claims.
- `notes.md` and `annotations.json` are authoritative user content. Display them alongside generated paper views; regeneration never edits them. Annotation pulls upsert by stable source IDs, preserve provenance, and report source edits/deletions without erasing local notes.
- Export batches are derived artifacts, but their manifests are authoritative for what left the library: each records the frozen selector resolution, the destination path and file hash written per paper, and the hash of any note pushed into Papers. A destination path absent from every manifest is foreign content and is never overwritten or deleted, and a paper already carrying a pushed-note hash refuses a second note push (D27, §7b).
- Structured claim, concept, and relation files back explicit SQLite tables and generated OKF views. Each edge names supporting claims and source version IDs. Reviewed edge decisions persist in relation records. Re-extraction invalidates affected evidence links and triggers an incremental graph refresh.
- Serialize mutations per PMID; use a library lock for citekey allocation and graph commits. Write each version into a staging directory, validate it, then atomically replace `current.json`. Write authoritative JSON updates with temporary files and atomic replacement. Record pending/running/complete/failed stage states and diagnostics.
- SQLite updates occur in transactions after file commits. There is no cross-filesystem/SQLite transaction: track indexed version IDs, detect mismatches on startup, and reconcile before retrieval. `/ref:index --rebuild` reconstructs the catalog from committed records; incomplete staging directories are ignored. Graph views carry version IDs and are refreshed or reported unavailable when stale.
- Retry interrupted stages from the last valid checkpoint. Cache conversion by source hash + converter/version/options; extraction by source hash + schema/model/prompt/options; vision by figure hash + model/prompt/options. Explicit refresh creates a new version. Limit retries and concurrent network/model work; retain actionable errors.


### 3b. Projects, review, and research artifacts

- A project has stable question IDs, scope, and optional chapter/experiment links. Membership references a paper once; relevance, priority, screening, and reading state belong to that membership. Preserve screening history with decision, reason, timestamp, and search-run reference. Exclusion from one project does not exclude a paper globally.
- Human reading states are `to_screen`, `to_read`, `reading`, and `read`. Neither acquisition nor model promotion marks a paper read. Show read status, evidence availability, extraction tier, and human verification separately.
- `corrections.json` stores accept/edit/reject decisions for claims and concept mappings, original and replacement values, rationale, reviewer, timestamp, and evidence locator/hash. Apply valid overlays to retrieval, tables, and graph projections. Never overwrite raw extraction. Preserve decisions on unchanged evidence; changed or superseded evidence makes an overlay pending review rather than silently applying or deleting it. Rejected claims are excluded from default synthesis and retained for audit.
- Study records link publications to an underlying investigation; dataset/cohort reuse is a separate relationship and does not automatically establish that publications describe the same study. Store grouping evidence, confidence, and review state. Summaries report publication counts and identified independent-study counts with uncertain groupings visible.
- Table and brief artifacts have a generated snapshot and a separate authoritative user-edit layer. A manifest records project/question, selected PMIDs, source version IDs, correction versions, and model/prompt versions. Explicit refresh creates a new snapshot and a change report; preserve prior versions and user text, flagging edits whose evidence changed. Research briefs retain unresolved questions and selected evidence, not only rendered prose.
- Typed source references initially resolve to PMID-backed papers; project, question, study, dataset, method, and claim IDs are independent. A future non-PubMed adapter can add identifier types without redesigning all relationships. Non-PubMed ingestion remains outside v1.


### 3c. PI identity, funding, and reporting contract

**Researcher identity and authorship.** Researcher IDs are independent of paper IDs. Profiles retain name variants, ORCID when supplied, dated affiliations, and confirmed/rejected/candidate matches to specific author entries. Name similarity alone cannot establish identity. Preserve the complete ordered published author list, raw metadata provenance, person/group author distinctions, and source completeness. If the list is incomplete or consortium structure makes position ambiguous, mark the role unresolved.

For a verified complete list, the mutually exclusive reporting categories are `sole` (one author), `first` (first of multiple), `last` (last of multiple), and `middle`. A sole author is not counted again as first and last. Preserve literal position and total author count separately. Shared-first, shared-senior, and corresponding authorship are independent flags requiring explicit contribution/correspondence evidence; do not infer seniority or correspondence from last position. Equal-contribution metadata alone does not identify a shared-senior role. Retain statement text, locator, source hash, and review state. See [NLM author metadata](https://www.ncbi.nlm.nih.gov/books/NBK3828/).

**Collaborator declarations.** `/ref:publications --coauthors --person <id> --since <date>` derives the coauthor list that NSF Collaborators and Other Affiliations and NIH reviewer-conflict forms require, from the ordered author lists already preserved above. The window uses the report date basis (§ below), not an unstated default. Output is one row per distinct person — name as published, affiliation at that publication's date when recorded, most recent shared publication, and the PMIDs establishing the relationship — de-duplicated across the window by confirmed researcher identity where one exists and by exact published name otherwise, with those two cases distinguished rather than silently merged.

Completeness is a compliance property here, not a convenience: an omitted collaborator invalidates the declaration. Any paper in the window whose author list is incomplete, truncated, or consortium-structured (the same conditions that make a role unresolved above) must appear in an explicit gap list with the reason, and the export must state that it is derived from library holdings rather than a complete publication record. Group authors are reported as the named group, never expanded into individuals. Unconfirmed same-name candidates are listed separately for review rather than counted as collaborators or dropped.

**Citation observations (D24).** `/ref:audit --citations` records a cited-by observation per paper: source (`pmc_elink`), the exact query, count, retrieval date, and the coverage statement for that source. Observations append to `citations.json`; they never overwrite an earlier one, so a count's movement over time stays visible and a failed check retains the prior observation with its date rather than writing a zero. Absence of an observation is unknown, not zero.

Every display and export carries the source and retrieval date, and labels the figure as citing articles indexed in PMC — not total citations, which this source cannot establish. Reports state the observation window and flag counts older than a configurable staleness threshold. Do not compute h-index, i10, or any field-normalized metric from this source: the input is known-incomplete and a derived index hides that incompleteness behind a single number. A paper with no PMCID or no ELink result is reported as no observation available with the reason.

**Grant identities and evidence.** A grant has a stable ID, funder identity, award number, approved aliases, title, dates, optional PI links, and aims. Preserve raw award strings beside normalized identifiers; normalization is funder-specific and must not collapse distinct awards or award periods without a reviewed rule. A publication can link to multiple grants. The link records the reported funder/award, exact funding statement or metadata evidence, source locator/hash, match method, timestamp, and review decision.

Preserve distinct funding observations: `explicit_acknowledgement_verified`, `indexed_funding_association`, `user_assigned_output`, `possible_match`, and `unknown`. These can coexist as separate evidence records for the same pair. An article's relevance to a grant aim or membership in a funded project does not prove an acknowledgement. Missing metadata, unavailable full text, or an unsuccessful text search must not become a definitive negative. Where checked, report “not found in the inspected sources” with coverage. Extract structured PubMed grants at ingest; inspect JATS funding elements and funding/acknowledgement passages during conversion, independently of scientific-claim promotion. PubMed normalizes some award numbers, so retain its raw response and original article wording when available. Sources: [PubMed GrantList](https://dtd.nlm.nih.gov/ncbi/pubmed/doc/out/250101/el-GrantList.html), [PMC funding markup](https://pmc.ncbi.nlm.nih.gov/tagging-guidelines/article/tags/), [NLM funding metadata](https://www.nlm.nih.gov/databases/download/pubmed_medline.html).

**Portfolio discovery and lab scope.** `/ref:discover` performs a manually initiated person/grant search, saves exact query, retrieval date, pagination/completion status, and candidates. User confirmation is required for ambiguous identity and explicit selection for library additions. Confirming a publication identity does not automatically verify every funding or author-role assertion. Retain rejected matches to prevent repeated suggestions. Lab reports use explicit dated memberships and a declared policy (membership at publication date versus selected roster), not inferred affiliation from coauthorship. Projects can link to grants and aims without changing acknowledgement evidence.

**Reproducible reports.** `/ref:report --person <id> --from <date> --to <date>` supports role filters and optional grant/lab grouping. Persist the chosen date basis (online publication or issue date), missing-date handling, publication types, identity review policy, funding evidence threshold, and deduplication policy. Never silently substitute dates. Report unique-publication totals; grant subtotals may overlap and must be labeled. Export citations, PMID/DOI, dates, author position/category and independent flags, award identifiers, funding evidence, verification status, and source references. CSV plus Markdown is the first export scope; Office-specific formatting can follow later.

Report snapshots retain selected records and metadata/evidence/correction versions, unresolved candidates, unavailable acknowledgement coverage, and the data cutoff. Frozen reports are reproducible; refresh produces a new version with a change summary. By default label scope “confirmed publications in this library,” with PubMed-only coverage and whether portfolio completeness has been reviewed. No report may imply that the curated reading collection is a complete career or lab bibliography. `/ref:verify` reviews identity, grant, and author-role evidence using the same persistent-overlay rules as claim correction.


### 3d. Identifier contract

Every stable ID in this plan falls into one of two classes, and the class determines its shape, who mints it, and what happens on collision. The split already exists implicitly — `raw/<sha256>/` is the machine pattern, the citekey is the human one — and is stated here as a rule because these IDs are written into committed records that reference each other.

**Human-facing IDs are user-minted slugs.** Lowercase `a–z`, `0–9`, and hyphen; 1–64 characters; no leading or trailing hyphen. That charset is safe both as a path segment and as an unquoted CLI token, which matters because these are the IDs you type into a selector (§5c).

| ID | Where | Scope |
|---|---|---|
| project | `projects/<slug>/` | library |
| question | `project.yaml` | **within its project** |
| study, dataset, method | `studies/*.jsonl` | library |
| concept | `graph/concepts.jsonl` | library |
| person, lab, grant | `people/`, `labs/`, `grants/` | library |
| saved query | `queries/<slug>.yaml` | library |

Question IDs are unique only within their project, so `--question` requires `--project` unless exactly one project is in scope. Every other user-minted ID is library-global.

Collisions are **refused**, naming the conflicting record, rather than silently suffixed — unlike a citekey, you can simply choose another name. The citekey is the deliberate exception (D13, §3a): it is minted automatically at ingest where there is nobody to ask, so it takes a collision suffix under the library lock instead.

Renaming is an explicit operation, never a hand edit: it rewrites references under the library lock and records the former ID as an alias, so existing artifacts keep resolving. Concepts additionally accumulate aliases from normalization, which is why their primary key is a slug you choose rather than a code.

**Machine-facing IDs are opaque.** Version IDs (`versions/<id>/`), `claim_id`, table/brief/PRISMA/report IDs, and content hashes are generated at commit, short, and never typed. They are stable once committed, because manifests and relation records reference them — but nothing outside the library may parse or construct one. Each is surfaced by a listing command or by the manifest that cites it.

**External codes are never primary keys, with one deliberate exception.** MeSH and UMLS codes, ORCID, DOI, and funder award numbers are recorded as aliases or attributes, never as the identity of a record, because they can be absent, ambiguous, or revised — so a MeSH descriptor resolves to a concept slug through the alias table rather than becoming the concept's ID, and ORCID is retained "when supplied" (§3c) beside a slug that always exists. The exception is PMID, which D10 makes the identity key for papers because v1 ingests nothing that lacks one; DOI in the same record only flags inconsistencies and never merges papers (§3a). That exception is exactly why D10 also requires typed source references to stay extensible: a future non-PubMed record will need an identity that PMID cannot supply.

**Every typed ID must be discoverable.** Projects, people, and grants list through their own management commands; studies, datasets, and methods through `/ref:methods` and comparison output; concepts through the `okf` plugin's `search_concepts` (§2). No selector may require an ID that has no way to be found.

Phase 0 fixes these formats as part of the schema deliverable. Changing one afterwards means migrating every committed record that references it, which is why it is decided before the first paper is ingested rather than discovered at phase 8.

## 4. Pipeline

```
  explicit PMID list | explicitly selected PubMed search results
            |
    [1] RESOLVE    metadata + ordered authors + indexed grants + abstract + initial status
    [2] DEDUP      PMID identity; stable citekey allocation; preserve raw response
    [3] EXTRACT    abstract evidence when available; provenance-backed claims
    [4] COMMIT     validated version -> metadata/passages/claims FTS -> citation export
            |
            +-- /ref:fetch <pmid...> (optional)
            |     Papers text when integration is available -> reusable PMC JATS
            |     -> Unpaywall PDF -> publisher HTML -> retain abstract-only availability
            |     preserve raw input -> convert -> available figures/captions + diagnostics
            |
            +-- /ref:extract <pmid...> (on demand, requires adequate converted full text)
                  full claim extraction + selective cached figure interpretation
                  -> commit new version -> refresh index and affected graph edges
            |
    [5] WEAVE     structured concepts/relations -> generated OKF views
                  supports | potential_conflict | contradicts | extends | replicates
```

Acquisition failures do not prevent metadata/abstract ingestion. Conversion success alone does not promote the extraction tier. Agent outputs are nondeterministic: persist and validate them before commit. Graph construction is core, built after comparison and writing workflows, and shares the provenance schema established in phase 0.

### 4a. Claim and relation contract

`/ref:extract <pmid...>` accepts multiple PMIDs and fans out one `ref-extractor` agent invocation per PMID (§3, `agents/ref-extractor.md`); each PMID commits its own version independently under its per-PMID lock, so one paper's extraction failure or missing full text does not block the others. Report a per-PMID result rather than a single pass/fail for the batch.

Each claim has a stable `claim_id`, PMID, version ID, evidence tier, source hash, section/page/table/figure locator, and supporting evidence span. Retain IDs for unchanged claims across reruns; materially changed claims receive new IDs with supersession links. Record schema, extractor, model, and prompt versions.

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

- `/ref:compare <selector>` (§5c) produces an evidence matrix for the selected papers: population/model, design, methods, sample size, comparator, results, uncertainty, limitations, and relevance to the question. Cells link to source passages or reviewed claims, distinguish not reported from not extracted, and retain extraction/verification status. Basic comparison does not depend on advanced risk-of-bias or certainty appraisal.
- `/ref:methods` extracts or retrieves protocols, instruments, controls, datasets, software/version, and analysis choices with the setting and source locator. Do not reconstruct unreported procedural details; link supplements when acquired and indicate when unavailable.
- `/ref:check-citations` accepts a paragraph and optional project/bibliography. Split it into checkable assertions and report supporting, conflicting, insufficient, or unavailable evidence; flag overstatement and mismatched citations. Suggestions preserve user prose until applied. Export selected references and the evidence report; available library coverage does not establish a comprehensive literature check.
- `/ref:review --prisma --project <slug>` renders a [PRISMA 2020](https://www.prisma-statement.org/prisma-2020-flow-diagram) flow record for the project's search, as counts plus a Markdown/CSV export and an optional flow diagram. Every number is a query over committed state, not a re-derivation: records identified come from the immutable run histories in `queries/*.yaml` (per source, with the exact query and retrieval date); duplicates removed come from PMID dedup at ingest; records screened and excluded-with-reasons come from `screening.jsonl`; reports sought versus not retrieved come from `acquisitions.json` availability; and included studies come from `studies.jsonl`, so the PRISMA reports-versus-studies distinction is reported rather than collapsed. A published flow must be reproducible: persist the snapshot with its data cutoff, source run IDs, and correction versions, exactly as report snapshots do (§3c). Counts that cannot be evidenced — a search run predating the project, screening performed outside the library — are reported as unknown with their coverage stated, never inferred to make the arithmetic balance. No appraisal, certainty rating, or synthesis-model call is required, so this ships before the phase 10 appraisal machinery.
- `/ref:brief` persists a research answer, its evidence and user revisions. Explicit refresh after additions or corrections reports new support, conflicts, withdrawn evidence, and unresolved questions. No scheduled monitoring or automatic ingestion is introduced.
- Initial graph views answer practical questions: which evidence supports a thesis argument; which publications share a study/dataset; why results differ; which claims lack checked full text; and which methods were used in comparable settings. Use typed project/question/study/dataset/method/claim relationships with provenance; extend these with researcher-authored-publication, publication-acknowledges-grant, publication-supports-aim, and dated researcher-lab membership relationships. Acknowledgement and aim support remain distinct. For scientific relationships, co-occurrence is distinct from evidential support.

### 5b. Gap analysis & hypothesis generation (D12)

Both commands consume structured graph evidence; `/ref:hypothesize` also needs the PubMed search adapter for candidate checking. Missing edges describe library coverage, not established gaps in the literature.

- **`/ref:gaps <selector>`** (§5c) — structural queries over the indexed concept, relation, and claim tables, with OKF views for navigation:
  - claims supported by a single study (fragile evidence)
  - `potential_conflict` and reviewed `contradicts` edges without a recorded resolution
  - concept pairs co-mentioned in text but never directly studied together
  - populations/outcomes absent for an intervention that has them elsewhere
- **`/ref:hypothesize --concept <id>`** (§5c) — Swanson ABC literature-based discovery: two-hop `get_neighbors` traversal (A–B edges from some papers, B–C from others), keep A–C pairs with no direct edge, then **check each candidate against PubMed** (`search_articles`) — untested in the library ≠ untested in the literature. Output: ranked hypotheses, each with its supporting A–B / B–C chains and the PubMed check result, exact search query, timestamp, and limitations. Zero results means “not found by this search,” not proof of novelty.

### 5c. Paper selection — one selector grammar

Every command that operates on a set of papers — `/ref:compare`, `/ref:summarize`, `/ref:review`, `/ref:ask`, `/ref:export`, and the batch acquisition commands — takes the same selectors rather than inventing its own. A bare free-text `topic` argument is **not** one of them (see *Why there is no bare topic argument* below).

| Selector | Resolves to | From |
|---|---|---|
| `<pmid...>` | exactly those papers; the base case | phase 1 |
| `--project <slug>` | project membership, optionally narrowed by `--question <qid>` | phase 1 |
| `--screened included\|excluded\|pending` | recorded screening decisions in `screening.jsonl` | phase 2 |
| `--read` / `--queue <state>` | human reading state, never model promotion (§3b) | phase 1 |
| `--query <slug> [--run <id>]` | one immutable saved search run from `queries/*.yaml` | phase 2 |
| `--search "<expr>"` | FTS hits, resolved once and frozen — never a standing definition | phase 2 |
| `--study <id>` | every publication of one investigation, via `studies.jsonl` | phase 5 |
| `--concept <id>` | a graph concept, resolved through its alias table | phase 8 |
| `--from-file <path>` | a PMID list from a file, for sets too large to type | phase 1 |

IDs used in these selectors follow §3d: typed IDs are lowercase slugs, and `--question` is scoped to its project. Selectors combine with AND: `--project thesis-ch3 --screened included --tier full` is the systematic-review set; `--study nhanes-2019` is everything from one cohort; a bare PMID list is an ad-hoc look at a handful of papers without creating a project first. `--tier abstract|full|any` and `--exclude <pmid...>` refine any of them. An empty resolution is an error naming the selector that matched nothing, not an empty synthesis.

**Resolve, report, then work.** Every selector resolves to an explicit PMID list before any expensive retrieval or model call, and that list is reported with counts by extraction tier, human verification state, and retraction/errata status. A comparison across twenty abstract-only papers is a categorically weaker artifact than one across twenty full-tier papers; surfacing that at selection makes it a decision rather than a footnote discovered afterwards. Commands that would exceed a configured paper or token budget say so and stop instead of silently truncating.

**Freeze the resolved set.** The artifact manifest records both the selector expression and the PMIDs it resolved to, with the resolution timestamp, source version IDs, and correction versions — the same contract `tables/`, `briefs/`, and `reports/` already follow (§3b, §3c). Re-running a selector later may legitimately match a different set; explicit refresh re-resolves and reports the delta as added, removed, and changed-evidence papers. A saved comparison never silently changes membership underneath its conclusions.

**Why there is no bare topic argument.** A free-text topic would be re-resolved at each run, so the same command a month later would quietly answer over a different paper set — which contradicts how every other saved artifact in this plan behaves. Durable named subjects are therefore project questions (`--question <qid>`, stable from phase 1) or graph concepts (`--concept <id>`, phase 8, where aliases make "MI" and "myocardial infarction" one node). Free text remains available through `--search`, where it is resolved once and frozen into the manifest. Before phase 8 there is no concept graph, so subject-shaped selection is project questions plus frozen searches; `--concept` is the later upgrade, not the starting point.

**Division of labour.** The three synthesis commands share the selector grammar and differ in output and prerequisites:

- **`/ref:compare`** — structured evidence matrix, one row per paper or grouped study, cells linked to passages or reviewed claims. No appraisal machinery; ships in phase 5.
- **`/ref:summarize`** — prose narrative across the selected set, or a single paper when the set is one. Phase 10.
- **`/ref:review`** — appraised synthesis: GRADE-style certainty and risk-of-bias judgements over the set, plus evidence tables. Phase 10. `--prisma` is a separate mode reporting the search itself rather than the papers (§5a), and needs no appraisal.

## 6. Full-text acquisition — scope and limits

`/ref:attach <pmid> <path> [<pmid> <path> ...]` supports one or more PDFs the user has already acquired, each PMID paired with its own path. Match embedded identifiers and bibliographic metadata to the existing record; refuse silent attachment on conflict, and request resolution for ambiguous identity. Store verified bytes under `raw/<sha256>/source.pdf` with attachment provenance, then use the same conversion and promotion pipeline. Duplicate content is a no-op. Process each pair independently so one conflict or failure does not block the rest of the batch. This works before Papers integration and does not add identifier-less records.

Clean and legal, in priority order:

1. **PMC Open Access subset** — free full text via the PubMed MCP / OA service. Check reusable full-text availability explicitly; a PMCID alone does not guarantee it. Prefer **JATS XML** over PDF when available. Preserve XML and linked assets, then convert with `pandoc -f jats -t gfm`; test tables, math, references, and figure links on fixtures. Record missing assets and conversion losses. See [PMC API availability](https://pmc.ncbi.nlm.nih.gov/tools/oai/).
2. **Unpaywall** (`api.unpaywall.org`, needs an email as API key — recorded in `config.json` at `/ref:init`, never prompted per fetch) — locates author manuscripts and publisher OA copies.
3. **Publisher HTML** for openly readable articles — fetched + converted with **trafilatura** first (local, free, article-aware boilerplate removal), **firecrawl scrape** as fallback for JS-rendered publisher SPAs. `<figure>` elements yield images + captions where present (D15, D16).
4. **Everything else stays paywalled.** ref-manager will record the paper with abstract + metadata only, set `full_text: false`, and hand the DOI to Papers.app, which holds the institutional credentials and is the appropriate place to fetch it. The plugin will not attempt to bypass paywalls or proxy authentication.

Abstract-only records stay first-class and visibly flagged, so a synthesis never silently treats an abstract as a read paper.

## 7. ReadCube Papers integration — selective, not bulk

**The library starts empty (D11).** No bulk import from Papers. The confirmed schema below is used for *targeted lookups* of papers you have already decided to add — never for a sweep.

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

- **Batch export** (spec: §7a) — `/ref:export --papers` takes explicitly selected PMIDs or a project selection and emits `exports/papers/<batch>/references.bib`, available PDFs under readable citekey filenames, and a manifest listing included/missing PDFs and source hashes. Copies leave originals unchanged. Import the bibliography and PDFs through Papers' import UI; verify matching and duplicates. Claims, graph records, and Markdown notes are not transferred by this export. No live database writes or automatic import are required.
- **Push** — `/ref:open <pmid>`: `open -a Papers <pdf>` sends a PDF ref-manager acquired into Papers for reading and annotating.
- **Opportunistic full text** — during `/ref:fetch` for a paper you added, check whether Papers already holds it (match on PMID, else DOI) and reuse its extracted `fulltext` instead of re-downloading. Preserve the text snapshot and item/hash provenance; report missing figures and source locators. Skip when absent, and continue acquisition when richer source material is needed.
- **Batch fetch** — `/ref:fetch <pmid...>` accepts multiple PMIDs; process each independently under its own per-PMID lock, so one acquisition failure or missing full text does not block the rest of the batch. Report a per-PMID result (acquired / abstract-only / failed), not a single pass/fail for the whole call.
- **Annotation pull** (storage and direction: §7b) — `/ref:pull-annotations <pmid>`: bring your highlights and margin notes for *that* paper into its record. Annotations persist in `annotations.json` and appear under **Your annotations** in the composed display. `/ref:note` writes `notes.md`. Neither is overwritten by generated views or blended with extracted evidence.

Snapshot and access contract:

- Query only a consistent snapshot. Create it using the [SQLite backup API](https://www.sqlite.org/backup.html) with a read-only source connection; the only live-database access is the snapshot read. Never copy an active `.db` file alone or discard its WAL. If a consistent snapshot cannot be obtained, warn and skip integration.
- **Never write** to it. `actions_queue` is a live ReadCube sync queue; writing risks corrupting your sync.
- The schema is undocumented and vendor-owned. Every read validates the paths it expects and warns-and-skips per field rather than failing the run.


### 7a. `/ref:export --papers` — the Papers handoff

Papers is the reading frontend; the repo stays the authority. The handoff is therefore a **one-way, file-based export into a folder Papers imports from**, never a write into the live database (§7 forbids that, and `actions_queue` makes it dangerous). Papers pulls, ref-manager pushes files.

The export format is not invented: the folder at `~/Library/Mobile Documents/com~apple~CloudDocs/PapersReadCube/` is Papers' *own* export output, and its shape is the specification this command reproduces — PDFs laid out as `<LastAuthor>/<Journal>-<Year>.pdf` beside `.bib` files whose entries carry `local-url` pointers to those PDFs. Matching the dialect the app itself emits is the cheapest way to be confident the import round-trips.

**Command.**

```
/ref:export --papers <selector> [--to <dir>] [--layout papers|flat] [--pdfs copy|link|none]
                                [--notes[=force]] [--tags <a,b>|--tags-from project]
                                [--skip-known|--force] [--collection <name>] [--dry-run] [--refresh]
```

`--notes` and `--tags` carry user content into the app's own fields; their contract is §7b.

`<selector>` is the §5c grammar, unchanged — `<pmid...>`, `--project`, `--screened included`, `--query`, `--search`, `--from-file`, refined by `--tier` and `--exclude`. It resolves, reports tier/verification/retraction counts, and freezes into the batch manifest before a single file is copied. There is no bare topic argument and no "export everything": an export is a set you chose.

**Destination.** `--to` defaults to `papers_export_dir` recorded by `/ref:init`. With no configured directory the command writes a self-contained batch under `exports/papers/<batch>/` and says so, rather than guessing a path inside iCloud.

**Layout.** `--layout papers` (default when exporting into the configured Papers folder) mirrors the app's convention `<LastAuthor>/<Journal>-<Year>.pdf`, sanitizing path separators and colons and suffixing `-2`, `-3` on collision, so the batch blends into the folder already there. `--layout flat` (default for `exports/papers/<batch>/`) writes `<citekey>.pdf`, which keeps a batch readable and self-describing. Either way the citekey stays the repo's `authorYearFirstword` (D13) — Papers matches on DOI/PMID, not on the key, so there is no reason to adopt its `Author.Year` style and lose stability.

**Emitted files.**

| File | Contents |
|---|---|
| `references.bib` | one entry per resolved PMID, in Papers' dialect |
| PDFs | copies of acquired full text, under the chosen layout; originals in `raw/` are never moved or altered |
| `manifest.json` | selector expression, resolved PMIDs, citekeys, per-paper PDF path and source hash, PDF-missing list, entry-field omissions, destination, timestamp |

**BibTeX contract**, taken from the observed export: `@article` for journal articles with a typed fallback for others; `title` and `abstract` double-braced to protect capitalization; `author = {Last, First and Last, First}` preserving ingest order (§3c); `journal`, `volume`, `number`, `pages` with an en-dash range as `--`, `issn`, `year`; `doi`, `pmid`, and `pmcid` when known, since those are what Papers deduplicates and enriches on; UTF-8 written literally (the observed file carries `Schulte-Rüther` and `Arnatkevičiūtė` unescaped) with BibTeX-special characters escaped; and `local-url = {file://localhost/<percent-encoded absolute path>}` when a PDF is included, which is the mechanism that attaches the file on import. `--pdfs none` omits `local-url` and produces a metadata-only bibliography.

**What is not exported.** Claims, evidence tiers, the concept graph, and `notes.md` do not cross. Annotations especially do not: §7 makes Papers the annotation *source* and `/ref:pull-annotations` the direction of travel, so pushing them back would create a two-master loop. `--collection <name>` only records an intended collection name in the manifest and in a per-batch subfolder; ref-manager does not create collections in the app.

**Duplicate handling.** Importing a paper Papers already holds creates a duplicate. With the read-only snapshot available (§7), the command checks each resolved PMID (else DOI) against the live library and reports already-present papers; `--skip-known` omits them from the batch, `--force` exports anyway. When no snapshot can be taken, it warns that duplicate detection is unavailable and continues — integration is optional at runtime (§8) and must not block the export.

**Re-export and foreign files.** The batch manifest makes re-export idempotent: an unchanged source hash reuses the existing path instead of re-copying, changed metadata rewrites only its bib entry, and `--refresh` re-resolves the selector and reports added, removed, and changed-evidence papers exactly as saved artifacts do (§5c). Any path in the destination that is not recorded in a ref-manager manifest is **foreign and never overwritten or deleted** — the configured folder already holds PDFs Papers itself wrote. `--dry-run` prints the resolved set, target paths, foreign-path conflicts, and missing PDFs without touching the filesystem.

**Import step, done by you.** Papers imports the `.bib` through its own UI; ref-manager does not drive the app beyond `/ref:open` (§7). The command prints the destination path and the import instruction, then stops. Whether Papers also ingests BibTeX dropped into a watched folder is unverified and must not be assumed by the design.

**Gate (phase 3).** Round-trip a three-paper batch into a scratch Papers library and confirm PMID, DOI, title, ordered authors, journal/year, and the attached PDF all arrive. Fixtures: a unicode author name; a title containing `&` and `%`; an abstract-tier paper with no PDF (entry exported, `local-url` absent, manifest lists it as missing); two papers producing the same `<Journal>-<Year>.pdf` name under one author; a re-export with one changed metadata field and one unchanged PDF; a destination containing a foreign PDF at a colliding path; and a run with the live database unreadable, which must still export.


### 7b. Where Papers keeps notes, and what ref-manager may push into them

Everything the app calls "notes" lives inside the one SQLite library (`~/Library/Application Support/Papers/<uuid>.db`), in each item's `json` blob — nothing is written into the PDF files, and nothing appears in the iCloud export folder, which carries only PDFs and `.bib`. Confirmed against a read-only snapshot of the live library (1080 items):

| Kind | Path | Shape | Observed |
|---|---|---|---|
| Item note (the **Notes** column) | `$.user_data.notes` | plain text, one per item | 76 items |
| Highlights and margin notes | `$.user_data.annotations[]` | `{id, type: highlight\|note, sha256, page_start, rects\|position, text, note, has_note, color_id, created, modified, user_*}` | 324 highlights, 5 notes |
| Tags | `$.user_data.tags` | JSON array of strings | 29 items |
| Rating, star, colour, read state | `$.user_data.rating\|star\|color\|unread\|last_read` | scalars | 19 / 18 / 8 / all |

Two consequences for the design. Annotations are anchored to a **file** (`sha256`) plus page rectangles, not to the bibliographic record — so they only make sense against the exact PDF Papers holds. And all of it is user-generated content sitting in a vendor-owned, cloud-synced store, which is why §7 makes this the pull direction: `/ref:pull-annotations` reads `$.user_data.annotations`, `/ref:note` owns `notes.md`, and the two are never blended.

**What the export channel can carry.** Papers' own BibTeX export round-trips three user fields, verified by matching its output against the live database: `note = {...}` ↔ `$.user_data.notes`, `keywords = {a,b}` ↔ `$.user_data.tags`, and `rating = {5}` ↔ `$.user_data.rating`. So the item note *is* exportable from ref-manager, on the same import path as the metadata:

- `--notes` emits `notes.md` as `note = {...}`, newlines preserved as the observed export does, BibTeX-special characters escaped. Off by default.
- `--tags <a,b>` or `--tags-from project` emits `keywords`, so an imported batch arrives already filed under the project it came from.
- Rating is never written: it is a reading judgement made in Papers, and the repo has no authority over it.

**One-way, and first-import only.** `notes.md` may itself have been *derived* from a Papers note by `/ref:pull-annotations`; re-exporting it would push a stale copy back over whatever you have since written in the app. So `--notes` applies only to papers the destination manifest has not exported before; for a paper already exported, it is refused with the conflict named, and `--notes=force` is required to overwrite. The manifest records, per paper, whether a note was pushed and the hash of the text that was pushed, which is what makes that check possible.

**Highlights and margin notes cannot be pushed, by construction.** There is no BibTeX field for them, writing the database is forbidden (§7), and their page-rectangle anchors are only valid against Papers' own copy of the file. If annotated PDFs are ever wanted in the app, the only safe route is a later opt-in `--burn-annotations`, which stamps ref-manager-held annotations into the *exported copy* of the PDF as standard PDF annotations — visible in any reader, but not Papers annotations: not in `$.user_data.annotations`, not synced, not searchable through the app's annotation index. That trade-off is why it stays out of the phase 3 scope.

**Gate addition (phase 3).** Export one paper with a note and two tags, import it, and confirm the note appears in the Notes column and the tags in Tags. Then re-export the same paper and confirm the note push is refused rather than silently overwriting the version edited in Papers.


## 8. Build order

| Phase | Deliverable | Gate |
|---|---|---|
| 0 | Scaffold/init/status; identifier contract (§3d); authority, project, researcher/authorship, grant/funding, claim/correction and study schemas; atomic commits, migrations, locks, rebuild contract | Empty library works; interrupted commit recovers; typed identities do not require PMID for non-paper entities; slug validation rejects illegal characters, a duplicate slug is refused with the conflicting record named rather than suffixed, a rename rewrites references and leaves a resolving alias, and question IDs collide freely across projects without ambiguity |
| 1 | `/ref:add`, `/ref:project`, `/ref:queue`, `/ref:note`, `/ref:person`, `/ref:grant`; ordered authors, indexed grants, stable citekeys and initial status checks | Fixtures cover missing abstracts, duplicate adds and citekey collisions; one paper belongs to two projects with independent relevance/screening/reading states; raw author order and grant strings survive ingest |
| 2 | Selector grammar (§5c) shared by set-valued commands; passage and personal-note search; `/ref:export --bib/--csl`, `/ref:cite`; PubMed discovery, saved query runs and project screening; `/ref:discover`, `/ref:publications` incl. `--coauthors`, basic `/ref:report` | Search finds evidence and personal comments with distinct labels; citation exports render correctly; manual rerun preserves history and requires explicit selection to add; index rebuild preserves results; a selector resolves to a reported PMID list with tier and status counts before work runs, an empty match errors rather than yielding an empty result, and a frozen set is re-resolved only on explicit refresh; same-name candidates remain unresolved, sole authors count once, incomplete lists do not yield confident roles, and frozen reports reproduce; the coauthor export de-duplicates across the window, reports group authors as groups, and lists every incomplete author list as a gap rather than omitting it silently |
| 3 | `/ref:attach`, `/ref:fetch`, source preservation and conversion, funding/acknowledgement and contribution-statement extraction; `/ref:open`, `/ref:export --papers` (§7a) | Local PDF identity conflicts are caught; incomplete conversion remains visible; retries preserve evidence; export includes selected references and available PDFs without altering originals; a three-paper batch round-trips into a scratch Papers library with PMID, DOI, ordered authors, and attached PDF intact, a pushed note and tags land in the app's Notes and Tags fields, a second export refuses to overwrite a note edited in Papers, a foreign file at a colliding destination path is never clobbered, and an unreadable live database degrades to an export without duplicate detection rather than a failure; funding locators resolve even without full claim promotion; missing acknowledgement sources remain unknown; a multi-PMID `/ref:fetch`/`/ref:attach` call reports per-PMID results and one failure does not block the rest |
| 4 | `/ref:extract`, `/ref:verify`; full extraction, selective vision, correction overlays including author/grant evidence review; targeted Papers snapshot/annotation pull | Claims resolve to sources; rejected claims leave default synthesis; corrections survive unchanged reruns and become pending on changed evidence; notes survive promotion; snapshot and repeat annotation pulls are consistent; grant aliases preserve distinct awards, shared-role flags require explicit statements, and report counts respect reviewed evidence; a multi-PMID `/ref:extract` call commits each paper's version independently and one paper's failure does not block the others |
| 5 | `/ref:compare` over any §5c selector, `/ref:methods`, `/ref:review --prisma`; study/dataset grouping and basic evidence tables | Table cells resolve to evidence; a bare PMID list and a project selector produce the same table for the same papers; the saved table records both the selector and the PMIDs it resolved to, and refresh reports added/removed/changed-evidence papers rather than changing membership silently; missing values are explicit; multiple papers from one study are grouped without treating all dataset reuse as the same study; methods retain source/context; the PRISMA flow reconciles against saved run histories and screening decisions, reports studies separately from reports, and marks unevidenced counts unknown rather than balancing the arithmetic |
| 6 | Project-scoped `/ref:ask`, saved `/ref:brief`; passage diversification and citation validation | Expected-evidence recall and assertion support are measured; project filters work; evidence tiers/status are visible; explicit brief refresh shows changes and preserves user edits |
| 7 | `/ref:check-citations`; argument support, selected bibliography/evidence export | Test paragraph includes supported, overstated, conflicting, and unsupported assertions; findings link to evidence and do not rewrite user text automatically |
| 8 | Structured graph + OKF views across questions/studies/datasets/methods/claims and researchers/grants/labs; conflict review | Practical graph questions resolve to source evidence; mismatched contexts do not become contradictions; stale edges invalidate; reviewed decisions survive rebuilding |
| 9 | `/ref:gaps`, `/ref:hypothesize`, `/ref:related`; PubMed candidate checking and snowballing | Candidates retain evidence chains and search query/date; missing edges or zero search results are not presented as proof of novelty |
| 10 | `/ref:summarize`, advanced `/ref:review`; certainty and risk-of-bias appraisal | Appraisal traces judgments to evidence, flags missing inputs, and distinguishes model drafts from human-reviewed assessments; both accept the §5c selectors, a one-paper set degrades to a single-paper summary, and a set that is wholly abstract-tier is reported as such before appraisal runs |
| 11 | `/ref:audit` refresh incl. `--citations`, `/ref:report --citations`; library maintenance | Changed status propagates to subsequent answers/views; saved artifacts expose stale evidence without overwriting their history; failed checks retain prior status with diagnostics; citation observations append rather than overwrite, a failed check keeps the prior dated count instead of writing zero, missing observations read as unknown not zero, and every display names the source and retrieval date |

**Collect and organize: phases 0–2. Read and verify: phases 3–4. Compare and write: phases 5–7. Connect and discover: phases 8–9.** Graph discovery remains required scope, while advanced appraisal follows the daily research workflow. Papers database integration is optional at runtime and must not block local attachment, export, or verification.

The PhD workflow acceptance test is: **take 20 papers for one thesis question, identify what they establish, inspect disagreements, and produce a paragraph whose citations can be verified.** Exercise project membership, local attachment, extraction correction, evidence comparison, and bibliography export along that path.

The PI workflow acceptance test is: **generate an annual publication report grouped by grant and authorship role, with every inclusion traceable and every unresolved match visible.** Fixtures cover name collisions, sole/first/middle/last positions, incomplete/group author lists, explicit shared contributions, multiple grants per paper, award aliases, funding metadata without full text, an acknowledgement absent from indexed metadata, uncertain identity, date-boundary cases, and cross-grant totals without double counting. Report generation queries structured reviewed records and must not need a synthesis-model call. Two adjacent PI obligations use the same records and the same evidence rules: a collaborator declaration for a submission window, whose fixtures include an incomplete author list that must surface as a gap rather than a short list; and citation observations, whose fixtures include a paper with no PMCID, a failed lookup that must retain its prior dated count, and a display that must not read as a total citation count.

Keep a small versioned fixture set and a labeled retrieval/answer evaluation set. Track recall at the candidate budget, conflicting-evidence inclusion, citation resolution, and manually assessed assertion support. Require all fixture citations to resolve and no user-content loss; record a retrieval baseline and reject regressions before expanding scope. Measure conversion/extraction cache hits, model-call counts, and latency to guide optimization instead of adding embeddings preemptively.

## 9. Residual assumptions — flagged, not blocking

1. **The repo and your Papers library will diverge.** That is the point of D11, but it is worth saying plainly: papers you read in Papers are not in the repo unless you add them, and `/ref:ask` can only reason over what the repo holds. If that gap becomes annoying, a one-off selective import is easy to add later — the schema work in §7 is already done.

2. **The import direction is only evidenced, not documented.** The export dialect in §7a and the `note`/`keywords`/`rating` mapping in §7b were read off Papers' own export and matched against its live database, which establishes what the app *writes* — the phase 3 round-trip gate exists because it does not by itself establish what the app accepts on import. Whether a watched folder ingests BibTeX unattended is unverified and nothing in the design may depend on it.

3. **Papers schema is vendor-owned and undocumented.** Confirmed correct today against a real library; a ReadCube update can move fields. The sync script validates expected paths up front and warns-and-skips per field rather than failing the run.

4. **No embeddings (D3) means FTS misses paraphrase.** Mitigated by MeSH/synonym query expansion, not solved by it. If `/ref:ask` starts missing papers you know are in the library, that is the signal to revisit D3 — worth watching deliberately rather than discovering late.

5. **Tiered extraction (D4) means most papers are abstract-only.** Every synthesis must label which tier backed each citation, so thin evidence cannot pass as a read paper.

6. **Paywalled full text stays out of reach.** Acquisition depends on PMC OA, Unpaywall, and whatever Papers happens to hold for papers you add. Local attachment provides another route for user-acquired PDFs; some records may still remain abstract-tier permanently.

7. **ABC hypothesis generation over-generates.** Two-hop co-occurrence produces many spurious A–C candidates; the PubMed novelty check filters known links but not implausible ones. `/ref:hypothesize` output is a ranked *reading list of candidates*, not claims — presentation must say so.

---

## 10. First implementation step

Phases 0 → 2: `/ref:init <path>` to create the library at a location you choose, then `/ref:add <PMID...>` to put the first papers in it deliberately. Target for the first working slice is a handful of papers you actually care about, ingested end to end — resolved, deduped, catalogued, abstract-tier extracted when available, findable via `/ref:search`, and exportable through stable citekeys and CSL-JSON/BibTeX. Define authority, claim provenance, and crash-recovery fixtures before writing the extractor. Include a project/question, relevance notes, reading queue, and project-specific screening in this slice. Finish it before introducing full-text conversion or graph generation.
