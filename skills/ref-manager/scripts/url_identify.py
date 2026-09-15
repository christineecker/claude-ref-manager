#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Extract DOI/PMID/PMCID clues from article URLs for `/ref:add-url`.

This script is local and deterministic. It parses stable URL patterns and
prints JSON. The slash command is responsible for fetching page HTML when a
publisher URL does not itself contain identifiers, resolving candidates through
PubMed MCP, and then delegating to add.py/fetch.py.
"""
from __future__ import annotations

import argparse
import json
import re
import urllib.parse

DOI_RE = re.compile(r"\b10\.\d{4,9}/[^\s\"<>?&#]+", re.IGNORECASE)


def _clean_doi(value: str) -> str:
    value = urllib.parse.unquote(value.strip())
    value = value.rstrip(".,;:)]}")
    return value


def _pmid_from_path(path: str) -> str | None:
    patterns = [
        r"/pubmed/(\d{5,10})(?:[/?#]|$)",
        r"/(\d{5,10})(?:[/?#]|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, path)
        if match:
            return match.group(1)
    return None


def _pmcid_from_text(text: str) -> str | None:
    match = re.search(r"\bPMC\d{5,10}\b", text, re.IGNORECASE)
    return match.group(0).upper() if match else None


def identify_url(url: str) -> dict:
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower()
    path = urllib.parse.unquote(parsed.path)
    full = urllib.parse.unquote(url)

    pmid = None
    pmcid = None
    doi = None
    source = None

    if "pubmed.ncbi.nlm.nih.gov" in host:
        pmid = _pmid_from_path(path)
        source = "pubmed_url" if pmid else None
    elif "pmc.ncbi.nlm.nih.gov" in host:
        pmcid = _pmcid_from_text(path)
        source = "pmc_url" if pmcid else None
    elif host in {"doi.org", "dx.doi.org"} or host.endswith(".doi.org"):
        doi = _clean_doi(path.lstrip("/"))
        source = "doi_url" if doi.startswith("10.") else None

    if doi is None:
        match = DOI_RE.search(full)
        if match:
            doi = _clean_doi(match.group(0))
            source = source or "doi_in_url"

    result = {
        "url": url,
        "result": "identified_clues" if (pmid or pmcid or doi) else "no_clues",
        "source": source,
        "pmid": pmid,
        "pmcid": pmcid,
        "doi": doi,
    }
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("urls", nargs="+")
    args = ap.parse_args()

    print(json.dumps([identify_url(url) for url in args.urls], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
