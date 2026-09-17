# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Researcher/grant graph relationships (PLAN.md §5a closing paragraph):
"extend these with researcher-authored-publication, publication-acknowledges-
grant, publication-supports-aim, and dated researcher-lab membership
relationships. Acknowledgement and aim support remain distinct."

Written to graph/people_relations.jsonl, a SEPARATE file from
graph/relations.jsonl (owned by the concurrently-developed scientific
concept/claim graph in this same phase) -- deliberately, to avoid a schema
collision between two independently-designed relation shapes landing in one
file at merge time. Reconcile into one store later if that turns out to be
worth it; two well-typed stores beat one file with two conflicting shapes.

Four relation types, built from data that ALREADY exists from earlier
phases -- nothing here is inferred or fabricated:

  researcher_authored_publication
    from people/<slug>.json's confirmed_publications (phase 2 person.py/
    discover.py) -- a confirmed (pmid, author_index) pair becomes an edge.

  publication_acknowledges_grant
    from papers/<pmid>/funding.json's observations, matched against
    grants/<slug>.json's award_number/approved_aliases. Only emitted when a
    funding observation's award identifier actually matches a specific grant
    record -- a bare unlinked award string in funding.json with no matching
    grants/ record produces NO edge (there is nothing to link it to).

  publication_supports_aim
    Checked for a backing mechanism across every prior phase: grants/<slug>.json
    has a free-text `aims` field, but nothing in this codebase links a
    specific publication to a specific aim (no aim IDs exist, no phase 1-7
    command populates such a link). This relation type is schema-ready
    (the row shape below supports it) but UNPOPULATED -- reported as such,
    never heuristically inferred from e.g. a project's relevance note or a
    grant's free-text aims matching claim text, which would be exactly the
    "co-occurrence is not evidential support" mistake §5a warns against.

  researcher_lab_membership
    labs/<slug>.json is named in PLAN.md's §3 repo layout but no command in
    any phase (0-8) creates lab records -- there is no /ref:lab command in
    PLAN.md's own §3 command list. Schema-ready, UNPOPULATED, for the same
    reason as above: nothing to link because no lab data exists yet.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from lib_atomic import atomic_write_text


def _load_grants(library_root: Path) -> list[dict]:
    d = library_root / "grants"
    if not d.is_dir():
        return []
    return [json.loads(p.read_text()) for p in sorted(d.glob("*.json"))]


def _match_grant(observation: dict, grants: list[dict]) -> dict | None:
    """An observation matches a grant record when its award identifier
    (award_number field, or a raw grant dict's grant_id/raw string) equals
    the grant's award_number or one of its approved_aliases. Exact match
    only -- no fuzzy matching, that is a reviewed /ref:verify decision, not
    something this deterministic script should guess."""
    candidates = set()
    if observation.get("award_number"):
        candidates.add(observation["award_number"])
    g = observation.get("grant")
    if isinstance(g, dict):
        for k in ("grant_id", "raw"):
            if g.get(k):
                candidates.add(g[k])
    if not candidates:
        return None
    for grant in grants:
        known = {grant.get("award_number")} | set(grant.get("approved_aliases", []))
        if candidates & known:
            return grant
    return None


def build(library_root: Path) -> dict:
    relations: list[dict] = []

    people_dir = library_root / "people"
    if people_dir.is_dir():
        for p in sorted(people_dir.glob("*.json")):
            person = json.loads(p.read_text())
            for c in person.get("confirmed_publications", []):
                relations.append({
                    "relation_id": f"rap-{person['slug']}-{c['pmid']}-{c.get('author_index', 0)}",
                    "type": "researcher_authored_publication",
                    "person_slug": person["slug"], "pmid": c["pmid"],
                    "author_index": c.get("author_index"),
                })

    grants = _load_grants(library_root)
    papers_dir = library_root / "papers"
    if papers_dir.is_dir() and grants:
        for pmid_dir in sorted(p.name for p in papers_dir.iterdir() if p.is_dir()):
            funding_path = papers_dir / pmid_dir / "funding.json"
            if not funding_path.exists():
                continue
            funding = json.loads(funding_path.read_text())
            for obs in funding.get("observations", []):
                grant = _match_grant(obs, grants)
                if grant is not None:
                    relations.append({
                        "relation_id": f"pag-{pmid_dir}-{grant['slug']}",
                        "type": "publication_acknowledges_grant",
                        "pmid": pmid_dir, "grant_slug": grant["slug"],
                        "evidence_kind": obs.get("kind"),
                    })

    # publication_supports_aim, researcher_lab_membership: intentionally
    # empty, see module docstring.

    out_path = library_root / "graph" / "people_relations.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # sort for deterministic/idempotent output
    relations.sort(key=lambda r: r["relation_id"])
    text = "\n".join(json.dumps(r, sort_keys=True) for r in relations)
    if text:
        text += "\n"
    atomic_write_text(out_path, text)

    return {
        "researcher_authored_publication": sum(1 for r in relations if r["type"] == "researcher_authored_publication"),
        "publication_acknowledges_grant": sum(1 for r in relations if r["type"] == "publication_acknowledges_grant"),
        "publication_supports_aim": 0,
        "researcher_lab_membership": 0,
        "publication_supports_aim_note": "unpopulated -- no mechanism in any phase links a publication to a specific grant aim (§5a)",
        "researcher_lab_membership_note": "unpopulated -- no /ref:lab command exists in PLAN.md; labs/<slug>.json has no writer yet",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    args = ap.parse_args()
    library_root = Path(args.repo).expanduser().resolve()
    if not library_root.is_dir():
        print(f"error: no library at {library_root}", file=sys.stderr)
        return 1
    result = build(library_root)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
