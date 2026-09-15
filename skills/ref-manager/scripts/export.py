#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""`/ref:export --bib/--csl` — selector-driven citation export (D10, D14, §5c).

Freezes the resolved selector into exports/<batch>/manifest.json alongside
references.bib and references.csl.json, matching the freeze/report contract
every other §5c artifact follows. A batch is identified by --batch <label>:
re-running with the same label and no --refresh reuses the frozen
resolution rather than re-resolving live (§5c: "a saved comparison never
silently changes membership underneath its conclusions"); --refresh
re-resolves and reports added/removed against the previous freeze.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from lib_atomic import atomic_write_json, atomic_write_text
from lib_cite import build_exports
from lib_selector import resolve_from_args, add_selector_args, SelectorError


def _batch_dir(library_root: Path, batch: str) -> Path:
    return library_root / "exports" / batch


def run_export(library_root: Path, batch: str, resolution: dict | None, refresh: bool) -> dict:
    bdir = _batch_dir(library_root, batch)
    manifest_path = bdir / "manifest.json"

    if manifest_path.exists() and not refresh:
        manifest = json.loads(manifest_path.read_text())
        return {"status": "reused_frozen_batch", "batch": batch, "manifest": manifest}

    if resolution is None:
        raise SelectorError("no selector resolution available for a new/refreshed batch")

    prior_pmids = []
    if manifest_path.exists():
        prior_pmids = json.loads(manifest_path.read_text())["pmids"]

    pmids = resolution["pmids"]
    csl_entries, bib_text = build_exports(library_root, pmids)

    bdir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(bdir / "references.csl.json", csl_entries)
    atomic_write_text(bdir / "references.bib", bib_text)

    manifest = {
        "batch": batch,
        "selector_expression": resolution["selector_expression"],
        "pmids": pmids,
        "citekeys": [c["id"] for c in csl_entries],
        "resolved_at": datetime.now(timezone.utc).isoformat(),
        "report": resolution["report"],
    }
    atomic_write_json(manifest_path, manifest)

    status = "created" if not prior_pmids else "refreshed"
    result = {"status": status, "batch": batch, "manifest": manifest}
    if prior_pmids:
        result["added"] = sorted(set(pmids) - set(prior_pmids))
        result["removed"] = sorted(set(prior_pmids) - set(pmids))
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    add_selector_args(ap)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--batch", required=True)
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    library_root = Path(args.repo).expanduser().resolve()
    if not library_root.is_dir():
        print(f"error: no library at {library_root}", file=sys.stderr)
        return 1

    manifest_exists = (_batch_dir(library_root, args.batch) / "manifest.json").exists()

    try:
        resolution = None
        if not manifest_exists or args.refresh:
            resolution = resolve_from_args(library_root, args)
        result = run_export(library_root, args.batch, resolution, args.refresh)
    except SelectorError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
