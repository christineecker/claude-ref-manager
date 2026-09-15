#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""`/ref:status` — report the configured library, counts, and recent papers."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

from init_repo import CONFIG_PATH, load_config
import project as project_mod
from lib_selector import recent


def _load_meta(path: Path) -> dict:
    return json.loads(path.read_text())


def _current_version(paper_dir: Path) -> str | None:
    current_path = paper_dir / "current.json"
    if not current_path.exists():
        return None
    try:
        return json.loads(current_path.read_text()).get("version")
    except (OSError, ValueError, TypeError):
        return None


def _paper_has_figures(paper_dir: Path) -> bool:
    version = _current_version(paper_dir)
    if not version:
        return False
    figures_path = paper_dir / "versions" / version / "figures.json"
    if not figures_path.exists():
        return False
    try:
        figures = json.loads(figures_path.read_text())
    except (OSError, ValueError, TypeError):
        return False
    return any(fig.get("asset_available") for fig in figures if isinstance(fig, dict))


def _paper_meta_rows(library_root: Path) -> list[dict]:
    papers_dir = library_root / "papers"
    if not papers_dir.is_dir():
        return []
    rows = []
    for pdir in sorted(papers_dir.iterdir()):
        meta_path = pdir / "meta.json"
        if not meta_path.exists():
            continue
        meta = _load_meta(meta_path)
        meta["pmid"] = pdir.name
        rows.append(meta)
    return rows


def _print_recent_papers(library_root: Path, limit: int = 5) -> None:
    rows = recent(library_root, limit=limit)
    print(f"recent papers: {len(rows)}")
    for row in rows:
        pmid = row.get("pmid")
        paper_dir = library_root / "papers" / pmid
        meta = _load_meta(paper_dir / "meta.json") if (paper_dir / "meta.json").exists() else {}
        source_badge = "metadata-only"
        if any((p / "source.pdf").exists() for p in (paper_dir / "raw").iterdir() if p.is_dir()) if (paper_dir / "raw").is_dir() else False:
            source_badge = "pdf-backed"
        elif meta.get("full_text"):
            source_badge = "full-text"
        elif meta.get("oa_location"):
            source_badge = "oa-pending"
        elif meta.get("abstract_available"):
            source_badge = "abstract-only"

        if source_badge in {"pdf-backed", "full-text"} and _paper_has_figures(paper_dir):
            source_badge += "+figures"

        title = row.get("title") or "(untitled)"
        citekey = row.get("citekey") or "n/a"
        year = row.get("year") or "n.d."
        checked_at = row.get("checked_at") or "unknown"
        print(f"  - {pmid}: [{source_badge}] {title} ({citekey}, {year}) [{checked_at}]")


def _print_project_overview(library_root: Path, limit: int = 5) -> None:
    projects = project_mod.list_projects(library_root)
    print(f"projects with questions: {len(projects)}")
    for proj in projects[:limit]:
        slug = proj.get("slug") or "unknown"
        scope = proj.get("scope") or "(no scope)"
        papers_path = library_root / "projects" / slug / "papers.yaml"
        paper_count = 0
        reading_counts = {"to_screen": 0, "to_read": 0, "reading": 0, "read": 0}
        if papers_path.exists():
            try:
                doc = json.loads(papers_path.read_text())
            except (OSError, ValueError):
                doc = {"papers": []}
            papers = doc.get("papers", [])
            paper_count = len(papers)
            for paper in papers:
                status = paper.get("reading_status")
                if status in reading_counts:
                    reading_counts[status] += 1
        question_count = int(proj.get("questions") or 0)
        print(
            f"  - {slug}: {paper_count} papers, {question_count} questions, "
            f"scope={scope}, read={reading_counts['read']}, reading={reading_counts['reading']}, "
            f"to_read={reading_counts['to_read']}, to_screen={reading_counts['to_screen']}"
        )


def _print_tier_breakdown(library_root: Path) -> None:
    counts = {"abstract": 0, "full": 0, "unavailable": 0}
    for meta in _paper_meta_rows(library_root):
        tier = meta.get("extraction_tier") or "unavailable"
        counts[tier] = counts.get(tier, 0) + 1
    print("papers by extraction tier:")
    for tier in ("full", "abstract", "unavailable"):
        print(f"  {tier}: {counts.get(tier, 0)}")


def _print_source_completeness(library_root: Path) -> None:
    counts = {
        "metadata_only": 0,
        "abstract_only": 0,
        "full_text": 0,
        "pdf_backed": 0,
        "oa_pending": 0,
    }
    for meta in _paper_meta_rows(library_root):
        paper_dir = library_root / "papers" / meta["pmid"]
        has_pdf = False
        raw_dir = paper_dir / "raw"
        if raw_dir.is_dir():
            has_pdf = any((p / "source.pdf").exists() for p in raw_dir.iterdir() if p.is_dir())
        has_oa = bool(meta.get("oa_location"))
        full_text = bool(meta.get("full_text"))
        abstract_available = bool(meta.get("abstract_available"))

        if has_pdf:
            counts["pdf_backed"] += 1
        elif full_text:
            counts["full_text"] += 1
        elif has_oa:
            counts["oa_pending"] += 1
        elif abstract_available:
            counts["abstract_only"] += 1
        else:
            counts["metadata_only"] += 1

    print("papers by source/completeness:")
    for key in ("full_text", "pdf_backed", "oa_pending", "abstract_only", "metadata_only"):
        print(f"  {key}: {counts.get(key, 0)}")


def main() -> int:
    config = load_config()
    if config is None:
        print(
            f"error: no library configured ({CONFIG_PATH} not found). "
            "Run /ref:init <path> first.",
            file=sys.stderr,
        )
        return 1

    library_root = Path(config["library_root"])
    print(f"library: {library_root}")
    if not library_root.is_dir():
        print("error: configured library_root does not exist on disk", file=sys.stderr)
        return 1

    db_path = library_root / "index" / "catalog.sqlite"
    if db_path.exists():
        conn = sqlite3.connect(db_path)
        (n_papers,) = conn.execute("SELECT COUNT(*) FROM papers").fetchone()
        print(f"papers indexed: {n_papers}")
        conn.close()
    else:
        print("catalog: not built yet (run /ref:index --rebuild)")

    n_projects = sum(1 for p in (library_root / "projects").iterdir() if p.is_dir()) if (library_root / "projects").is_dir() else 0
    print(f"projects: {n_projects}")
    _print_tier_breakdown(library_root)
    _print_source_completeness(library_root)
    _print_project_overview(library_root)
    _print_recent_papers(library_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
