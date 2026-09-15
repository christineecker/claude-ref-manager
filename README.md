<p align="center">
  <img src="docs/assets/icon.svg" alt="ref-manager icon" width="128">
</p>

# ref-manager

Claude Code plugin for scientific reference management: acquire, extract, and
retrieve PMID-keyed papers into a personal library, with an OKF knowledge graph
over claims and concepts. Full design in [`PLAN.md`](PLAN.md); the planned
knowledge layer (phases 12–18) is in [`PLAN-v2.md`](PLAN-v2.md).

**Documentation:** <https://christineecker.github.io/claude-ref-manager/>
(source in [`docs/`](docs/index.html); open `docs/index.html` locally for an offline copy)

Status: phases 0–11 implemented.

## Installation

### Prerequisites

| Need | Why |
|---|---|
| [Claude Code](https://claude.com/claude-code) | Every `/ref:*` command is a Claude Code slash command. |
| Python ≥ 3.11 | Scripts are standard-library-only, single-file Python. |
| PubMed MCP connector | `/ref:add`, `/ref:fetch` and `/ref:extract` resolve metadata and full text through it. Papers can't be ingested without it. |
| pandoc *(optional)* | Converts JATS XML to Markdown. |
| uv *(optional)* | Runs the trafilatura worker for publisher HTML. |
| anydoc *(optional)* | Converts PDFs for `/ref:attach`. |
| pdftotext *(optional)* | From poppler; `/ref:attach` uses it to check a PDF matches the paper. |

### Install from the marketplace (recommended)

The repo is its own Claude Code plugin marketplace
(`.claude-plugin/marketplace.json`). Inside Claude Code:

```
/plugin marketplace add christineecker/claude-ref-manager
/plugin install ref-manager@claude-ref-manager
```

Or from a terminal:

```bash
claude plugin marketplace add christineecker/claude-ref-manager
claude plugin install ref-manager@claude-ref-manager
```

Restart Claude Code; the commands appear as `/ref:<name>`. To pick up new
versions later:

```bash
claude plugin marketplace update claude-ref-manager
```

### Load from a local clone (development)

```bash
git clone https://github.com/christineecker/claude-ref-manager.git
claude --plugin-dir /path/to/claude-ref-manager
```

`--plugin-dir` loads the plugin for that session only.

## Quick start

```
/ref:init <path-to-library-root>
/ref:status
/ref:add <pmid> [<pmid> ...]
```

`/ref:init` records the library root in `~/.config/ref-manager/config.json` (D2);
every other command resolves it from there rather than taking `--repo`.
The [Get started](https://christineecker.github.io/claude-ref-manager/getting-started.html)
tutorial walks through adding, fetching, extracting, searching and citing papers.

## Change log

Latest commits, regenerated automatically by
[`.github/workflows/readme-log.yml`](.github/workflows/readme-log.yml) on every push.
Run `python .github/scripts/update_readme_log.py` to refresh it locally.

<!-- changelog:start -->
- 2026-09-15 · [`25fea0e`](https://github.com/christineecker/claude-ref-manager/commit/25fea0e) docs: replace app icon with teal reader mascot; add .nojekyll for GitHub Pages
- 2026-09-15 · [`c35cdc5`](https://github.com/christineecker/claude-ref-manager/commit/c35cdc5) docs: add HTML documentation site and app icon for phases 0–11
- 2026-09-15 · [`f51a462`](https://github.com/christineecker/claude-ref-manager/commit/f51a462) docs: add PLAN-v2 knowledge layer plan and overview figure
- 2026-09-15 · [`3a2f0b0`](https://github.com/christineecker/claude-ref-manager/commit/3a2f0b0) fix: /ref:audit --citations rejects malformed input instead of silently recording check_failed
- 2026-09-15 · [`4c5d8de`](https://github.com/christineecker/claude-ref-manager/commit/4c5d8de) Phase 11: /ref:audit, citation observations, cache invalidation, /ref:report --citations
- 2026-09-15 · [`03aec9e`](https://github.com/christineecker/claude-ref-manager/commit/03aec9e) fix: /ref:summarize's candidate-building step is a real CLI path, not a fragile inline snippet
- 2026-09-15 · [`41487c0`](https://github.com/christineecker/claude-ref-manager/commit/41487c0) Phase 10: /ref:summarize, advanced /ref:review (GRADE, RoB2/NOS/AMSTAR-2)
- 2026-09-15 · [`69f757b`](https://github.com/christineecker/claude-ref-manager/commit/69f757b) fix: correct linkset parsing doc, add relation.py create-manual
- 2026-09-15 · [`19cf7e2`](https://github.com/christineecker/claude-ref-manager/commit/19cf7e2) Phase 9 (gaps half): /ref:gaps, /ref:hypothesize
- 2026-09-15 · [`f188b28`](https://github.com/christineecker/claude-ref-manager/commit/f188b28) Phase 9 (related half): /ref:related backward/forward snowballing
- 2026-09-15 · [`58f724a`](https://github.com/christineecker/claude-ref-manager/commit/58f724a) fix: okf_emit.py concept entries carry tags even with no aliases yet
- 2026-09-15 · [`f8796d3`](https://github.com/christineecker/claude-ref-manager/commit/f8796d3) Phase 8 (graph half): concept/relation graph, conflict review, stale-edge invalidation
- 2026-09-15 · [`ad1639a`](https://github.com/christineecker/claude-ref-manager/commit/ad1639a) Phase 8 (OKF/people-graph half): okf_emit.py, graph_people.py, /ref:weave
- 2026-09-15 · [`cb781fa`](https://github.com/christineecker/claude-ref-manager/commit/cb781fa) Phase 7: /ref:check-citations
- 2026-09-15 · [`a367eaa`](https://github.com/christineecker/claude-ref-manager/commit/a367eaa) Phase 6: /ref:ask retrieval + synthesis validation, /ref:brief
<!-- changelog:end -->
