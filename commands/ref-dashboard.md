# /ref:dashboard

Dashboard over the paper library: health state, source coverage, pipeline
funnel, papers-by-year, lint trend, a searchable/sortable paper table, a
coverage matrix, per-project reading progress, maintenance sparklines, a
paper panel (details + notes), and a PDF viewer
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
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/dashboard.py" serve --repo <library_root> [--port <n>] [--open]
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
- Nothing but `note.py append` ever writes to the library.

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

Both modes: selecting rows in the Papers tab builds ready-to-copy
`/ref:fetch` / `/ref:extract` commands for the papers that still need them.

Suggested follow-up:

- `/ref:dashboard` for daily use; `/ref:dashboard --static --open` after
  `/ref:lint --snapshot` to hand someone a static snapshot with the trend
  update baked in.
