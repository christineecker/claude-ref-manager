# /ref:dashboard

Dashboard over the paper library: health state, source coverage, pipeline
funnel, papers-by-year, lint trend, a searchable/sortable paper table with
the coverage matrix folded in as a per-row strip (click a column header to
filter to papers missing it), per-project reading progress, maintenance
sparklines, a docked paper panel (details + notes), and a PDF viewer
(LIBRARY_VIEWER_IMPLEMENTATION_PLAN.md §6-§7). Read-only except notes, built
on the same `lib_inventory.rows()`/`detail()` every other view uses.

**Default is `serve`** — a local HTTP server on `127.0.0.1` with a live
API, an in-page pdf.js viewer (thumbnails, zoom, fit-width, page jump,
find-in-PDF), and notes that save immediately. Pass `--static` (or `build`
explicitly) for the old self-contained-HTML mode instead (good for sharing
a snapshot; no server, no in-page PDF, notes are copy-to-clipboard drafts).

Parse `$ARGUMENTS` for:

- `--static` — build the static HTML dashboard instead of serving.
- `--port <n>` — serve mode only. Fixed port instead of an OS-assigned one.
- `--open` — open the dashboard in the default browser after it's ready
  (built index.html for `--static`; the served URL for `serve`).
- `--view '<query>'` — serve mode only. Reopen a shared view: the string a
  "Copy as command" button produced (e.g. `tab=insights&project=foo`). Only
  `tab`, `q`, `project`, `issue`, `source`, `missing`, `sort`, `insight`,
  `center`, `hops` are accepted.

Steps:

1. Resolve the library root from `~/.config/ref-manager/config.json` (fail
   loudly, pointing at `/ref:init`, if unconfigured).
2. If `--static` was passed (or the literal word `build`), print then run:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/dashboard.py" build --repo <library_root> [--open]
   ```

   Print the script output verbatim (the path to the written `index.html`)
   and stop.

3. Otherwise (the default), print then run:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/dashboard.py" serve --repo <library_root> [--port <n>] [--open] [--view '<query>']
   ```

   This blocks, serving until interrupted (Ctrl-C). Print the launch URL
   line the script prints on startup verbatim — it includes the one-time
   token query param the page needs. Tell the user to open that URL and
   that Ctrl-C stops the server.

Notes (serve mode):

- Binds `127.0.0.1` only, with a random per-run token required on every
  API/file request and checked against the `Host`/`Origin` headers
  (LIBRARY_VIEWER_IMPLEMENTATION_PLAN.md §7.3) — it is not reachable from
  other machines or other browser tabs without the token in the URL.
- The PDF tab renders in-page via a vendored pdf.js; the notes composer
  saves straight to `notes.md` through `note.py append` (same file/format
  as `/ref:note`), falling back to a local draft only if the save request
  fails. A refresh button re-fetches the paper table without restarting
  the server.
- Writes to the library: notes (`note.py append`), PDF highlights
  (`highlight.py`), triage decisions, and PDFs dropped onto a paper row or
  the PDF tab (`attach.py`, same identity check as `/ref:attach`; replacing
  asks first and keeps the old PDF as a variant; a PDF that can't be
  converted is stored without repointing the current version).
- Read-only JSON for monitoring/agents (token header required):
  `/api/health` (per-source status + warnings; 503 only if rows fail),
  `/api/summary` (counts, coverage, top issue buckets, ranked next actions;
  `?scope=project|issue`, `?detail=pmids`), `/api/knowledge` (claims,
  concepts, relations, MeSH terms for the Insights tab).

Notes (static mode, `--static`):

- Writes atomically to `<library_root>/reports/dashboard/` (template +
  inline rows/lint JSON at `index.html`, one `details/<pmid>.js` per paper
  loaded on demand). A rebuild replaces the whole directory in one step; a
  failed build never touches the previous dashboard.
- The PDF tab opens the paper's PDF in a new browser tab — no in-page
  viewer in static mode.
- The notes composer only ever writes a draft to this browser's local
  storage, with a "Copy `/ref:note`" button; committed notes still come
  from `/ref:note <pmid>`.

Both modes:

- Filters, sort, tab and Insights view live in the URL ("Copy link" /
  "Copy as command"); saved views stay in browser storage.
- Selecting rows builds `/ref:fetch` / `/ref:extract` / `/ref:fetch-pdf` /
  `/ref:audit` commands (copy each or all, `c`) and exports PMIDs or CSV
  (`e`) — only selected rows the current filters show.
- **Next actions** ranks work by `weight × papers × project boost`, each with
  its reason and command; can be limited to the current filters.
- **Insights** tab (claims-based, follows the Papers filters + a year range):
  notable-in-scope cards (most connected paper, open conflicts, single-study
  findings, unextracted papers, growing/fading topics), evidence map (e.g.
  population × outcome coloured by effect direction), gaps (a population ×
  outcome grid per intervention concept using the same rule as `/ref:gaps`,
  plus heuristic sparse pairs, single-study findings and unresolved
  conflicts, with PubMed/`/ref:search-pubmed` suggestions), topic timeline,
  knowledge graph (concepts / papers & authors / claim network / a 1–2 hop
  neighborhood around one paper or concept — "Show in graph" in the paper
  drawer; every relation type and its review state drawn distinctly, with
  rationale, supporting claims and a `/ref:weave review` command; a Table
  toggle lists the same nodes and edges), concept clusters (cards with a
  papers-per-year sparkline and growing/fading label, or a cluster map of
  clusters sharing papers), evidence maturity per intervention concept
  (papers, outcome breadth, coverage, full-text share, open conflicts — shown
  separately, no combined score) with `/ref:review` GRADE/risk-of-bias
  batches overlaid, and a deterministic synthesis draft (copy or `.md`).
  Graph nodes can be dragged; drag the background to pan, ⌘/Ctrl + scroll to
  zoom, Shift + arrow keys to move a focused node, "Re-layout" to reset.

Suggested follow-up:

- `/ref:dashboard` for daily use; `/ref:dashboard --static --open` after
  `/ref:lint --snapshot` to hand someone a static snapshot with the trend
  update baked in.
