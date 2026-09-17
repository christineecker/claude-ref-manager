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

import catalog
from init_repo import CONFIG_PATH, load_config
import project as project_mod
from lib_inventory import rows as inventory_rows


def _print_recent_papers(rows: list[dict], limit: int = 5) -> None:
    recent = sorted(rows, key=lambda r: r.get("checked_at") or "", reverse=True)[:limit]
    print(f"recent papers: {len(recent)}")
    for row in recent:
        pmid = row.get("pmid")
        source_badge = row.get("source_badge") or "unknown"
        if source_badge in {"pdf-backed", "full-text"} and row.get("figures_with_image"):
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
    for row in rows:
        tier = row.get("extraction_tier") or "unavailable"
        counts[tier] = counts.get(tier, 0) + 1
    return counts


def _print_tier_breakdown(counts: dict) -> None:
    print("papers by extraction tier:")
    for tier in ("full", "abstract", "unavailable"):
        print(f"  {tier}: {counts.get(tier, 0)}")


def _source_counts(rows: list[dict]) -> dict:
    counts = {
        "metadata_only": 0,
        "abstract_only": 0,
        "full_text": 0,
        "pdf_backed": 0,
        "oa_pending": 0,
    }
    for row in rows:
        badge = row.get("source_badge")
        if badge is None:  # missing/malformed meta.json -- lib_inventory.rows() still
            continue       # emits a row for it, but it has no source state to classify
        counts[badge.replace("-", "_")] += 1
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
    catalog_stale: bool = False,
) -> tuple[str, list[str], list[str]]:
    """One-pass health check derived from the same counts already printed
    below -- no separate recommendation engine (UX_BACKLOG.md #2)."""
    attention = []
    actions = []

    n_papers = len(rows)
    not_indexed = n_papers > 0 and (not catalog_built or n_indexed < n_papers or catalog_stale)
    missing_metadata = sum(1 for m in rows if not m.get("title"))
    needs_full_text = source_counts["metadata_only"] + source_counts["abstract_only"] + source_counts["oa_pending"]
    no_active_project = n_projects == 0 and n_papers > 0

    if not_indexed:
        if catalog_built and n_indexed >= n_papers:
            attention.append("catalog out of date (papers changed since last rebuild)")
        else:
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

    rows = inventory_rows(library_root)
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
    source_counts = _source_counts(rows)

    catalog_stale = catalog.is_stale(library_root)
    state, attention, actions = _health(rows, source_counts, n_projects, catalog_built, n_indexed, catalog_stale)

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
        _print_recent_papers(rows, limit=15)
    else:
        _print_project_overview(library_root)
        _print_recent_papers(rows, limit=3)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
