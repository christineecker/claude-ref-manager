#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Shared intake resolver (UX_BACKLOG.md #4).

`/ref:import`, `/ref:add-url`, and `/ref:add-pdf` used to each re-derive "what
kind of thing is this input" in markdown prose, duplicated three times. This
module is the local, deterministic classification step those commands share:
given a raw string (PMID, DOI, URL, local PDF/dir path, or bib/CSL file), say
what kind it is and extract whatever identity clues are available without
touching the network or PubMed MCP -- that resolution stays in the calling
command, same as it does today for url_identify.py/pdf_identify.py.

`main()` below is the CLI entry point `/ref:import` shells out to (mirrors
url_identify.py/pdf_identify.py's own "print JSON, no side effects" shape).

Out of scope: parsing bib/csl.json file contents (flagged here as
"unparsed" -- see UX_BACKLOG.md #4 risk note, biggest unknown left for a
follow-up pass) and add.py's own post-resolution DOI/title conflict scan
(`_flag_doi_title_conflicts`), which stays as its own single-pass walk rather
than doing a second directory scan through `find_existing_by_identity`.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pdf_identify
import url_identify

PMID_RE = re.compile(r"^\d{5,10}$")
DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)
URL_RE = re.compile(r"^https?://", re.IGNORECASE)


def _identity(item: dict) -> tuple[str, str] | None:
    """Best available identity clue for cross-item duplicate detection,
    priority pmid > doi > pmcid > path/url (D11: PMID is the identity key,
    everything else is a candidate clue until resolved)."""
    kind = item["kind"]
    if kind == "pmid":
        return ("pmid", item["pmid"])
    if kind == "doi":
        return ("doi", item["doi"].lower())
    if kind in ("url", "pdf"):
        if item.get("pmid"):
            return ("pmid", item["pmid"])
        if item.get("doi"):
            return ("doi", item["doi"].lower())
        if item.get("pmcid"):
            return ("pmcid", item["pmcid"])
        return (kind, item["raw"])
    if kind in ("pdf_dir", "bib_file", "csl_file", "unknown"):
        return (kind, item["raw"])
    return None


def classify_item(item: str) -> dict:
    """Classify one raw intake string/path. Local and deterministic -- no
    network, no MCP. See module docstring for scope."""
    stripped = item.strip()

    if PMID_RE.match(stripped):
        return {"raw": item, "kind": "pmid", "pmid": stripped, "result": "identified_clues"}

    if DOI_RE.match(stripped):
        return {"raw": item, "kind": "doi", "doi": stripped, "result": "identified_clues"}

    if URL_RE.match(stripped):
        identified = url_identify.identify_url(stripped)
        return {"raw": item, "kind": "url", **identified}

    path = Path(stripped).expanduser()
    if path.is_dir():
        pdfs = sorted(str(p) for p in path.glob("*.pdf"))
        return {
            "raw": item,
            "kind": "pdf_dir",
            "path": str(path),
            "pdfs": pdfs,
            "result": "identified_dir" if pdfs else "no_clues",
        }
    if path.is_file():
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            identified = pdf_identify.identify_pdf(path)
            return {"raw": item, "kind": "pdf", **identified}
        if suffix == ".bib":
            return {"raw": item, "kind": "bib_file", "path": str(path), "result": "unparsed"}
        if path.name.lower().endswith(".csl.json"):
            return {"raw": item, "kind": "csl_file", "path": str(path), "result": "unparsed"}

    return {"raw": item, "kind": "unknown", "result": "no_clues"}


def classify_all(items: list[str]) -> list[dict]:
    """Classify a batch, expanding `pdf_dir` results into individual `pdf`
    items (so callers always work with a flat list), then flag within-batch
    duplicates by identity clue before any of them reach PubMed MCP."""
    flat: list[dict] = []
    for raw in items:
        classified = classify_item(raw)
        if classified["kind"] == "pdf_dir":
            if not classified["pdfs"]:
                flat.append(classified)
                continue
            for pdf_path in classified["pdfs"]:
                sub = classify_item(pdf_path)
                sub["from_dir"] = classified["path"]
                flat.append(sub)
        else:
            flat.append(classified)

    seen: dict[tuple[str, str], int] = {}
    for idx, entry in enumerate(flat):
        identity = _identity(entry)
        entry["identity"] = identity
        if identity is None:
            continue
        first_idx = seen.get(identity)
        if first_idx is None:
            seen[identity] = idx
        else:
            entry["status"] = "duplicate_in_batch"
            entry["duplicate_of"] = flat[first_idx]["raw"]

    return flat


def find_existing_by_identity(library_root: Path, identity: tuple[str, str]) -> str | None:
    """Look up whether `identity` (as produced by `_identity`) already
    matches a paper in the library. Returns the existing PMID, or None.
    `doi`/`pmcid` require a directory scan -- deliberately separate from
    add.py's own `_flag_doi_title_conflicts` scan (see module docstring)."""
    kind, value = identity
    papers_dir = library_root / "papers"
    if not papers_dir.is_dir():
        return None

    if kind == "pmid":
        return value if (papers_dir / value / "meta.json").exists() else None

    if kind not in ("doi", "pmcid"):
        return None

    for pdir in papers_dir.iterdir():
        meta_path = pdir / "meta.json"
        if not meta_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text())
        except (OSError, ValueError):
            continue
        if kind == "doi" and (meta.get("doi") or "").lower() == value:
            return meta.get("pmid") or pdir.name
        if kind == "pmcid" and meta.get("pmcid") == value:
            return meta.get("pmid") or pdir.name
    return None


def resolve_batch(library_root: Path, items: list[str]) -> list[dict]:
    """`classify_all()` plus a friendly "already imported" flag against the
    live library, so a caller never has to burn a PubMed MCP round trip on an
    input that's already in `papers/`. Within-batch duplicates (from
    `classify_all`) are checked first and take priority over a library hit,
    since there's nothing new to look up once an earlier item in the same
    batch already claimed that identity."""
    results = classify_all(items)
    for entry in results:
        if entry.get("status") == "duplicate_in_batch":
            continue
        identity = entry.get("identity")
        if identity is None:
            continue
        existing_pmid = find_existing_by_identity(library_root, identity)
        if existing_pmid:
            entry["status"] = "already_imported"
            entry["existing_pmid"] = existing_pmid
    return results


def main() -> int:
    """`python3 lib_intake.py classify --repo <root> <item...>` -- prints
    `resolve_batch()` as JSON. The CLI entry point `/ref:import` (and any
    other command with mixed-type input) shells out to."""
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    classify_ap = sub.add_parser("classify", help="classify a batch of raw intake inputs")
    classify_ap.add_argument("items", nargs="+")
    classify_ap.add_argument("--repo", required=True)
    args = ap.parse_args()

    library_root = Path(args.repo).expanduser().resolve()
    print(json.dumps(resolve_batch(library_root, args.items), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
