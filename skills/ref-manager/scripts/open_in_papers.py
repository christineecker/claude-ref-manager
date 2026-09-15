#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""`/ref:open <pmid>` — push an acquired PDF into Papers for reading (§7).

`open -a Papers <pdf>`. This is the only Papers.app interaction that is
allowed to touch the app itself (never the database) — it hands the OS a
file to open, same as double-clicking it in Finder.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from export_papers import resolve_pdf


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pmid")
    ap.add_argument("--repo", required=True)
    args = ap.parse_args()

    library_root = Path(args.repo).expanduser().resolve()
    if not library_root.is_dir():
        print(f"error: no library at {library_root}", file=sys.stderr)
        return 1

    meta_path = library_root / "papers" / args.pmid / "meta.json"
    if not meta_path.exists():
        print(f"error: no paper {args.pmid} in this library", file=sys.stderr)
        return 1

    pdf = resolve_pdf(library_root, args.pmid)
    if pdf is None:
        print(json.dumps({
            "pmid": args.pmid,
            "status": "no_pdf_acquired",
            "message": "no acquired PDF for this paper yet — run /ref:fetch or /ref:attach first",
        }, indent=2))
        return 0

    pdf_path, _hash = pdf
    subprocess.run(["open", "-a", "Papers", str(pdf_path)], check=True)
    print(json.dumps({"pmid": args.pmid, "status": "opened", "path": str(pdf_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
