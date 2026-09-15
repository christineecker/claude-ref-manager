#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""`/ref:add <PMID...>` — pipeline [1] RESOLVE + [2] DEDUP (PLAN.md §4, §4a header).

This script never calls the network or an MCP tool itself (it's a plain
subprocess). The calling command markdown resolves metadata via the PubMed
MCP tool first, normalizes it into the envelope documented below, writes it
to a JSON file, and passes that file here with --metadata-file.

Input envelope (--metadata-file): a JSON array, one object per paper:
{
  "pmid": "12345",                 # required, identity key (D11)
  "title": "...",                  # required
  "abstract": "..." | null,        # null/absent -> extraction_tier "unavailable"
  "authors": [{"last": "Smith", "first": "Jane", "raw": "Smith Jane"}, ...],
                                    # required, ORDER PRESERVED as given (§3c)
  "journal": "...", "year": "2020", "doi": "..." | null, "pmcid": "..." | null,
  "grants": [{"agency": "...", "grant_id": "...", "raw": "..."}]  # optional,
                                    # PubMed-indexed GrantList entries, if any
}

PMID is the identity key (D11/§3a): dedup is by PMID only. A DOI/title match
against a *different* existing PMID is flagged as an inconsistency, never
silently merged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from lib_atomic import atomic_write_json, pmid_lock
from lib_ids import allocate_citekey
from lib_schema import validate_meta, SchemaError


def _first_title_word(title: str) -> str:
    m = re.search(r"[A-Za-z0-9]+", title or "")
    return m.group(0) if m else "untitled"


def _first_author_lastname(authors: list) -> str:
    if not authors:
        return "anon"
    a = authors[0]
    return a.get("last") or (a.get("raw") or "anon").split()[0]


def _normalize_title(title: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()


def _flag_doi_title_conflicts(library_root: Path, pmid: str, doi: str | None, title: str) -> list[str]:
    warnings = []
    papers_dir = library_root / "papers"
    if not papers_dir.is_dir():
        return warnings
    title_norm = _normalize_title(title)
    for pdir in papers_dir.iterdir():
        if pdir.name == pmid:
            continue
        meta_path = pdir / "meta.json"
        if not meta_path.exists():
            continue
        other = json.loads(meta_path.read_text())
        other_doi = other.get("doi")
        other_title_norm = _normalize_title(other.get("title"))
        other_pmid = other.get("pmid") or pdir.name
        if doi and other_doi and other_doi == doi:
            warnings.append(
                f"inconsistency: pmid {pmid} shares doi {doi!r} with existing pmid "
                f"{other_pmid} — NOT merged, both records kept (D11/§3a)"
            )
            if title_norm and other_title_norm and title_norm != other_title_norm:
                warnings.append(
                    f"metadata mismatch: pmid {pmid} has title {title!r} but existing pmid "
                    f"{other_pmid} with the same doi has title {other.get('title')!r}"
                )
        elif title_norm and other_title_norm and title_norm == other_title_norm and doi and other_doi and other_doi != doi:
            warnings.append(
                f"metadata mismatch: pmid {pmid} shares title {title!r} with existing pmid "
                f"{other_pmid} but the DOIs differ ({doi!r} vs {other_doi!r})"
            )
    return warnings


def add_one(library_root: Path, record: dict) -> dict:
    pmid = str(record["pmid"])
    paper_dir = library_root / "papers" / pmid
    meta_path = paper_dir / "meta.json"

    with pmid_lock(library_root, pmid):
        if meta_path.exists():
            existing = json.loads(meta_path.read_text())
            return {"pmid": pmid, "result": "already_present", "citekey": existing.get("citekey")}

        title = record.get("title") or ""
        authors = record.get("authors") or []
        abstract = record.get("abstract")
        year = record.get("year") or "n.d."

        if not title and not authors:
            raise ValueError(f"no metadata returned for PMID {pmid}")

        citekey = allocate_citekey(
            library_root,
            _first_author_lastname(authors),
            year,
            _first_title_word(title),
        )

        extraction_tier = "abstract" if abstract else "unavailable"
        now = datetime.now(timezone.utc).isoformat()

        meta = {
            "pmid": pmid,
            "citekey": citekey,
            "title": title,
            "doi": record.get("doi"),
            "pmcid": record.get("pmcid"),
            "journal": record.get("journal"),
            "year": year,
            "status": "active",
            "checked_at": now,
            "extraction_tier": extraction_tier,
            "abstract_available": bool(abstract),
        }
        validate_meta(meta)

        raw_bytes = json.dumps(record, sort_keys=True).encode("utf-8")
        raw_hash = hashlib.sha256(raw_bytes).hexdigest()
        raw_dir = paper_dir / "raw" / raw_hash
        raw_dir.mkdir(parents=True, exist_ok=True)
        raw_path = raw_dir / "response.json"
        if not raw_path.exists():
            atomic_write_json(raw_path, record)

        atomic_write_json(meta_path, meta)
        atomic_write_json(paper_dir / "authorship.json", {
            "pmid": pmid,
            "authors": authors,
            "source": "pubmed",
            "raw_order_preserved": True,
        })

        grants = record.get("grants") or []
        atomic_write_json(paper_dir / "funding.json", {
            "pmid": pmid,
            "observations": [
                {"grant": g, "kind": "indexed_funding_association", "source": "pubmed_grantlist"}
                for g in grants
            ] if grants else [],
            "state": "indexed_funding_association" if grants else "not_checked",
        })

        if abstract is None:
            note = "no abstract available — metadata-only record, not fabricated (§3a)"
        else:
            note = None

    warnings = _flag_doi_title_conflicts(library_root, pmid, record.get("doi"), title)
    result = {"pmid": pmid, "result": "added", "citekey": citekey, "extraction_tier": extraction_tier}
    if note:
        result["note"] = note
    if warnings:
        result["warnings"] = warnings
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["add"])
    ap.add_argument("--repo", required=True)
    ap.add_argument("--metadata-file", required=True)
    args = ap.parse_args()

    library_root = Path(args.repo).expanduser().resolve()
    if not library_root.is_dir():
        print(f"error: no library at {library_root}", file=sys.stderr)
        return 1

    records = json.loads(Path(args.metadata_file).read_text())
    if not isinstance(records, list):
        records = [records]

    results = []
    exit_code = 0
    for record in records:
        try:
            results.append(add_one(library_root, record))
        except (SchemaError, KeyError, ValueError) as e:
            results.append({"pmid": record.get("pmid", "?"), "result": "failed", "error": str(e)})
            exit_code = 1

    for r in results:
        line = f"{r['pmid']}: {r['result']}"
        if r.get("citekey"):
            line += f" (citekey={r['citekey']})"
        if r.get("note"):
            line += f" — {r['note']}"
        if r.get("error"):
            line += f" — {r['error']}"
        print(line)
        for w in r.get("warnings", []):
            print(f"  warning: {w}")

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
