# ref-manager — Claude Code plugin for scientific reference management

Status: **design settled, ready to implement.** All decisions in §0. Residual assumptions flagged in §9.

## 0. Decisions made

| # | Decision | Consequence |
|---|---|---|
| D1 | **Standalone OKF bundle.** ref-manager does not write into wiki-manager's bundle. | Own `okf/` under the library root. OKF v0.2 semantics are re-read from the spec, not inherited from wiki-manager. `okf` plugin MCP + validate/visualize skills still apply to the bundle since they are bundle-generic. |
| D2 | **Library path chosen at init.** `/ref:init [path]` asks for the library root and records it in config; the plugin never hardcodes a location. | Needs a config file resolving the active library, plus a guard so every command fails loudly when no library is configured. |
| D3 | **No embeddings in v1.** Retrieval = SQLite FTS5 + OKF concept graph. | Phase 7 becomes optional/deferred. Retrieval design must not assume a vector store exists. |
| D4 | **Tiered extraction.** Every paper gets an abstract-level record; full atomic-claim extraction only on demand. | `meta.json` carries an `extraction_tier` field (`abstract` / `full`), promotable. Retrieval and synthesis must state which tier backed each cited claim. |
| D5 | **Papers.app: push + *selective* pull.** No bulk import. | The library starts empty and grows only by your explicit choice. Papers is a reading target, plus an opportunistic full-text and annotation source for papers you have already chosen to add. |
| D6 | **Scale: 500–5k papers, ongoing multi-topic.** | FTS5 holds. OKF concept graph becomes the primary navigation surface, not a nicety. Extraction template must cover several study designs, not one. |
| D8 | **Mixed field — template detected per paper.** | The extractor first classifies study type (RCT / cohort / case-control / meta-analysis / molecular / imaging / review), then applies the matching extraction template. No fixed-field assumption; `study_type` becomes a first-class queryable key. |
| D9 | **Discovery is manual and explicit.** | `/ref:add <PMID>` and PubMed search are the ways in. No scheduled jobs, no background ingest. Standing queries exist but are re-run manually (`/ref:update-queries`), never on a schedule. Clipping in the browser still files a paper in Papers for reading; it enters the repo only when you add it. |
| D10 | **Citations: BibTeX + CSL-JSON stored; style chosen at output; default APA 7.** | CSL-JSON is canonical, generated from `meta.json`. Rendering via CSL style files at export time, so any style works without re-ingesting. |
| D11 | **PubMed only in v1.** | Every paper must resolve to a PMID. No preprint, arXiv, or identifier-less PDF path. Keeps dedup and identifiers single-keyed. |
| D12 | **Library starts empty.** Papers are added deliberately, one decision at a time. | No seeding, no backfill. Growth is curated rather than inherited, so every record in the repo is there because you put it there. |
| D13 | **Knowledge graph is core, not compounding value.** Gap analysis and hypothesis generation (Swanson ABC literature-based discovery) are first-class outputs. | OKF weaving moves up in the build order (right after `/ref:ask`). Claim extraction must produce normalized, comparable claim tuples `(population, exposure/intervention, outcome, direction, effect)` — designed before the extractor is written, since ABC linking and contradiction detection depend on them. New commands `/ref:gaps` and `/ref:hypothesize`. |
| D14 | **Stable citekeys + single export path.** Citekey `authorYearFirstword` assigned at ingest, recorded in `meta.json`, never regenerated. | CSL-JSON canonical (D10) feeds every target: `/ref:export` emits BibTeX (`--bib`) and CSL-JSON (`--csl`); pandoc and quarto both consume `.bib`/CSL + `@citekey`, so one exporter covers LaTeX, Word/Zotero, and markdown writing. |
| D15 | **Systematic-review machinery built, but staged.** PICO query building and a screening log land with the core; GRADE certainty, risk-of-bias checklists, and evidence tables come later. | `/ref:search-pubmed` parses questions into PICO and logs include/exclude decisions with reasons in `queries/*.yaml`. Full-tier extraction templates later gain RoB 2 (RCT), Newcastle-Ottawa (cohort/case-control), AMSTAR-2 (meta-analysis); `/ref:review` gains GRADE-style certainty ratings and evidence tables. |
| D16 | **Conversion toolchain: JATS-first, anydoc for PDFs, trafilatura for HTML.** `pandoc -f jats -t gfm` whenever a PMCID exists (near-lossless structure, no scraping); **anydoc** (`@firecrawl/anydoc`, local Rust, LaTeX equations, hosted OCR fallback for scans) replaces pdf2md; publisher HTML via **trafilatura**, falling back to firecrawl scrape for JS-rendered pages. anydoc takes no HTML input — it is the PDF/Office leg only. | Three converters, one output contract: GFM `source.md` + extracted assets. Each `meta.json` records which converter produced `source.md`. |
| D17 | **Figures are first-class knowledge.** Every conversion path extracts figures + captions into the paper's directory; captions are FTS-indexed; full-tier promotion adds a vision-model description per figure. | `figures/` holds image files + `figures.json` (id, label, caption, source, sha256). Captions searchable via `/ref:search`; figure descriptions land in `paper.md` and are weavable into `okf/` like any claim. `source.pdf` stays immutable — figures are derived artifacts, regenerable. |

