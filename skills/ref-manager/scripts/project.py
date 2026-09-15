#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""`/ref:project` — projects/<slug>/{project.yaml,papers.yaml} (§3b, D20).

No YAML dependency (D: minimize deps) — these are JSON files with a .yaml
extension per PLAN.md's naming, written/read as JSON. Simple enough not to
need a real YAML lib; revisit if PLAN.md later requires hand-editing.

Membership references a paper once per project; relevance/priority/reading
state live on that membership record, independently of every other
project's membership for the same paper (§3b — this is the phase-1 gate's
"one paper belongs to two projects with independent state" requirement).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from lib_atomic import atomic_write_json
from lib_ids import allocate_slug, check_question_id, SlugError
from lib_schema import validate_project, SchemaError

READING_STATES = ("to_screen", "to_read", "reading", "read")


def _project_dir(library_root: Path, slug: str) -> Path:
    return library_root / "projects" / slug


def _load(path: Path, default):
    return json.loads(path.read_text()) if path.exists() else default


def _paper_source_badge(library_root: Path, pmid: str) -> str:
    paper_dir = library_root / "papers" / pmid
    meta_path = paper_dir / "meta.json"
    if not meta_path.exists():
        return "metadata-only"
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


def _paper_source_counts(library_root: Path, papers: list[dict]) -> dict[str, int]:
    counts = {
        "metadata_only": 0,
        "abstract_only": 0,
        "full_text": 0,
        "pdf_backed": 0,
        "oa_pending": 0,
    }
    for paper in papers:
        badge = _paper_source_badge(library_root, str(paper["pmid"]))
        counts[badge.replace("-", "_")] += 1
    return counts


def create(library_root: Path, slug: str, scope: str | None) -> dict:
    allocate_slug(library_root, "project", slug)  # validates + refuses collision
    pdir = _project_dir(library_root, slug)
    pdir.mkdir(parents=True)
    project = {"slug": slug, "scope": scope, "questions": []}
    validate_project(project)
    atomic_write_json(pdir / "project.yaml", project)
    atomic_write_json(pdir / "papers.yaml", {"papers": []})
    return project


def add_question(library_root: Path, slug: str, qid: str, text: str) -> dict:
    pdir = _project_dir(library_root, slug)
    project_path = pdir / "project.yaml"
    if not project_path.exists():
        raise SlugError(f"project {slug!r} does not exist")
    project = json.loads(project_path.read_text())
    check_question_id(project, qid)  # scoped per-project (§3d)
    project["questions"].append({"id": qid, "text": text})
    validate_project(project)
    atomic_write_json(project_path, project)
    return project


def add_paper(
    library_root: Path, slug: str, pmid: str, relevance: str | None,
    priority: int | None, reading_status: str | None,
) -> dict:
    pdir = _project_dir(library_root, slug)
    papers_path = pdir / "papers.yaml"
    if not papers_path.exists():
        raise SlugError(f"project {slug!r} does not exist")
    if reading_status is not None and reading_status not in READING_STATES:
        raise SchemaError(f"reading_status must be one of {READING_STATES}")

    doc = _load(papers_path, {"papers": []})
    for m in doc["papers"]:
        if m["pmid"] == pmid:
            return m  # already a member; membership references a paper once (§3b)

    membership = {
        "pmid": pmid,
        "relevance": relevance,
        "priority": priority,
        "reading_status": reading_status,
        "why_saved": None,
        "screening": None,
        "added_at": datetime.now(timezone.utc).isoformat(),
    }
    doc["papers"].append(membership)
    atomic_write_json(papers_path, doc)
    return membership


def show(library_root: Path, slug: str) -> dict:
    pdir = _project_dir(library_root, slug)
    project_path = pdir / "project.yaml"
    if not project_path.exists():
        raise SlugError(f"project {slug!r} does not exist")
    papers_doc = _load(pdir / "papers.yaml", {"papers": []})
    papers = papers_doc.get("papers", [])
    reading = {"to_screen": 0, "to_read": 0, "reading": 0, "read": 0}
    for paper in papers:
        status = paper.get("reading_status")
        if status in reading:
            reading[status] += 1
    source = _paper_source_counts(library_root, papers)
    return {
        "project": json.loads(project_path.read_text()),
        "papers": papers_doc,
        "summary": {
            "paper_count": len(papers),
            "reading": reading,
            "source": source,
            "question_count": len(json.loads(project_path.read_text()).get("questions", [])),
        },
    }


def list_projects(library_root: Path) -> list[dict]:
    projects_dir = library_root / "projects"
    out = []
    if projects_dir.is_dir():
        for pdir in sorted(projects_dir.iterdir()):
            p = pdir / "project.yaml"
            if p.exists():
                proj = json.loads(p.read_text())
                papers_path = pdir / "papers.yaml"
                papers_doc = _load(papers_path, {"papers": []}) if papers_path.exists() else {"papers": []}
                papers = papers_doc.get("papers", [])
                reading = {"to_screen": 0, "to_read": 0, "reading": 0, "read": 0}
                for paper in papers:
                    status = paper.get("reading_status")
                    if status in reading:
                        reading[status] += 1
                source = _paper_source_counts(library_root, papers)
                out.append({
                    "slug": proj["slug"],
                    "scope": proj.get("scope"),
                    "questions": len(proj["questions"]),
                    "papers": len(papers),
                    "reading": reading,
                    "source": source,
                })
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["create", "add-question", "add-paper", "show", "list"])
    ap.add_argument("--repo", required=True)
    ap.add_argument("--slug")
    ap.add_argument("--scope")
    ap.add_argument("--question-id")
    ap.add_argument("--text")
    ap.add_argument("--pmid")
    ap.add_argument("--relevance")
    ap.add_argument("--priority", type=int)
    ap.add_argument("--reading-status")
    args = ap.parse_args()

    library_root = Path(args.repo).expanduser().resolve()
    if not library_root.is_dir():
        print(f"error: no library at {library_root}", file=sys.stderr)
        return 1

    try:
        if args.action == "create":
            result = create(library_root, args.slug, args.scope)
        elif args.action == "add-question":
            result = add_question(library_root, args.slug, args.question_id, args.text)
        elif args.action == "add-paper":
            result = add_paper(library_root, args.slug, args.pmid, args.relevance, args.priority, args.reading_status)
        elif args.action == "show":
            result = show(library_root, args.slug)
        else:
            result = list_projects(library_root)
    except (SlugError, SchemaError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
