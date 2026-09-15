#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""`/ref:read <pmid>` -- render the current converted paper as readable HTML.

This is a reading view for acquired full text, not a publisher-layout
reconstruction. It renders the current version's source.md and appends any
figures recorded in figures.json, linking to locally downloaded figure bytes
when available.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import subprocess
import sys
import urllib.parse
from pathlib import Path

from lib_atomic import atomic_write_json, atomic_write_text, pmid_lock


def _read_json(path: Path) -> dict | list | None:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _inline_md(text: str) -> str:
    text = html.escape(text)
    text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r'<span class="md-image-ref">[\1]</span>', text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", text)
    return text


def _markdown_to_html(markdown: str) -> str:
    blocks: list[str] = []
    paragraph: list[str] = []
    list_kind: str | None = None
    in_code = False
    code_lines: list[str] = []

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            blocks.append("<p>" + _inline_md(" ".join(paragraph)) + "</p>")
            paragraph = []

    def close_list() -> None:
        nonlocal list_kind
        if list_kind:
            blocks.append(f"</{list_kind}>")
            list_kind = None

    for raw in markdown.splitlines():
        line = raw.rstrip()
        if re.match(r"^\s*</?div(?:\s+[^>]*)?>\s*$", line):
            continue
        if line.startswith("```"):
            if in_code:
                blocks.append("<pre><code>" + html.escape("\n".join(code_lines)) + "</code></pre>")
                code_lines = []
                in_code = False
            else:
                flush_paragraph()
                close_list()
                in_code = True
            continue
        if in_code:
            code_lines.append(line)
            continue

        if not line.strip():
            flush_paragraph()
            close_list()
            continue

        heading = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading:
            flush_paragraph()
            close_list()
            level = len(heading.group(1))
            blocks.append(f"<h{level}>{_inline_md(heading.group(2))}</h{level}>")
            continue

        unordered = re.match(r"^\s*[-*]\s+(.+)$", line)
        ordered = re.match(r"^\s*\d+[.)]\s+(.+)$", line)
        if unordered or ordered:
            flush_paragraph()
            kind = "ul" if unordered else "ol"
            if list_kind != kind:
                close_list()
                blocks.append(f"<{kind}>")
                list_kind = kind
            item = unordered.group(1) if unordered else ordered.group(1)
            blocks.append(f"<li>{_inline_md(item)}</li>")
            continue

        if line.startswith(">"):
            flush_paragraph()
            close_list()
            blocks.append("<blockquote>" + _inline_md(line.lstrip("> ")) + "</blockquote>")
            continue

        close_list()
        paragraph.append(line.strip())

    if in_code:
        blocks.append("<pre><code>" + html.escape("\n".join(code_lines)) + "</code></pre>")
    flush_paragraph()
    close_list()
    return "\n".join(blocks)


def _quote_path(path: str) -> str:
    return "/".join(urllib.parse.quote(part) for part in path.split("/"))


def _figure_asset_relpath(version: str, locator: str) -> str:
    return f"../versions/{urllib.parse.quote(version)}/figures/{_quote_path(locator)}"