---

## 1. What it does

| Capability | Mechanism |
|---|---|
| Search PubMed by criteria / question / PMID list | PubMed MCP (`search_articles`, `get_article_metadata`, `find_related_articles`, `convert_article_ids`); questions parsed into PICO → boolean MeSH + free-text query (D15) |
| Snowball from a known paper | `/ref:related <pmid>` — backward (reference list from full text) + forward (`find_related_articles`, ELink cited-by); stays within D11 |
| Cite in any style | CSL-JSON canonical + BibTeX export; rendered at output, default APA 7; stable citekeys (D14); `/ref:export` for `.bib`/CSL files, `/ref:cite` for inline `@citekey` while writing |
| Acquire full text | PMC OA JATS XML (`get_full_text_article`) → Unpaywall OA PDF → publisher HTML ; Papers' own extracted fulltext tried first |
| Convert to markdown | JATS → `pandoc -f jats -t gfm` ; PDF → **anydoc** (local, OCR fallback) ; HTML → **trafilatura** → firecrawl scrape for JS-rendered pages (D16) |
| Extract & index figures | every converter path emits `figures/` + `figures.json` (caption, label, sha256); captions FTS-indexed; vision descriptions at full tier (D17) |
| Normalize to a central repo | one directory per paper, immutable source + derived extraction |
| Structured extraction | OKF v0.2 `Reference` note per paper, paper-specific keys on top |
| Search the repo | SQLite FTS5 (lexical) + vector index (semantic) + OKF concept graph (structural) |
| Answer scientific questions | retrieval → grounded synthesis with `[^pmid]` citations, contradiction surfacing |
| Find gaps & generate hypotheses | `/ref:gaps` (single-study claims, unresolved contradictions, untested concept pairs) and `/ref:hypothesize` (Swanson ABC traversal over the OKF graph, candidates checked against PubMed) — D13 |
| Summaries / reviews | per-paper, per-topic, and evidence-table outputs; GRADE certainty + risk-of-bias appraisal at full tier (D15) |
| Library hygiene | `/ref:audit` — re-check retraction/errata status for all PMIDs; `/ref:note <pmid>` — your own free-text thoughts, kept distinct from model extraction |
| Read in ReadCube Papers | push PDF into Papers; mirror Papers library state back into the catalog |

## 2. Prior art in this environment — reuse, don't rebuild

Discovered on this machine:

- **`wiki-manager` skill** (`~/.agents/skills/wiki-manager/`) already implements OKF v0.2 frontmatter, `op-ingest-paper.md` (PMID/DOI → literature note), dedup protocol, query, lint, merge, audit. Roughly 60–70% conceptual overlap with this request.
- **`okf` plugin** ships `okf_mcp.py` with `search_concepts` / `read_concept` / `get_neighbors`, plus validate/visualize/backfill skills. That is a ready-made knowledge-graph retrieval layer.
- **`firecrawl`**, **`graphify`**, **`deep-research`** skills exist and cover HTML scraping, graph building, and multi-source research. (`pdf2md` also exists but is superseded by anydoc — D16.)
- **Papers.app** (`com.ReadCube.Papers`) is an Electron app with a local SQLite library at
  `~/Library/Application Support/Papers/<uuid>.db` — tables `items`, `collections`, `fulltext`, `fts`, `actions_queue`, `sync_meta`.
  It registers **no custom URL scheme**; it is a PDF document handler.

