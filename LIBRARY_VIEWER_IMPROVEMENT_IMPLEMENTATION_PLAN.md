# Library Viewer Improvement Implementation Plan

Date: 2026-09-16
Status: Implemented (P0, P1, P2 all shipped; see skills/ref-manager/scripts/dashboard_assets/, tests in test_dashboard.py::TestViewerUxWiring)
Scope: Improve library viewer functionality and user friendliness for /ref:list and /ref:dashboard.

## 1. Objectives

1. Increase day-to-day usability for literature triage and maintenance work.
2. Reduce friction for keyboard-heavy workflows and large-library browsing.
3. Improve reliability and debuggability of live dashboard behavior.
4. Add high-value features without breaking the read-only design principle.

## 2. Principles

1. Keep "one inventory" architecture: all list/dashboard views continue to derive from lib_inventory.rows() and lib_inventory.detail().
2. Preserve safety boundary: dashboard remains read-only except the existing notes append path.
3. Prefer incremental changes with test coverage before broader UX enhancements.
4. Maintain compatibility with static and serve modes.

## 3. Success Metrics

1. Live refresh updates all visible data surfaces, including maintenance snapshots.
2. Keyboard-only flow can complete search -> open paper -> navigate -> save note.
3. Viewer remains responsive with large datasets (target: 5k papers).
4. Reduced user confusion from clearer API/load failure messages.

## 4. Phase Plan

## Phase P0: Correctness + Core UX (1-2 days)

### P0.1 Live refresh correctness

- Update refresh pipeline so /api/snapshots is re-fetched on manual refresh.
- Ensure maintenance visualizations are re-rendered from fresh snapshot data.

Primary files:
- skills/ref-manager/scripts/dashboard_assets/app.js

Acceptance criteria:
- Manual refresh updates Papers, Coverage, Health, and Maintenance from current server state.
- No hard reload is needed for maintenance trend/delta updates.

### P0.2 Actionable error handling

- Normalize fetch wrappers to check HTTP status before JSON parsing.
- Surface endpoint-specific error feedback (for example: /api/rows 403).
- Keep last known-good data on partial refresh failures.

Primary files:
- skills/ref-manager/scripts/dashboard_assets/app.js

Acceptance criteria:
- Initial load and refresh failures show meaningful endpoint and status details.
- UI remains usable with stale cached state when a subset of endpoints fails.

### P0.3 Keyboard productivity

- Add shortcuts:
- / focuses search input.
- Enter opens selected row.
- Arrow keys or j/k move selection.
- n/p moves previous/next paper in drawer.
- Escape closes drawer (already present, keep).

Primary files:
- skills/ref-manager/scripts/dashboard_assets/app.js
- skills/ref-manager/scripts/dashboard_assets/index.html

Acceptance criteria:
- Keyboard-only navigation works end-to-end in papers table and drawer.

### P0.4 Drawer focus behavior

- On open: set initial focus to drawer controls.
- While open: trap focus within drawer.
- On close: return focus to previously focused table row.

Primary files:
- skills/ref-manager/scripts/dashboard_assets/app.js
- skills/ref-manager/scripts/dashboard_assets/index.html

Acceptance criteria:
- Focus never escapes to background content while drawer is open.
- Closing drawer restores context for continued keyboard browsing.

### P0.5 Baseline UI smoke coverage

- Add lightweight integration checks for:
- initial load,
- filtering/search,
- selection action bar,
- drawer open/close,
- notes save flow (serve mode),
- refresh behavior.

Primary files:
- skills/ref-manager/scripts/tests/test_dashboard.py
- skills/ref-manager/scripts/tests/test_dashboard_serve.py

Acceptance criteria:
- New tests catch regressions in key user flows.

## Phase P1: Added Functionality (3-5 days)

### P1.1 Saved views and presets

- Allow saving named filter/sort/project combinations.
- Add quick apply, rename, delete actions.
- Persist presets in browser local storage.

Primary files:
- skills/ref-manager/scripts/dashboard_assets/app.js
- skills/ref-manager/scripts/dashboard_assets/index.html
- skills/ref-manager/scripts/dashboard_assets/app.css

