# ref-manager Implementation Plan

This document replaces the older planning split across `PLAN.md`, `PLAN-v2.md`, and `BACKLOG.md`. It is ordered by implementation priority and written for execution, not design exploration.

## Goals

- Reduce friction in day-to-day reference management.
- Keep the PMID-centric library model intact.
- Preserve provenance, recoverability, and explicit state.
- Deliver the most visible workflow wins first, then fill in structural gaps.

## Phase 1: Browseable selection instead of PMID memory

### Objective

Let users start work from the library instead of requiring them to remember or copy PMIDs.

### Deliverables

- Shared no-selector fallback for PMID-taking commands.
- Recent-papers picker with `AskUserQuestion` multi-select.
- Consistent behavior across `/ref:fetch`, `/ref:extract`, `/ref:summarize`, `/ref:attach`, `/ref:describe-figure`, and similar commands.

### Acceptance criteria

- A user can invoke a PMID-taking command with no arguments and select papers from recent library entries.
- The picker surfaces title, citekey, and year.
- Commands proceed as if PMIDs had been passed positionally.

### Dependencies

- Selector resolution in `skills/ref-manager/scripts/lib_selector.py`.
- Command docs for no-selector fallback behavior.

## Phase 2: Full-text acquisition with figure fidelity

### Objective

Make acquisition preserve the structural and visual evidence users need for reading and figure description.

### Deliverables

- JATS-first fetch path when PMCID is available.
- Graceful fallback to PubMed plain text, Unpaywall, and publisher HTML.
- Figure asset download/attach support for JATS-based acquisitions.
- Meaningful diagnostics when figures remain unavailable.

### Acceptance criteria

- Fetched papers keep section structure and figure captions when JATS exists.
- At least the supported figure-image cases are stored as usable bytes in the library.
- `/ref:describe-figure` can operate on real figure assets without manual repair in the common case.

### Dependencies

- Fetch/conversion plumbing in `skills/ref-manager/scripts/fetch.py`, `convert.py`, and `attach_figures.py`.
- Command docs for `/ref:fetch` and `/ref:describe-figure`.

## Phase 2b: Unified intake across source types

### Objective

Make it easy to add papers from the places users actually encounter them, not just from PMID lists.

### Deliverables

- A single source-aware intake front door that routes PMIDs, URLs, and local
  PDFs into the existing add/fetch/attach flows.
- Folder-drop intake that expands local directories into their PDFs.
- BibTeX and CSL-JSON intake through the same front door.
- DOI-only intake through the same front door.
- Auto-detection of the best import path with a confirmation step before writing records.
- Clear per-item reporting that shows where the record came from and what could be resolved.

### Next extensions

- None for the initial intake surface; remaining work is polish and deeper source coverage.

### Acceptance criteria

- Users can paste mixed-source input and have the tool resolve as much as possible without manual pre-normalization.
- Ambiguous or unresolved items are surfaced for review instead of failing the whole batch.
- The result line tells the user whether the paper came from PubMed, PMC, publisher HTML, or PDF.

### Dependencies

- Add/fetch/attach orchestration.
- Metadata resolution for DOI, URL, citation export, and local-file inputs.

## Phase 2c: Retry and fallback acquisition flow

### Objective

Reduce dead ends when the first source is incomplete or unavailable.

### Deliverables

- A guided “retry from another source” path when acquisition is partial or fails.
- Automatic fallback from metadata-only to PMC JATS, publisher HTML, or local PDF attachment when available.
- Explicit source-completeness badges so the user can see what was acquired.

### Acceptance criteria

- The user can see the next best available source without having to restart the whole workflow manually.
- Partial acquisitions remain useful and clearly labeled instead of looking complete.

### Dependencies

- Source detection in intake and fetch workflows.
- Record-level completeness/state reporting.

## Phase 2d: Figure and attachment ergonomics

### Objective

Make figure/image recovery and PDF attachment feel like part of acquisition, not a separate cleanup task.

### Deliverables

- Better automatic figure-asset retrieval for JATS-based papers.
- Easier post-hoc attachment of missing figure bytes.
- PDF attachment flows that make it obvious when identity checks pass or fail.

