#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""graph/relations.jsonl -- typed edges between concepts (PLAN.md §4a, §3a).

WEAVE step (§4 pipeline [5]): compares two claims that are ALREADY mapped
to a concept pair (mapping happens inline in the calling command, per
concept.py's docstring) and proposes an edge type. This module's
`propose_relation()` is a pure function over two claim dicts plus their
concept-id mapping -- deterministic, testable, no LLM involved. Only
`potential_conflict` is ever auto-proposed; `contradicts` requires an
explicit human review decision via review_relation() (§4a: "`contradicts`
requires a recorded review decision and rationale").

Comparability (§4a): "Opposite directions under comparable contexts
create potential_conflict edges. Mismatched measures, comparators, follow-
up periods, or populations do not establish contradiction; missing
context lowers comparability." This is implemented as an exact,
case/whitespace-normalized match requirement on comparator, effect_measure,
timepoint, and population, with "unknown" on either side counting as a
mismatch (never a pass) -- conservative on purpose: a false "these aren't
comparable" is recoverable (a human can still relate them manually via
/ref:weave --force or a future review step), a false "these conflict" is
not (§4a's own reasoning, echoing phase 4's claim-supersession tradeoff:
prefer under-linking over inventing a conflict that wasn't earned).

Only "increase" vs "decrease" (in either order) counts as an opposite
direction pair -- "no significant difference"/"not reported" against
either is treated as inconclusive, not oppositional, since a null result
disagreeing with a positive one is a substantively different (and much
more common, much weaker) kind of disagreement that this simple pass
deliberately does not try to adjudicate automatically.

relations.jsonl row: see lib_schema.py's validate_relation() docstring
for the full shape and field meanings.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from lib_atomic import library_lock, now_iso, read_jsonl, write_jsonl
from lib_ids import gen_opaque_id, SlugError
from lib_schema import validate_relation, SchemaError, RELATION_TYPES

_PATH = "graph/relations.jsonl"
_OPPOSITE_DIRECTIONS = {("increase", "decrease"), ("decrease", "increase")}
_COMPARABLE_FIELDS = ("comparator", "effect_measure", "timepoint", "population")


def _norm(s) -> str:
    return " ".join((s or "").split()).casefold()


def _jsonl_path(library_root: Path) -> Path:
    return library_root / _PATH


def _read_all(library_root: Path) -> list[dict]:
    return read_jsonl(_jsonl_path(library_root))


def _write_all(library_root: Path, rows: list[dict]) -> None:
    write_jsonl(_jsonl_path(library_root), rows)


def comparable(claim_a: dict, claim_b: dict) -> tuple[bool, list[str]]:
    """Returns (is_comparable, mismatched_fields). A field mismatches if
    the two claims' normalized values differ OR either is "unknown"/empty
    (§4a: missing context lowers comparability, it does not pass by
    default)."""
    mismatched = []
    for f in _COMPARABLE_FIELDS:
        va, vb = claim_a.get(f), claim_b.get(f)
        if _norm(va) in ("", "unknown") or _norm(vb) in ("", "unknown") or _norm(va) != _norm(vb):
            mismatched.append(f)
    return (not mismatched, mismatched)


def opposite_directions(claim_a: dict, claim_b: dict) -> bool:
    da, db = _norm(claim_a.get("direction")), _norm(claim_b.get("direction"))
    return (da, db) in _OPPOSITE_DIRECTIONS


def propose_relation(claim_a: dict, claim_b: dict, subject_concept_id: str, object_concept_id: str) -> dict | None:
    """claim_a/claim_b must each carry at least: pmid, claim_id, version_id,
    direction, comparator, effect_measure, timepoint, population. Returns a
    proposal dict (not yet persisted) for a `potential_conflict` edge, or
    None if the claims aren't an opposite-direction comparable pair. This
    NEVER returns `contradicts` -- that only happens via review_relation()."""
    if not opposite_directions(claim_a, claim_b):
        return None
    ok, mismatched = comparable(claim_a, claim_b)
    if not ok:
        return None
    return {
        "type": "potential_conflict",
        "subject_concept_id": subject_concept_id,
        "object_concept_id": object_concept_id,
        "supporting_claims": [
            {"pmid": claim_a["pmid"], "claim_id": claim_a["claim_id"]},
            {"pmid": claim_b["pmid"], "claim_id": claim_b["claim_id"]},
        ],
        "source_version_ids": sorted({v for v in (claim_a.get("version_id"), claim_b.get("version_id")) if v}),
    }


def create_relation(library_root: Path, rel_type: str, subject_concept_id: str, object_concept_id: str,
                     supporting_claims: list[dict], source_version_ids: list[str] | None = None) -> dict:
    if rel_type == "contradicts":
        raise SchemaError(
            "create_relation() cannot mint a 'contradicts' edge directly -- "
            "create it as 'potential_conflict' (or another type) first, then "
            "promote via review_relation() with an explicit rationale (§4a)"
        )
    now = now_iso()
    row = {
        "relation_id": gen_opaque_id("rel-"), "type": rel_type,
        "subject_concept_id": subject_concept_id, "object_concept_id": object_concept_id,
        "supporting_claims": supporting_claims, "source_version_ids": source_version_ids or [],
        "review_state": "unreviewed", "rationale": None,
        "stale": False, "created_at": now, "updated_at": now,
    }
    validate_relation(row)
    with library_lock(library_root):
        rows = _read_all(library_root)
        rows.append(row)
        _write_all(library_root, rows)
    return row


def review_relation(library_root: Path, relation_id: str, new_type: str, reviewer: str, rationale: str | None) -> dict:
    """Promote/demote a relation's type via explicit human decision.
    Promoting to "contradicts" requires a non-empty rationale (§4a) --
    refused otherwise. Reviewing also clears `stale` (a review is by
    definition a fresh look at current evidence -- see refresh_relations()'s
    docstring for why staleness otherwise persists until explicitly
    reconfirmed)."""
    with library_lock(library_root):
        rows = _read_all(library_root)
        target = next((r for r in rows if r["relation_id"] == relation_id), None)
        if target is None:
            raise SlugError(f"relation {relation_id!r} does not exist")
        if new_type == "contradicts" and not (rationale or "").strip():
            raise SchemaError(
                "promoting to 'contradicts' requires a non-empty rationale -- "
                "never auto-promoted from potential_conflict (§4a)"
            )
        target["type"] = new_type
        target["review_state"] = "reviewed"
        target["rationale"] = rationale
        target["reviewer"] = reviewer
        target["reviewed_at"] = now_iso()
        target["stale"] = False
        target["updated_at"] = now_iso()
        validate_relation(target)
        _write_all(library_root, rows)
        return target


def refresh_relations(library_root: Path) -> dict:
    """Recompute `stale` across every relation by checking whether each
    supporting claim is still active in its paper's claim_registry.json
    (§3a: "Re-extraction invalidates affected evidence links and triggers
    an incremental graph refresh"). Idempotent, safe to run repeatedly.

    Going stale NEVER clears review_state/rationale -- a reviewed
    "contradicts" edge stays reviewed with its rationale intact, just
    flagged stale, until someone explicitly reconfirms it via
    review_relation() (which clears stale as a side effect of a fresh
    review). This mirrors §3b's claim-correction pending_review pattern:
    changed evidence flags for re-confirmation, it never silently
    re-applies or silently drops the prior decision.
    """
    registries: dict[str, dict] = {}

    def _claim_active(pmid: str, claim_id: str) -> bool:
        if pmid not in registries:
            p = library_root / "papers" / pmid / "claim_registry.json"
            registries[pmid] = json.loads(p.read_text()) if p.exists() else {"claims": {}}
        entry = registries[pmid]["claims"].get(claim_id)
        if entry is None:
            return False
        return entry.get("status") == "active" and not entry.get("excluded_from_synthesis")

    went_stale = []
    with library_lock(library_root):
        rows = _read_all(library_root)
        for row in rows:
            all_active = all(_claim_active(sc["pmid"], sc["claim_id"]) for sc in row["supporting_claims"])
            if not all_active and not row["stale"]:
                row["stale"] = True
                row["stale_reason"] = "one or more supporting claims are no longer active (superseded or excluded)"
                row["updated_at"] = now_iso()
                went_stale.append(row["relation_id"])
        _write_all(library_root, rows)
    return {"relations_checked": len(rows), "went_stale": went_stale}


def get_relation(library_root: Path, relation_id: str) -> dict | None:
    return next((r for r in _read_all(library_root) if r["relation_id"] == relation_id), None)


def neighbors(library_root: Path, concept_id: str) -> dict:
    """get_neighbors-shaped query (§5's structural retrieval layer): every
    relation touching this concept, split by direction, each carrying its
    full supporting-claim evidence trail. This is a local JSONL scan, not
    the okf plugin's own get_neighbors (which will traverse the generated
    OKF bundle another phase-8 agent builds) -- kept separate on purpose so
    this module has zero dependency on OKF generation landing first."""
    outgoing, incoming = [], []
    for row in _read_all(library_root):
        if row["subject_concept_id"] == concept_id:
            outgoing.append(row)
        if row["object_concept_id"] == concept_id:
            incoming.append(row)
    return {"concept_id": concept_id, "outgoing": outgoing, "incoming": incoming}


def list_relations(library_root: Path) -> list[dict]:
    return _read_all(library_root)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=[
        "propose", "create", "create-manual", "review", "refresh", "show", "list", "neighbors",
    ])
    ap.add_argument("--repo", required=True)
    ap.add_argument("--id")
    ap.add_argument("--type")
    ap.add_argument("--reviewer", default="user")
    ap.add_argument("--rationale")
    ap.add_argument("--concept")
    ap.add_argument("--claim-a-file")
    ap.add_argument("--claim-b-file")
    ap.add_argument("--subject-concept")
    ap.add_argument("--object-concept")
    args = ap.parse_args()

    library_root = Path(args.repo).expanduser().resolve()
    if not library_root.is_dir():
        print(f"error: no library at {library_root}", file=sys.stderr)
        return 1

    try:
        if args.action == "propose":
            claim_a = json.loads(Path(args.claim_a_file).read_text())
            claim_b = json.loads(Path(args.claim_b_file).read_text())
            result = propose_relation(claim_a, claim_b, args.subject_concept, args.object_concept)
        elif args.action == "create":
            claim_a = json.loads(Path(args.claim_a_file).read_text())
            claim_b = json.loads(Path(args.claim_b_file).read_text())
            proposal = propose_relation(claim_a, claim_b, args.subject_concept, args.object_concept)
            if proposal is None:
                print("error: these claims are not an opposite-direction, comparable pair "
                      "-- nothing to create", file=sys.stderr)
                return 1
            result = create_relation(
                library_root, proposal["type"], proposal["subject_concept_id"],
                proposal["object_concept_id"], proposal["supporting_claims"],
                proposal["source_version_ids"],
            )
        elif args.action == "create-manual":
            # Found live during phase 9 (gaps.py's real graph testing needed
            # supports/extends/replicates edges, which "create" can't mint --
            # it always goes through propose_relation()'s opposite-direction
            # comparability check, so it can only ever produce
            # potential_conflict). create_relation() itself already accepts
            # any non-"contradicts" type; this path just exposes that
            # directly for a human/calling-agent judgment call that isn't a
            # claim-pair auto-comparison (e.g. "paper B explicitly extends
            # paper A's method" is a human/synthesis-agent's reading of the
            # papers, not something propose_relation()'s deterministic check
            # can derive from PICO fields alone).
            if not args.type:
                print("error: --type required for create-manual "
                      f"(one of {RELATION_TYPES})", file=sys.stderr)
                return 1
            claims = json.loads(Path(args.claim_a_file).read_text()) if args.claim_a_file else []
            if not isinstance(claims, list):
                claims = [claims]
            result = create_relation(
                library_root, args.type, args.subject_concept, args.object_concept,
                claims, [],
            )
        elif args.action == "review":
            result = review_relation(library_root, args.id, args.type, args.reviewer, args.rationale)
        elif args.action == "refresh":
            result = refresh_relations(library_root)
        elif args.action == "show":
            result = get_relation(library_root, args.id)
        elif args.action == "neighbors":
            result = neighbors(library_root, args.concept)
        else:
            result = list_relations(library_root)
    except (SlugError, SchemaError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
