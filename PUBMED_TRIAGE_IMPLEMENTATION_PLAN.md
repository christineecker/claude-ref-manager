# PubMed Search Triage Implementation Plan

Date: 2026-09-16
Status: Implemented (P0, P1, P2). Code: `triage.py`, `lib_eutils.py`, `dashboard.py` triage routes, `dashboard_assets/` Triage tab; tests in `tests/test_triage.py` and `tests/test_dashboard_serve.py::TestTriageRoutes`. P3 not started.
Scope: A Triage tab in `/ref:dashboard` that opens after `/ref:search-pubmed`, lists
every PMID of a saved search with basic metadata, records include / maybe / exclude
decisions (Include adds the paper to the library), and runs PDF / full-text
acquisition for a selection.
Mockup: https://claude.ai/artifact/Uftx7q973eQipMdnWEhVv7 (v3)

## 1. Decisions already made

| # | Decision |
|---|---|
| T1 | Design = mockup Screen A: one table per saved search inside the existing dashboard server. No separate keyboard-screening screen in v1. |
| T2 | **One triage per saved search** (`queries/<slug>.yaml`). Re-runs from `/ref:update-queries` merge into the same triage. |
| T3 | A triage links to **zero or one project**. A project can have several triages. Linking can happen at creation or later. |
| T4 | **Include adds the paper** to the library immediately (`add.add_one`). |
| T5 | Metadata loads in **batches of 100**. The next batch loads only after the user confirms. |
| T6 | Batch loading runs in the server via **NCBI E-utilities `efetch`** (stdlib `urllib`), the same kind of deterministic direct call `fetch.py` already makes to Unpaywall. |

## 2. Principles

1. **PMID stays the identity key** (D11). Decisions, batches and pending work are all keyed by PMID.
2. **Saved runs stay immutable** (D15). Triage state lives beside the run, never inside `queries/<slug>.yaml`.
3. **Append-only decision history.** The newest decision per PMID wins; nothing is rewritten.
4. **The library is never deleted from.** Exclude after Include leaves `papers/<pmid>/` untouched.
5. **Reuse existing writers.** Library writes go through `add.add_one`, `fetch_pmc_pdf.fetch_pmc_pdf_one` and `screen.decide`. The only new writers are the triage files in §4.
6. **Keep the dashboard's safety boundary.** Every new route uses the existing token, Host and Origin checks and body-size caps (LIBRARY_VIEWER_IMPLEMENTATION_PLAN.md §7.3).
7. **Claude-only steps stay with Claude.** Full text from JATS, PubMed MCP text and publisher HTML needs MCP or WebFetch, so the server queues it instead of attempting it.

## 3. User flow

1. `/ref:search-pubmed "<question>" --slug <slug> --create [--project <p>]`
   - Claude builds the query and pages `search_articles` (via `retstart`) to collect **all** PMIDs. It asks before collecting more than 1,000.
   - `pubmed_query.py new-run` saves the run (unchanged).
   - `triage.py init` creates the triage (optionally linked to `<p>`).
   - `triage.py load-batch` loads metadata for the first 100 PMIDs.
   - Claude launches `dashboard.py serve --open --triage <slug>`, which opens on the Triage tab.
2. In the dashboard the user filters, reads abstracts and sets decisions.
   - **Include** adds the paper (and, with a project, records `screen.decide(included)`).
3. The user ticks rows and clicks:
   - **Get PDFs**: the server runs `fetch_pmc_pdf_one` per PMID. Results `no_pdf`, `no_pmcid` and `refused` go to the pending list.
   - **Fetch full text**: the PMIDs go to the pending list.
4. The dashboard shows a strip with the command to copy: `/ref:triage apply <slug>`. Claude runs the `/ref:fetch` ladder for pending PMIDs and clears them. The tab picks up the new state on its next poll.
5. Below the table, **Load next 100…** asks for confirmation, then the server runs `load-batch`.
6. Later, `/ref:update-queries <slug>` appends a run, and `triage.py sync` merges it:
   - new PMIDs get a "new since <date>" badge;
   - if there are ≤100 new PMIDs they load automatically, otherwise the user is asked.

## 4. Data model

The folder is created lazily, like `projects/` and `queries/` (see `init_repo.py` comment). Everything lives under `triage/<slug>/`, where `<slug>` is the saved-query slug.

### 4.1 `triage/<slug>/triage.json` (atomic write)

```json
{
  "slug": "asd-cortical-thickness",
  "project": "asd-structural-review",
  "created_at": "2026-09-16T14:02:11+00:00",
  "project_linked_at": "2026-09-16T14:02:11+00:00",
  "synced_run_ids": ["run-f81a0c", "run-k3v9q2"],
  "batch_size": 100
}
```

