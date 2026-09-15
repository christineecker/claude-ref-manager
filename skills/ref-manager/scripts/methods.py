#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""`/ref:methods <selector>` -- protocols/instruments/controls/datasets/
software/analysis choices per paper or study group (§5a).

Scope note: the claim schema (§4a, phase 4) captures `study_design` and
`adjustment_context` per claim but has no instrument/software/control
fields -- full protocol extraction is a future dedicated step, not this
phase's job. This command aggregates what's already knowable: claim-level
study_design/adjustment_context, plus explicit studies/methods.jsonl and
studies/datasets.jsonl links (study.py, this same phase). Anything not
covered by either source is "not_reported" -- never inferred, per §5a's
"Do not reconstruct unreported procedural details."
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from lib_selector import resolve_from_args, add_selector_args, SelectorError
from lib_verify_link import load_registry
import study as study_mod


def _active_claims(library_root: Path, pmid: str) -> list[dict]:
    registry = load_registry(library_root, pmid)
    return [c for c in registry.get("claims", {}).values() if c.get("status") == "active"]


def methods_for_pmid(library_root: Path, pmid: str) -> dict:
    claims = _active_claims(library_root, pmid)

    designs = sorted({c["study_design"] for c in claims if c.get("study_design", "unknown") != "unknown"})
    adjustments = sorted({c["adjustment_context"] for c in claims if c.get("adjustment_context", "unknown") != "unknown"})
    cohorts = sorted({c["cohort_identity"] for c in claims if c.get("cohort_identity", "unknown") != "unknown"})

    linked_methods = [m for m in study_mod.list_methods(library_root) if pmid in m.get("pmids", [])]
    linked_datasets = [d for d in study_mod.list_datasets(library_root) if pmid in d.get("pmids", [])]

    return {
        "pmid": pmid,
        "study_design": designs or "not_reported",
        "adjustment_context": adjustments or "not_reported",
        "cohort_identity": cohorts or "not_reported",
        "linked_methods": [
            {"method_id": m["method_id"], "name": m["name"], "context": m["context"],
             "source_locator": m["source_locator"]}
            for m in linked_methods
        ] or "not_reported",
        "linked_datasets": [
            {"dataset_id": d["dataset_id"], "name": d["name"]} for d in linked_datasets
        ] or "not_reported",
        "instruments": "not_reported",
        "software": "not_reported",
        "controls": "not_reported",
    }


def run(library_root: Path, pmids: list[str]) -> list[dict]:
    remaining = set(pmids)
    rows = []
    seen_studies = set()
    for pmid in pmids:
        if pmid not in remaining:
            continue
        study_row = study_mod.study_for_pmid(library_root, pmid)
        if study_row and study_row["study_id"] not in seen_studies:
            seen_studies.add(study_row["study_id"])
            group = sorted(p for p in study_row["pmids"] if p in remaining)
            remaining -= set(group)
            rows.append({
                "pmids": group, "study": {"study_id": study_row["study_id"],
                                           "confidence": study_row["confidence"]},
                "per_paper": [methods_for_pmid(library_root, p) for p in group],
            })
        elif not study_row:
            remaining.discard(pmid)
            rows.append({"pmids": [pmid], "study": None,
                          "per_paper": [methods_for_pmid(library_root, pmid)]})
    rows.sort(key=lambda r: r["pmids"][0])
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    add_selector_args(ap)
    ap.add_argument("--repo", required=True)
    args = ap.parse_args()

    library_root = Path(args.repo).expanduser().resolve()
    if not library_root.is_dir():
        print(f"error: no library at {library_root}", file=sys.stderr)
        return 1

    try:
        resolution = resolve_from_args(library_root, args)
        rows = run(library_root, resolution["pmids"])
    except SelectorError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(json.dumps({"report": resolution["report"], "rows": rows}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
