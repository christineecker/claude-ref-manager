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
from datetime import datetime, timezone
from pathlib import Path

import catalog
from lib_inventory import LINT_BUCKETS, rows as inventory_rows


def lint(library_root: Path, stale_days: int = 180) -> dict:
    issues: dict[str, list[str]] = {bucket: [] for bucket in LINT_BUCKETS}

    paper_rows = inventory_rows(library_root, stale_days=stale_days)
    for row in paper_rows:
        for flag in row["lint_flags"]:
            issues[flag].append(row["pmid"])

    catalog_present = catalog.catalog_info(library_root) is not None
    catalog_stale = catalog.is_stale(library_root)

    summaries = {
        "papers_total": len(paper_rows),
        "issues_total": sum(len(v) for v in issues.values()),
        "catalog_present": catalog_present,
        "catalog_stale": catalog_stale,
    }

    recommendations: list[str] = []
    if catalog_stale:
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
    print(f"catalog_stale: {summary['catalog_stale']}")

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


def _list_snapshots(library_root: Path) -> list[Path]:
    """`maintenance/*.json` sorted by filename -- `_write_snapshot()` names
    them `<UTC-timestamp>.json`, so filename order is timestamp order."""
    snapshot_dir = library_root / "maintenance"
    if not snapshot_dir.is_dir():
        return []
    return sorted(snapshot_dir.glob("*.json"))


def _resolve_diff_snapshot(library_root: Path, snapshot_arg: str | None) -> Path:
    """Resolve `--diff [snapshot]`'s snapshot argument: an explicit filename
    or stem under `maintenance/`, or (when omitted) the most recent existing
    snapshot -- i.e. the previous one relative to the report being computed
    now (§8: "vs a snapshot (default: previous)")."""
    snapshots = _list_snapshots(library_root)
    if snapshot_arg is None:
        if not snapshots:
            raise ValueError("no snapshots found under maintenance/ to diff against "
                              "(run /ref:lint --snapshot first)")
        return snapshots[-1]

    candidate = Path(snapshot_arg)
    candidates = [candidate] if candidate.is_absolute() else [
        library_root / "maintenance" / snapshot_arg,
        library_root / "maintenance" / f"{snapshot_arg}.json",
        candidate,
    ]
    for c in candidates:
        if c.is_file():
            return c
    raise ValueError(f"snapshot not found: {snapshot_arg!r} (looked under {library_root / 'maintenance'})")


def diff_report(library_root: Path, report: dict, snapshot_arg: str | None) -> dict:
    """Per-bucket added/removed PMIDs between `report` (the just-computed
    live report) and a prior snapshot (§8: `lint.py run --diff [snapshot]`).
    Returns `{"against": <snapshot stem>, "buckets": {bucket: {"added": [...], "removed": [...]}}}`,
    only including buckets with an actual change."""
    snapshot_path = _resolve_diff_snapshot(library_root, snapshot_arg)
    old_report = json.loads(snapshot_path.read_text())
    old_issues = old_report.get("issues", {}) if isinstance(old_report, dict) else {}
    new_issues = report.get("issues", {})

    buckets: dict[str, dict[str, list[str]]] = {}
    for bucket in sorted(set(old_issues) | set(new_issues)):
        before = set(old_issues.get(bucket) or [])
        after = set(new_issues.get(bucket) or [])
        added = sorted(after - before)
        removed = sorted(before - after)
        if added or removed:
            buckets[bucket] = {"added": added, "removed": removed}

    return {"against": snapshot_path.stem, "buckets": buckets}


def _print_human_diff(diff: dict) -> None:
    print(f"\ndiff vs snapshot {diff['against']}:")
    if not diff["buckets"]:
        print("- no changes")
        return
    for bucket, changes in diff["buckets"].items():
        parts = [f"+{p}" for p in changes["added"]] + [f"-{p}" for p in changes["removed"]]
        print(f"- {bucket}: {', '.join(parts)}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["run"])
    ap.add_argument("--repo", required=True)
    ap.add_argument("--stale-days", type=int, default=180)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--snapshot", action="store_true",
                     help="Write the report to maintenance/<timestamp>.json in the library root.")
    ap.add_argument("--diff", nargs="?", const="", default=None, metavar="SNAPSHOT",
                     help="Also report per-bucket added/removed PMIDs vs a snapshot under "
                          "maintenance/ (filename or stem). Defaults to the most recent snapshot.")
    args = ap.parse_args()

    library_root = Path(args.repo).expanduser().resolve()
    if not library_root.is_dir():
        print(f"error: no library at {library_root}", file=sys.stderr)
        return 1

    report = lint(library_root, stale_days=args.stale_days)

    diff = None
    if args.diff is not None:
        snapshot_arg = args.diff or None  # bare --diff (no value) -> default to the previous snapshot
        try:
            diff = diff_report(library_root, report, snapshot_arg)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1

    snapshot_path = None
    if args.snapshot:
        snapshot_path = _write_snapshot(library_root, report)

    output = dict(report, diff=diff) if diff is not None else report
    if args.json:
        print(json.dumps(output, indent=2))
    else:
        _print_human(report)
        if diff is not None:
            _print_human_diff(diff)
    if snapshot_path is not None:
        print(f"\nsnapshot written: {snapshot_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