- `project` is `null` for a standalone triage.
- Project → triages is **derived** by scanning `triage/*/triage.json`. `project.yaml` is not changed, so there is no second place to keep in sync and no `validate_project` change.

### 4.2 `triage/<slug>/metadata/batch-NNNN.json` (one file per batch, atomic write)

```json
{
  "batch": 1,
  "loaded_at": "…",
  "source": "ncbi_efetch",
  "records": [
    {
      "pmid": "42244394",
      "title": "…",
      "abstract": "…",
      "authors": [{"last": "Esposto", "first": "…", "raw": "…"}],
      "journal": "Autism Res",
      "year": "2026",
      "doi": "…",
      "pmcid": "PMC13377343",
      "grants": [],
      "publication_types": ["Journal Article"],
      "mesh_terms": ["…"]
    }
  ],
  "missing": ["<pmid efetch returned nothing for>"]
}
```

- Records use the `add.py` input envelope plus two extra display fields. `add_one` reads fields with `record.get`, so the extras are ignored.
- The set of loaded PMIDs is the union of all batch files. Batches are keyed by content, not by position, so re-run reordering can't corrupt them.
- A failed batch writes nothing, so earlier batches stay valid.

### 4.3 `triage/<slug>/decisions.jsonl` (append-only)

```json
{"pmid": "42244394", "decision": "included", "reason": "adult ASD sample", "timestamp": "…", "run_id": "run-k3v9q2", "origin": "dashboard"}
```

- `decision` uses screening's own vocabulary: `included | excluded | pending | cleared`.
  - The UI label "Maybe" maps to `pending`.
  - `cleared` exists only here (it un-sets a decision) and is mirrored to a project as `pending`.
- `reason` defaults to `triage:<slug>` when the user doesn't choose one.

### 4.4 `triage/<slug>/pending.json` (atomic write)

```json
{"42390005": {"kind": "full_text", "why": "no_pdf", "queued_at": "…"}}
```

## 5. Decision rules

| Action | Library | Triage log | Linked project |
|---|---|---|---|
| Include | `add_one(batch record)`; `already_present` is fine | append `included` | `screen.decide(included, run_ref)`, which makes the paper a member |
| Maybe | — | append `pending` | `screen.decide(pending)` |
| Exclude | untouched, even if added earlier | append `excluded` | `screen.decide(excluded)`; membership stays (existing behaviour) |
| Clear | untouched | append `cleared` | `screen.decide(pending)` |

- **Order for Include:** add first, then log. If `add_one` raises (for example no metadata), nothing is logged and the row shows the error.
- **Linking a project later:** replay the newest non-`cleared` decision per PMID into `screen.decide` with reason `triage:<slug>: <original reason>`, then set `triage.json.project`. Replaying is safe to repeat because it is append-only and the newest decision wins.
- **Unlinking or switching:** the old project's `screening.jsonl` is left as is (append-only history). The switch then replays into the new project.
- **Bulk decisions** run per PMID, and one failure doesn't stop the rest (same rule as `search-add-fetch`).

## 6. Components

### 6.1 New `lib_eutils.py`

- `efetch_pubmed(pmids: list[str], *, email: str, api_key: str | None, tool="ref-manager") -> tuple[list[dict], list[str]]`
  - Sends `POST https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi` with `db=pubmed&retmode=xml&id=…`.
  - Chunks of 100, throttled to 3 requests/s (10/s with `api_key`), with a timeout and one retry on 429/5xx.
- `parse_pubmed_xml(xml: bytes) -> list[dict]` builds the envelope in §4.2:
  - `ArticleTitle` and `AbstractText` (joined, keeping `Label=` as `LABEL: text`);
  - `AuthorList` (`LastName`/`ForeName`, or `CollectiveName`);
  - `Journal/ISOAbbreviation`;
  - `PubDate/Year`, falling back to the first 4-digit year in `MedlineDate`;
  - `ArticleIdList` with `IdType` `doi` and `pmc`;
  - `GrantList`, `PublicationTypeList`, `MeshHeadingList`.
- Uses `xml.etree.ElementTree` only. The XML comes from a fixed NCBI host, but the parser still refuses DTD/entity declarations (defensive check on the raw bytes before parsing).
- Config keys in `~/.config/ref-manager/config.json`:
  - `ncbi_email` (falls back to `unpaywall_email`, errors with a pointer to the config if both are missing);
  - optional `ncbi_api_key`.

### 6.2 New `triage.py` (library functions + CLI, stdlib only)

