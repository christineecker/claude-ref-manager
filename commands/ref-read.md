Render a readable local HTML copy of one or more already-fetched papers.

Parse `$ARGUMENTS` for:
- `<pmid...>` — one or more PubMed IDs. Each must already exist and have a
  current full-text version with `source.md` from `/ref:fetch` or `/ref:attach`.
- `--engine simple|quarto` — renderer. Default is `simple`; `quarto` writes an
  intermediate `article.qmd` and renders through Quarto.
- `--format html|pdf|both` — output format for `--engine quarto`. Default
  `html`. The simple renderer supports HTML only.
- `--table-images` — with `--engine quarto` and an HTML output, snapshot each
  rendered HTML table to `reader/tables/table-<n>.png` and insert the image
  below the live table. Keeps the live/searchable table as the default source.
- `--open` — after rendering, open each generated HTML file in the default
  browser, or the primary Quarto output.

Steps:
1. Resolve the library root (fail loudly, pointing at `/ref:init`, if
   unconfigured).
2. Print, then run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/read_article.py" --repo <library_root> [--engine simple|quarto] [--format html|pdf|both] [--table-images] [--open] <pmid...>
   ```
3. Print the script's own output verbatim. Per PMID:
   - `rendered` — wrote `papers/<pmid>/reader/article.html` and
     `papers/<pmid>/reader/manifest.json`.
   - `no_full_text` — the paper exists but has no current `source.md`; point at
     `/ref:fetch`, `/ref:fetch-pdf`, or `/ref:attach`.
   - `failed` — missing record or filesystem/open error.

Notes:
- This is a reading reconstruction, not the publisher PDF. It renders the
  current converted `source.md` and appends a figure gallery from
  `figures.json`, linking to local files under `versions/<v>/figures/` when
  image bytes are available.
- In Quarto mode, inline image references from converted JATS/Pandoc output are
  rewritten to those local figure assets before `article.qmd` is rendered, so
  the article body does not show broken figure icons when the assets exist.
- With `--table-images`, tables remain real HTML tables and image snapshots are
  added underneath them. This is useful for cramped or complex tables while
  preserving copy/search/accessibility from the live table.
- Missing figure images do not fail rendering; the HTML shows a placeholder and
  the output reports `images=<available>/<figures>`.
