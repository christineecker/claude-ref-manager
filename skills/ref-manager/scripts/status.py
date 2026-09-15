#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""`/ref:status` — report the configured library, counts, and recent papers."""
from __future__ import annotations

import argparse
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


def _tier_counts(rows: list[dict]) -> dict:
    counts = {"abstract": 0, "full": 0, "unavailable": 0}
    for meta in rows:
        tier = meta.get("extraction_tier") or "unavailable"
        counts[tier] = counts.get(tier, 0) + 1
    return counts


def _print_tier_breakdown(counts: dict) -> None:
    print("papers by extraction tier:")
    for tier in ("full", "abstract", "unavailable"):
        print(f"  {tier}: {counts.get(tier, 0)}")


def _source_counts(library_root: Path, rows: list[dict]) -> dict:
    counts = {
        "metadata_only": 0,
        "abstract_only": 0,
        "full_text": 0,
        "pdf_backed": 0,
        "oa_pending": 0,
    }
    for meta in rows:
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
    return counts


def _print_source_completeness(counts: dict) -> None:
    print("papers by source/completeness:")
    for key in ("full_text", "pdf_backed", "oa_pending", "abstract_only", "metadata_only"):
        print(f"  {key}: {counts.get(key, 0)}")


def _health(
    rows: list[dict],
    source_counts: dict,
    n_projects: int,
    catalog_built: bool,
    n_indexed: int,
) -> tuple[str, list[str], list[str]]:
    """One-pass health check derived from the same counts already printed
    below -- no separate recommendation engine (UX_BACKLOG.md #2)."""
    attention = []
    actions = []

    n_papers = len(rows)
    not_indexed = n_papers > 0 and (not catalog_built or n_indexed < n_papers)
    missing_metadata = sum(1 for m in rows if not m.get("title"))
    needs_full_text = source_counts["metadata_only"] + source_counts["abstract_only"] + source_counts["oa_pending"]
    no_active_project = n_projects == 0 and n_papers > 0

    if not_indexed:
        attention.append(f"catalog not fully indexed ({n_indexed}/{n_papers} papers)")
        actions.append("/ref:index --rebuild")
    if missing_metadata:
        attention.append(f"{missing_metadata} paper(s) missing title/metadata")
        actions.append("check papers/<pmid>/meta.json against the PubMed record (no auto re-fetch yet)")
    if needs_full_text:
        attention.append(f"{needs_full_text} paper(s) without full text (abstract-only or metadata-only)")
        actions.append("/ref:fetch to acquire full text for open-access papers")
    if no_active_project:
        attention.append("no active project")
        actions.append("/ref:project create <slug> to start organizing papers")

    if n_papers == 0:
        attention.append("no papers added yet")
        actions.append("/ref:add <pmid> to add your first paper")
        state = "empty"
    elif not_indexed:
        state = "not indexed"
    elif missing_metadata:
        state = "needs metadata"
    elif needs_full_text:
        state = "needs full text"
    elif no_active_project:
        state = "no active project"
    else:
        state = "healthy"

    return state, attention, actions[:3]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--verbosity", choices=["quick", "normal", "verbose"], default="normal",
        help="quick: health header only. normal (default): + breakdowns and a few recent papers. "
             "verbose: + the full project list and more recent papers.",
    )
    args = ap.parse_args()

    config = load_config()
    if config is None:
        print(
            f"error: no library configured ({CONFIG_PATH} not found). "
            "Run /ref:init <path> first.",
            file=sys.stderr,
        )
        return 1

    library_root = Path(config["library_root"])
    if not library_root.is_dir():
        print(
            f"error: configured library_root does not exist on disk ({library_root}). "
            f"Restore it, or run /ref:init <path> --force to point at a different location.",
            file=sys.stderr,
        )
        return 1

    rows = _paper_meta_rows(library_root)
    n_papers = len(rows)

    db_path = library_root / "index" / "catalog.sqlite"
    catalog_built = db_path.exists()
    n_indexed = 0
    if catalog_built:
        conn = sqlite3.connect(db_path)
        (n_indexed,) = conn.execute("SELECT COUNT(*) FROM papers").fetchone()
        conn.close()

    n_projects = sum(1 for p in (library_root / "projects").iterdir() if p.is_dir()) if (library_root / "projects").is_dir() else 0
    tier_counts = _tier_counts(rows)
    source_counts = _source_counts(library_root, rows)

    state, attention, actions = _health(rows, source_counts, n_projects, catalog_built, n_indexed)

    print(f"status: {state}")
    print(f"library: {library_root}")
    print(f"papers: {n_papers} ({n_indexed} indexed)  projects: {n_projects}")
    print()

    if attention:
        print("needs attention:")
        for item in attention:
            print(f"  - {item}")
        print()
    if actions:
        print("suggested next actions:")
        for action in actions:
            print(f"  - {action}")
        print()

    if args.verbosity == "quick":
        return 0

    _print_tier_breakdown(tier_counts)
    _print_source_completeness(source_counts)
    if args.verbosity == "verbose":
        _print_project_overview(library_root, limit=n_projects or 1)
        _print_recent_papers(library_root, limit=15)
    else:
        _print_project_overview(library_root)
        _print_recent_papers(library_root, limit=3)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
