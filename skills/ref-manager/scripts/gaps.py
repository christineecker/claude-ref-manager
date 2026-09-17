#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""`/ref:gaps <selector>` -- structural gap queries over already-committed
concept/relation/claim tables (PLAN.md §5b, D13). No LLM judgment: every
gap type here is a deterministic query, unlike phase 4/6/7/8's judgment
steps. Findings always cite the specific claim_ids/relation_ids/pmids they
rest on -- never an unevidenced summary.

Four gap types (§5b), each its own function below:
  1. single_study_fragile   -- a claim backed by only one study
  2. unresolved_conflicts   -- potential_conflict (unreviewed) or
                                contradicts (gone stale) relations
  3. co_mentioned_ungrouped -- concept pairs whose names/aliases appear
                                together in a claim's evidence_span, with
                                no relation edge between their concepts
  4. population_outcome_gap -- for one intervention concept, a
                                population x outcome combination with zero
                                claims where a "sibling" combination
                                (same intervention, different population
                                or outcome) has at least one claim.
                                Population/outcome values that exactly
                                match (case-insensitively) a concept's name
                                or alias are folded onto that concept's
                                name; unmapped values stay as written --
                                never a fuzzy merge.

Fragility boundary (design decision, not pinned by PLAN.md): a claim is
NOT single-study-fragile if either (a) its paper belongs to a confirmed
study group (studies.jsonl, phase 5) with >=2 member PMIDs -- the paper
isn't evidentially alone even if this specific claim wasn't independently
re-reported by the sibling papers, since the study grouping IS the
recorded evidence that these publications describe one investigation --
or (b) some other claim, from a DIFFERENT pmid, appears alongside it as a
supporting_claim on the same non-potential_conflict/non-contradicts
relation (a `supports`/`extends`/`replicates` edge is itself a recorded
corroboration). Everything else is fragile. This deliberately does not
try to detect corroboration that was never turned into a relation edge --
that's exactly the kind of graph-based structural query §5b asks for, not
a text-similarity heuristic.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from concept import find_concept, list_concepts  # noqa: E402
from relation import list_relations  # noqa: E402
from study import study_for_pmid  # noqa: E402
import lib_selector  # noqa: E402
from lib_schema import clean_claim_value  # noqa: E402


def _active_claims(library_root: Path, pmids: list[str]) -> list[dict]:
    out = []
    for pmid in pmids:
        reg_path = library_root / "papers" / pmid / "claim_registry.json"
        if not reg_path.exists():
            continue
        reg = json.loads(reg_path.read_text())
        for c in reg["claims"].values():
            if c.get("status") == "active" and not c.get("excluded_from_synthesis"):
                out.append(c)
    return out


def single_study_fragile(library_root: Path, pmids: list[str]) -> list[dict]:
    claims = _active_claims(library_root, pmids)
    relations = list_relations(library_root)

    corroborated_claim_ids: set[str] = set()
    for r in relations:
        if r["type"] in ("potential_conflict", "contradicts"):
            continue
        supporting = r.get("supporting_claims", [])
        pmids_in_relation = {sc["pmid"] for sc in supporting}
        if len(pmids_in_relation) >= 2:
            corroborated_claim_ids.update(sc["claim_id"] for sc in supporting)

    findings = []
    for c in claims:
        study = study_for_pmid(library_root, c["pmid"])
        in_multi_paper_study = bool(study) and len(study.get("pmids", [])) >= 2
        if in_multi_paper_study or c["claim_id"] in corroborated_claim_ids:
            continue
        findings.append({
            "gap_type": "single_study_fragile",
            "claim_id": c["claim_id"], "pmid": c["pmid"],
            "outcome": c.get("outcome"), "intervention": c.get("intervention"),
        })
    return findings


def unresolved_conflicts(library_root: Path, pmids: list[str] | None = None) -> list[dict]:
    pmid_set = set(pmids) if pmids else None
    findings = []
    for r in list_relations(library_root):
        if r["type"] not in ("potential_conflict", "contradicts"):
            continue
        if pmid_set is not None:
            relation_pmids = {sc["pmid"] for sc in r.get("supporting_claims", [])}
            if not (relation_pmids & pmid_set):
                continue
        unresolved = (r["type"] == "potential_conflict" and r.get("review_state") != "reviewed") or \
                     (r["type"] == "contradicts" and r.get("stale"))
        if not unresolved:
            continue
        findings.append({
            "gap_type": "unresolved_conflict",
            "relation_id": r["relation_id"], "type": r["type"],
            "stale": r.get("stale", False),
            "subject_concept_id": r["subject_concept_id"], "object_concept_id": r["object_concept_id"],
            "supporting_claims": r.get("supporting_claims", []),
        })
    return findings


