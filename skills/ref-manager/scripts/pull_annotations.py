#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""`/ref:pull-annotations <pmid>` (PLAN.md §7's "Annotation pull" bullet, §7b,
§3a's annotation-pull ownership rule).

Reads $.user_data.annotations[] for the Papers item matching this PMID
(fallback to DOI, §7's own match order) from a read-only snapshot
(papers_snapshot.py) and upserts into papers/<pmid>/annotations.json,
keyed by each annotation's own stable Papers `id` -- never re-derived.

Upsert semantics:
  - unchanged upstream annotation -> unchanged local record (idempotent;
    a repeat pull with no upstream changes is byte-identical).
  - upstream annotation edited (text/note/rects changed) -> local record
    updated in place from the upstream fields; a `local` sub-object (for
    any future ref-manager-side annotation-level data) is preserved as-is
    across the update, never overwritten by the upstream refresh.
  - upstream annotation no longer present -> TOMBSTONED, not deleted
    locally: `deleted_upstream: true` / `deleted_upstream_at: <iso8601>`
    is set on the existing record and it is kept, not removed. This
    matches the library's general provenance stance elsewhere (raw
    acquisitions are immutable, rejected claims are retained for audit,
    corrections are never silently dropped) -- an annotation you already
    pulled is evidence you once had, and losing it upstream (accidental
    deletion in Papers, a sync hiccup) should not silently erase your
    local copy. The pull's own output reports which ids were tombstoned
    this run, so it is never a silent loss.

This command NEVER touches notes.md (phase 1's /ref:note) -- annotations
and the free-text note are stored and displayed separately, never blended
(§7 closing paragraph; this phase's gate: "notes survive promotion").
Anchors (file sha256 + page position) are stored exactly as Papers reports
them -- they are anchored to *Papers'* copy of the file, not necessarily
ref-manager's raw/<sha256>/ copy, so no attempt is made to reconcile them.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from lib_atomic import atomic_write_json, pmid_lock, now_iso
from papers_snapshot import try_read_items, find_duplicate


def annotations_path(library_root: Path, pmid: str) -> Path:
    return library_root / "papers" / pmid / "annotations.json"


def _find_item_for_pmid(items: list[dict], pmid: str, doi: str | None) -> dict | None:
    return find_duplicate(items, pmid, doi)


def pull(library_root: Path, pmid: str, papers_db_path: Path | None) -> dict:
    paper_dir = library_root / "papers" / pmid
    meta_path = paper_dir / "meta.json"
    if not meta_path.exists():
        raise ValueError(f"pmid {pmid!r} not found -- add it first via /ref:add")
    meta = json.loads(meta_path.read_text())
    doi = meta.get("doi")

    if papers_db_path is None:
        return {"pmid": pmid, "status": "no_papers_db_configured"}

    items, err = try_read_items(papers_db_path)
    if items is None:
        return {"pmid": pmid, "status": "snapshot_unavailable", "reason": err}

    item = _find_item_for_pmid(items, pmid, doi)
    if item is None:
        return {"pmid": pmid, "status": "no_matching_papers_item"}

    upstream = item.get("annotations") or []
    upstream_by_id = {}
    for a in upstream:
        aid = a.get("id")
        if not aid:
            continue
        upstream_by_id[aid] = a

    with pmid_lock(library_root, pmid):
        path = annotations_path(library_root, pmid)
        if path.exists():
            doc = json.loads(path.read_text())
        else:
            doc = {"pmid": pmid, "papers_item_id": item["id"], "annotations": {}}

        existing = doc.get("annotations") or {}
        added, updated, tombstoned, unchanged = [], [], [], []

        for aid, a in upstream_by_id.items():
            upstream_fields = {
                "id": aid,
                "type": a.get("type"),
                "sha256": a.get("sha256"),
                "page_start": a.get("page_start"),
                "position": a.get("position"),
                "rects": a.get("rects"),
                "text": a.get("text"),
                "note": a.get("note"),
                "has_note": a.get("has_note"),
                "color_id": a.get("color_id"),
                "created": a.get("created"),
                "modified": a.get("modified"),
                "source": "papers",
                "deleted_upstream": False,
                "deleted_upstream_at": None,
            }
            if aid in existing:
                prior = existing[aid]
                prior_compare = {k: v for k, v in prior.items() if k != "local"}
                if prior_compare == upstream_fields:
                    unchanged.append(aid)
                    continue
                new_record = dict(upstream_fields)
                new_record["local"] = prior.get("local", {})
                existing[aid] = new_record
                updated.append(aid)
            else:
                new_record = dict(upstream_fields)
                new_record["local"] = {}
                existing[aid] = new_record
                added.append(aid)

        # tombstone: any locally-known papers-sourced annotation no longer
        # present upstream this pull.
        now = now_iso()
        for aid, rec in existing.items():
            if rec.get("source") != "papers":
                continue
            if aid in upstream_by_id:
                continue
            if rec.get("deleted_upstream"):
                continue
            rec["deleted_upstream"] = True
            rec["deleted_upstream_at"] = now
            tombstoned.append(aid)

        doc["annotations"] = existing
        doc["papers_item_id"] = item["id"]
        doc["last_pulled_at"] = now
        atomic_write_json(path, doc)

    return {
        "pmid": pmid, "status": "ok",
        "added": added, "updated": updated,
        "tombstoned": tombstoned, "unchanged": unchanged,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--pmid", required=True)
    ap.add_argument("--papers-db")
    args = ap.parse_args()

    library_root = Path(args.repo).expanduser().resolve()
    if not library_root.is_dir():
        print(f"error: no library at {library_root}", file=sys.stderr)
        return 1

    papers_db = Path(args.papers_db).expanduser().resolve() if args.papers_db else None

    try:
        result = pull(library_root, args.pmid, papers_db)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
