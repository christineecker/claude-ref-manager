#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""`/ref:discover --person <id>|--grant <id>` — §3c "Portfolio discovery".

Manually initiated only (D9) — the calling command markdown builds a query
from the person/grant record and calls the PubMed MCP search tool, then
hands the exact query text + candidate list here (same split as add.py:
this script never calls PubMed itself). Candidates require explicit
confirmation before becoming library additions (person.py confirm-
publication / reject-publication); rejected matches are retained so they
are never re-suggested.

Candidates are stored on the person record itself (people/<slug>.json) —
PLAN.md's §3 layout table doesn't name a separate discover/ directory, and
the person record already owns confirmed/candidate/rejected publication
state, so this reuses it rather than inventing a new location (flagged
assumption). Grant-scoped discovery isn't wired to a record yet since
grants/<slug>.json has no candidate-publication fields in Phase 0's
schema — out of Phase 2 scope; --grant errors clearly instead of silently
doing nothing.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import person as person_mod
from lib_ids import SlugError


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--person")
    ap.add_argument("--grant")
    ap.add_argument("--query-text", required=True)
    ap.add_argument("--candidates-file", required=True)
    args = ap.parse_args()

    library_root = Path(args.repo).expanduser().resolve()
    if not library_root.is_dir():
        print(f"error: no library at {library_root}", file=sys.stderr)
        return 1

    if args.grant and not args.person:
        print("error: --grant discovery is not implemented in phase 2 (grants have no "
              "candidate-publication fields yet); use --person", file=sys.stderr)
        return 1
    if not args.person:
        print("error: --person <id> is required", file=sys.stderr)
        return 1

    candidates = json.loads(Path(args.candidates_file).read_text())

    try:
        result = person_mod.add_candidates(library_root, args.person, args.query_text, candidates)
    except SlugError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
