#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""`/ref:compare <selector>` -- evidence matrix over the §5c-selected papers
(§5a, §3b).

Freeze/manifest contract matches export.py exactly (§5c: "a saved
comparison never silently changes membership underneath its
conclusions"): --batch <label> identifies the table; re-running without
--refresh reuses the frozen resolution; --refresh re-resolves and reports
added/removed/changed-evidence papers.

Rows group by recorded study (study.py, phase 5): papers sharing a
studies.jsonl grouping become one row; ungrouped papers get their own
single-paper row. Dataset reuse (datasets.jsonl) never causes grouping on
its own (§3b) -- only an explicit study record does.

Cell semantics, deliberately distinct (an explicit Phase 5 gate requirement):
  - "not_extracted": no claim covers this dimension for this paper at all
    (either the paper has zero active claims, or the column has no mapping
    in the claim schema at all, e.g. sample_size/limitations/relevance --
    the extractor (§4a) never captures those fields, so they are always
    not_extracted unless a study/dataset/method record or project relevance
    note separately supplies them)
  - "not_reported": at least one active claim covers this paper, but every
    such claim's underlying field is the literal "unknown" the extractor
    writes when the paper's text doesn't state it (§4a)
  - otherwise: the actual normalized value(s), each tagged with the
    claim_id(s) backing it -- "cells link to source passages or reviewed
    claims" (§5a)

A bare PMID list and an equivalent --project selector must produce
byte-identical `rows` (only the manifest's selector_expression differs) --
row construction depends only on the resolved PMID set and on-disk claim/
study state, never on how the set was selected.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from lib_atomic import atomic_write_json
from lib_selector import resolve_from_args, add_selector_args, SelectorError
from lib_verify_link import load_registry
from lib_status_check import current_status, diff_status
import study as study_mod

CLAIM_COLUMNS = {
    "population": "population",
    "design": "study_design",
    "comparator": "comparator",
    "uncertainty": "uncertainty_interval",
}
# structurally unmapped by the claim schema (§4a never captures these) --
# always "not_extracted" unless a study/dataset/method/project record fills
# them in via a side channel (methods, relevance) noted per-column below.
UNMAPPED_COLUMNS = ("methods", "sample_size", "limitations", "relevance")
ALL_COLUMNS = ("population", "design", "methods", "sample_size", "comparator",
                "results", "uncertainty", "limitations", "relevance")


def _active_claims(library_root: Path, pmid: str) -> list[dict]:
    registry = load_registry(library_root, pmid)
    return [c for c in registry.get("claims", {}).values() if c.get("status") == "active"]


def _results_cell(claims: list[dict]) -> dict:
    parts = []
    claim_ids = []
    any_reported = False
    for c in claims:
        direction = c.get("direction", "unknown")
        value = c.get("effect_value", "unknown")
        measure = c.get("effect_measure", "unknown")
        if direction == "unknown" and value == "unknown" and measure == "unknown":
            continue
        any_reported = True
        bits = [b for b in (direction, value, measure) if b not in ("unknown", None)]
        if bits:
            parts.append(" / ".join(bits))
            claim_ids.append(c["claim_id"])
    if not any_reported:
        return {"value": "not_reported"}
    return {"value": sorted(set(parts)), "claim_ids": claim_ids}


def _claim_field_cell(claims: list[dict], field: str) -> dict:
    values = []
    claim_ids = []
    for c in claims:
        v = c.get(field, "unknown")
        if v != "unknown":
            values.append(v)
            claim_ids.append(c["claim_id"])
    if not values:
        return {"value": "not_reported"}
    return {"value": sorted(set(values)), "claim_ids": claim_ids}


def _relevance_cell(library_root: Path, project: str | None, pmid: str) -> dict:
    if not project:
        return {"value": "not_extracted"}
    papers_path = library_root / "projects" / project / "papers.yaml"
    if not papers_path.exists():
        return {"value": "not_extracted"}
    members = json.loads(papers_path.read_text()).get("papers", [])
    m = next((m for m in members if m["pmid"] == pmid), None)
    relevance = m.get("relevance") if m else None
    if not relevance:
        return {"value": "not_extracted"}
    return {"value": relevance}


def _paper_provenance(library_root: Path, pmid: str) -> dict:
    meta_path = library_root / "papers" / pmid / "meta.json"
    if not meta_path.exists():
        return {"extraction_tier": "missing_record", "checked_at": "", "abstract_available": False, "full_text": False}
    meta = json.loads(meta_path.read_text())
    return {
        "extraction_tier": meta.get("extraction_tier") or "unavailable",
        "checked_at": meta.get("checked_at") or "",
        "abstract_available": bool(meta.get("abstract_available")),
        "full_text": bool(meta.get("full_text")),
    }


def _methods_cell(library_root: Path, pmid: str) -> dict:
    matches = [m for m in study_mod.list_methods(library_root) if pmid in m.get("pmids", [])]
    if not matches:
        return {"value": "not_extracted"}
    return {"value": sorted(m["name"] for m in matches), "method_ids": [m["method_id"] for m in matches]}


def build_cells(library_root: Path, pmid: str, project: str | None) -> dict:
    claims = _active_claims(library_root, pmid)
    cells = {}
    if not claims:
        for col in ("population", "design", "comparator", "results", "uncertainty"):
            cells[col] = {"value": "not_extracted"}
    else:
        for col, field in CLAIM_COLUMNS.items():
            cells[col] = _claim_field_cell(claims, field)
        cells["results"] = _results_cell(claims)
    cells["methods"] = _methods_cell(library_root, pmid)
    cells["sample_size"] = {"value": "not_extracted"}
    cells["limitations"] = {"value": "not_extracted"}
    cells["relevance"] = _relevance_cell(library_root, project, pmid)
    return cells


def _cell_hash(cells: dict) -> str:
    return hashlib.sha256(json.dumps(cells, sort_keys=True).encode()).hexdigest()


def build_rows(library_root: Path, pmids: list[str], project: str | None) -> list[dict]:
    """Group by recorded study; independent of how `pmids` was selected."""
    remaining = set(pmids)
    grouped: list[dict] = []
    seen_studies = set()

    for pmid in pmids:
        if pmid not in remaining:
            continue
        study_row = study_mod.study_for_pmid(library_root, pmid)
        if study_row and study_row["study_id"] not in seen_studies:
            seen_studies.add(study_row["study_id"])
            group_pmids = sorted(p for p in study_row["pmids"] if p in remaining)
            remaining -= set(group_pmids)
            grouped.append({
                "pmids": group_pmids,
                "study": {
                    "study_id": study_row["study_id"],
                    "confidence": study_row["confidence"],
                    "evidence": study_row["evidence"],
                },
                "cells": {p: build_cells(library_root, p, project) for p in group_pmids},
                "provenance": {p: _paper_provenance(library_root, p) for p in group_pmids},
            })
        elif not study_row:
            remaining.discard(pmid)
            grouped.append({
                "pmids": [pmid], "study": None,
                "cells": {pmid: build_cells(library_root, pmid, project)},
                "provenance": {pmid: _paper_provenance(library_root, pmid)},
            })
        # else: pmid belongs to an already-grouped study, handled above

    # stable order: by first pmid in each row, matching input order intent
    grouped.sort(key=lambda r: r["pmids"][0])
    return grouped


def _batch_dir(library_root: Path, batch: str, project: str | None) -> Path:
    if project:
        return library_root / "projects" / project / "tables" / batch
    return library_root / "tables" / batch


def run_compare(library_root: Path, batch: str, project: str | None,
                 resolution: dict | None, refresh: bool) -> dict:
    bdir = _batch_dir(library_root, batch, project)
    manifest_path = bdir / "manifest.json"
    table_path = bdir / "table.json"
    edits_path = bdir / "edits.json"

    if manifest_path.exists() and not refresh:
        manifest = json.loads(manifest_path.read_text())
        rows = json.loads(table_path.read_text())
        return {"status": "reused_frozen_table", "batch": batch, "manifest": manifest, "rows": rows}

    if resolution is None:
        raise SelectorError("no selector resolution available for a new/refreshed table")

    prior_pmids = []
    prior_status_snapshot = {}
    if manifest_path.exists():
        prior_manifest = json.loads(manifest_path.read_text())
        prior_pmids = prior_manifest["pmids"]
        prior_status_snapshot = prior_manifest.get("retraction_status_snapshot", {})

    pmids = resolution["pmids"]
    rows = build_rows(library_root, pmids, project)
    status_changes = diff_status(library_root, prior_status_snapshot) if prior_pmids else []

    edits = json.loads(edits_path.read_text()) if edits_path.exists() else {}
    changed_evidence = []
    if edits:
        for row in rows:
            for pmid, cells in row["cells"].items():
                for col, cell in cells.items():
                    key = f"{pmid}::{col}"
                    edit = edits.get(key)
                    if not edit:
                        continue
                    fresh_hash = _cell_hash(cell)
                    if fresh_hash != edit["based_on_cell_hash"]:
                        edit["stale"] = True
                        changed_evidence.append(key)
                    else:
                        edit["stale"] = False
                    cell["user_edit"] = edit
        atomic_write_json(edits_path, edits)

    bdir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(table_path, rows)

    manifest = {
        "batch": batch,
        "selector_expression": resolution["selector_expression"],
        "pmids": pmids,
        "project": project,
        "resolved_at": datetime.now(timezone.utc).isoformat(),
        "report": resolution["report"],
        # Phase 11: snapshot current status per PMID so the NEXT refresh can
        # detect a retraction-status change against this frozen version.
        "retraction_status_snapshot": {pmid: current_status(library_root, pmid) for pmid in pmids},
    }
    atomic_write_json(manifest_path, manifest)

    status = "created" if not prior_pmids else "refreshed"
    result = {"status": status, "batch": batch, "manifest": manifest, "rows": rows}
    if prior_pmids:
        result["added"] = sorted(set(pmids) - set(prior_pmids))
        result["removed"] = sorted(set(prior_pmids) - set(pmids))
        if changed_evidence:
            result["changed_evidence_cells"] = sorted(set(changed_evidence))
        result["retraction_status_changes"] = status_changes
    return result


def edit_cell(library_root: Path, batch: str, project: str | None, pmid: str, column: str, value) -> dict:
    bdir = _batch_dir(library_root, batch, project)
    table_path = bdir / "table.json"
    edits_path = bdir / "edits.json"
    if not table_path.exists():
        raise SelectorError(f"no table {batch!r} to edit -- run /ref:compare first")

    rows = json.loads(table_path.read_text())
    row = next((r for r in rows if pmid in r["cells"]), None)
    if row is None:
        raise SelectorError(f"pmid {pmid!r} is not in table {batch!r}")
    current_cell = {k: v for k, v in row["cells"][pmid][column].items() if k != "user_edit"}

    edits = json.loads(edits_path.read_text()) if edits_path.exists() else {}
    key = f"{pmid}::{column}"
    edits[key] = {
        "value": value,
        "based_on_cell_hash": _cell_hash(current_cell),
        "edited_at": datetime.now(timezone.utc).isoformat(),
        "stale": False,
    }
    atomic_write_json(edits_path, edits)
    return edits[key]


def main() -> int:
    ap = argparse.ArgumentParser()
    add_selector_args(ap)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--batch", required=True)
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--edit-pmid")
    ap.add_argument("--edit-column")
    ap.add_argument("--edit-value")
    args = ap.parse_args()

    library_root = Path(args.repo).expanduser().resolve()
    if not library_root.is_dir():
        print(f"error: no library at {library_root}", file=sys.stderr)
        return 1

    try:
        if args.edit_pmid:
            result = edit_cell(library_root, args.batch, args.project, args.edit_pmid,
                                args.edit_column, args.edit_value)
        else:
            manifest_exists = (_batch_dir(library_root, args.batch, args.project) / "manifest.json").exists()
            resolution = None
            if not manifest_exists or args.refresh:
                resolution = resolve_from_args(library_root, args)
            result = run_compare(library_root, args.batch, args.project, resolution, args.refresh)
    except SelectorError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
