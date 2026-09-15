<p align="center">
  <img src="docs/assets/icon.svg" alt="ref-manager icon" width="128">
</p>

# ref-manager

Claude Code plugin for scientific reference management: acquire, extract, and
retrieve PMID-keyed papers into a personal library, with an OKF knowledge graph
over claims and concepts. The repository's implementation plan is in
 [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md).

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
/ref:import <item...>
```

`/ref:init` records the library root in `~/.config/ref-manager/config.json` (D2);
every other command resolves it from there rather than taking `--repo`.
For mixed intake from URLs, PDFs, DOI strings, or bibliography files, use
`/ref:import` or the source-specific `/ref:add-url`, `/ref:add-pdf`, and
`/ref:add-fetch` commands.
The [Get started](https://christineecker.github.io/claude-ref-manager/getting-started.html)
tutorial walks through adding, fetching, extracting, searching and citing papers.

## Change log

Latest commits, regenerated automatically by
[`.github/workflows/readme-log.yml`](.github/workflows/readme-log.yml) on every push.
Run `python .github/scripts/update_readme_log.py` to refresh it locally.

<!-- changelog:start -->
- 2026-09-15 · [`eda8686`](https://github.com/christineecker/claude-ref-manager/commit/eda8686) docs: sync command reference with phase 5/6 changes
- 2026-09-15 · [`eae23af`](https://github.com/christineecker/claude-ref-manager/commit/eae23af) Implement phases 5 and 6 provenance and identity updates
- 2026-09-15 · [`4130e2f`](https://github.com/christineecker/claude-ref-manager/commit/4130e2f) Add /ref:add-url command with local URL identify helper
- 2026-09-15 · [`5133704`](https://github.com/christineecker/claude-ref-manager/commit/5133704) Add PubMed query workflow wrappers
- 2026-09-15 · [`e453797`](https://github.com/christineecker/claude-ref-manager/commit/e453797) Add PDF identification wrapper
- 2026-09-15 · [`7e65c5f`](https://github.com/christineecker/claude-ref-manager/commit/7e65c5f) Add reader rendering and PMC PDF fetch
- 2026-09-15 · [`5ac4b9d`](https://github.com/christineecker/claude-ref-manager/commit/5ac4b9d) Add add-fetch wrapper and improve fetch assets
- 2026-09-15 · [`62964e0`](https://github.com/christineecker/claude-ref-manager/commit/62964e0) release: v0.2.0
- 2026-09-15 · [`a317423`](https://github.com/christineecker/claude-ref-manager/commit/a317423) feat: create only core library dirs at init, rest lazily on first write
- 2026-09-15 · [`4e80136`](https://github.com/christineecker/claude-ref-manager/commit/4e80136) docs: add "Adding papers" tutorial covering four ways to find papers
- 2026-09-15 · [`da340ee`](https://github.com/christineecker/claude-ref-manager/commit/da340ee) Auto-acquire JATS figure images; add no-selector picker fallback
- 2026-09-15 · [`1d587eb`](https://github.com/christineecker/claude-ref-manager/commit/1d587eb) docs: README with install instructions and auto-updating change log; add plugin marketplace manifest
- 2026-09-15 · [`25fea0e`](https://github.com/christineecker/claude-ref-manager/commit/25fea0e) docs: replace app icon with teal reader mascot; add .nojekyll for GitHub Pages
- 2026-09-15 · [`c35cdc5`](https://github.com/christineecker/claude-ref-manager/commit/c35cdc5) docs: add HTML documentation site and app icon for phases 0–11
- 2026-09-15 · [`f51a462`](https://github.com/christineecker/claude-ref-manager/commit/f51a462) docs: add PLAN-v2 knowledge layer plan and overview figure
<!-- changelog:end -->
