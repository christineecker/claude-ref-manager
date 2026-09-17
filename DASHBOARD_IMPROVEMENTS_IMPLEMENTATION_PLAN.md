# Dashboard Improvements Implementation Plan

Date: 2026-09-16
Status: Draft
Scope: 4 high-priority dashboard enhancements for the live dashboard experience

## Overview

This plan adds four improvements to the existing dashboard flow:

1. Shareable filtered views
2. Better bulk export and batch actions
3. Actionable “what should I do next?” panel
4. API health and summary endpoints

These changes are designed to stay within the current architecture of the dashboard server in `skills/ref-manager/scripts/dashboard.py` and the client in `skills/ref-manager/scripts/dashboard_assets/app.js`, without changing the library model or the safety boundary already enforced by the dashboard.

---

## Principles

- Keep the dashboard read-heavy and UI-fast.
- Reuse existing `lib_inventory.rows()` / `lint` / `matrix` / `snapshots` logic instead of duplicating semantics.
- Keep server-side writes to the same, explicit, audited paths.
- Avoid adding a second source of truth for dashboard state.
- Prefer URL-state and structured API outputs that are shareable and testable.

---

## 1) Shareable filtered views

### Goal

Allow users to capture, restore, and share a dashboard state that includes search, project, issue filters, and source filters.

### Problem

The current saved views are local to the browser via `localStorage` and are not shareable. This makes them useful for individual work, but not for handoff, collaboration, or recreating the same view later from a direct link.

### User story

> As a user reviewing the library, I want to save a filter state and open the same filtered dashboard from a URL or shared link so that I can hand off work and reproduce the exact dataset.

### Proposed design

#### Client-side behavior
- Add a shareable URL state encoder for:
  - search query
  - selected project
  - issue chips
  - source filter set
  - sort state
  - active tab
- Serialize state as a compact query string, e.g.:
  - `?tab=papers&q=autism&project=foo&issue=missing_meta&source=pdf-backed`
- When the page loads, parse state from the URL and apply it automatically.
- Add a “Copy link” button next to saved-view actions.
- Continue supporting browser-local saved views as a convenience layer.

#### Server-side behavior
- No server-side storage required for v1.
- The dashboard state is a pure client-side derived view keyed by URL parameters.
- For safety, keep all shared state read-only and deterministic.

#### Data model
- No new library files are required.
- Add a small client helper layer for:
  - `encodeViewState()`
  - `decodeViewState()`
  - `applyViewState()`
- Keep existing `captureView()` / `applyView()` logic but make it URL-aware.

### Acceptance criteria
- A filtered dashboard can be opened by URL alone.
- The URL round-trips the same filter state without refresh drift.
- Saved browser views remain available alongside shareable links.
- State changes update the URL without a page reload.

### Implementation steps
1. Add state serialization helpers in `app.js`.
2. Hook URL parsing on initial load and on filter changes.
3. Add a copy-link button in the filters bar.
4. Support `history.replaceState` for live URL updates.
5. Preserve existing saved-view local storage behavior as a fallback.

### Risks and mitigations
- Long URLs: keep the state compact and limited to a few fields.
- Filters that are too complex: only encode the stable, core view state.
- Duplicate state semantics: ensure URL state and local saved-view state resolve in one consistent precedence order.

---

## 2) Better bulk export and batch actions

### Goal

Turn selection-driven commands into a more complete operations layer for bulk work.

### Problem

The action bar currently generates copy-ready commands for a few issue types, but it does not support broader operational tasks such as exports, grouped actions, or richer selection workflows.

### User story

> As a user triaging a large library, I want to export the current selection and perform bulk follow-up actions without manually reconstructing command sets.

### Proposed design

#### Bulk action types
Add a richer action model for selected rows:
- export selected PMIDs
- export selected titles + metadata as CSV
- open selected PDFs in a new tab set
- run bulk follow-up commands
- copy a combined command block for `/ref:fetch`, `/ref:extract`, `/ref:fetch-pdf`, `/ref:audit`

#### UI design
- Keep the action bar but expand it with grouped actions:
  - Export
  - Copy commands
  - Open items
  - Bulk fix suggestions
- Add a selection summary line:
  - `42 selected · 12 need fetch · 8 need extract · 5 stale`

#### Backend support
- No new server writes required for export-only actions.
- If a selection export is implemented via client-side generation, it can be done entirely in-browser.
- If the action is server-backed, add endpoints like:
  - `GET /api/export/pmids?ids=...`
  - `GET /api/export/csv?...`

### Acceptance criteria
- Selected rows can be exported to PMIDs or CSV without a page reload.
- Bulk command generation includes only the relevant subset and reflects current selection.
- The action bar stays readable even with large selections.
- Exported data is deterministic and reflects the visible filtered set.

