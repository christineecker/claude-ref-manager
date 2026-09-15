#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""`/ref:grant` — grants/<slug>.json: funder, award number, approved aliases,
title, dates, optional PI links, aims (§3c)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from lib_atomic import atomic_write_json
from lib_ids import allocate_slug, SlugError
from lib_schema import validate_grant, SchemaError


def _path(library_root: Path, slug: str) -> Path:
    return library_root / "grants" / f"{slug}.json"


def create(
    library_root: Path, slug: str, funder: str, award_number: str,
    title: str | None, pi: str | None, aims: str | None,
) -> dict:
    allocate_slug(library_root, "grant", slug)
    grant = {
        "slug": slug,
        "funder": funder,
        "award_number": award_number,
        "approved_aliases": [award_number],
        "title": title,
        "pi": pi,
        "aims": aims,
        "publication_links": [],
    }
    validate_grant(grant)
    atomic_write_json(_path(library_root, slug), grant)
    return grant


def add_alias(library_root: Path, slug: str, alias: str) -> dict:
    p = _path(library_root, slug)
    if not p.exists():
        raise SlugError(f"grant {slug!r} does not exist")
    grant = json.loads(p.read_text())
    if alias not in grant["approved_aliases"]:
        grant["approved_aliases"].append(alias)
        atomic_write_json(p, grant)
    return grant


def show(library_root: Path, slug: str) -> dict:
    p = _path(library_root, slug)
    if not p.exists():
        raise SlugError(f"grant {slug!r} does not exist")
    return json.loads(p.read_text())


def list_grants(library_root: Path) -> list[dict]:
    d = library_root / "grants"
    out = []
    if d.is_dir():
        for f in sorted(d.glob("*.json")):
            g = json.loads(f.read_text())
            out.append({"slug": g["slug"], "funder": g["funder"], "award_number": g["award_number"]})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["create", "add-alias", "show", "list"])
    ap.add_argument("--repo", required=True)
    ap.add_argument("--slug")
    ap.add_argument("--funder")
    ap.add_argument("--award")
    ap.add_argument("--alias")
    ap.add_argument("--title")
    ap.add_argument("--pi")
    ap.add_argument("--aims")
    args = ap.parse_args()

    library_root = Path(args.repo).expanduser().resolve()
    if not library_root.is_dir():
        print(f"error: no library at {library_root}", file=sys.stderr)
        return 1

    try:
        if args.action == "create":
            result = create(library_root, args.slug, args.funder, args.award, args.title, args.pi, args.aims)
        elif args.action == "add-alias":
            result = add_alias(library_root, args.slug, args.alias)
        elif args.action == "show":
            result = show(library_root, args.slug)
        else:
            result = list_grants(library_root)
    except (SlugError, SchemaError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
