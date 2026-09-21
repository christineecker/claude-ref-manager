<p align="center">
  <img src="docs/assets/icon.svg" alt="ref-manager icon" width="128">
</p>

# ref-manager

Claude Code plugin for scientific reference management: acquire, extract, and
retrieve PMID-keyed papers into a personal library, with an OKF knowledge graph
over claims and concepts.

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
| NCBI E-utilities access + `ncbi_email` in config | `/ref:query-pubmed` / `/ref:triage` load search-result metadata from eutils.ncbi.nlm.nih.gov in batches of 100. |
| pandoc *(optional)* | Converts JATS XML to Markdown. |
| uv *(optional)* | Runs the trafilatura worker for publisher HTML. |
| anydoc *(optional)* | Converts PDFs for `/ref:attach`. |
| pdftotext *(optional)* | From poppler; `/ref:attach` uses it to check a PDF matches the paper. |

### Install from the marketplace (recommended)

The repo is its own Claude Code plugin marketplace
(`.claude-plugin/marketplace.json`). Inside Claude Code:

```
/plugin marketplace add christineecker/claude-ref-manager
/plugin install ref@claude-ref-manager
```

Or from a terminal:

```bash
claude plugin marketplace add christineecker/claude-ref-manager
claude plugin install ref@claude-ref-manager
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
/ref:add-sources <item...>
```

`/ref:init` records the library root in `~/.config/ref-manager/config.json` (D2);
every other command resolves it from there rather than taking `--repo`.
For mixed intake from URLs, PDFs, DOI strings, or bibliography files, use
`/ref:add-sources` or the source-specific `/ref:add-url`, `/ref:add-pdf`, and
`/ref:add-fetch` commands.
The [Get started](https://christineecker.github.io/claude-ref-manager/getting-started.html)
tutorial walks through adding, fetching, extracting, searching and citing papers.

## Change log

Latest commits, regenerated automatically by
[`.github/workflows/readme-log.yml`](.github/workflows/readme-log.yml) on every push.
Run `python .github/scripts/update_readme_log.py` to refresh it locally.

<!-- changelog:start -->
- 2026-09-18 · [`c2b552a`](https://github.com/christineecker/claude-ref-manager/commit/c2b552a) feat: dashboard nav redesign — rail+sidebar shell, projects/queries, reports, question links
- 2026-09-18 · [`0d47cbc`](https://github.com/christineecker/claude-ref-manager/commit/0d47cbc) refactor: nest triage under queries/<slug>/; rename query commands
- 2026-09-18 · [`879ef7b`](https://github.com/christineecker/claude-ref-manager/commit/879ef7b) refactor: rename /ref:import to /ref:add-sources; add claim docs
- 2026-09-18 · [`bb4bc6a`](https://github.com/christineecker/claude-ref-manager/commit/bb4bc6a) fix: update stale dashboard viewer tests after coverage-matrix merge
- 2026-09-18 · [`2a1fc70`](https://github.com/christineecker/claude-ref-manager/commit/2a1fc70) refactor: rename /ref:search-add-fetch to /ref:pubmed-add-fetch
- 2026-09-18 · [`09a25d6`](https://github.com/christineecker/claude-ref-manager/commit/09a25d6) docs: add teachme workspace for paper-repo maintenance course
- 2026-09-17 · [`57dd57d`](https://github.com/christineecker/claude-ref-manager/commit/57dd57d) Add dashboard planning and graph visualization docs
- 2026-09-17 · [`cd76d6c`](https://github.com/christineecker/claude-ref-manager/commit/cd76d6c) feat(dashboard): fold coverage matrix into Papers table; docked ReadCube-style paper panel
- 2026-09-17 · [`8d0427d`](https://github.com/christineecker/claude-ref-manager/commit/8d0427d) docs: document the dashboard Insights graph features
- 2026-09-17 · [`0012be6`](https://github.com/christineecker/claude-ref-manager/commit/0012be6) docs: align plugin version (0.4.0) across docs; remove implemented plan
- 2026-09-17 · [`5947cc7`](https://github.com/christineecker/claude-ref-manager/commit/5947cc7) ci: pin setup-uv to v10.1.0
- 2026-09-17 · [`32f3cd1`](https://github.com/christineecker/claude-ref-manager/commit/32f3cd1) ci: move workflow actions to Node 24 releases and test on Node 24
- 2026-09-17 · [`426c5e9`](https://github.com/christineecker/claude-ref-manager/commit/426c5e9) ci: install pandoc and uv for the conversion tests
- 2026-09-17 · [`929dab8`](https://github.com/christineecker/claude-ref-manager/commit/929dab8) feat: dashboard graph visualization (plan phases 1-5)
- 2026-09-17 · [`1b65776`](https://github.com/christineecker/claude-ref-manager/commit/1b65776) docs: graph visualization implementation plan (v2)
<!-- changelog:end -->
