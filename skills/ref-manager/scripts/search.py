#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""`/ref:search` — §5 retrieval, phase-2 subset.

No full-text conversion exists until phase 3 and no passage FTS index is
populated until then either (catalog.py's passages_fts stays an empty
stub) — so "evidence" search here is still metadata-only, but it now checks
more of the structured library surface than just title/abstract/journal.

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
    meta_path = paper_dir / "meta.json"
    if not meta_path.exists():
        return "missing_record"
    meta = json.loads(meta_path.read_text())
    raw_dir = paper_dir / "raw"
    has_pdf = raw_dir.is_dir() and any((p / "source.pdf").exists() for p in raw_dir.iterdir() if p.is_dir())
    if has_pdf:
        return "pdf-backed"
    if meta.get("full_text"):
        return "full-text"
    if meta.get("oa_location"):
        return "oa-pending"
    if meta.get("abstract_available"):
        return "abstract-only"
    return "metadata-only"


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
        authors = _paper_authors(library_root, pdir.name)
        funding = _paper_funding(library_root, pdir.name)
        title = meta.get("title") or ""
        journal = meta.get("journal") or ""
        abstract = _paper_abstract(library_root, pdir.name) or ""
        haystack = "\n".join([
            title,
            journal,
            meta.get("doi") or "",
            meta.get("pmcid") or "",
            meta.get("citekey") or "",
            abstract,
            "\n".join(a.get("raw") or f"{a.get('last', '')} {a.get('first', '')}".strip() for a in authors),
            "\n".join(
                " ".join(str(v) for v in (obs.get("funder"), obs.get("award_number"), obs.get("text"), obs.get("locator")) if v)
                for obs in funding
            ),
        ]).lower()
        if q in haystack:
            if q in title.lower():
                snippet_source = title
                field = "title"
            elif q in (meta.get("doi") or "").lower():
                snippet_source = meta.get("doi") or ""
                field = "doi"
            elif q in (meta.get("pmcid") or "").lower():
                snippet_source = meta.get("pmcid") or ""
                field = "pmcid"
            elif q in (meta.get("citekey") or "").lower():
                snippet_source = meta.get("citekey") or ""
                field = "citekey"
            elif any(q in (a.get("raw") or f"{a.get('last', '')} {a.get('first', '')}".strip()).lower() for a in authors):
                snippet_source = next((a.get("raw") or f"{a.get('last', '')} {a.get('first', '')}".strip() for a in authors if q in (a.get("raw") or f"{a.get('last', '')} {a.get('first', '')}".strip()).lower()), abstract or journal)
                field = "author"
            elif any(
                q in " ".join(str(v) for v in (obs.get("funder"), obs.get("award_number"), obs.get("text"), obs.get("locator")) if v).lower()
                for obs in funding
            ):
                first = next(
                    (obs for obs in funding if q in " ".join(str(v) for v in (obs.get("funder"), obs.get("award_number"), obs.get("text"), obs.get("locator")) if v).lower()),
                    {},
                )
                snippet_source = " ".join(str(v) for v in (first.get("funder"), first.get("award_number"), first.get("text"), first.get("locator")) if v)
                field = "grant"
            else:
                snippet_source = abstract or journal
                field = "abstract" if q in abstract.lower() else "journal"
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
        print("(no evidence/passage index exists yet before phase 3 — this searched title/abstract/notes only)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
