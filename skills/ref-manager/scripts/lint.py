#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""`/ref:lint` -- library maintenance lint for paper-repo health.

Read-only checks for incomplete metadata/full-text state, stale status checks,
and repo hygiene signals. This script does not call PubMed or any MCP tool.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _load_json(path: Path) -> dict | list | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _paper_dirs(library_root: Path) -> list[Path]:
    papers_dir = library_root / "papers"
    if not papers_dir.is_dir():
        return []
    return sorted([p for p in papers_dir.iterdir() if p.is_dir()], key=lambda p: p.name)


def _is_true(value: object) -> bool:
    return bool(value)


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def lint(library_root: Path, stale_days: int = 180) -> dict:
    issues: dict[str, list[str]] = {
        "missing_meta": [],
        "missing_title": [],
        "missing_year": [],
        "missing_journal": [],
        "missing_abstract": [],
        "metadata_only": [],
        "abstract_only": [],
        "oa_pending": [],
        "missing_doi": [],
        "missing_current": [],
        "missing_claim_registry": [],
        "stale_retraction_check": [],
        "malformed_meta": [],
    }

    now = datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(days=stale_days)

    for pdir in _paper_dirs(library_root):
        pmid = pdir.name
        meta_path = pdir / "meta.json"
        if not meta_path.exists():
            issues["missing_meta"].append(pmid)
            continue

        meta_obj = _load_json(meta_path)
        if not isinstance(meta_obj, dict):
            issues["malformed_meta"].append(pmid)
            continue
        meta = meta_obj

        if not (meta.get("title") or "").strip():
            issues["missing_title"].append(pmid)
        if not (meta.get("year") or "").strip():
            issues["missing_year"].append(pmid)
        if not (meta.get("journal") or "").strip():
            issues["missing_journal"].append(pmid)
        if not (meta.get("doi") or "").strip():
            issues["missing_doi"].append(pmid)

        full_text = _is_true(meta.get("full_text"))
        abstract_available = _is_true(meta.get("abstract_available"))
        oa_pending = bool(meta.get("oa_location"))

        if not abstract_available:
            issues["missing_abstract"].append(pmid)
        if not full_text and not abstract_available:
            issues["metadata_only"].append(pmid)
        if not full_text and abstract_available and not oa_pending:
            issues["abstract_only"].append(pmid)
        if oa_pending and not full_text:
            issues["oa_pending"].append(pmid)

        if not (pdir / "current.json").exists():
            issues["missing_current"].append(pmid)
        if not (pdir / "claim_registry.json").exists():
            issues["missing_claim_registry"].append(pmid)

        checked_at = _parse_iso(meta.get("checked_at"))
        if checked_at is not None and checked_at.tzinfo is None:
            checked_at = checked_at.replace(tzinfo=timezone.utc)
        if checked_at is not None and checked_at < stale_cutoff:
            issues["stale_retraction_check"].append(pmid)

    index_db = library_root / "index" / "catalog.sqlite"
    catalog_present = index_db.exists()

    summaries = {
        "papers_total": len(_paper_dirs(library_root)),
        "issues_total": sum(len(v) for v in issues.values()),
        "catalog_present": catalog_present,
    }

    recommendations: list[str] = []
    if not catalog_present:
        recommendations.append("run /ref:index --rebuild")
    if issues["metadata_only"] or issues["abstract_only"] or issues["oa_pending"]:
        recommendations.append("run /ref:fetch <pmid...> or /ref:add-fetch <pmid...>")
    if issues["stale_retraction_check"]:
        recommendations.append("run /ref:audit")
    if issues["missing_claim_registry"]:
        recommendations.append("run /ref:extract <pmid...> for papers needing claims")

    return {
        "summary": summaries,
        "issues": issues,
        "recommendations": recommendations,
    }


def _print_human(report: dict) -> None:
    summary = report["summary"]
    print(f"papers_total: {summary['papers_total']}")
    print(f"issues_total: {summary['issues_total']}")
    print(f"catalog_present: {summary['catalog_present']}")

    print("\nissues:")
    for key, pmids in report["issues"].items():
        if pmids:
            print(f"- {key}: {len(pmids)} [{', '.join(pmids[:15])}{' ...' if len(pmids) > 15 else ''}]")
        else:
            print(f"- {key}: 0")

    print("\nrecommended next actions:")
    for action in report["recommendations"]:
        print(f"- {action}")


def _write_snapshot(library_root: Path, report: dict) -> Path:
    snapshot_dir = library_root / "maintenance"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snapshot_path = snapshot_dir / f"{stamp}.json"
    snapshot_path.write_text(json.dumps(report, indent=2) + "\n")
    return snapshot_path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["run"])
    ap.add_argument("--repo", required=True)
    ap.add_argument("--stale-days", type=int, default=180)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--snapshot", action="store_true",
                     help="Write the report to maintenance/<timestamp>.json in the library root.")
    args = ap.parse_args()

    library_root = Path(args.repo).expanduser().resolve()
    if not library_root.is_dir():
        print(f"error: no library at {library_root}", file=sys.stderr)
        return 1

    report = lint(library_root, stale_days=args.stale_days)

    snapshot_path = None
    if args.snapshot:
        snapshot_path = _write_snapshot(library_root, report)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print_human(report)
    if snapshot_path is not None:
        print(f"\nsnapshot written: {snapshot_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