def _figure_asset_map(version: str, figures: list[dict]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for fig in figures:
        locator = fig.get("source_locator")
        if not locator or not fig.get("asset_available"):
            continue
        relpath = _figure_asset_relpath(version, locator)
        mapping[locator] = relpath
        mapping[Path(locator).name] = relpath
        if fig.get("id"):
            mapping[str(fig["id"])] = relpath
    return mapping


def _rewrite_inline_figure_paths(markdown: str, version: str, figures: list[dict]) -> tuple[str, int]:
    mapping = _figure_asset_map(version, figures)
    rewrites = 0

    def resolve(src: str) -> str:
        nonlocal rewrites
        clean = src.strip()
        key = clean.split("#", 1)[0].split("?", 1)[0]
        replacement = mapping.get(key) or mapping.get(Path(key).name)
        if replacement and replacement != src:
            rewrites += 1
            return replacement
        return src

    def markdown_image(match: re.Match) -> str:
        alt, src = match.group(1), match.group(2)
        return f"![{alt}]({resolve(src)})"

    def html_img_src(match: re.Match) -> str:
        return f'{match.group(1)}{resolve(match.group(2))}{match.group(3)}'

    markdown = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", markdown_image, markdown)
    markdown = re.sub(r'(<img\b[^>]*\bsrc=["\'])([^"\']+)(["\'])', html_img_src, markdown, flags=re.IGNORECASE)
    return markdown, rewrites


def _clean_converted_markdown(markdown: str) -> str:
    markdown = re.sub(r"^\s*</?div(?:\s+[^>]*)?>\s*\n", "", markdown, flags=re.MULTILINE)
    markdown = re.sub(r"([^\n])\n(#{1,6}\s+)", r"\1\n\n\2", markdown)
    markdown = re.sub(r"(#{1,6}[^\n]+)\n([-*]\s+)", r"\1\n\n\2", markdown)
    return markdown


def _figures_html(version: str, figures: list[dict]) -> tuple[str, int]:
    if not figures:
        return "", 0

    parts = ['<section class="figures"><h2>Figures</h2>']
    available = 0
    for fig in figures:
        label = fig.get("label") or fig.get("id") or "Figure"
        caption = fig.get("caption") or ""
        locator = fig.get("source_locator") or ""
        parts.append('<figure class="paper-figure">')
        if fig.get("asset_available") and locator:
            available += 1
            src = _figure_asset_relpath(version, locator)
            parts.append(f'<img src="{src}" alt="{html.escape(label)}">')
        else:
            parts.append('<div class="missing-figure">image bytes unavailable</div>')
        parts.append(f"<figcaption><strong>{html.escape(label)}</strong>")
        if caption:
            parts.append(f" {_inline_md(caption)}")
        parts.append("</figcaption></figure>")
    parts.append("</section>")
    return "\n".join(parts), available


def _authors(meta: dict) -> str:
    authors = meta.get("authors") or []
    names = []
    for author in authors:
        if isinstance(author, dict):
            names.append(author.get("raw") or " ".join(p for p in [author.get("first"), author.get("last")] if p))
        elif isinstance(author, str):
            names.append(author)
    return ", ".join(n for n in names if n)


def _html_doc(meta: dict, version: str, source_html: str, figures_html: str, figures: int, images: int) -> str:
    title = meta.get("title") or f"PMID {meta.get('pmid', '')}"
    authors = _authors(meta)
    details = []
    for key, label in (("journal", "Journal"), ("year", "Year"), ("doi", "DOI"), ("pmcid", "PMCID"), ("pmid", "PMID")):
        if meta.get(key):
            details.append(f"<dt>{label}</dt><dd>{html.escape(str(meta[key]))}</dd>")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
:root {{ color-scheme: light dark; }}
body {{ margin: 0; font: 17px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f7f7f4; color: #1e1f22; }}
main {{ max-width: 820px; margin: 0 auto; padding: 40px 22px 80px; }}
header {{ border-bottom: 1px solid #d8d8d0; margin-bottom: 28px; padding-bottom: 20px; }}
h1 {{ font-size: clamp(28px, 5vw, 44px); line-height: 1.12; margin: 0 0 12px; }}
h2, h3, h4 {{ line-height: 1.25; margin-top: 1.8em; }}
.authors {{ color: #555b62; margin: 0 0 16px; }}
dl {{ display: grid; grid-template-columns: max-content 1fr; gap: 4px 14px; color: #555b62; font-size: 14px; }}
dt {{ font-weight: 650; }}
dd {{ margin: 0; }}
.reader-note {{ background: #fff; border: 1px solid #deded7; padding: 12px 14px; border-radius: 8px; color: #4e545b; font-size: 14px; }}
article {{ overflow-wrap: anywhere; }}
pre {{ overflow-x: auto; background: #ecece6; padding: 12px; border-radius: 8px; }}
code {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .92em; }}
a {{ color: #0b5cad; }}
.figures {{ margin-top: 48px; border-top: 1px solid #d8d8d0; padding-top: 18px; }}
.paper-figure {{ margin: 26px 0; }}
.paper-figure img {{ display: block; max-width: 100%; height: auto; background: white; border: 1px solid #deded7; }}
figcaption {{ margin-top: 8px; color: #4e545b; font-size: 14px; }}
.missing-figure {{ display: grid; place-items: center; min-height: 120px; border: 1px dashed #b7b7ae; color: #6b6f76; background: #efefea; }}
.md-image-ref {{ color: #6b6f76; font-style: italic; }}
@media (prefers-color-scheme: dark) {{
  body {{ background: #161718; color: #ededeb; }}
  header, .figures {{ border-color: #343638; }}
  .authors, dl, figcaption, .reader-note {{ color: #babbb7; }}
  .reader-note, .paper-figure img {{ background: #202224; border-color: #343638; }}
  pre, .missing-figure {{ background: #202224; border-color: #44474a; }}
  a {{ color: #8dbdff; }}
}}
</style>
</head>
<body>
<main>
<header>
<h1>{html.escape(title)}</h1>
{f'<p class="authors">{html.escape(authors)}</p>' if authors else ''}
<dl>
{''.join(details)}
<dt>Version</dt><dd>{html.escape(version)}</dd>
</dl>
</header>
<p class="reader-note">Reading reconstruction from converted full text. This is not the publisher PDF layout. Figures available: {images}/{figures}.</p>
<article>
{source_html}
</article>
{figures_html}
</main>
</body>
</html>
"""


def _yaml_string(value: object) -> str:
    return str(value or "").replace('"', "'")


def _quarto_source(meta: dict, version: str, source_markdown: str, figures: list[dict]) -> tuple[str, int]:
    title = _yaml_string(meta.get("title") or f"PMID {meta.get('pmid', '')}")
    authors = _authors(meta).split(", ") if _authors(meta) else []
    yaml_authors = "\n".join(f'  - "{_yaml_string(name)}"' for name in authors[:12]) or '  - ""'
    subtitle_bits = [
        str(value) for value in (
            meta.get("journal"),
            meta.get("year"),
            f"DOI {meta.get('doi')}" if meta.get("doi") else None,
            meta.get("pmcid"),
        ) if value
    ]
    source_markdown, rewrites = _rewrite_inline_figure_paths(
        _clean_converted_markdown(source_markdown), version, figures,
    )
    images = sum(1 for fig in figures if fig.get("asset_available"))
    return f"""---
title: "{title}"
author:
{yaml_authors}
date: "{_yaml_string(meta.get('year'))}"
subtitle: "{_yaml_string(' · '.join(subtitle_bits))}"
format:
  html:
    toc: true
    toc-depth: 3
    number-sections: false
    theme: cosmo
    standalone: true
    embed-resources: false
    css: reader.css
  pdf:
    toc: true
    number-sections: false
execute:
  echo: false
---

::: {{.callout-note appearance="simple"}}
Reading reconstruction from converted full text. This is not the publisher PDF layout. Figures available: {images}/{len(figures)}.
:::

{source_markdown}
""", rewrites


def _write_quarto_reader(reader_dir: Path, meta: dict, version: str, source_markdown: str, figures: list[dict]) -> tuple[Path, int]:
    qmd, rewrites = _quarto_source(meta, version, source_markdown, figures)
    qmd_path = reader_dir / "article.qmd"
    atomic_write_text(qmd_path, qmd)
    atomic_write_text(reader_dir / "reader.css", """
body { line-height: 1.58; }
table { font-size: 0.9rem; }
figcaption, .figure-caption { color: #555; font-size: 0.92rem; }
img { max-width: 100%; height: auto; }
.table-snapshot { margin: 1rem 0 1.5rem; }
.table-snapshot img { border: 1px solid #ddd; background: white; }
""".lstrip())
    return qmd_path, rewrites


def _render_quarto(reader_dir: Path, output_format: str) -> list[str]:
    if shutil.which("quarto") is None:
        raise ValueError("quarto is not installed or not on PATH")
    targets = ["html", "pdf"] if output_format == "both" else [output_format]
    outputs: list[str] = []
    for target in targets:
        subprocess.run(
            ["quarto", "render", "article.qmd", "--to", target],
            cwd=reader_dir, check=True,
        )
        outputs.append(f"article.{target}")
    return outputs


def _capture_table_images(html_path: Path, tables_dir: Path) -> list[str]:
    if shutil.which("node") is None:
        raise ValueError("node is not installed or not on PATH; cannot render table images")
    tables_dir.mkdir(parents=True, exist_ok=True)
    for old in tables_dir.glob("table-*.png"):
        old.unlink()

    script = r"""
const { createRequire } = require("module");
const require2 = createRequire(process.cwd() + "/x.js");
const { chromium } = require2("playwright");

(async () => {
  const htmlPath = process.argv[1];
  const outDir = process.argv[2];
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1200 }, deviceScaleFactor: 2 });
  await page.goto("file://" + htmlPath, { waitUntil: "networkidle", timeout: 30000 });
  const tables = await page.locator("table").count();
  const outputs = [];
  for (let i = 0; i < tables; i++) {
    const table = page.locator("table").nth(i);
    await table.scrollIntoViewIfNeeded();
    const out = `${outDir}/table-${i + 1}.png`;
    await table.screenshot({ path: out });
    outputs.push(`tables/table-${i + 1}.png`);
  }
  await browser.close();
  console.log(JSON.stringify(outputs));
})().catch(async (e) => {
  console.error(e.stack || String(e));
  process.exit(1);
});
"""
    repo_root = Path(__file__).resolve().parents[3]
    proc = subprocess.run(
        ["node", "-e", script, str(html_path), str(tables_dir)],
        cwd=repo_root, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        check=True,
    )
    return json.loads(proc.stdout or "[]")


def _insert_table_image_refs(html_text: str, table_images: list[str]) -> tuple[str, int]:
    if not table_images:
        return html_text, 0

    index = 0

    def replacement(match: re.Match) -> str:
        nonlocal index
        table_html = match.group(0)
        if index >= len(table_images):
            return table_html
        src = html.escape(table_images[index])
        label = f"Table {index + 1} image"
        index += 1
        return (
            table_html
            + "\n"
            + f'<figure class="table-snapshot"><img src="{src}" alt="{label}">'
            + f"<figcaption>{label}</figcaption></figure>"
        )

    updated = re.sub(r"</table>", replacement, html_text, flags=re.IGNORECASE)
    return updated, index


def _add_table_images(html_path: Path) -> tuple[int, list[str]]:
    table_images = _capture_table_images(html_path, html_path.parent / "tables")
    html_text = html_path.read_text()
    updated, inserted = _insert_table_image_refs(html_text, table_images)
    atomic_write_text(html_path, updated)
    return inserted, table_images


def render_one(
    library_root: Path,
    pmid: str,
    open_file: bool = False,
    engine: str = "simple",
    output_format: str = "html",
    table_images: bool = False,
) -> dict:
    paper_dir = library_root / "papers" / str(pmid)
    meta_path = paper_dir / "meta.json"
    if not meta_path.exists():
        raise ValueError(f"pmid {pmid} has no meta.json -- run /ref:add first")

    with pmid_lock(library_root, str(pmid)):
        meta = json.loads(meta_path.read_text())
        current = _read_json(paper_dir / "current.json")
        if not isinstance(current, dict) or not current.get("version"):
            return {"pmid": str(pmid), "result": "no_full_text", "reason": "no current version -- run /ref:fetch first"}

        version = current["version"]
        vdir = paper_dir / "versions" / version
        source_path = vdir / "source.md"
        if not source_path.exists():
            return {"pmid": str(pmid), "result": "no_full_text", "version": version, "reason": "current version has no source.md"}

        figures_raw = _read_json(vdir / "figures.json")
        figures = figures_raw if isinstance(figures_raw, list) else []

        reader_dir = paper_dir / "reader"
        reader_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = reader_dir / "manifest.json"
        source_markdown = source_path.read_text()
        inline_figure_rewrites = 0
        table_image_count = 0
        table_image_paths: list[str] = []

        if engine == "quarto":
            qmd_path, inline_figure_rewrites = _write_quarto_reader(reader_dir, meta, version, source_markdown, figures)
            outputs = _render_quarto(reader_dir, output_format)
            article_path = reader_dir / ("article.html" if "article.html" in outputs else outputs[0])
            output_paths = [str(reader_dir / output) for output in outputs]
            qmd_rel = str(qmd_path.relative_to(paper_dir))
            if table_images:
                if "article.html" not in outputs:
                    raise ValueError("--table-images requires Quarto HTML output; use --format html or both")
                table_image_count, table_image_paths = _add_table_images(reader_dir / "article.html")
        else:
            if table_images:
                raise ValueError("--table-images requires --engine quarto")
            if output_format not in {"html", "both"}:
                raise ValueError("simple renderer only supports html output")
            figures_block, images_for_html = _figures_html(version, figures)
            source_html = _markdown_to_html(source_markdown)
            article_path = reader_dir / "article.html"
            atomic_write_text(article_path, _html_doc(meta, version, source_html, figures_block, len(figures), images_for_html))
            output_paths = [str(article_path)]
            qmd_rel = None

        images = sum(1 for fig in figures if fig.get("asset_available"))
        atomic_write_json(manifest_path, {
            "pmid": str(pmid),
            "version": version,
            "article": article_path.name,
            "engine": engine,
            "format": output_format,
            "outputs": [Path(path).name for path in output_paths],
            "qmd": qmd_rel,
            "figures": len(figures),
            "images_available": images,
            "inline_figure_rewrites": inline_figure_rewrites,
            "table_images": table_image_count,
            "table_image_paths": table_image_paths,
            "source": str(source_path.relative_to(paper_dir)),
        })

    result = {
        "pmid": str(pmid), "result": "rendered", "version": version,
        "path": str(article_path), "outputs": output_paths, "engine": engine,
        "figures": len(figures), "images_available": images,
        "inline_figure_rewrites": inline_figure_rewrites,
        "table_images": table_image_count,
        "table_image_paths": table_image_paths,
    }
    if open_file:
        subprocess.run(["open", str(article_path)], check=True)
        result["opened"] = True
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--open", action="store_true", help="open the primary rendered file")
    ap.add_argument("--engine", choices=["simple", "quarto"], default="simple")
    ap.add_argument("--format", choices=["html", "pdf", "both"], default="html")
    ap.add_argument("--table-images", action="store_true", help="snapshot live HTML tables as PNG images and insert them under the tables")
    ap.add_argument("pmids", nargs="+")
    args = ap.parse_args()

    library_root = Path(args.repo).expanduser().resolve()
    if not library_root.is_dir():
        print(f"error: no library at {library_root}", file=sys.stderr)
        return 1

    exit_code = 0
    for pmid in args.pmids:
        try:
            result = render_one(
                library_root, pmid, open_file=args.open,
                engine=args.engine, output_format=args.format,
                table_images=args.table_images,
            )
        except (ValueError, OSError, subprocess.CalledProcessError) as e:
            result = {"pmid": pmid, "result": "failed", "error": str(e)}
            exit_code = 1

        line = f"{result['pmid']}: {result['result']}"
        if result.get("path"):
            line += f" -- {result['path']}"
        if result.get("figures") is not None:
            line += f" (figures={result['figures']}, images={result['images_available']}/{result['figures']})"
        if result.get("inline_figure_rewrites"):
            line += f" inline_figures_rewritten={result['inline_figure_rewrites']}"
        if result.get("table_images"):
            line += f" table_images={result['table_images']}"
        if result.get("reason"):
            line += f" -- {result['reason']}"
        if result.get("error"):
            line += f" -- {result['error']}"
        print(line)
        for output in result.get("outputs", [])[1:]:
            print(f"  output: {output}")

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
