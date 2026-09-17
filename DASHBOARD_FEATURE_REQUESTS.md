# Dashboard Feature Requests

Date: 2026-09-16
Status: Draft

## Overview

This document collects product-style feature requests for the dashboard and related knowledge-mining workflows. The features are grouped by operational productivity, library management, and research synthesis.

---

## FR-01: Shareable filtered dashboard views

As a researcher, I want to save and share the exact dashboard filter state so that I can hand off a specific paper set or reproduce a review context without redoing filters.

Acceptance criteria:
- A filter state can be copied as a URL.
- The same URL restores search, project, issue, and source filters.
- Saved local views remain available as a convenience fallback.
- URL state is updated as filters change.

---

## FR-02: Bulk export of selected papers

As a researcher, I want to export the currently selected papers so that I can pass a cleaned list to another tool, script, or collaborator.

Acceptance criteria:
- Selected papers can be exported as PMIDs.
- Selected papers can be exported as CSV.
- Export reflects the currently visible filtered selection.
- Export is available from the action bar.

---

## FR-03: Bulk command generation for repair workflows

As a user managing paper backlog, I want the dashboard to generate ready-to-copy commands for the selected papers so that I can efficiently run repair or fetch tasks without manual assembly.

Acceptance criteria:
- The dashboard creates commands for `/ref:fetch`, `/ref:extract`, `/ref:fetch-pdf`, and `/ref:audit`.
- Commands are generated per selection subset.
- The user can copy whole command blocks or individual commands.
- Commands reflect current filters and selection state.

---

## FR-04: "What should I do next?" action panel

As a library owner, I want the dashboard to prioritize my next actions so that I can focus on the highest-impact fixes instead of reading every issue row.

Acceptance criteria:
- The dashboard shows a ranked list of next actions.
- Actions are based on issue count, urgency, and project impact.
- Each action includes a suggested command or workflow.
- The panel updates after refresh.

---

## FR-05: API health endpoint

As an operator, I want a compact dashboard health API so that I can monitor whether data sources and the dashboard itself are currently healthy.

Acceptance criteria:
- `/api/health` returns a simple health summary.
- It reports row, lint, matrix, and snapshot status.
- It returns warnings or degraded-state information.
- It is suitable for automation or monitoring.

---

## FR-06: API summary endpoint

As an operator or agent, I want a summary API so that I can inspect the current dashboard state without scraping the UI.

Acceptance criteria:
- `/api/summary` returns counts, issue totals, coverage totals, and top issue buckets.
- The response is compact and structured for automation.
- It reflects the same data that drives the dashboard UI.
- It includes enough information to drive a next-action panel.

---

## FR-07: Drop-in PDF attachment for papers

As a user reviewing a paper, I want to attach a PDF file directly from the dashboard so that I can bind a local PDF to the paper without leaving the workflow.

Acceptance criteria:
- A PDF can be dropped onto a paper or selected via file picker.
- The attachment is stored in the library’s canonical paper file layout.
- Invalid or non-PDF files are rejected with clear feedback.
- The PDF tab updates immediately after successful upload.

---

## FR-08: Drag-and-drop PDF replacement

As a researcher, I want to replace an existing paper PDF with a newer version so that I can correct or update the PDF without using a separate terminal workflow.

Acceptance criteria:
- The user can replace an existing PDF from the dashboard.
- The replacement is confirmed before overwriting.
- The new PDF is immediately viewable in the existing PDF tab.
- Previous PDFs are preserved if the library supports multiple variants.

---

## FR-09: Research evidence map

As a reviewer, I want to see an evidence map by population, intervention, outcome, and study characteristics so that I can identify what evidence already exists and what gaps remain.

Acceptance criteria:
- The dashboard shows a heatmap or matrix of evidence dimensions.
- Rows and columns represent relevant review dimensions.
- Cells are color-coded by evidence strength or effect direction.
- The map is filtered by project and search context.

---

## FR-10: Concept and claim graph

As a researcher, I want a graph of connected concepts, claims, and papers so that I can discover relationships and clusters across the literature.

