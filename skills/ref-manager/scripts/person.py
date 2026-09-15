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
        "confirmed_publications": [],   # [{"pmid": "...", "author_index": N}]
        "candidate_publications": [],   # from /ref:discover, pending confirmation
        "rejected_publications": [],    # retained to prevent repeated suggestion (§3c)
    }
    validate_person(person)
    atomic_write_json(_path(library_root, slug), person)
    return person


def show(library_root: Path, slug: str) -> dict:
    p = _path(library_root, slug)
    if not p.exists():
        raise SlugError(f"person {slug!r} does not exist")
    return json.loads(p.read_text())


def confirm_publication(library_root: Path, slug: str, pmid: str, author_index: int) -> dict:
    """Link a specific author-list position to this person — the evidenced
    identity match §3c requires before a role can be assigned (never
    inferred from name similarity alone)."""
    person = show(library_root, slug)
    person.setdefault("rejected_publications", [])
    person["candidate_publications"] = [
        c for c in person.get("candidate_publications", []) if c.get("pmid") != pmid
    ]
    if not any(c["pmid"] == pmid for c in person["confirmed_publications"]):
        person["confirmed_publications"].append({"pmid": pmid, "author_index": author_index})
    atomic_write_json(_path(library_root, slug), person)
    return person


def reject_publication(library_root: Path, slug: str, pmid: str) -> dict:
    person = show(library_root, slug)
    person.setdefault("rejected_publications", [])
    person["candidate_publications"] = [
        c for c in person.get("candidate_publications", []) if c.get("pmid") != pmid
    ]
    if pmid not in person["rejected_publications"]:
        person["rejected_publications"].append(pmid)
    atomic_write_json(_path(library_root, slug), person)
    return person


def add_candidates(library_root: Path, slug: str, query_text: str, candidates: list[dict]) -> dict:
    """Persist a /ref:discover run: exact query, retrieval date, candidates
    (§3c "Portfolio discovery"). Rejected pmids are never re-suggested."""
    from datetime import datetime, timezone

    person = show(library_root, slug)
    rejected = set(person.get("rejected_publications", []))
    confirmed = {c["pmid"] for c in person["confirmed_publications"]}
    person.setdefault("discovery_runs", [])
    new_candidates = [c for c in candidates if c["pmid"] not in rejected and c["pmid"] not in confirmed]
    person["discovery_runs"].append({
        "query": query_text,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "candidate_count": len(new_candidates),
    })
    existing_pmids = {c["pmid"] for c in person["candidate_publications"]}
    for c in new_candidates:
        if c["pmid"] not in existing_pmids:
            person["candidate_publications"].append(c)
    atomic_write_json(_path(library_root, slug), person)
    return person


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
    ap.add_argument("action", choices=[
        "create", "show", "list", "confirm-publication", "reject-publication",
    ])
    ap.add_argument("--repo", required=True)
    ap.add_argument("--slug")
    ap.add_argument("--name")
    ap.add_argument("--orcid")
    ap.add_argument("--pmid")
    ap.add_argument("--author-index", type=int)
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
        elif args.action == "confirm-publication":
            result = confirm_publication(library_root, args.slug, args.pmid, args.author_index)
        elif args.action == "reject-publication":
            result = reject_publication(library_root, args.slug, args.pmid)
        else:
            result = list_people(library_root)
    except (SlugError, SchemaError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
