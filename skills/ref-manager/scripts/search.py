#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""`/ref:search` — §5 retrieval, phase-2 subset.

No full-text conversion exists until phase 3 and no passage FTS index is
populated until then either (catalog.py's passages_fts stays an empty
stub) — so "evidence" search here is title/abstract/journal only. Say so
plainly rather than pretending passage search exists.

--scope evidence   title/abstract/journal (raw/<hash>/response.json's
                    'abstract', since meta.json never stores abstract text
                    itself — only an abstract_available flag, §3a).
--scope notes      papers/<pmid>/notes.md + project membership relevance/
                    why_saved text (personal content, never evidence).
--scope all        both, each result tagged with its kind so a personal
                    note can never be mistaken for a published finding (§5).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _paper_abstract(library_root: Path, pmid: str) -> str | None:
    raw_dir = library_root / "papers" / pmid / "raw"
    if not raw_dir.is_dir():
        return None
    for d in sorted(raw_dir.iterdir()):
        resp = d / "response.json"
        if resp.exists():
            data = json.loads(resp.read_text())
            return data.get("abstract")
    return None


def _evidence_hits(library_root: Path, query: str) -> list[dict]:
    q = query.lower()
    hits = []
    papers_dir = library_root / "papers"
    if not papers_dir.is_dir():
        return hits
    for pdir in sorted(papers_dir.iterdir()):
        meta_path = pdir / "meta.json"
        if not meta_path.exists():
            continue
        meta = json.loads(meta_path.read_text())
        title = meta.get("title") or ""
        journal = meta.get("journal") or ""
        abstract = _paper_abstract(library_root, pdir.name) or ""
        haystack = f"{title}\n{journal}\n{abstract}".lower()
        if q in haystack:
            snippet_source = title if q in title.lower() else (abstract or journal)
            hits.append({
                "kind": "evidence",
                "pmid": pdir.name,
                "citekey": meta.get("citekey"),
                "field": "title" if q in title.lower() else ("abstract" if q in abstract.lower() else "journal"),
                "snippet": snippet_source[:240],
            })
    return hits


def _notes_hits(library_root: Path, query: str) -> list[dict]:
    q = query.lower()
    hits = []
    papers_dir = library_root / "papers"
    if papers_dir.is_dir():
        for pdir in sorted(papers_dir.iterdir()):
            notes_path = pdir / "notes.md"
            if notes_path.exists():
                text = notes_path.read_text()
                if q in text.lower():
                    hits.append({
                        "kind": "personal_note",
                        "pmid": pdir.name,
                        "snippet": text.strip()[:240],
                    })
    projects_dir = library_root / "projects"
    if projects_dir.is_dir():
        for pdir in sorted(projects_dir.iterdir()):
            papers_path = pdir / "papers.yaml"
            if not papers_path.exists():
                continue
            doc = json.loads(papers_path.read_text())
            for m in doc.get("papers", []):
                for field in ("relevance", "why_saved"):
                    val = m.get(field)
                    if val and q in val.lower():
                        hits.append({
                            "kind": "project_relevance",
                            "pmid": m["pmid"],
                            "project": pdir.name,
                            "field": field,
                            "snippet": val[:240],
                        })
    return hits


def run(library_root: Path, scope: str, query: str) -> list[dict]:
    if scope == "evidence":
        return _evidence_hits(library_root, query)
    if scope == "notes":
        return _notes_hits(library_root, query)
    if scope == "all":
        return _evidence_hits(library_root, query) + _notes_hits(library_root, query)
    raise ValueError(f"unknown scope {scope!r}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--scope", default="evidence", choices=["evidence", "notes", "all"])
    ap.add_argument("--q", required=True)
    args = ap.parse_args()

    library_root = Path(args.repo).expanduser().resolve()
    if not library_root.is_dir():
        print(f"error: no library at {library_root}", file=sys.stderr)
        return 1

    hits = run(library_root, args.scope, args.q)
    print(json.dumps({"query": args.q, "scope": args.scope, "results": hits}, indent=2))
    if not hits:
        print("(no evidence/passage index exists yet before phase 3 — this searched title/abstract/notes only)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