Acceptance criteria:
- Nodes represent papers, concepts, authors, or claims.
- Edges represent meaningful relationships such as citation overlap, shared concepts, or claim similarity.
- Users can click a node to inspect the connected paper set.
- The graph is filterable by project or search query.

---

## FR-11: Topic timeline / trend view

As a synthesis-focused user, I want a timeline of research topics so that I can see when concepts or methods become prominent and where the field is shifting.

Acceptance criteria:
- Topic trends are shown over time.
- The timeline reflects paper frequency or concept intensity.
- Users can compare multiple topics side by side.
- The chart is linked to the underlying paper corpus.

---

## FR-12: Literature gap analysis

As a reviewer, I want a gap view that highlights under-served combinations of population, intervention, and outcome so that I can identify where the literature is sparse.

Acceptance criteria:
- The dashboard identifies sparsely covered combinations.
- Gap analysis is derived from the library’s actual metadata.
- Users can click a gap to inspect candidate papers or missing search terms.
- The view is project-aware.

---

## FR-13: Knowledge graph explorer

As a researcher, I want to visualize the library as an interactive knowledge graph so that I can explore papers, concepts, claims, and authors as a connected research map rather than as a flat list.

Acceptance criteria:
- The dashboard shows a graph of research objects such as papers, concepts, claims, and authors.
- Users can filter the graph by project, topic, year, or search context.
- Clicking a node opens a neighborhood view with related papers and concepts.
- Edge and cluster density remain readable even in larger libraries.

---

## FR-14: Concept and topic cluster map

As a researcher, I want a cluster view of related concepts and topics so that I can identify semantic neighborhoods and thematic areas in the library.

Acceptance criteria:
- Related concepts are grouped into clusters.
- Cluster size reflects the number of associated papers or extracted concepts.
- Users can drill into a cluster to inspect the underlying papers.
- Clusters are filterable by project, year, and topic.

---

## FR-15: Claim-network view

As a reviewer, I want a graph of claims and outcomes so that I can compare evidence patterns across papers and detect conflicting or repeated findings.

Acceptance criteria:
- The graph connects claim nodes to interventions, outcomes, and populations.
- Direction of effect and evidence tier are visible as metadata.
- Conflicting claims are visually distinct from consistent ones.
- Users can inspect the underlying papers behind each claim cluster.

---

## FR-16: Literature gap map

As a researcher, I want a graph-based or matrix-based gap view so that I can see underrepresented combinations of topic, population, method, and outcome.

Acceptance criteria:
- Sparse or missing combinations are highlighted.
- The view is built from actual paper metadata and extracted claims.
- Users can click a gap to inspect candidate search or review areas.
- The view supports project-scoped analysis.

---

## FR-17: Synthesis draft panel

As a researcher, I want a generated synthesis summary so that I can review a structured overview of the literature before writing a narrative review or report.

Acceptance criteria:
- The dashboard produces a structured summary of key findings.
- The summary includes main themes, contradictions, and open questions.
- The output is derived from paper metadata, claims, and notes.
- It can be copied or exported.

---

## Suggested backlog ordering

1. FR-01 Shareable views
2. FR-02 Bulk export
3. FR-03 Bulk command generation
4. FR-04 Next-action panel
5. FR-05 / FR-06 API health and summary
6. FR-07 / FR-08 PDF drop-in workflow
7. FR-09 Evidence map
8. FR-10 Concept graph
9. FR-11 Topic timeline
10. FR-12 Literature gaps
11. FR-13 Knowledge graph explorer
12. FR-14 Concept cluster map
13. FR-15 Claim-network view
14. FR-16 Literature gap map
15. FR-17 Synthesis draft panel

---

## Notes

These requests are intentionally oriented toward a research library dashboard that supports both operational maintenance and knowledge mining. The highest-value first phase is the operational layer: shareable views, bulk actions, next-step recommendations, and API health/summary support. The synthesis and graph features then extend the dashboard into a true research intelligence surface.
