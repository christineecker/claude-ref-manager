#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Read-only Papers.app snapshot access (PLAN.md §7 closing paragraph).

"Query only a consistent snapshot ... using the SQLite backup API with a
read-only source connection ... Never write to it." This module never opens
the live database for anything but a backup() call into a temp file; every
other read happens against that temp copy. If a consistent snapshot cannot
be obtained, callers get a clear unavailable status, never an exception —
"warn and skip per field rather than failing the run" (§7, §9.3), and at
the command layer "an unreadable live database degrades to an export
without duplicate detection rather than a failure" (§8 Phase 3 gate).
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path


class SnapshotUnavailable(Exception):
    pass


def take_snapshot(db_path: Path) -> Path:
    """Back up the live (possibly WAL-mode, possibly locked) database into a
    private temp file via sqlite3's backup API against a read-only source
    connection. Raises SnapshotUnavailable on any failure — never touches
    the source beyond opening it read-only and reading pages for backup."""
    db_path = Path(db_path)
    if not db_path.exists():
        raise SnapshotUnavailable(f"no database at {db_path}")
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".papers-snapshot.sqlite")
    import os
    os.close(tmp_fd)
    tmp_path = Path(tmp_path)
    try:
        src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            dst = sqlite3.connect(str(tmp_path))
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
    except sqlite3.Error as e:
        with __import__("contextlib").suppress(FileNotFoundError):
            tmp_path.unlink()
        raise SnapshotUnavailable(f"could not snapshot {db_path}: {e}") from e
    return tmp_path


# Expected shape (PLAN.md §7): items(id TEXT PK, collection_id TEXT, json TEXT)
# with $.ext_ids.pmid/.doi/.pmcid, $.article.*, $.user_data.notes/tags/
# annotations[]/rating/..., $.files[].sha256/$.primary_file_hash. Every read
# below validates paths defensively and skips a malformed row/field rather
# than raising, per §7's own "warns-and-skips per field" rule.

def read_items(snapshot_path: Path) -> list[dict]:
    """Return normalized item dicts: {id, pmid, doi, pmcid, notes, tags,
    rating, primary_file_hash, deleted}. Malformed rows are skipped, not
    fatal — this function itself never raises for per-row problems."""
    con = sqlite3.connect(f"file:{snapshot_path}?mode=ro", uri=True)
    try:
        try:
            cur = con.execute("SELECT id, collection_id, json FROM items")
        except sqlite3.OperationalError as e:
            raise SnapshotUnavailable(f"unexpected schema: {e}") from e
        out = []
        for row_id, collection_id, raw_json in cur.fetchall():
            try:
                doc = json.loads(raw_json)
            except (TypeError, ValueError):
                continue
            ext = doc.get("ext_ids") or {}
            article = doc.get("article") or {}
            user = doc.get("user_data") or {}
            out.append({
                "id": row_id,
                "collection_id": collection_id,
                "pmid": ext.get("pmid"),
                "doi": ext.get("doi"),
                "pmcid": ext.get("pmcid"),
                "title": article.get("title"),
                "notes": user.get("notes"),
                "tags": user.get("tags") or [],
                "rating": user.get("rating"),
                "primary_file_hash": doc.get("primary_file_hash"),
                "deleted": bool(doc.get("deleted")),
            })
        return out
    finally:
        con.close()


def try_read_items(db_path: Path) -> tuple[list[dict] | None, str | None]:
    """Best-effort: (items, None) on success, (None, reason) on failure.
    Callers use this to degrade gracefully rather than propagate exceptions."""
    try:
        snap = take_snapshot(db_path)
    except SnapshotUnavailable as e:
        return None, str(e)
    try:
        return read_items(snap), None
    except SnapshotUnavailable as e:
        return None, str(e)
    finally:
        import contextlib
        with contextlib.suppress(FileNotFoundError):
            snap.unlink()


def find_duplicate(items: list[dict], pmid: str | None, doi: str | None) -> dict | None:
    for it in items:
        if it["deleted"]:
            continue
        if pmid and it.get("pmid") == pmid:
            return it
        if doi and it.get("doi") and it["doi"].lower() == doi.lower():
            return it
    return None
