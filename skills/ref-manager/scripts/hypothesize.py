#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""`/ref:hypothesize --concept <id>` -- Swanson ABC literature-based
discovery (PLAN.md §5b, D13).

Two-hop graph traversal (deterministic, no LLM) finds A-C candidate pairs;
checking a candidate against PubMed needs the PubMed MCP tool, which this
script can't call itself -- same command-markdown-calls-MCP-then-hands-
result-to-script split every prior phase uses (add.py/fetch.py/etc). So
this module has two entry points:
  `candidates()` -- pure graph traversal, no network, fully testable
  `finalize()`   -- attaches a PubMed check result (query/timestamp/pmids)
                    the calling agent already ran, and produces the final
                    ranked hypothesis records

Independence rule (§5b: "A-B edges from some papers, B-C from others"):
an A-B/B-C chain is excluded when the two edges are backed by the EXACT
SAME set of PMIDs -- that's one paper mentioning three things, not an
independent two-hop link. Any other overlap (partial, or none) counts as
independent; requiring fully-disjoint PMID sets would be too strict once
libraries grow and the same well-studied paper legitimately backs many
edges.

Ranking (design decision, not pinned by PLAN.md): candidates are ranked
by the number of independent A-B/B-C chain pairs supporting them (more
independent chains = higher-ranked candidate), tie-broken alphabetically
by the C concept_id for determinism. This is the simplest signal that's
actually meaningful (more independent routes to the same unstudied pair
is a stronger prior than one), without inventing a scoring model PLAN.md
never asked for.

Zero PubMed results is reported literally as "not found by this search"
-- never as "novel" or "confirmed gap" (§5b's closing line, and the
Phase 9 gate's exact wording). A nonzero result is reported as evidence
the connection may be studied in the wider literature but isn't in this
library yet -- informative, not disqualifying.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from relation import neighbors  # noqa: E402


def _edge_pmids(edge: dict) -> frozenset[str]:
    return frozenset(sc["pmid"] for sc in edge.get("supporting_claims", []))


def _concept_edges(library_root: Path, concept_id: str) -> list[tuple[str, dict]]:
    """[(other_concept_id, edge_dict), ...] for every relation touching
    concept_id, either direction."""
    n = neighbors(library_root, concept_id)
    out = []
    for e in n["outgoing"]:
        out.append((e["object_concept_id"], e))
    for e in n["incoming"]:
        out.append((e["subject_concept_id"], e))
    return out


def candidates(library_root: Path, concept_a: str) -> list[dict]:
    a_edges = _concept_edges(library_root, concept_a)
    # chains[c_id] = list of (b_id, ab_edge, bc_edge)
    chains: dict[str, list[tuple[str, dict, dict]]] = {}
    for b_id, ab_edge in a_edges:
        if b_id == concept_a:
            continue
        for c_id, bc_edge in _concept_edges(library_root, b_id):
            if c_id in (concept_a, b_id):
                continue
            if _edge_pmids(ab_edge) == _edge_pmids(bc_edge):
                continue  # same-paper-only chain, not independent (§5b)
            chains.setdefault(c_id, []).append((b_id, ab_edge, bc_edge))

    # exclude any C already directly connected to A
    existing_direct = {other for other, _ in a_edges}
    for c_id in list(chains):
        if c_id in existing_direct:
            del chains[c_id]

    out = []
    for c_id, chain_list in chains.items():
        out.append({
            "concept_a": concept_a, "concept_c": c_id,
            "chain_count": len(chain_list),
            "chains": [
                {
                    "concept_b": b_id,
                    "a_b_relation_id": ab["relation_id"], "a_b_type": ab["type"],
                    "a_b_supporting_claims": ab.get("supporting_claims", []),
                    "b_c_relation_id": bc["relation_id"], "b_c_type": bc["type"],
                    "b_c_supporting_claims": bc.get("supporting_claims", []),
                }
                for b_id, ab, bc in chain_list
            ],
        })
    out.sort(key=lambda h: (-h["chain_count"], h["concept_c"]))
    return out


def finalize(candidate: dict, pubmed_check: dict) -> dict:
    """pubmed_check: {"query": str, "retrieved_at": iso8601 str,
    "result_pmids": [str, ...]}. Attaches it and produces the final
    record with an explicit, non-generic limitations note."""
    n = len(pubmed_check.get("result_pmids", []))
    if n == 0:
        pubmed_note = f"Not found by this search ({pubmed_check['query']!r}) -- untested in the library, and this specific search found no evidence it's studied in the wider literature either. Not proof of novelty: a different query might find something this one didn't."
    else:
        pubmed_note = f"Untested in this library, but {n} PubMed result(s) for {pubmed_check['query']!r} suggest the connection may already be studied elsewhere -- this is a library-coverage gap, not necessarily a literature gap."
    return {
        **candidate,
        "pubmed_check": pubmed_check,
        "pubmed_note": pubmed_note,
        "limitations": (
            f"Candidate derived from {candidate['chain_count']} independent A-B/B-C chain(s) in this "
            f"library's graph between {candidate['concept_a']!r} and {candidate['concept_c']!r}. "
            "Missing edges describe library coverage, not established literature gaps (§5b). "
            "This is a reading-list candidate, not a validated claim."
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["candidates", "finalize"])
    ap.add_argument("--repo", required=True)
    ap.add_argument("--concept")
    ap.add_argument("--checks-file", help="finalize: JSON {concept_c_id: {query, retrieved_at, result_pmids}}")
    args = ap.parse_args()

    library_root = Path(args.repo).expanduser().resolve()

    if args.action == "candidates":
        if not args.concept:
            print("error: --concept is required", file=sys.stderr)
            return 1
        result = candidates(library_root, args.concept)
        print(json.dumps(result, indent=2))
        return 0

    # finalize
    if not args.concept or not args.checks_file:
        print("error: --concept and --checks-file are required for finalize", file=sys.stderr)
        return 1
    cands = candidates(library_root, args.concept)
    checks = json.loads(Path(args.checks_file).read_text())
    finalized = []
    for c in cands:
        check = checks.get(c["concept_c"])
        if check is None:
            continue  # calling agent chose not to check this candidate; omit rather than fabricate
        finalized.append(finalize(c, check))
    print(json.dumps(finalized, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
