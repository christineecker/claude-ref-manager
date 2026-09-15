#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""`/ref:note <pmid>` — papers/<pmid>/notes.md, authoritative user content
(§3a: "never overwritten by extraction"). Phase 1 only needs append/show;
no generated process may ever call append() on this file."""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path


def notes_path(library_root: Path, pmid: str) -> Path:
    return library_root / "papers" / pmid / "notes.md"


def append(library_root: Path, pmid: str, text: str) -> Path:
    path = notes_path(library_root, pmid)
    if not path.parent.is_dir():
        raise FileNotFoundError(f"pmid {pmid!r} not found — add it first via /ref:add")
    stamp = datetime.now(timezone.utc).isoformat()
    with path.open("a", encoding="utf-8") as f:
        f.write(f"\n---\n{stamp}\n\n{text}\n")
    return path


def show(library_root: Path, pmid: str) -> str:
    path = notes_path(library_root, pmid)
    return path.read_text() if path.exists() else ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["append", "show"])
    ap.add_argument("--repo", required=True)
    ap.add_argument("--pmid", required=True)
    ap.add_argument("--text")
    args = ap.parse_args()

    library_root = Path(args.repo).expanduser().resolve()
    if not library_root.is_dir():
        print(f"error: no library at {library_root}", file=sys.stderr)
        return 1

    try:
        if args.action == "append":
            if not args.text:
                print("error: --text is required for append", file=sys.stderr)
                return 1
            path = append(library_root, args.pmid, args.text)
            print(f"appended to {path}")
        else:
            print(show(library_root, args.pmid), end="")
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