### Implementation steps
1. Extend `renderActionBar()` in `app.js` to include export buttons.
2. Add `buildSelectedPMIDList()` and `buildSelectedCSV()` helpers.
3. Add selection summary logic to show counts by action type.
4. Add server routes only if export needs to be generated from the live backend instead of browser memory.
5. Add keyboard support for bulk action shortcuts.

### Risks and mitigations
- Huge selections degrade performance: cap exports and provide progress feedback for large lists.
- CSV generation can drift from visible rows: generate it from the exact `state.selected` set and current `ROWS` data.
- Command duplication: group commands by category to avoid repeated or conflicting actions.

---

## 3) Actionable “what should I do next?” panel

### Goal

Replace generic health widgets with a prioritized action panel that tells the user what to do next, not just what is broken.

### Problem

The current dashboard reports counts and issues well, but it does not rank the next actions by impact or urgency. The user can see lots of issues without knowing which ones are worth doing first.

### User story

> As a user operating the dashboard, I want to see the highest-impact next steps ranked by urgency so I can spend my time on the papers and issues that move the library forward fastest.

### Proposed design

#### Panel content
Create a panel near the health header with a ranked action list, such as:
- `1. Fetch full text for 22 papers in Project X`
- `2. Add missing metadata for 17 papers`
- `3. Rebuild catalog index`
- `4. Review 6 stale checks before the next sweep`

#### Ranking logic
Compute priority using a weighted score from current library state, for example:
- missing metadata / malformed metadata
- missing claims registry
- stale check
- no PDF / no full text
- project-specific backlog size
- source coverage bottlenecks
- paper age or stagnation

#### Optional action metadata
Each item should display:
- count
- issue type
- suggested command
- project or filter scope
- impact estimate

### Acceptance criteria
- The panel ranks actions in a clear order.
- The top action is always tied to a real issue present in the current data.
- Suggested commands are copyable and match the state of the visible filter set.
- The panel updates after refresh.

### Implementation steps
1. Add a new `renderNextActions()` function in `app.js`.
2. Build a scoring model for issue buckets and projects.
3. Render top actions in a compact, prioritized list.
4. Add click-through actions to apply a relevant issue filter or jump to a project view.
5. Ensure stale data and failed refreshes do not blank the panel.

### Risks and mitigations
- Overfitting to a narrow heuristic: keep the scoring explainable and visible in the UI.
- User confusion about why an item ranks above another: include a short explanation line.
- Constant churn in ranking: only update the panel after a full data refresh, not on every keystroke.

---

## 4) API health and summary endpoints

### Goal

Give the dashboard a more operational API so it can be monitored, debugged, and integrated with other automation without scraping the HTML.

### Problem

Current dashboard endpoints expose the underlying data, but not a concise health or summary model. This makes operational monitoring and diagnostics harder than necessary.

### User story

> As an operator or agent, I want a small summary API that tells me whether the dashboard is healthy, which data sources failed, and what is currently preventing the library from being fully processed.

### Proposed design

#### New routes
Add server routes in `dashboard.py` such as:
- `GET /api/health`
- `GET /api/summary`
- `GET /api/summary?scope=project`
- `GET /api/summary?scope=issue`

#### Response shapes
Example response for `/api/health`:

```json
{
  "ok": true,
  "library_root": "/path/to/library",
  "generated_at": "2026-09-16T12:00:00Z",
  "data_sources": {
    "rows": "ok",
    "lint": "ok",
    "matrix": "ok",
    "snapshots": "ok"
  },
  "warnings": []
}
```

Example response for `/api/summary`:

```json
{
  "paper_count": 1240,
  "issues_total": 87,
  "top_actions": [
    { "type": "missing_meta", "count": 22, "suggested_command": "/ref:list --issue missing_meta --format pmids" },
    { "type": "oa_pending", "count": 18, "suggested_command": "/ref:fetch-pdf" }
  ],
  "coverage": {
    "pdf_backed": 510,
    "full_text": 642,
    "abstract_only": 136
  },
  "catalog_stale": false
}
```

#### Diagnostics model
The summary response should include:
- library item count
- issue total
- top issue buckets
- project counts
- stale catalog state
- failed or degraded data-source status
- last refresh / generation timestamp

### Acceptance criteria
- `/api/health` returns a single, stable health model for monitoring.
- `/api/summary` returns enough actionable data for a UI panel or automation layer.
- Non-2xx responses from data sources are reported without taking down the whole dashboard.
- The summary model is derived from the same underlying inventory and lint objects already used by the UI.

### Implementation steps
1. Add a shared helper to compute a summary object from `ROWS`, `LINT`, and `SNAPSHOTS`.
2. Add `GET /api/health` route in the dashboard server.
3. Add `GET /api/summary` route and convert it to a JSON payload.
4. Update the live dashboard refresh flow to consume summary metadata if needed.
5. Add a small status indicator in the UI based on `/api/health`.