def co_mentioned_ungrouped(library_root: Path, pmids: list[str]) -> list[dict]:
    claims = _active_claims(library_root, pmids)
    concepts = list_concepts(library_root)
    relations = list_relations(library_root)
    edge_pairs = {frozenset((r["subject_concept_id"], r["object_concept_id"])) for r in relations}

    names = {}  # concept_id -> lowercased [name, *aliases]
    for c in concepts:
        names[c["concept_id"]] = [c["name"].lower()] + [a.lower() for a in c.get("aliases", [])]

    findings = []
    seen_pairs = set()
    concept_ids = list(names)
    for c in claims:
        text = (c.get("evidence_span") or "").lower()
        if not text:
            continue
        mentioned = [cid for cid in concept_ids if any(term in text for term in names[cid])]
        for i in range(len(mentioned)):
            for j in range(i + 1, len(mentioned)):
                a, b = mentioned[i], mentioned[j]
                pair = frozenset((a, b))
                if pair in edge_pairs or pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                findings.append({
                    "gap_type": "co_mentioned_ungrouped",
                    "concept_a": a, "concept_b": b,
                    "claim_id": c["claim_id"], "pmid": c["pmid"],
                })
    return findings


def population_outcome_gap(library_root: Path, pmids: list[str], intervention_concept_id: str) -> list[dict]:
    claims = _active_claims(library_root, pmids)
    concept = next((c for c in list_concepts(library_root) if c["concept_id"] == intervention_concept_id), None)
    if concept is None:
        raise ValueError(f"no such concept: {intervention_concept_id!r}")
    names = {concept["name"].lower(), *[a.lower() for a in concept.get("aliases", [])]}

    # Placeholder values ("unknown", "not reported", ...) are not a population
    # or outcome, and whitespace variants are one value (lib_schema). A value
    # that is some concept's name or alias is that concept -- "preschool ASD"
    # and "preschool children with autism" are one row once /ref:concept has
    # recorded the alias. The dashboard's population x outcome grid applies
    # the same rule (insights.js populationOutcomeGaps).
    canonical: dict[str, str] = {}
    for other in list_concepts(library_root):
        for term in [other["name"], *other.get("aliases", [])]:
            canonical.setdefault(term.lower(), other["name"])

    def field(c, name):
        value = clean_claim_value(c.get(name))
        return canonical.get(value.lower(), value) if value else None

    own = [c for c in claims if (clean_claim_value(c.get("intervention")) or "").lower() in names]
    if not own:
        return []

    populations = sorted({field(c, "population") for c in own} - {None})
    outcomes = sorted({field(c, "outcome") for c in own} - {None})
    covered = {(field(c, "population"), field(c, "outcome")) for c in own}

    findings = []
    for p in populations:
        for o in outcomes:
            if (p, o) in covered:
                continue
            backing_pop = [c["claim_id"] for c in own if field(c, "population") == p]
            backing_outcome = [c["claim_id"] for c in own if field(c, "outcome") == o]
            findings.append({
                "gap_type": "population_outcome_gap",
                "intervention_concept_id": intervention_concept_id,
                "missing_population": p, "missing_outcome": o,
                "population_evidenced_by": backing_pop,
                "outcome_evidenced_by": backing_outcome,
            })
    return findings


def main() -> int:
    ap = argparse.ArgumentParser()
    lib_selector.add_selector_args(ap)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--intervention-concept", help="required for the population_outcome_gap query")
    ap.add_argument("--types", nargs="*",
                     choices=["single_study_fragile", "unresolved_conflicts",
                              "co_mentioned_ungrouped", "population_outcome_gap"],
                     help="restrict to specific gap types; default runs all applicable")
    args = ap.parse_args()

    library_root = Path(args.repo).expanduser().resolve()
    resolution = lib_selector.resolve_from_args(library_root, args)
    pmids = resolution["pmids"]

    want = set(args.types) if args.types else None
    out: dict[str, list[dict]] = {}
    if want is None or "single_study_fragile" in want:
        out["single_study_fragile"] = single_study_fragile(library_root, pmids)
    if want is None or "unresolved_conflicts" in want:
        out["unresolved_conflicts"] = unresolved_conflicts(library_root, pmids)
    if want is None or "co_mentioned_ungrouped" in want:
        out["co_mentioned_ungrouped"] = co_mentioned_ungrouped(library_root, pmids)
    if args.intervention_concept and (want is None or "population_outcome_gap" in want):
        out["population_outcome_gap"] = population_outcome_gap(library_root, pmids, args.intervention_concept)

    print(json.dumps({"selector_expression": resolution["selector_expression"], "gaps": out}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