**Design consequence:** ref-manager should be the *acquisition + extraction + retrieval engine* and delegate knowledge-article maintenance to the OKF/wiki layer, rather than forking a second OKF implementation. See Q1.

## 3. Repository layout

Plugin (this folder, versioned):

```
ref-manager/
  .claude-plugin/plugin.json
  commands/            /ref:init /ref:add /ref:fetch /ref:promote /ref:search
                       /ref:ask /ref:search-pubmed /ref:update-queries /ref:related
                       /ref:gaps /ref:hypothesize /ref:export /ref:cite
                       /ref:summarize /ref:review /ref:audit /ref:note
                       /ref:open /ref:pull-annotations /ref:index /ref:status
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
    meta.json         # normalized bibliographic record (canonical) + extraction_tier + citekey
    source.pdf        # original, immutable
    source.md         # full text as markdown
    paper.md          # OKF Reference note: frontmatter + atomic extracted claims
                      #   + figure descriptions (vision model, full tier — D17)
    figures/          # extracted images (derived, regenerable)
    figures.json      # per figure: id, label, caption, source, sha256
  okf/                # OKF v0.2 bundle — cross-paper Concept/Entity notes (standalone, D1)
  index/
    catalog.sqlite    # metadata + FTS5 over source.md + dedup keys
                      # vectors.sqlite deferred — D3
  queries/<slug>.yaml # saved/standing searches + their result history
  inbox/              # dropped PDFs awaiting ingest
  log.md              # append-only operation log
```

Rule: `source.*` is immutable ground truth. `paper.md` and everything in `okf/` is derived and regenerable.

## 4. Pipeline

```
  query | PMID list | DOI | dropped PDF
            |
    [1] RESOLVE    PubMed MCP -> PMID/DOI/PMCID + metadata          -> meta.json
            |
    [2] DEDUP      PMID -> DOI -> normalized title -> PDF sha256
            |
    [3] ACQUIRE    Papers fulltext (if it happens to hold this paper)
            |         -> PMC OA (JATS XML preferred over PDF)
            |         -> Unpaywall PDF -> publisher HTML -> abstract-only
            |         (copyright check before any verbatim quoting)
    [4] CONVERT    (D16) JATS -> pandoc -f jats -t gfm              -> source.md
            |             PDF  -> anydoc (OCR fallback for scans)      + figures/
            |             HTML -> trafilatura -> firecrawl scrape      + figures.json
            |         figures + captions extracted on every path (D17);
            |         captions -> FTS index alongside body text
            |
    [5] EXTRACT    tiered (D4):
            |         tier=abstract -> cheap record, always, on ingest
            |         study_type classified first -> selects template (D8)
            |         tier=full     -> ref-extractor agent, on demand/promotion:
            |                          atomic claims w/ effect sizes, study design,
            |                          cohort, limitations, retraction status
            |         claims normalized to tuples (D13):
            |           (population, exposure/intervention, outcome, direction, effect)
            |         -- schema fixed in phase 3, before the extractor exists
    [6] INDEX      FTS5 rows + CSL-JSON/BibTeX record               -> index/
            |
    [7] WEAVE      claims -> OKF Concept notes, typed relations     -> okf/
                   supports | contradicts | extends | replicates
                   (relations computed over claim tuples, not prose --
                    same tuple key + opposite direction = contradicts)
```

Steps 1–6 are deterministic scripts + one agent; step 7 is the knowledge-building step and is where an existing OKF skill can be delegated to. Per D13 it is core, not optional: `/ref:gaps` and `/ref:hypothesize` read this graph.

## 5. Retrieval — cheapest layer first

1. **Lexical** — SQLite FTS5 over `source.md` and `paper.md`, ranked by built-in BM25. Exact terms, gene names, drug names, author names. Free, instant, no model.
2. **Structural** — OKF concept graph traversal (`get_neighbors`) for "what contradicts X", "what else came out of this cohort".
3. ~~Semantic (embeddings)~~ — **deferred, D3.** Design constraint: nothing in retrieval may assume a vector store. To compensate for FTS's literal matching, `/ref:ask` expands queries first — MeSH terms, synonyms, gene/drug aliases from the resolved metadata — before hitting FTS.

