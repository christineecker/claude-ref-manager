#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""`/ref:queue` — human reading state, priority, and why-saved (§1, §3b).

Reading state belongs to a paper's PROJECT MEMBERSHIP record, not to the
paper globally (§3b: "Membership references a paper once; relevance,
priority, screening, and reading state belong to that membership"). Neither
acquisition nor model promotion may set it — only this command.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from lib_atomic import atomic_write_json
from project import READING_STATES, _project_dir, _load
from lib_schema import SchemaError


def set_state(
    library_root: Path, slug: str, pmid: str,
    status: str | None, priority: int | None, why: str | None,
) -> dict:
    papers_path = _project_dir(library_root, slug) / "papers.yaml"
    if not papers_path.exists():
        raise SchemaError(f"project {slug!r} does not exist")
    if status is not None and status not in READING_STATES:
        raise SchemaError(f"status must be one of {READING_STATES}")

    doc = _load(papers_path, {"papers": []})
    for m in doc["papers"]:
        if m["pmid"] == pmid:
            if status is not None:
                m["reading_status"] = status
            if priority is not None:
                m["priority"] = priority
            if why is not None:
                m["why_saved"] = why
            atomic_write_json(papers_path, doc)
            return m
    raise SchemaError(f"pmid {pmid!r} is not a member of project {slug!r} (add it first via /ref:project)")


def show(library_root: Path, slug: str, pmid: str | None) -> list[dict]:
    doc = _load(_project_dir(library_root, slug) / "papers.yaml", {"papers": []})
    if pmid:
        return [m for m in doc["papers"] if m["pmid"] == pmid]
    return doc["papers"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["set", "show"])
    ap.add_argument("--repo", required=True)
    ap.add_argument("--project", required=True)
    ap.add_argument("--pmid")
    ap.add_argument("--status")
    ap.add_argument("--priority", type=int)
    ap.add_argument("--why")
    args = ap.parse_args()

    library_root = Path(args.repo).expanduser().resolve()
    if not library_root.is_dir():
        print(f"error: no library at {library_root}", file=sys.stderr)
        return 1

    try:
        if args.action == "set":
            if not args.pmid:
                raise SchemaError("--pmid is required for set")
            result = set_state(library_root, args.project, args.pmid, args.status, args.priority, args.why)
        else:
            result = show(library_root, args.project, args.pmid)
    except SchemaError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