### Risks and mitigations
- The summary becomes stale if recomputed from partial refresh payloads: compute it only from the same fresh state used by the dashboard render.
- Response bloat: keep summary responses compact and limited to the high-value fields.
- Hidden assumptions: ensure summary calculations use the same `rows()` and lint logic as the UI to avoid divergence.

---

## 5) Drop-in PDF upload for papers

### Goal

Allow a user to drag and drop or select a PDF file for an existing paper record and have it stored in the library in the same way other paper attachments are handled.

### Problem

The current dashboard can display PDFs and save highlights for attached PDFs, but the library does not yet have a first-class, in-dashboard workflow for dropping a file onto a paper record when the PDF is not already in the library.

### User story

> As a user working with a paper record, I want to drag a PDF onto the dashboard or choose a file from disk and attach it to the paper so that the paper has a valid document without leaving the dashboard workflow.

### Proposed design

#### UI behavior
- Add a small attachment control in the paper drawer or paper detail panel.
- Support drag-and-drop onto the PDF tab or a dedicated “Attach PDF” area.
- Accept a local PDF file from the browser and show a progress indicator while it is uploaded.
- After success, refresh the paper's file metadata and update the PDF tab immediately.

#### Server behavior
- Add a secure POST route to receive a PDF for a given PMID, using the existing token and Host/Origin checks.
- Validate:
  - PMID format
  - file type is PDF
  - file size stays under a reasonable threshold
  - path is scoped to the specific paper directory
- Store the file under the same canonical paper file layout already used by the library.
- Update the paper's file metadata / inventory representation without touching unrelated library state.

#### File handling
- Prefer a server-side write to the library's canonical `papers/<pmid>/...` layout.
- Preserve the path semantics already used by the dashboard for reading and exporting PDFs.
- Keep the attachment operation limited to either:
  - `source.pdf`
  - the paper's active PDF path
  - or an additional, explicit PDF asset slot, depending on the current library conventions
- If there are multiple PDF variants, allow the user to choose the active file in the UI, without deleting previous copies.

#### UX flow
- Click “Attach PDF” in the paper drawer.
- Select a file or drag it onto the drop zone.
- Show “Uploading …” and any validation errors.
- On success, the PDF view refreshes and the file appears as an attached source.

### Acceptance criteria
- A PDF can be attached to a paper from the dashboard without using a terminal.
- The PDF is stored in a library-consistent path and is immediately viewable.
- Invalid files are rejected with clear feedback.
- Re-attaching or replacing a PDF does not corrupt other paper metadata.

### Implementation steps
1. Add file-upload route(s) in the dashboard server, protected by the existing token checks.
2. Add validation for file type, size, and PMID path handling.
3. Add a client upload UI in the paper drawer / PDF tab.
4. Implement drag-and-drop support and a fallback file picker.
5. Refresh the current paper detail state after a successful attach.
6. Add a small “replace existing PDF” confirmation when a paper already has a PDF.

### Risks and mitigations
- File type confusion: enforce PDF-only MIME checks and filename checks.
- Path traversal: require strict path construction under the paper directory.
- Storage drift: keep all storage rules aligned with the existing paper file conventions.
- Large files: enforce a maximum upload size and progress feedback.

This feature complements the dashboard improvement set and is especially valuable for papers that are manually fetched, scanned, or received outside the normal import pipeline.

---

## Cross-cutting implementation sequence

### Phase 1: low-risk, user-visible improvements
1. Shareable filtered views
2. Bulk export and selection actions
3. Next-action panel

### Phase 2: API and operational support
4. `/api/health` and `/api/summary`

### Phase 3: polish and tuning
- Add URL deep-linking for project and triage-specific views
- Add summary panel metric explanations
- Add keyboard shortcuts and selection helpers
- Add telemetry-safe logging around failures and degraded data

---

## Dependency notes

These changes rely on the following existing code paths:
- `lib_inventory.rows()`
- `lint_module.lint()`
- `list_cli.MATRIX_COLUMNS` / `_matrix_row()`
- `SNAPSHOTS` and snapshot history loading
- dashboard refresh flow in `app.js`
- token-protected API routes in `dashboard.py`

No new library write paths are required for the first milestone of this plan, which keeps the safety boundary intact.

---

## Success criteria for the full bundle

The dashboard is considered improved when a user can:
- open any filtered state as a link,
- export and act on selected rows quickly,
- understand what to do next without inspecting every issue manually,
- and use the dashboard API for health and summary monitoring without scraping the UI.

This delivers a more operational dashboard experience while keeping the implementation grounded in the existing architecture and guardrails.