`/ref:ask` runs both layers, merges (BM25 top-30 → LLM listwise rerank → top-8), then synthesizes with mandatory `[^pmid]` citations, an explicit note of which papers were abstract-tier vs full-tier, and an honest "evidence is thin / conflicting here" verdict rather than false confidence. Question parsing uses PICO framing (D15) to build both the FTS query expansion and, when escalating to `/ref:search-pubmed`, the boolean MeSH query.

### 5a. Gap analysis & hypothesis generation (D13)

Both commands are pure graph consumers — they need the OKF weave and claim tuples, nothing else new.

- **`/ref:gaps [topic]`** — structural queries over `okf/` + the claim-tuple table:
  - claims supported by a single study (fragile evidence)
  - `contradicts` edges with no later resolving study
  - concept pairs co-mentioned in text but never directly studied together
  - populations/outcomes absent for an intervention that has them elsewhere
- **`/ref:hypothesize [concept]`** — Swanson ABC literature-based discovery: two-hop `get_neighbors` traversal (A–B edges from some papers, B–C from others), keep A–C pairs with no direct edge, then **check each candidate against PubMed** (`search_articles`) — untested in the library ≠ untested in the literature. Output: ranked hypotheses, each with its supporting A–B / B–C chains and the PubMed novelty check result.

## 6. Full-text acquisition — scope and limits

Clean and legal, in priority order:

1. **PMC Open Access subset** — free full text via the PubMed MCP / OA service. Prefer **JATS XML** over the PDF: `pandoc -f jats -t gfm` is near-lossless (sections, tables, refs, math) and JATS `<fig>` elements carry captions + graphic links, making figure extraction trivial (D16, D17).
2. **Unpaywall** (`api.unpaywall.org`, needs an email as API key — recorded in `config.json` at `/ref:init`, never prompted per fetch) — locates author manuscripts and publisher OA copies.
3. **Publisher HTML** for openly readable articles — fetched + converted with **trafilatura** first (local, free, article-aware boilerplate removal), **firecrawl scrape** as fallback for JS-rendered publisher SPAs. `<figure>` elements yield images + captions where present (D16, D17).
4. **Everything else stays paywalled.** ref-manager will record the paper with abstract + metadata only, set `full_text: false`, and hand the DOI to Papers.app, which holds the institutional credentials and is the appropriate place to fetch it. The plugin will not attempt to bypass paywalls or proxy authentication.

Abstract-only records stay first-class and visibly flagged, so a synthesis never silently treats an abstract as a read paper.

## 7. ReadCube Papers integration — selective, not bulk

**The library starts empty (D12).** Nothing is imported from Papers. The confirmed schema below is used for *targeted lookups* of papers you have already decided to add — never for a sweep.

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

Three interaction points, all initiated by you:

- **Push** — `/ref:open <pmid>`: `open -a Papers <pdf>` sends a PDF ref-manager acquired into Papers for reading and annotating.
- **Opportunistic full text** — during `/ref:fetch` for a paper you added, check whether Papers already holds it (match on PMID, else DOI) and reuse its extracted `fulltext` instead of re-downloading. Saves a round-trip; skipped silently when absent.
- **Annotation pull** — `/ref:pull-annotations <pmid>`: bring your highlights and margin notes for *that* paper into its record. Annotations land in `paper.md` under a separate **Your annotations** heading, never blended with model-extracted claims — your own reading is a different grade of evidence and stays visibly distinct.

Safety contract, unchanged:

- Read only from a **copy** of the database, never the live file.
- **Never write** to it. `actions_queue` is a live ReadCube sync queue; writing risks corrupting your sync.
- The schema is undocumented and vendor-owned. Every read validates the paths it expects and warns-and-skips per field rather than failing the run.


## 8. Build order

