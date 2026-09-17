#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""graph/concepts.jsonl -- stable concept nodes with accumulating aliases
(PLAN.md §3, §3d, D13).

Concept mapping (turning a claim's free-text population/intervention/
outcome/etc. into a concept node) needs judgment -- PLAN.md names no
subagent for it (only ref-extractor and ref-synthesizer exist, neither
fits; same reasoning phase 7 already applied to /ref:check-citations).
So the calling command does mapping inline: before minting a new concept
it MUST call find_concept() to check for an existing name/alias match,
so "MI" and "myocardial infarction" end up as two aliases of one concept
instead of two concepts. This script only validates and persists what
the calling agent decides -- it never guesses a match itself beyond
exact (case-insensitive, whitespace-normalized) string comparison.

concepts.jsonl row:
{"concept_id": "<slug>", "name": "<canonical display name>",
 "aliases": ["<string>", ...],
 "alias_provenance": {"<alias, case-preserved as first seen>":
     {"source": "claim:<pmid>:<claim_id>" | "manual", "added_at": "..."}},
 "created_at": "...", "updated_at": "..."}

`name` itself counts as an implicit alias for matching purposes but is
not duplicated into the `aliases` list.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from lib_atomic import library_lock, now_iso, read_jsonl, write_jsonl
from lib_ids import allocate_slug, SlugError
from lib_schema import validate_concept, SchemaError

_PATH = "graph/concepts.jsonl"


def _norm(s: str) -> str:
    return " ".join((s or "").split()).casefold()


def _jsonl_path(library_root: Path) -> Path:
    return library_root / _PATH


def _read_all(library_root: Path) -> list[dict]:
    return read_jsonl(_jsonl_path(library_root))


def _write_all(library_root: Path, rows: list[dict]) -> None:
    write_jsonl(_jsonl_path(library_root), rows)


def find_concept(library_root: Path, name_or_alias: str) -> dict | None:
    """Case-insensitive, whitespace-normalized match against a concept's
    name or any of its aliases. Returns the full concept row, or None."""
    target = _norm(name_or_alias)
    for row in _read_all(library_root):
        if _norm(row["name"]) == target:
            return row
        if any(_norm(a) == target for a in row["aliases"]):
            return row
    return None


def create_concept(library_root: Path, concept_id: str, name: str,
                    initial_aliases: list[str] | None = None,
                    source: str = "manual") -> dict:
    existing = find_concept(library_root, name)
    if existing is not None:
        raise SlugError(
            f"a concept already matches {name!r}: {existing['concept_id']!r} "
            f"(name={existing['name']!r}) -- use find_concept()/add_alias() "
            "instead of minting a duplicate"
        )
    allocate_slug(library_root, "concept", concept_id)
    now = now_iso()
    row = {
        "concept_id": concept_id, "name": name, "aliases": [],
        "alias_provenance": {}, "created_at": now, "updated_at": now,
    }
    with library_lock(library_root):
        rows = _read_all(library_root)
        rows.append(row)
        _write_all(library_root, rows)
    if initial_aliases:
        for a in initial_aliases:
            add_alias(library_root, concept_id, a, source)
        row = get_concept(library_root, concept_id)
    validate_concept(row)
    return row


def add_alias(library_root: Path, concept_id: str, alias: str, source: str) -> dict:
    """No-op (besides updated_at) if this alias (or the concept's own name)
    already resolves here. Refuses if the alias would collide with a
    DIFFERENT concept -- that's a merge decision, not something this
    function does silently."""
    with library_lock(library_root):
        rows = _read_all(library_root)
        target = None
        for row in rows:
            if row["concept_id"] == concept_id:
                target = row
                break
        if target is None:
            raise SlugError(f"concept {concept_id!r} does not exist")

        norm_alias = _norm(alias)
        if _norm(target["name"]) == norm_alias or any(_norm(a) == norm_alias for a in target["aliases"]):
            return target  # already resolves here, nothing to do

        for row in rows:
            if row["concept_id"] == concept_id:
                continue
            if _norm(row["name"]) == norm_alias or any(_norm(a) == norm_alias for a in row["aliases"]):
                raise SlugError(
                    f"alias {alias!r} already resolves to a DIFFERENT concept "
                    f"{row['concept_id']!r} -- this is a merge decision, not "
                    "an automatic alias addition"
                )

        target["aliases"].append(alias)
        target["alias_provenance"][alias] = {"source": source, "added_at": now_iso()}
        target["updated_at"] = now_iso()
        validate_concept(target)
        _write_all(library_root, rows)
        return target


def get_concept(library_root: Path, concept_id: str) -> dict | None:
    for row in _read_all(library_root):
        if row["concept_id"] == concept_id:
            return row
    return None


def list_concepts(library_root: Path) -> list[dict]:
    return _read_all(library_root)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["create", "find", "add-alias", "show", "list"])
    ap.add_argument("--repo", required=True)
    ap.add_argument("--id")
    ap.add_argument("--name")
    ap.add_argument("--alias")
    ap.add_argument("--source", default="manual")
    args = ap.parse_args()

    library_root = Path(args.repo).expanduser().resolve()
    if not library_root.is_dir():
        print(f"error: no library at {library_root}", file=sys.stderr)
        return 1

    try:
        if args.action == "create":
            result = create_concept(library_root, args.id, args.name)
        elif args.action == "find":
            result = find_concept(library_root, args.name)
        elif args.action == "add-alias":
            result = add_alias(library_root, args.id, args.alias, args.source)
        elif args.action == "show":
            result = get_concept(library_root, args.id)
        else:
            result = list_concepts(library_root)
    except (SlugError, SchemaError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
