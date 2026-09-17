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
| NCBI E-utilities access + `ncbi_email` in config | `/ref:search-pubmed` / `/ref:triage` load search-result metadata from eutils.ncbi.nlm.nih.gov in batches of 100. |
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
- 2026-09-17 · [`32f3cd1`](https://github.com/christineecker/claude-ref-manager/commit/32f3cd1) ci: move workflow actions to Node 24 releases and test on Node 24
- 2026-09-17 · [`426c5e9`](https://github.com/christineecker/claude-ref-manager/commit/426c5e9) ci: install pandoc and uv for the conversion tests
- 2026-09-17 · [`929dab8`](https://github.com/christineecker/claude-ref-manager/commit/929dab8) feat: dashboard graph visualization (plan phases 1-5)
- 2026-09-17 · [`1b65776`](https://github.com/christineecker/claude-ref-manager/commit/1b65776) docs: graph visualization implementation plan (v2)
- 2026-09-17 · [`baf5c84`](https://github.com/christineecker/claude-ref-manager/commit/baf5c84) feat: triage follow-ups (PRISMA link, --triage selector, reason chips)
- 2026-09-17 · [`5783b81`](https://github.com/christineecker/claude-ref-manager/commit/5783b81) feat: dashboard insights, next actions, shareable views, PDF upload
- 2026-09-17 · [`a61852f`](https://github.com/christineecker/claude-ref-manager/commit/a61852f) docs: dashboard feature requests and improvements plan
- 2026-09-16 · [`0912d26`](https://github.com/christineecker/claude-ref-manager/commit/0912d26) feat: PubMed search triage tab with batch metadata loading
- 2026-09-16 · [`39b1a8c`](https://github.com/christineecker/claude-ref-manager/commit/39b1a8c) feat: full-screen PDF reader with text-layer highlighting and export
- 2026-09-16 · [`9e51278`](https://github.com/christineecker/claude-ref-manager/commit/9e51278) fix: library-viewer drawer hidden-attribute override; rename plugin ref-manager -> ref
- 2026-09-16 · [`6ed94ae`](https://github.com/christineecker/claude-ref-manager/commit/6ed94ae) docs: remove plan docs
- 2026-09-16 · [`b004d0d`](https://github.com/christineecker/claude-ref-manager/commit/b004d0d) docs: fix D-number gap in decision tables
- 2026-09-16 · [`c0eb24f`](https://github.com/christineecker/claude-ref-manager/commit/c0eb24f) feat: /ref:read opens live PDF+notes viewer instead of md reconstruction
- 2026-09-16 · [`e7fde72`](https://github.com/christineecker/claude-ref-manager/commit/e7fde72) docs: PhD-friendly command explanations + file-structure trees in tutorials
- 2026-09-16 · [`02ae63d`](https://github.com/christineecker/claude-ref-manager/commit/02ae63d) Implement library viewer UX improvements (P0-P2)
<!-- changelog:end -->
