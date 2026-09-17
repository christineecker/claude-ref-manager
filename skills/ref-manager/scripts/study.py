#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Study/dataset/method records (PLAN.md §3b, §3d, D22).

studies/studies.jsonl   -- one line per study: a stated GROUPING of PMIDs
                            believed to be the same underlying investigation,
                            with explicit confidence + evidence. Grouping is
                            never automatic (not from shared authors, not
                            from shared dataset) -- a human/agent asserts it.
studies/datasets.jsonl  -- cohort/dataset identities papers may reuse. This
                            is a SEPARATE relationship from study grouping:
                            two papers reusing the same dataset are not
                            thereby the same study (§3b).
studies/methods.jsonl   -- protocols/tools/controls with context + locator,
                            optionally shared across papers.

All three use user-minted, library-global slugs (§3d) via lib_ids.py's
existing allocator -- registered under kind "study"/"dataset"/"method",
which lib_ids.py's _SLUG_LAYOUT already names as jsonl-registry kinds.

Record shapes (not pinned by PLAN.md beyond "store grouping evidence,
confidence, and review state" for studies -- this is this phase's own
design decision, documented here for /ref:compare and any later phase
that reads these files):

studies.jsonl row:
{"study_id": "<slug>", "pmids": ["..."], "confidence": "confirmed|likely|uncertain",
 "evidence": "<free text: why these are the same investigation>",
 "review_state": "reviewed|unreviewed", "created_at": "...", "updated_at": "..."}

datasets.jsonl row:
{"dataset_id": "<slug>", "name": "<display name>", "pmids": ["..."],
 "notes": "<free text or null>", "created_at": "..."}

methods.jsonl row:
{"method_id": "<slug>", "name": "<display name>", "pmids": ["..."],
 "context": "<free text or null>", "source_locator": "<string or null>",
 "created_at": "..."}
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from lib_atomic import library_lock, now_iso, read_jsonl, write_jsonl
from lib_ids import allocate_slug, SlugError
from lib_schema import validate_study

CONFIDENCES = ("confirmed", "likely", "uncertain")


_JSONL_FILENAMES = {"study": "studies.jsonl", "dataset": "datasets.jsonl", "method": "methods.jsonl"}


def _jsonl_path(library_root: Path, kind: str) -> Path:
    # PLAN.md §3's repo layout (and prisma.py's reader) names these
    # studies.jsonl/datasets.jsonl/methods.jsonl -- plural, not f"{kind}.jsonl".
    return library_root / "studies" / _JSONL_FILENAMES[kind]


def _append_row(library_root: Path, kind: str, row: dict) -> dict:
    path = _jsonl_path(library_root, kind)
    with library_lock(library_root):
        rows = read_jsonl(path)
        rows.append(row)
        write_jsonl(path, rows)
    return row


def create_study(library_root: Path, study_id: str, pmids: list[str], confidence: str, evidence: str) -> dict:
    if confidence not in CONFIDENCES:
        raise SlugError(f"confidence must be one of {CONFIDENCES}, got {confidence!r}")
    if not pmids:
        raise SlugError("a study must group at least one PMID")
    if not evidence or not evidence.strip():
        raise SlugError("evidence is required: why these PMIDs are the same investigation (§3b)")
    allocate_slug(library_root, "study", study_id)
    now = now_iso()
    row = {
        "study_id": study_id, "pmids": sorted(set(pmids)),
        "confidence": confidence, "evidence": evidence,
        "review_state": "unreviewed", "created_at": now, "updated_at": now,
    }
    validate_study(row)
    return _append_row(library_root, "study", row)


def create_dataset(library_root: Path, dataset_id: str, name: str, pmids: list[str] | None = None, notes: str | None = None) -> dict:
    allocate_slug(library_root, "dataset", dataset_id)
    row = {
        "dataset_id": dataset_id, "name": name, "pmids": sorted(set(pmids or [])),
        "notes": notes, "created_at": now_iso(),
    }
    return _append_row(library_root, "dataset", row)


def create_method(library_root: Path, method_id: str, name: str, pmids: list[str] | None,
                   context: str | None, source_locator: str | None) -> dict:
    allocate_slug(library_root, "method", method_id)
    row = {
        "method_id": method_id, "name": name, "pmids": sorted(set(pmids or [])),
        "context": context, "source_locator": source_locator, "created_at": now_iso(),
    }
    return _append_row(library_root, "method", row)


def study_for_pmid(library_root: Path, pmid: str) -> dict | None:
    """The (first) recorded study grouping this PMID belongs to, or None.
    A PMID is expected to belong to at most one study in this phase's
    design -- if the fixtures ever need multi-study membership, that's a
    documented extension point, not silently supported today."""
    for row in read_jsonl(_jsonl_path(library_root, "study")):
        if pmid in row.get("pmids", []):
            return row
    return None


def list_studies(library_root: Path) -> list[dict]:
    return read_jsonl(_jsonl_path(library_root, "study"))


def list_datasets(library_root: Path) -> list[dict]:
    return read_jsonl(_jsonl_path(library_root, "dataset"))


def list_methods(library_root: Path) -> list[dict]:
    return read_jsonl(_jsonl_path(library_root, "method"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=[
        "create-study", "create-dataset", "create-method",
        "list-studies", "list-datasets", "list-methods",
    ])
    ap.add_argument("--repo", required=True)
    ap.add_argument("--id")
    ap.add_argument("--pmid", nargs="*", default=[])
    ap.add_argument("--confidence")
    ap.add_argument("--evidence")
    ap.add_argument("--name")
    ap.add_argument("--notes")
    ap.add_argument("--context")
    ap.add_argument("--locator")
    args = ap.parse_args()

    library_root = Path(args.repo).expanduser().resolve()
    if not library_root.is_dir():
        print(f"error: no library at {library_root}", file=sys.stderr)
        return 1

    try:
        if args.action == "create-study":
            result = create_study(library_root, args.id, args.pmid, args.confidence, args.evidence)
        elif args.action == "create-dataset":
            result = create_dataset(library_root, args.id, args.name, args.pmid, args.notes)
        elif args.action == "create-method":
            result = create_method(library_root, args.id, args.name, args.pmid, args.context, args.locator)
        elif args.action == "list-studies":
            result = list_studies(library_root)
        elif args.action == "list-datasets":
            result = list_datasets(library_root)
        else:
            result = list_methods(library_root)
    except SlugError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
