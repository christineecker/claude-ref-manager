#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""`/ref:related <pmid>` -- backward + forward snowballing from a known paper
(PLAN.md §1: "backward (reference list from full text) + forward
(find_related_articles, ELink cited-by); stays within D11").

This script never calls PubMed itself. Forward candidates come from the
calling command markdown invoking mcp__claude_ai_PubMed__find_related_articles
and handing the normalized result here (same command-markdown-calls-MCP-
then-hands-JSON-to-script split as add.py/fetch.py). Backward candidates
are extracted locally from already-committed full text.

**Honesty note on "ELint cited-by"**: the live PubMed MCP server's
find_related_articles tool exposes link_type values pubmed_pubmed (default:
word-weighted title/abstract/MeSH similarity -- explicitly NOT citation-
based, per the tool's own description), pubmed_pmc, pubmed_gene,
pubmed_protein, pubmed_nucleotide. There is no "cited-by" link_type on this
tool. So "forward" candidates recorded here are computational-similarity
results, not true citation-graph cited-by data, unless/until a real ELink
cited-by capability is wired in some other way. The `method` field on every
forward candidate always names exactly which link_type produced it, so this
distinction is never hidden. This mirrors D25's "cited-by counts are dated
observations from a named source, never THE citation count" discipline even
though this script does not implement D25 itself (that is /ref:audit
--citations, a later phase).

**Honesty note on backward references**: converted full text's References
section is free-text citation strings in whatever format the source used
(JATS, HTML, or plain-text extraction, phase 3). This script does NOT
attempt to parse a citation string into a resolved PMID -- that needs either
embedded identifiers (rare in reference-list text) or a further PubMed
citation-lookup step the calling agent can optionally do per-candidate.
Backward candidates are therefore raw text by default, `resolved: false`,
with an optional `pmid` field the calling agent can attach after a separate
lookup.

related.json row (papers/<pmid>/related.json, a JSON array):
{"candidate": "<pmid or raw citation text>", "resolved": bool,
 "direction": "backward"|"forward", "method": "reference_list"|
 "find_related_articles:<link_type>", "query": {...}, "retrieved_at": "...",
 "already_in_library": bool}

Upsert key: (direction, method, candidate) -- calling /ref:related twice
updates retrieved_at on unchanged candidates rather than duplicating rows.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from lib_atomic import atomic_write_json, pmid_lock


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _related_path(library_root: Path, pmid: str) -> Path:
    return library_root / "papers" / pmid / "related.json"


def _load(library_root: Path, pmid: str) -> list[dict]:
    p = _related_path(library_root, pmid)
    if p.exists():
        return json.loads(p.read_text())
    return []


def _already_in_library(library_root: Path, candidate: str, resolved: bool) -> bool:
    if not resolved:
        return False
    return (library_root / "papers" / candidate / "meta.json").exists()


def _upsert(rows: list[dict], new_rows: list[dict]) -> list[dict]:
    by_key = {(r["direction"], r["method"], r["candidate"]): r for r in rows}
    for nr in new_rows:
        key = (nr["direction"], nr["method"], nr["candidate"])
        by_key[key] = nr  # replace wholesale -- retrieved_at etc. refresh on re-run
    return list(by_key.values())


def backward(library_root: Path, pmid: str) -> dict:
    """Extract raw reference-list candidates from this paper's committed
    full text, if any. Returns a report dict; never raises on "nothing
    found" -- that's a legitimate, explicitly-stated outcome (§8 gate:
    "missing edges ... are not presented as proof of novelty")."""
    paper_dir = library_root / "papers" / pmid
    current_path = paper_dir / "current.json"
    if not current_path.exists():
        return {"available": False, "reason": "no committed full-text version for this PMID (run /ref:fetch or /ref:attach first)"}

    version_id = json.loads(current_path.read_text())["version"]
    source_md = paper_dir / "versions" / version_id / "source.md"
    if not source_md.exists():
        return {"available": False, "reason": f"version {version_id} has no source.md"}

    text = source_md.read_text()
    m = re.search(r"^#{1,3}\s*References\s*$", text, re.MULTILINE | re.IGNORECASE)
    if not m:
        return {"available": False, "reason": "no References/Bibliography heading found in converted full text"}

    rest = text[m.end():]
    next_heading = re.search(r"^#{1,3}\s+\S", rest, re.MULTILINE)
    refs_block = rest[: next_heading.start()] if next_heading else rest

    candidates = []
    for line in refs_block.splitlines():
        line = line.strip()
        line = re.sub(r"^(\d+[.)]|[-*])\s*", "", line)
        if len(line) >= 15:  # skip stray blank/short lines, not a real citation
            candidates.append(line)

    if not candidates:
        return {"available": True, "candidates": [], "note": "References heading found but no citation lines extracted"}

    now = _now()
    rows = [
        {
            "candidate": c, "resolved": False, "direction": "backward",
            "method": "reference_list", "query": {"source_version": version_id},
            "retrieved_at": now, "already_in_library": False,
        }
        for c in candidates
    ]
    return {"available": True, "candidates": rows, "count": len(rows)}


def forward(library_root: Path, pmid: str, link_type: str, result_pmids: list[str], query_params: dict) -> dict:
    now = _now()
    rows = []
    for cand in result_pmids:
        rows.append({
            "candidate": cand, "resolved": True, "direction": "forward",
            "method": f"find_related_articles:{link_type}",
            "query": {"link_type": link_type, "source_pmid": pmid, **query_params},
            "retrieved_at": now,
            "already_in_library": _already_in_library(library_root, cand, True),
        })
    return {
        "count": len(rows), "rows": rows,
        "zero_results": len(rows) == 0,
        "note": None if rows else f"zero results from find_related_articles (link_type={link_type}) -- not evidence of no related work, just this query's result",
    }


def persist(library_root: Path, pmid: str, new_rows: list[dict]) -> dict:
    with pmid_lock(library_root, pmid):
        rows = _load(library_root, pmid)
        merged = _upsert(rows, new_rows)
        atomic_write_json(_related_path(library_root, pmid), merged)
    already = sum(1 for r in merged if r.get("already_in_library"))
    return {"total_candidates": len(merged), "already_in_library": already, "not_yet_added": len(merged) - already}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["backward", "forward", "show"])
    ap.add_argument("--repo", required=True)
    ap.add_argument("--pmid", required=True)
    ap.add_argument("--link-type", default="pubmed_pubmed")
    ap.add_argument("--results-file", help="JSON array of forward-related PMIDs")
    ap.add_argument("--max-results")
    args = ap.parse_args()

    library_root = Path(args.repo).expanduser().resolve()
    if not library_root.is_dir():
        print(f"error: no library at {library_root}", file=sys.stderr)
        return 1

    if args.action == "backward":
        report = backward(library_root, args.pmid)
        if report["available"] and report.get("candidates"):
            for r in report["candidates"]:
                r["already_in_library"] = _already_in_library(library_root, r["candidate"], r["resolved"])
            summary = persist(library_root, args.pmid, report["candidates"])
            report["persisted"] = summary
        print(json.dumps(report, indent=2))
        return 0

    if args.action == "forward":
        if not args.results_file:
            print("error: --results-file required for forward", file=sys.stderr)
            return 1
        result_pmids = json.loads(Path(args.results_file).read_text())
        query_params = {"max_results": args.max_results} if args.max_results else {}
        report = forward(library_root, args.pmid, args.link_type, result_pmids, query_params)
        summary = persist(library_root, args.pmid, report["rows"])
        report["persisted"] = summary
        print(json.dumps(report, indent=2))
        return 0

    # show
    rows = _load(library_root, args.pmid)
    print(json.dumps(rows, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
