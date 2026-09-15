#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""`/ref:publications --person <id> --role <role>` incl. `--coauthors` (§3c).

Author role classification (sole/first/last/middle, mutually exclusive) and
collaborator-declaration export, built entirely from committed
authorship.json + person.confirmed_publications records — evidenced
identity links, never name-similarity guesses.

authorship.json (extended here, optionally, beyond phase-1's minimal shape):
  "complete": bool          # default True if absent; False -> role "unresolved"
  authors[i]: {"last", "first", "raw", "affiliation"? , "is_group"?}
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _meta(library_root: Path, pmid: str) -> dict:
    return json.loads((library_root / "papers" / pmid / "meta.json").read_text())


def _authorship(library_root: Path, pmid: str) -> dict:
    p = library_root / "papers" / pmid / "authorship.json"
    if not p.exists():
        return {"authors": [], "complete": True}
    doc = json.loads(p.read_text())
    doc.setdefault("complete", True)
    return doc


def _person(library_root: Path, slug: str) -> dict:
    return json.loads((library_root / "people" / f"{slug}.json").read_text())


def _all_people(library_root: Path) -> list[dict]:
    d = library_root / "people"
    return [json.loads(f.read_text()) for f in sorted(d.glob("*.json"))] if d.is_dir() else []


def classify_role(author_index: int | None, total: int, complete: bool) -> str:
    if not complete or author_index is None or author_index >= total:
        return "unresolved"
    if total == 1:
        return "sole"
    if author_index == 0:
        return "first"
    if author_index == total - 1:
        return "last"
    return "middle"


def roles(library_root: Path, person_slug: str, role_filter: str | None) -> list[dict]:
    person = _person(library_root, person_slug)
    out = []
    for cp in person.get("confirmed_publications", []):
        pmid, idx = cp["pmid"], cp["author_index"]
        auth = _authorship(library_root, pmid)
        total = len(auth.get("authors", []))
        role = classify_role(idx, total, auth.get("complete", True))
        if role_filter and role != role_filter:
            continue
        out.append({"pmid": pmid, "author_index": idx, "role": role, "author_count": total})
    return out


def _find_confirmed_identity(library_root: Path, pmid: str, author_index: int, exclude_slug: str) -> str | None:
    for p in _all_people(library_root):
        if p["slug"] == exclude_slug:
            continue
        for cp in p.get("confirmed_publications", []):
            if cp["pmid"] == pmid and cp["author_index"] == author_index:
                return p["slug"]
    return None


def _find_ambiguous_name_person(library_root: Path, name: str, exclude_slug: str) -> str | None:
    for p in _all_people(library_root):
        if p["slug"] == exclude_slug:
            continue
        if name in p.get("name_variants", []):
            return p["slug"]
    return None


def coauthors(library_root: Path, person_slug: str, since: str, until: str | None) -> dict:
    person = _person(library_root, person_slug)
    since_y, until_y = since[:4], (until[:4] if until else None)

    rows: dict[tuple, dict] = {}
    unconfirmed_candidates: dict[str, dict] = {}
    gaps: list[dict] = []

    for cp in person.get("confirmed_publications", []):
        pmid, self_idx = cp["pmid"], cp["author_index"]
        meta = _meta(library_root, pmid)
        year = str(meta.get("year") or "")[:4]
        if year < since_y or (until_y and year > until_y):
            continue

        auth = _authorship(library_root, pmid)
        authors = auth.get("authors", [])
        if not auth.get("complete", True):
            gaps.append({"pmid": pmid, "reason": "incomplete author list"})

        for i, a in enumerate(authors):
            if i == self_idx:
                continue
            if a.get("is_group"):
                key = ("group", a.get("raw") or a.get("last", ""))
                name = a.get("raw") or a.get("last", "")
                method = "group"
            else:
                name = a.get("raw") or f"{a.get('last', '')} {a.get('first', '')}".strip()
                confirmed_slug = _find_confirmed_identity(library_root, pmid, i, person_slug)
                if confirmed_slug:
                    key = ("confirmed_identity", confirmed_slug)
                    method = "confirmed_identity"
                else:
                    ambiguous_slug = _find_ambiguous_name_person(library_root, name, person_slug)
                    if ambiguous_slug:
                        cand = unconfirmed_candidates.setdefault(name, {
                            "name": name, "candidate_person": ambiguous_slug, "pmids": [],
                        })
                        if pmid not in cand["pmids"]:
                            cand["pmids"].append(pmid)
                        continue
                    key = ("exact_name", name)
                    method = "exact_name"

            row = rows.setdefault(key, {
                "name": name, "identity_method": method, "affiliation": None,
                "most_recent_pub": None, "pmids": [],
            })
            if pmid not in row["pmids"]:
                row["pmids"].append(pmid)
            if a.get("affiliation"):
                row["affiliation"] = a["affiliation"]
            if row["most_recent_pub"] is None or year > row["most_recent_pub"]:
                row["most_recent_pub"] = year

    return {
        "person": person_slug,
        "since": since,
        "until": until,
        "coauthors": sorted(rows.values(), key=lambda r: r["name"]),
        "unconfirmed_candidates": sorted(unconfirmed_candidates.values(), key=lambda r: r["name"]),
        "gaps": gaps,
        "scope_note": "derived from library holdings, not a complete publication record (§3c)",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--person", required=True)
    ap.add_argument("--role")
    ap.add_argument("--coauthors", action="store_true")
    ap.add_argument("--since")
    ap.add_argument("--to")
    args = ap.parse_args()

    library_root = Path(args.repo).expanduser().resolve()
    if not library_root.is_dir():
        print(f"error: no library at {library_root}", file=sys.stderr)
        return 1

    if args.coauthors:
        if not args.since:
            print("error: --coauthors requires --since <date>", file=sys.stderr)
            return 1
        result = coauthors(library_root, args.person, args.since, args.to)
    else:
        result = roles(library_root, args.person, args.role)

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
