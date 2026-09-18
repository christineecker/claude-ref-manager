## Project

**claude-ref-manager**: Claude Code plugin for scientific reference management —
acquires, extracts, and retrieves PMID-keyed papers into a personal library,
with an OKF knowledge graph over claims and concepts. Docs at
https://christineecker.github.io/claude-ref-manager/ (source in `docs/`).

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).

## teachme skill

When the `teachme` skill (`/teach`) runs in this repo, its workspace files go under
`docs/teachme/`, not the repo root: `docs/teachme/MISSION.md`, `RESOURCES.md`,
`NOTES.md`, `lessons/`, `assets/`, `reference/`, `learning-records/`. Link paths inside
those files must account for the extra nesting depth (`docs/teachme/lessons/*.html`
reaching repo-root docs like `docs/concepts.html` needs `../../concepts.html`, etc.).
