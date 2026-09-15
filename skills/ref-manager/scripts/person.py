#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""`/ref:person` — people/<slug>.json: name variants, ORCID (when supplied),
dated affiliation history, confirmed/candidate publication matches (§3c)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from lib_atomic import atomic_write_json
from lib_ids import allocate_slug, SlugError
from lib_schema import validate_person, SchemaError


def _path(library_root: Path, slug: str) -> Path:
    return library_root / "people" / f"{slug}.json"


def create(library_root: Path, slug: str, name: str, orcid: str | None) -> dict:
    allocate_slug(library_root, "person", slug)
    person = {
        "slug": slug,
        "name_variants": [name],
        "orcid": orcid,
        "affiliations": [],
        "confirmed_publications": [],
        "candidate_publications": [],
    }
    validate_person(person)
    atomic_write_json(_path(library_root, slug), person)
    return person


def show(library_root: Path, slug: str) -> dict:
    p = _path(library_root, slug)
    if not p.exists():
        raise SlugError(f"person {slug!r} does not exist")
    return json.loads(p.read_text())


def list_people(library_root: Path) -> list[dict]:
    d = library_root / "people"
    out = []
    if d.is_dir():
        for f in sorted(d.glob("*.json")):
            person = json.loads(f.read_text())
            out.append({"slug": person["slug"], "name_variants": person["name_variants"]})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["create", "show", "list"])
    ap.add_argument("--repo", required=True)
    ap.add_argument("--slug")
    ap.add_argument("--name")
    ap.add_argument("--orcid")
    args = ap.parse_args()

    library_root = Path(args.repo).expanduser().resolve()
    if not library_root.is_dir():
        print(f"error: no library at {library_root}", file=sys.stderr)
        return 1

    try:
        if args.action == "create":
            result = create(library_root, args.slug, args.name, args.orcid)
        elif args.action == "show":
            result = show(library_root, args.slug)
        else:
            result = list_people(library_root)
    except (SlugError, SchemaError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
