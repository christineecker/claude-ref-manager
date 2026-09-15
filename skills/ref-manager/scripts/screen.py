#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""`/ref:screen` — project-specific screening decisions (§3b), feeding the
§5c `--screened included|excluded|pending` selector.

Decisions append to projects/<slug>/screening.jsonl (full history, never
mutated) and mirror the latest decision onto the paper's membership record
in papers.yaml (m["screening"]) so the selector can look it up without
replaying the whole log. If the PMID isn't yet a project member, screening
implicitly adds it with no relevance note — you can screen a search result
before deciding it's worth annotating (not spelled out in PLAN.md; flagged
assumption).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from lib_atomic import atomic_write_json
from lib_schema import validate_screening_record, SchemaError
from project import _project_dir, _load

DECISIONS = ("included", "excluded", "pending")


def decide(library_root: Path, slug: str, pmid: str, decision: str, reason: str, run_ref: str | None) -> dict:
    if decision not in DECISIONS:
        raise SchemaError(f"decision must be one of {DECISIONS}")
    pdir = _project_dir(library_root, slug)
    if not pdir.is_dir():
        raise SchemaError(f"project {slug!r} does not exist")

    now = datetime.now(timezone.utc).isoformat()
    record = {"pmid": pmid, "decision": decision, "reason": reason, "timestamp": now}
    if run_ref:
        record["search_run"] = run_ref
    validate_screening_record(record)

    log_path = pdir / "screening.jsonl"
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, sort_keys=True) + "\n")

    papers_path = pdir / "papers.yaml"
    doc = _load(papers_path, {"papers": []})
    membership = next((m for m in doc["papers"] if m["pmid"] == pmid), None)
    if membership is None:
        membership = {
            "pmid": pmid, "relevance": None, "priority": None, "reading_status": None,
            "why_saved": None, "screening": None, "added_at": now,
        }
        doc["papers"].append(membership)
    membership["screening"] = {"decision": decision, "reason": reason, "timestamp": now}
    atomic_write_json(papers_path, doc)
    return record


def history(library_root: Path, slug: str, pmid: str | None) -> list[dict]:
    log_path = _project_dir(library_root, slug) / "screening.jsonl"
    if not log_path.exists():
        return []
    records = [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]
    if pmid:
        records = [r for r in records if r["pmid"] == pmid]
    return records


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["decide", "history"])
    ap.add_argument("--repo", required=True)
    ap.add_argument("--project", required=True)
    ap.add_argument("--pmid")
    ap.add_argument("--decision")
    ap.add_argument("--reason")
    ap.add_argument("--run")
    args = ap.parse_args()

    library_root = Path(args.repo).expanduser().resolve()
    if not library_root.is_dir():
        print(f"error: no library at {library_root}", file=sys.stderr)
        return 1

    try:
        if args.action == "decide":
            if not (args.pmid and args.decision and args.reason):
                raise SchemaError("--pmid, --decision, --reason are all required")
            result = decide(library_root, args.project, args.pmid, args.decision, args.reason, args.run)
        else:
            result = history(library_root, args.project, args.pmid)
    except SchemaError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
