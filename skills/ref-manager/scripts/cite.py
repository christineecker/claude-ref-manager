#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""`/ref:cite <pmid>` — print the stable inline `@citekey` for a paper while
writing (D14). Cheap: just reads meta.json, no export batch involved."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def cite(library_root: Path, pmid: str) -> str:
    meta_path = library_root / "papers" / pmid / "meta.json"
    if not meta_path.exists():
        raise FileNotFoundError(f"pmid {pmid!r} not in library — add it first via /ref:add")
    meta = json.loads(meta_path.read_text())
    return f"@{meta['citekey']}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--pmid", required=True)
    args = ap.parse_args()

    library_root = Path(args.repo).expanduser().resolve()
    if not library_root.is_dir():
        print(f"error: no library at {library_root}", file=sys.stderr)
        return 1

    try:
        print(cite(library_root, args.pmid))
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