Acceptance criteria:
- Users can restore frequent workflows in one click.

### P1.2 Maintenance diff by paper

- Extend maintenance tab to show paper-centric changes:
- newly added issues,
- resolved issues,
- issue type transitions.

Primary files:
- skills/ref-manager/scripts/dashboard_assets/app.js

Acceptance criteria:
- User can identify exactly which papers changed and why.

### P1.3 Project-focused mode

- Add project-centric dashboard lens with completion metrics:
- full-text coverage,
- claim extraction coverage,
- reading progress status.
- Add quick command suggestions from project context.

Primary files:
- skills/ref-manager/scripts/dashboard_assets/app.js
- skills/ref-manager/scripts/dashboard_assets/index.html

Acceptance criteria:
- Project maintainers can prioritize work directly from dashboard state.

### P1.4 Expanded batch actions

- Extend action bar command suggestions beyond fetch/extract:
- fetch-pdf,
- audit stale retraction checks,
- verify-oriented follow-ups where applicable.

Primary files:
- skills/ref-manager/scripts/dashboard_assets/app.js

Acceptance criteria:
- Selected-paper actions map to common maintenance tasks with copy-ready commands.

## Phase P2: Scale + Polish (4-7 days)

### P2.1 Table scalability

- Implement pagination or virtualization for the papers table.
- Keep sort/filter semantics unchanged.

Primary files:
- skills/ref-manager/scripts/dashboard_assets/app.js
- skills/ref-manager/scripts/dashboard_assets/app.css

Acceptance criteria:
- Smooth interactions on large libraries (target: 5k papers).

### P2.2 Coverage matrix scalability

- Add lazy render or windowed rendering for matrix rows.
- Preserve stable column order and cell semantics.

Primary files:
- skills/ref-manager/scripts/dashboard_assets/app.js

Acceptance criteria:
- Coverage tab opens quickly and remains responsive for large datasets.

### P2.3 Mobile-friendlier papers view

- Add compact card mode for narrow screens.
- Preserve all core metadata and actions in mobile layout.

Primary files:
- skills/ref-manager/scripts/dashboard_assets/index.html
- skills/ref-manager/scripts/dashboard_assets/app.css
- skills/ref-manager/scripts/dashboard_assets/app.js

Acceptance criteria:
- Small-screen browsing no longer depends on horizontal table scrolling alone.

### P2.4 Accessibility pass

- Improve ARIA semantics, status announcements, and focus order.
- Validate color contrast and visible focus styles.

Primary files:
- skills/ref-manager/scripts/dashboard_assets/index.html
- skills/ref-manager/scripts/dashboard_assets/app.css
- skills/ref-manager/scripts/dashboard_assets/app.js

Acceptance criteria:
- Keyboard and assistive-technology interaction is predictable and complete.

## 5. Test Strategy

1. Keep existing unit and serve-route tests as safety net.
2. Add UI behavior tests for keyboard and refresh scenarios.
3. Add synthetic large-data performance checks (timing assertions with generous thresholds).
4. Validate static and serve modes separately for regression isolation.

## 6. Delivery Sequence

1. Ship P0.1 and P0.2 first to improve correctness and diagnostics.
2. Ship P0.3 and P0.4 next for immediate UX gains.
3. Add P0.5 tests before or alongside each P0 feature.
4. Implement P1 features in vertical slices (preset + minimal UI + tests).
5. Start P2 only after P1 stabilizes.

## 7. Risks and Mitigations

1. Risk: Frontend complexity grows quickly.
- Mitigation: Keep state transitions centralized and introduce helper wrappers for data fetch and error display.

2. Risk: Performance regressions during feature growth.
- Mitigation: Add synthetic large-row test fixtures and guardrail timings before P2.

3. Risk: Behavior drift between static and serve modes.
- Mitigation: Keep rendering paths shared where possible and include mode-specific tests.

## 8. Definition of Done

1. P0 items complete with passing tests and no regressions in existing dashboard/list behavior.
2. P1 items ship with clear user-facing documentation updates in command/help docs.
3. P2 items meet responsiveness and accessibility expectations on desktop and mobile.
4. All changes preserve data authority and read-only boundaries described in the current architecture.
