#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""`/ref:search` — substring search over the library's structured surface.

Metadata-level only (title/abstract/ids/authors/funding, notes, project
relevance, saved queries); ranked full-text retrieval over claims and
passages is `ask_retrieve.py`.

-scope evidence   title/abstract/journal/doi/pmcid/citekey/authors (raw/<hash>/
                    response.json's 'abstract', since meta.json never stores
                    abstract text itself — only an abstract_available flag, §3a).
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

from lib_atomic import read_json
from lib_selector import source_badge


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


def _paper_authors(library_root: Path, pmid: str) -> list[dict]:
    path = library_root / "papers" / pmid / "authorship.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text()).get("authors", [])
    except (OSError, ValueError):
        return []


def _paper_funding(library_root: Path, pmid: str) -> list[dict]:
    path = library_root / "papers" / pmid / "funding.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text()).get("observations", [])
    except (OSError, ValueError):
        return []


def _paper_lifecycle(library_root: Path, pmid: str) -> str:
    paper_dir = library_root / "papers" / pmid
    meta = read_json(paper_dir / "meta.json")
    return source_badge(paper_dir, meta) if meta else "missing_record"


def _author_text(a: dict) -> str:
    return a.get("raw") or f"{a.get('last', '')} {a.get('first', '')}".strip()


def _funding_text(obs: dict) -> str:
    return " ".join(str(v) for v in (obs.get("funder"), obs.get("award_number"), obs.get("text"), obs.get("locator")) if v)


def _query_matches(library_root: Path, query: str) -> list[dict]:
    q = query.lower()
    hits = []
    queries_dir = library_root / "queries"
    if not queries_dir.is_dir():
        return hits
    for path in sorted(queries_dir.glob("*.yaml")):
        try:
            doc = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        slug = doc.get("slug") or path.stem
        for run in doc.get("runs", []):
            haystack = "\n".join([
                slug,
                run.get("query") or "",
                run.get("source") or "",
                run.get("run_id") or "",
                " ".join(run.get("pmids") or []),
            ]).lower()
            if q in haystack:
                hits.append({
                    "kind": "saved_query",
                    "slug": slug,
                    "run_id": run.get("run_id"),
                    "source": run.get("source"),
                    "snippet": (run.get("query") or slug)[:240],
                    "lifecycle": "query",
                })
                break
    return hits


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
        abstract = _paper_abstract(library_root, pdir.name) or ""
        journal = meta.get("journal") or ""
        # (field, candidate strings) in the order a hit is attributed
        fields = [
            ("title", [meta.get("title") or ""]),
            ("doi", [meta.get("doi") or ""]),
            ("pmcid", [meta.get("pmcid") or ""]),
            ("citekey", [meta.get("citekey") or ""]),
            ("author", [_author_text(a) for a in _paper_authors(library_root, pdir.name)]),
            ("grant", [_funding_text(o) for o in _paper_funding(library_root, pdir.name)]),
            ("abstract", [abstract]),
            ("journal", [journal]),
        ]
        match = next(
            ((field, text) for field, texts in fields for text in texts if text and q in text.lower()),
            None,
        )
        if match:
            field, snippet_source = match
            hits.append({
                "kind": "evidence",
                "pmid": pdir.name,
                "citekey": meta.get("citekey"),
                "field": field,
                "snippet": snippet_source[:240],
                "source_kind": "metadata",
                "lifecycle": _paper_lifecycle(library_root, pdir.name),
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
                        "lifecycle": _paper_lifecycle(library_root, pdir.name),
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
                            "lifecycle": _paper_lifecycle(library_root, m["pmid"]),
                        })
    return hits


def run(library_root: Path, scope: str, query: str) -> list[dict]:
    if scope == "evidence":
        return _evidence_hits(library_root, query)
    if scope == "notes":
        return _notes_hits(library_root, query)
    if scope == "all":
        return _evidence_hits(library_root, query) + _notes_hits(library_root, query) + _query_matches(library_root, query)
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
        print("(no matches; this searches metadata, notes and saved queries -- use /ref:ask for full-text retrieval)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