| Function / subcommand | Does |
|---|---|
| `init --slug [--project]` | Requires `queries/<slug>.yaml`; creates `triage.json`; runs `sync`. |
| `sync --slug` | Reads all runs and records new `run_id`s in `synced_run_ids`; returns `{new_pmids, dropped_pmids}`. |
| `load-batch --slug [--size 100] [--pmids-file]` | Picks the next unloaded PMIDs in display order (§6.3), calls `lib_eutils`, writes a batch file. |
| `decide --slug --pmids-file --decision --reason` | Applies §5 rules; per-PMID results as JSON. |
| `link --slug --project <p>\|--none` | Applies §5 linking rules. |
| `pending --slug` / `clear-pending --slug --pmids-file` | For `/ref:triage apply`. |
| `show --slug` | The same view model the API returns (§6.3), for CLI/tests. |
| `list` | All triages with project, found/loaded/decided counts. |

- Locking:
  - `triage_lock(library_root, slug)` (new helper in `lib_atomic.py`, same `_flock` pattern) wraps every write to the triage folder.
  - `screen.decide` gets wrapped in a new `project_lock(library_root, slug)`, because it read-modify-writes `papers.yaml` without a lock and the threaded server makes concurrent calls possible.
  - Lock order is always pmid → project → triage.

### 6.3 View model (`triage.view(library_root, slug)`)

