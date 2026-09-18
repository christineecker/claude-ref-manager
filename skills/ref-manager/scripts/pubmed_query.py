#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""`/ref:query-pubmed` / `/ref:update-query` — immutable saved search runs
(D15, §5c "`--query <slug> [--run <id>]` — one immutable saved search run").

PICO parsing and the actual PubMed call happen in the calling command
markdown (same split as add.py) — this script only persists what it's
given: exact query string, source, retrieval date, result PMIDs. Runs
append; nothing is ever mutated or replaced, so a saved comparison never
silently changes membership underneath its conclusions.

queries/<slug>/query.yaml shape (lib_queries):
{"slug": "...", "runs": [{"run_id": "<opaque>", "query": "<exact expr>",
                           "source": "pubmed", "retrieved_at": "<iso8601>",
                           "pmids": ["..."]}]}
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from lib_atomic import atomic_write_json, now_iso
from lib_ids import allocate_slug, gen_opaque_id, SlugError
from lib_queries import query_file, query_slugs


def _path(library_root: Path, slug: str) -> Path:
    return query_file(library_root, slug)


def _load(library_root: Path, slug: str) -> dict:
    p = _path(library_root, slug)
    if not p.exists():
        raise SlugError(f"saved query {slug!r} does not exist")
    return json.loads(p.read_text())


def new_run(library_root: Path, slug: str, query_text: str, source: str, pmids: list[str], create: bool) -> dict:
    p = _path(library_root, slug)
    if not p.exists():
        if not create:
            raise SlugError(f"saved query {slug!r} does not exist (pass --create for a first run)")
        allocate_slug(library_root, "query", slug)
        doc = {"slug": slug, "runs": []}
    else:
        doc = _load(library_root, slug)

    run = {
        "run_id": gen_opaque_id("run-"),
        "query": query_text,
        "source": source,
        "retrieved_at": now_iso(),
        "pmids": pmids,
    }
    doc["runs"].append(run)
    atomic_write_json(p, doc)
    return run


def rerun(library_root: Path, slug: str, pmids: list[str], query_text: str | None = None) -> dict:
    """Re-run the query's own stored expression (D9: explicit manual re-run
    only) and append a new run — never mutates prior runs (§5c). A
    `query_text` records a user-refined expression for this run instead;
    added/removed are still reported against the prior run."""
    doc = _load(library_root, slug)
    if not doc["runs"]:
        raise SlugError(f"saved query {slug!r} has no prior run to re-run")
    last = doc["runs"][-1]
    run = {
        "run_id": gen_opaque_id("run-"),
        "query": query_text or last["query"],  # stored expression unless explicitly refined
        "source": last["source"],
        "retrieved_at": now_iso(),
        "pmids": pmids,
    }
    doc["runs"].append(run)
    atomic_write_json(_path(library_root, slug), doc)
    added = sorted(set(pmids) - set(last["pmids"]))
    removed = sorted(set(last["pmids"]) - set(pmids))
    return {"run": run, "added": added, "removed": removed}


def show(library_root: Path, slug: str) -> dict:
    return _load(library_root, slug)


def list_queries(library_root: Path) -> list[str]:
    return query_slugs(library_root)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["new-run", "rerun", "show", "list"])
    ap.add_argument("--repo", required=True)
    ap.add_argument("--slug")
    ap.add_argument("--query-text")
    ap.add_argument("--source", default="pubmed")
    ap.add_argument("--pmids-file")
    ap.add_argument("--create", action="store_true")
    args = ap.parse_args()

    library_root = Path(args.repo).expanduser().resolve()
    if not library_root.is_dir():
        print(f"error: no library at {library_root}", file=sys.stderr)
        return 1

    pmids = []
    if args.pmids_file:
        pmids = json.loads(Path(args.pmids_file).read_text())

    try:
        if args.action == "new-run":
            if not args.query_text:
                raise SlugError("--query-text is required for new-run")
            result = new_run(library_root, args.slug, args.query_text, args.source, pmids, args.create)
        elif args.action == "rerun":
            result = rerun(library_root, args.slug, pmids, args.query_text)
        elif args.action == "show":
            result = show(library_root, args.slug)
        else:
            result = list_queries(library_root)
    except SlugError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
