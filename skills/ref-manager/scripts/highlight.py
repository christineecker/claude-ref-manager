#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""papers/<pmid>/highlights.json — user-created PDF text highlights made in
the `/ref:dashboard serve` in-page reader (see dashboard.py's PDF tab). Only
the dashboard server's POST/DELETE handlers ever call add()/remove(); no
generated process may write this file."""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from pathlib import Path

from lib_atomic import atomic_write_json, pmid_lock


def highlights_path(library_root: Path, pmid: str) -> Path:
    return library_root / "papers" / pmid / "highlights.json"


def load(library_root: Path, pmid: str) -> list[dict]:
    path = highlights_path(library_root, pmid)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


def add(
    library_root: Path,
    pmid: str,
    *,
    page: int,
    rects: list[dict],
    text: str,
    color: str,
    note: str | None = None,
) -> dict:
    paper_dir = library_root / "papers" / pmid
    if not paper_dir.is_dir():
        raise FileNotFoundError(f"pmid {pmid!r} not found — add it first via /ref:add")
    entry = {
        "id": secrets.token_hex(8),
        "page": page,
        "rects": rects,
        "text": text,
        "color": color,
        "note": note,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    with pmid_lock(library_root, pmid):
        items = load(library_root, pmid)
        items.append(entry)
        atomic_write_json(highlights_path(library_root, pmid), items)
    return entry


def remove(library_root: Path, pmid: str, highlight_id: str) -> bool:
    with pmid_lock(library_root, pmid):
        items = load(library_root, pmid)
        kept = [i for i in items if i.get("id") != highlight_id]
        if len(kept) == len(items):
            return False
        atomic_write_json(highlights_path(library_root, pmid), kept)
    return True
