# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Conversion toolchain (PLAN.md D16, D17): one output contract, three
backends selected by source type — JATS -> pandoc, HTML -> trafilatura
(via convert_html_worker.py, run under `uv run` so the dependency stays
out of this dependency-free script's own environment), PDF -> anydoc.

Every backend returns the same shape and writes the same files into the
staging version directory handed to it:
  {"converter": "<name>", "version": "<tool version or None>",
   "status": "ok" | "unavailable" | "error",
   "diagnostics": ["..."],           # missing tables/math/refs/figures/assets
   "figures": [<figures.json entries>]}
and, on status "ok", writes <staging>/source.md and (if any figures were
found) <staging>/figures/ + <staging>/figures.json — the "available assets,
source locators, and completeness diagnostics" contract (D16).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from lib_atomic import atomic_write_json, atomic_write_text

_XLINK = "{http://www.w3.org/1999/xlink}"

WORKER = Path(__file__).resolve().parent / "workers" / "convert_html_worker.py"
# NB: kept in its own subdirectory. `uv run` adds a script's own directory to
# sys.path, and this scripts/ dir has a queue.py (for /ref:queue) that shadows
# stdlib `queue` -- which urllib3 (a trafilatura dependency) imports. Running
# the worker from a directory with no colliding module names avoids that.


def _write_figures(staging: Path, figures: list[dict]) -> None:
    if not figures:
        return
    (staging / "figures").mkdir(parents=True, exist_ok=True)
    atomic_write_json(staging / "figures.json", figures)


# ---------------- JATS -> pandoc ----------------

def _jats_figures(xml_text: str) -> tuple[list[dict], list[str]]:
    """Extract <fig> label/caption/graphic-href locators. JATS references
    external graphic files by href; the bytes usually aren't embedded in the
    XML we received, so figures are recorded with their source locator and
    flagged asset_available=False unless a same-name file was preserved
    alongside the XML (out of scope here — later fetch stages can attach)."""
    figures, diags = [], []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        return [], [f"JATS figure scan skipped: XML parse error ({e})"]
    for i, fig in enumerate(root.iter("fig"), start=1):
        fig_id = fig.get("id") or f"fig{i}"
        label_el = fig.find("label")
        caption_el = fig.find("caption")
        caption = "".join(caption_el.itertext()).strip() if caption_el is not None else ""
        graphic = fig.find("graphic")
        href = graphic.get(f"{_XLINK}href") if graphic is not None else None
        figures.append({
            "id": fig_id,
            "label": label_el.text if label_el is not None else None,
            "caption": caption,
            "source_locator": href or f"fig[id={fig_id}]",
            "sha256": None,
            "asset_available": False,
        })
    if figures:
        diags.append(f"{len(figures)} figure(s) referenced in JATS; image bytes not embedded, asset_available=False")
    return figures, diags


def convert_jats(xml_text: str, staging: Path) -> dict:
    pandoc = shutil.which("pandoc")
    if not pandoc:
        return {"converter": "pandoc-jats", "version": None, "status": "unavailable",
                "diagnostics": ["JATS conversion unavailable: pandoc not installed"], "figures": []}

    proc = subprocess.run(
        [pandoc, "-f", "jats", "-t", "gfm"],
        input=xml_text.encode("utf-8"), capture_output=True,
    )
    version = subprocess.run([pandoc, "--version"], capture_output=True, text=True).stdout.splitlines()[0]
    if proc.returncode != 0:
        return {"converter": "pandoc-jats", "version": version, "status": "error",
                "diagnostics": [f"pandoc failed: {proc.stderr.decode('utf-8', 'replace')[:500]}"], "figures": []}

    md = proc.stdout.decode("utf-8")
    atomic_write_text(staging / "source.md", md)

    figures, diags = _jats_figures(xml_text)
    _write_figures(staging, figures)

    if "<table" in xml_text and "|" not in md:
        diags.append("source contained <table> elements pandoc did not render as markdown tables")
    if "<disp-formula" in xml_text or "<inline-formula" in xml_text:
        diags.append("source contains math markup; verify pandoc rendered it acceptably (not auto-checked)")
    if "<ref-list" in xml_text and "# References" not in md and "## References" not in md:
        diags.append("source has a <ref-list> but no References heading was detected in the rendered markdown")

    return {"converter": "pandoc-jats", "version": version, "status": "ok",
            "diagnostics": diags, "figures": figures}


# ---------------- HTML -> trafilatura ----------------

def convert_html(html_text: str, staging: Path) -> dict:
    uv = shutil.which("uv")
    if not uv:
        return {"converter": "trafilatura", "version": None, "status": "unavailable",
                "diagnostics": ["HTML conversion unavailable: uv not installed"], "figures": []}
    if not WORKER.exists():
        return {"converter": "trafilatura", "version": None, "status": "error",
                "diagnostics": [f"HTML conversion worker missing: {WORKER}"], "figures": []}

    proc = subprocess.run(
        [uv, "run", str(WORKER)],
        input=html_text.encode("utf-8"), capture_output=True,
    )
    if proc.returncode != 0:
        return {"converter": "trafilatura", "version": None, "status": "error",
                "diagnostics": [f"trafilatura worker failed: {proc.stderr.decode('utf-8', 'replace')[:500]}"],
                "figures": []}

    try:
        result = json.loads(proc.stdout.decode("utf-8").strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as e:
        return {"converter": "trafilatura", "version": None, "status": "error",
                "diagnostics": [f"could not parse worker output: {e}"], "figures": []}

    md = result.get("markdown")
    diags = []
    if not md:
        diags.append("trafilatura returned no extractable content (boilerplate-only page, or blocked)")
        md = ""
    atomic_write_text(staging / "source.md", md)

    figures: list[dict] = []
    for i, m in enumerate(re.finditer(r"!\[([^\]]*)\]\(([^)]+)\)", md), start=1):
        figures.append({
            "id": f"fig{i}", "label": None, "caption": m.group(1) or "",
            "source_locator": m.group(2), "sha256": None, "asset_available": False,
        })
    if figures:
        diags.append(f"{len(figures)} image reference(s) found in extracted markdown; bytes not fetched here")
        _write_figures(staging, figures)

    return {"converter": "trafilatura", "version": "runtime-resolved-by-uv", "status": "ok",
            "diagnostics": diags, "figures": figures}


# ---------------- PDF -> anydoc ----------------

def convert_pdf(pdf_path: Path, staging: Path) -> dict:
    anydoc = shutil.which("anydoc")
    if not anydoc:
        return {"converter": "anydoc", "version": None, "status": "unavailable",
                "diagnostics": ["PDF conversion unavailable: anydoc not installed (D16 supersedes pdf2md; "
                                "no substitute converter is used)"], "figures": []}

    proc = subprocess.run([anydoc, "convert", str(pdf_path), "--out", str(staging)], capture_output=True)
    if proc.returncode != 0:
        return {"converter": "anydoc", "version": None, "status": "error",
                "diagnostics": [f"anydoc failed: {proc.stderr.decode('utf-8', 'replace')[:500]}"], "figures": []}
    return {"converter": "anydoc", "version": None, "status": "ok", "diagnostics": [], "figures": []}


def main() -> int:
    """CLI wrapper for manual/diagnostic use: convert.py {jats|html|pdf} <input> <staging-dir>."""
    if len(sys.argv) != 4:
        print("usage: convert.py {jats|html|pdf} <input-file> <staging-dir>", file=sys.stderr)
        return 2
    kind, input_path, staging = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
    staging.mkdir(parents=True, exist_ok=True)
    if kind == "jats":
        result = convert_jats(input_path.read_text(), staging)
    elif kind == "html":
        result = convert_html(input_path.read_text(), staging)
    elif kind == "pdf":
        result = convert_pdf(input_path, staging)
    else:
        print(f"unknown kind {kind!r}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
