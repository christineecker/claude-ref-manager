#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Extract bibliographic identifiers from local PDFs for `/ref:add-pdf`.

This script is intentionally local-only: it reads the PDF text with
pdftotext, extracts DOI/PMID/PMCID clues, and prints JSON. The slash command
does the PubMed MCP resolution, then existing add.py and attach.py perform the
actual ingest and attachment.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

PDFTOTEXT_PAGES = 3

DOI_RE = re.compile(r"\b10\.\d{4,9}/[^\s\"<>]+", re.IGNORECASE)
PMID_RE = re.compile(r"\bPMID\s*:?\s*(\d{5,10})\b", re.IGNORECASE)
PMCID_RE = re.compile(r"\bPMC(?:ID)?\s*:?\s*(PMC?\d{5,10})\b", re.IGNORECASE)


def _clean_doi(value: str) -> str:
    value = value.strip().rstrip(".,;:)]}")
    value = value.replace("\u200b", "")
    return value


def _extract_pdf_text(pdf_path: Path, pages: int = PDFTOTEXT_PAGES) -> tuple[str | None, str | None]:
    pdftotext = shutil.which("pdftotext")
    if not pdftotext:
        return None, "pdftotext unavailable"
    proc = subprocess.run(
        [pdftotext, "-f", "1", "-l", str(pages), str(pdf_path), "-"],
        capture_output=True,
    )
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace").strip()
        return None, err or "pdftotext failed"
    return proc.stdout.decode("utf-8", "replace"), None


def _title_guess(text: str) -> str | None:
    lines = []
    for raw in text.splitlines()[:80]:
        line = " ".join(raw.split())
        if not line:
            continue
        lower = line.lower()
        if (
            lower.startswith(("doi", "pmid", "pmcid", "abstract", "keywords", "copyright"))
            or "journal" in lower[:30]
            or len(line) < 20
        ):
            continue
        lines.append(line)
        if len(" ".join(lines)) > 180:
            break
    return " ".join(lines)[:300] if lines else None


def identify_pdf(path: Path) -> dict:
    if not path.is_file():
        return {"path": str(path), "result": "failed", "error": f"no such file: {path}"}

    text, error = _extract_pdf_text(path)
    if text is None:
        return {"path": str(path), "result": "failed", "error": error}

    dois = []
    for match in DOI_RE.findall(text):
        doi = _clean_doi(match)
        if doi and doi.lower() not in [d.lower() for d in dois]:
            dois.append(doi)

    pmids = []
    for match in PMID_RE.findall(text):
        if match not in pmids:
            pmids.append(match)

    pmcids = []
    for match in PMCID_RE.findall(text):
        value = match.upper()
        if value.startswith("PMC"):
            pmcid = value
        elif value.startswith("PM"):
            pmcid = "PMC" + value[2:]
        else:
            pmcid = "PMC" + value
        if pmcid not in pmcids:
            pmcids.append(pmcid)

    result = {
        "path": str(path),
        "result": "identified_clues" if (dois or pmids or pmcids) else "no_clues",
        "doi": dois[0] if dois else None,
        "pmid": pmids[0] if pmids else None,
        "pmcid": pmcids[0] if pmcids else None,
        "dois": dois,
        "pmids": pmids,
        "pmcids": pmcids,
        "title_guess": _title_guess(text),
    }
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdfs", nargs="+")
    args = ap.parse_args()

    results = [identify_pdf(Path(p).expanduser().resolve()) for p in args.pdfs]
    print(json.dumps(results, indent=2, sort_keys=True))
    return 1 if any(r["result"] == "failed" for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
