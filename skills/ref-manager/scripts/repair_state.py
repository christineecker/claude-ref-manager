#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""`/ref:repair-fulltext` resume-state read/merge -- atomic, lock-serialized.

State file: `<library_root>/maintenance/repair-fulltext-state.json`, a JSON
object keyed by PMID: `{"<pmid>": {"result": "...", "attempted_at": "..."}}`.

This script owns all reads/writes of that file so callers never hand-roll
JSON merges (the write path always goes through `lib_atomic.atomic_write_json`
under `library_lock`, matching the write pattern used by `lib_ids.py`,
`relation.py`, `person.py`, `project.py`).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from lib_atomic import atomic_write_json, library_lock


def _state_path(library_root: Path) -> Path:
    return library_root / "maintenance" / "repair-fulltext-state.json"


def read_state(library_root: Path) -> dict:
    path = _state_path(library_root)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def merge_state(library_root: Path, entries: dict) -> dict:
    """Merge `entries` (PMID -> {result, attempted_at}) into the state file.

    Locked for the read-modify-write so concurrent repair runs against the
    same library can't clobber each other's entries.
    """
    path = _state_path(library_root)
    with library_lock(library_root):
        state = read_state(library_root)
        state.update(entries)
        atomic_write_json(path, state)
    return state


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["read", "merge"])
    ap.add_argument("--repo", required=True)
    ap.add_argument(
        "--entries",
        help="merge only: JSON object {pmid: {result, attempted_at}} to merge in, "
        "or '-' to read it from stdin",
    )
    args = ap.parse_args()

    library_root = Path(args.repo).expanduser().resolve()
    if not library_root.is_dir():
        print(f"error: no library at {library_root}", file=sys.stderr)
        return 1

    if args.action == "read":
        result = read_state(library_root)
    else:
        if not args.entries:
            print("error: --entries required for merge", file=sys.stderr)
            return 1
        raw = sys.stdin.read() if args.entries == "-" else args.entries
        try:
            entries = json.loads(raw)
        except ValueError as e:
            print(f"error: --entries is not valid JSON: {e}", file=sys.stderr)
            return 1
        result = merge_state(library_root, entries)

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