### Acceptance criteria

- The common case produces usable figure bytes without manual intervention.
- When manual follow-up is needed, the tool says exactly what is missing and how to attach it.

### Dependencies

- `attach_figures.py`, `attach.py`, and fetch-time asset handling.

## Phase 2e: Source provenance and completeness visibility

### Objective

Show the user what kind of evidence each record contains as soon as it enters the library.

### Deliverables

- Source badges for metadata-only, abstract-only, full-text, JATS+figures, and PDF-backed records.
- Result lines and listing views that expose provenance and completeness.
- Consistent terminology for acquisition source and retrieval quality.

### Acceptance criteria

- The user can tell at a glance what was fetched, what was attached, and what is still incomplete.

### Dependencies

- Add/fetch/status/listing output formatting.

## Phase 2f: Browse-first discovery for intake

### Objective

Help users start from the library or from recent work when they do not have an identifier ready.

### Deliverables

- Browse-first selectors for recent PMIDs, recent imports, and unresolved items.
- Multi-select selection flows for commands that can operate on several papers at once.
- Clear fallback lists for items that need follow-up.

### Acceptance criteria

- Users can choose papers from browseable lists instead of memorizing or copying identifiers.
- Intake and fetch flows can continue from recent or unresolved items without a separate search step.

### Dependencies

- Selector infrastructure in `lib_selector.py`.
- Command docs for no-argument and browse-first fallback behavior.

## Phase 3: Search that reflects a reference library

### Objective

Let search reach the library’s important metadata and research context, not just paper text.

### Deliverables

- Search over additional structured fields beyond title/abstract/journal.
- Clear distinction between published evidence and personal/project metadata.
- More useful result summaries for evidence work.

### Acceptance criteria

- Users can find records by author, project, grant, concept, and saved-query context where available.
- Search output labels what kind of content each result represents.

### Dependencies

- The search command and catalog/index surface.
- Library state models for projects, grants, and related records.

## Phase 4: Operational visibility

### Objective

Make library state visible enough that users can tell what is current, derived, or needs attention.

### Deliverables

- A richer `/ref:status` dashboard.
- Explicit indicators for extraction tier, reading state, stale audits, and failures.
- Lifecycle state surfaced in listings and search output.

### Acceptance criteria

- A user can see at a glance what changed recently and what needs attention.
- Paper listings show enough state to avoid opening multiple files just to orient.

### Dependencies

- Status reporting and list-rendering commands.
- Existing record fields for state, tier, and diagnostics.

## Phase 5: Ingest trust and identity hygiene

### Objective

Expose identity and provenance problems earlier so records stay trustworthy.

### Deliverables

- Earlier duplicate and DOI/title mismatch warnings during ingest.
- Better provenance messaging in add/fetch flows.
- Actionable diagnostics that make the next step obvious.

### Acceptance criteria

- Ambiguous or conflicting identity data is visible before the user treats the record as settled.
- Warnings are understandable without reading implementation details.

### Dependencies

- Add/ingest workflow and metadata validation.

## Phase 6: Project-first workflows and provenance-rich outputs

### Objective

Make the library easier to use around research questions, reading queues, and evidence synthesis.

### Deliverables

- Stronger project-scoped organization views.
- Better surfacing of membership, relevance, screening, and reading state together.
- More explicit source tier, verification, and freshness metadata in downstream outputs.

### Acceptance criteria

- A project question can drive a coherent workflow without paper-by-paper hunting.
- Outputs used for writing and review carry enough provenance to trust and reuse them.

### Dependencies

- Project, compare, summarize, brief, and retrieval commands.

## Execution Order

1. Shared no-selector paper picker.
2. JATS-first fetch and figure asset support.
3. Broader search surface.
4. Status/dashboard expansion.
5. Earlier identity and provenance warnings.
6. Project-first workflows and provenance-rich outputs.

## Retired Documents

- `PLAN.md`
- `PLAN-v2.md`
- `BACKLOG.md`

This implementation plan is now the single planning document for the repository.