| Phase | Deliverable | Gate |
|---|---|---|
| 0 | Plugin scaffold, `plugin.json`, `/ref:init <path>` + config resolution (incl. Unpaywall email), `catalog.sqlite` schema | `/ref:status` reports an empty library at the chosen path |
| 1 | `/ref:add <PMID...>` — resolve, dedup, metadata, abstract, citekey (D14), catalog row | 10 PMIDs ingested, re-running is a no-op |
| 2 | `/ref:fetch` — acquisition ladder + `convert.py` (JATS→pandoc / PDF→anydoc / HTML→trafilatura, D16) → `source.md` + `figures/` + `figures.json`, captions FTS-indexed (D17) | a PMC OA paper lands as markdown; its figures sit in `figures/` and a caption phrase is findable via `/ref:search` |
| 3 | **Claim-tuple schema (D13)** + tiered extraction: abstract records on ingest + `ref-extractor` agent for `/ref:promote`; promotion also writes a vision-model description per figure into `paper.md` (D17) | claims carry stats, design, limitations, normalized tuples; tier visible in every note; a promoted paper's figure content is queryable in `/ref:ask` |
| 4 | `/ref:search` — FTS5 lexical search, BM25-ranked; MeSH/synonym query expansion | paraphrase query still finds the right paper |
| 5 | `/ref:ask` — retrieval + LLM rerank + grounded synthesis with citations | answer cites only ingested papers |
| 6 | **OKF weaving** → `okf/` concept notes + typed relations over claim tuples *(moved up — D13)* | contradiction between two papers is queryable |
| 7 | `/ref:gaps` + `/ref:hypothesize` — graph gap analysis + ABC discovery with PubMed novelty check | a known A–C untested pair in a toy library is surfaced and ranked |
| 8 | `/ref:search-pubmed` — PICO parsing, boolean MeSH query, triage with screening log, batch add; saved queries + `/ref:update-queries`; `/ref:related` snowballing | a manually re-run standing query adds only new hits; every exclusion has a logged reason |
| 9 | `/ref:export` (BibTeX / CSL-JSON) + `/ref:cite` inline citekeys | a quarto doc and a `.bib` file both render the same reference correctly |
| 10 | Papers hooks: `/ref:open` push, opportunistic fulltext reuse, `/ref:pull-annotations` | a paper you added is readable in Papers and its highlights come back |
| 11 | `/ref:summarize`, `/ref:review` — evidence tables, GRADE certainty, RoB checklists per study_type (D15) | produces a cited review of a topic with per-study evidence table |
| 12 | `/ref:audit` (retraction/errata re-check), `/ref:note` | a retracted paper in the library is flagged on audit |

Phases 1–7 are the usable core — ingest through hypothesis generation. Everything after is compounding value.

## 9. Residual assumptions — flagged, not blocking

1. **The repo and your Papers library will diverge.** That is the point of D12, but it is worth saying plainly: papers you read in Papers are not in the repo unless you add them, and `/ref:ask` can only reason over what the repo holds. If that gap becomes annoying, a one-off selective import is easy to add later — the schema work in §7 is already done.

2. **Papers schema is vendor-owned and undocumented.** Confirmed correct today against a real library; a ReadCube update can move fields. The sync script validates expected paths up front and warns-and-skips per field rather than failing the run.

3. **No embeddings (D3) means FTS misses paraphrase.** Mitigated by MeSH/synonym query expansion, not solved by it. If `/ref:ask` starts missing papers you know are in the library, that is the signal to revisit D3 — worth watching deliberately rather than discovering late.

4. **Tiered extraction (D4) means most papers are abstract-only.** Every synthesis must label which tier backed each citation, so thin evidence cannot pass as a read paper.

5. **Paywalled full text stays out of reach.** Acquisition depends on PMC OA, Unpaywall, and whatever Papers happens to hold for papers you add. Expect a meaningful fraction to remain abstract-tier permanently.

6. **ABC hypothesis generation over-generates.** Two-hop co-occurrence produces many spurious A–C candidates; the PubMed novelty check filters known links but not implausible ones. `/ref:hypothesize` output is a ranked *reading list of candidates*, not claims — presentation must say so.

---

## 10. First implementation step

Phases 0 → 1: `/ref:init <path>` to create the library at a location you choose, then `/ref:add <PMID...>` to put the first papers in it deliberately. Target for the first working slice is a handful of papers you actually care about, ingested end to end — resolved, deduped, catalogued, abstract-tier extracted, and findable via `/ref:search`.