- **Display order:** the latest run's PMID order (PubMed's order), then PMIDs that appear only in earlier runs.
- **Per PMID:**
  - `loaded`, `metadata` (null if not loaded) and `decision` (newest, or null);
  - `new_since` (the run where the PMID first appeared, if that isn't the first run) and `in_latest_run`;
  - `pending`;
  - `library`: from `lib_inventory.rows()` joined by PMID, either `none` or `{has_fulltext, has_pdf, extraction_tier, projects}`.
- **Counts:** found (union of runs), loaded, per decision, library states, PMC availability.
- `rows()` scans the whole library, so it runs once per request, not once per PMID.

### 6.4 `dashboard.py` routes (serve mode only)

| Method & path | Body / result |
|---|---|
| `GET /api/triages` | `triage.list` |
| `GET /api/triage/<slug>` | `triage.view` |
| `POST /api/triage/<slug>/decisions` | `{pmids[≤500], decision, reason?}` → per-PMID results |
| `POST /api/triage/<slug>/project` | `{project: str\|null}` |
| `POST /api/triage/<slug>/batch` | `{confirm: true}` → `{job_id}` |
| `POST /api/triage/<slug>/jobs` | `{kind: "pdf"\|"full_text", pmids[≤500]}` → `{job_id}`; `full_text` is synchronous (queues to pending) |
| `GET /api/jobs/<id>` | `{state, done, total, results[]}` |

- **Validation:** `<slug>` goes through `lib_ids.validate_slug` and must have `triage/<slug>/triage.json`; PMIDs go through `_valid_pmid`; `decision` and `kind` go through allowlists.
- **Jobs:** an in-memory registry (dict plus lock) on the server object, with one worker thread per job and at most 2 concurrent jobs. Jobs don't survive a restart; the files on disk are the truth.
  - A PDF job runs `add_one` first for PMIDs not yet added (it needs `meta.json`), then `fetch_pmc_pdf_one`.
  - It maps `no_pdf`, `no_pmcid`, `refused` and `failed` to pending with `why`.
  - It never calls `fetch.fetch_one`, which would stamp `full_text: false` with no inputs.
- **CLI flag:** `--triage <slug>` on `serve` appends `#triage/<slug>` to the launch URL.

### 6.5 `dashboard_assets` (index.html, app.js, app.css)

- A new `tab-triage` button. It is hidden in static mode (no API) and when `/api/triages` is empty.
- The triage picker is a `<select>` of triages. Deep link: `#triage/<slug>`.
- Layout follows the mockup:
  - run header and project `<select>`;
  - three summary bars;
  - filter chips: All, New since, Undecided, Included, Maybe, Excluded, Included without PDF, In PMC, Reviews;
  - text filter;
  - table with an expandable abstract row;
  - batch strip with a two-step confirm;
  - pending strip with a copy command;
  - sticky action bar.
- The title click opens the existing paper drawer when the PMID is in the library; otherwise it expands the abstract.
- Polling: `GET /api/jobs/<id>` every 1 s while a job runs. `GET /api/triage/<slug>` every 5 s while `pending` is non-empty, plus the existing manual refresh.
- Keyboard: `i`/`m`/`x` on the focused row, and `Space` to toggle selection. These extend the existing j/k row navigation.
- Rendering is windowed the same way as `MATRIX_PAGE_SIZE`, so 1,000+ loaded rows stay fast.

### 6.6 Commands

- `commands/search-pubmed.md`:
  - page `search_articles` to collect all PMIDs;
  - add `--project <p>` and `--no-triage`;
  - after `new-run`, run `triage.py init` + `load-batch`, then `dashboard.py serve --open --triage <slug>`;
  - print `found: N · loaded: 100 · load more from the Triage tab or /ref:triage <slug> --more`.
- **New** `commands/triage.md`:
  - `/ref:triage <slug> [--project <p>|--no-project] [--more]` opens, links or loads the next batch (asking first);
  - `/ref:triage apply <slug>` runs the `/ref:fetch` ladder for `triage.py pending`, then `clear-pending` for PMIDs that reached `full_text` or `abstract_only`;
  - `/ref:triage list`.
- `commands/update-queries.md`: after `rerun`, run `triage.py sync` if `triage/<slug>/` exists. Auto-load when there are ≤100 new PMIDs, otherwise ask.
- `commands/project.md` `show`: list linked triages (derived, §4.1).
- `commands/help.md`, `docs/` commands reference and the getting-started tutorial: document the triage flow.
- `/ref:search-add-fetch` stays unchanged.

## 7. Phases

### P0: Data + read-only tab

- `lib_eutils.py` + fixtures (saved efetch XML for 3–5 PMIDs, including a structured abstract, a `MedlineDate` and a `CollectiveName`).
- `triage.py`: `init`, `sync`, `load-batch`, `show`, `list`, `view`.
- Routes: `GET /api/triages`, `GET /api/triage/<slug>`.
- UI: tab, header, summary bars, filters, table, abstract row. Buttons shown disabled.
- `search-pubmed.md` changes (collect all PMIDs, init, batch 1, open).

Acceptance:
- A fresh search opens the dashboard on its triage with 100 loaded rows.
- Counts match `queries/<slug>.yaml` and the batch files.

### P1: Decisions + projects

- `triage.decide`, `triage.link`; `project_lock`, `triage_lock`.
- Routes: decisions, project.
- UI: decision buttons, bulk bar, project select, `i`/`m`/`x`.
- `/ref:triage` command (open, `--project`); `project show` lists triages.

Acceptance:
- Include creates `papers/<pmid>/meta.json` and, with a project, a `screening.jsonl` line with `search_run`.
- Linking a project later copies past decisions over.
- `/ref:review --prisma --project <p> --query <slug>` counts the triage's screening.

### P2: Batches, jobs, re-runs

- Batch route + two-step confirm; `/ref:triage --more`.
- Job registry, PDF job, pending file, pending strip; `/ref:triage apply`.
- `update-queries.md` + `triage.sync` merge; new-since chip and badge; "not in latest run" marker.

Acceptance:
- Loading 200 → 300 works in the dashboard and CLI.
- A PDF job with a mix of PMC and non-PMC PMIDs attaches the PMC ones and queues the rest.
- A re-run with 14 new PMIDs shows them under New since.

### P3: Follow-ups (not scheduled)

- `prisma.py` defaults `--query` to the project's linked triages.
- Export included PMIDs (`/ref:export-papers --triage <slug>`).
- Reason chips configurable per project.

## 8. Tests

New `tests/test_triage.py` and additions to `tests/test_dashboard_serve.py`. No network: `lib_eutils` is tested against fixtures, and the HTTP layer is monkeypatched.

1. `parse_pubmed_xml`: structured abstract labels, `MedlineDate` year, `CollectiveName`, DOI/PMCID extraction, a missing abstract gives `abstract: null`.
2. The parser refuses XML containing `<!DOCTYPE` / `<!ENTITY`.
3. `load-batch` picks the next unloaded PMIDs in display order. A simulated efetch failure writes no batch file and leaves earlier batches intact.
4. Decisions: newest wins; `cleared` un-sets; Maybe is stored as `pending`.
5. Include is idempotent (the second call gives `already_present`) and logs nothing if `add_one` raises.
6. Exclude after Include leaves `papers/<pmid>/` byte-identical.
7. With a project, each decision appends to `screening.jsonl` with `search_run`. Linking late replays the newest decisions exactly once per PMID state.
8. Concurrency: 20 threads deciding different PMIDs into one project leave a valid `papers.yaml` with 20 members.
9. `sync` after a rerun reports new and dropped PMIDs; decisions on dropped PMIDs survive.
10. PDF job: a mocked `fetch_pmc_pdf_one` returning `attached`, `no_pdf` and `no_pmcid` puts exactly the last two in pending.
11. Routes: 403 without the token or with a bad Origin; 400 for a bad slug, bad PMID, oversized body or unknown decision/kind; 404 for an unknown triage.

## 9. Risks / notes

- **MCP `search_articles` paging:** verified 2026-09-16 — `max_results` is capped at 200 per call, so `search-pubmed.md` pages with `retstart` in steps of 200.
- **Query parity:** the search still runs through MCP while metadata comes from efetch. Both are keyed by PMID, so there is no mismatch risk for identity. Only the display metadata's source changes.
- **NCBI etiquette:** `tool` + `email` on every request, throttling as in §6.1, and no parallel batch jobs for the same triage (the route returns 409 while one runs).
- **The README prerequisites table** gains "network access to eutils.ncbi.nlm.nih.gov (triage metadata)".
