#!/usr/bin/env python3
"""Phase 8 (concept graph, relations, conflict review) gate fixtures
(PLAN.md §8 build-order row for phase 8, the graph half).

Run: python3 skills/ref-manager/scripts/tests/test_phase8_graph.py
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import add  # noqa: E402
import extract  # noqa: E402
import concept  # noqa: E402
import relation  # noqa: E402
import init_repo  # noqa: E402
from lib_ids import SlugError  # noqa: E402
from lib_schema import SchemaError  # noqa: E402


def author(last, first):
    return {"last": last, "first": first, "raw": f"{last} {first}"}


def claim(locator="Results/p1", **overrides):
    c = {
        "locator": locator, "evidence_span": "quoted text here",
        "population": "adults with hypertension", "intervention": "drug X", "comparator": "placebo",
        "outcome": "systolic blood pressure", "timepoint": "12 weeks", "direction": "decrease",
        "effect_value": "5", "effect_measure": "mmHg", "uncertainty_interval": "95% CI 2-8",
        "study_design": "RCT", "cohort_identity": "unknown", "adjustment_context": "unknown",
    }
    c.update(overrides)
    return c


STAMPS = {"extractor": "ref-extractor", "model": "test", "prompt_version": "1"}


class TempLibrary(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.library_root = self.tmp / "lib"
        for rel in init_repo.LIBRARY_DIRS:
            (self.library_root / rel).mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def add_paper(self, pmid, **overrides):
        record = {
            "pmid": pmid, "title": "A trial of drug X", "abstract": "abs",
            "authors": [author("Smith", "Jane")],
            "journal": "X", "year": "2022", "doi": f"10.1/{pmid}", "pmcid": None, "grants": [],
        }
        record.update(overrides)
        return add.add_one(self.library_root, record)

    def extract_claim(self, pmid, claim_obj, evidence_tier="full", source_hash="deadbeef", study_type="rct"):
        record = {
            "pmid": pmid, "study_type": study_type, "study_type_confidence": "confident",
            "claims": [claim_obj], "evidence_tier": evidence_tier, "source_hash": source_hash,
        }
        result = extract.extract_one(self.library_root, record, STAMPS)
        registry = json.loads((self.library_root / "papers" / pmid / "claim_registry.json").read_text())
        # newest active claim at this locator
        active = [c for c in registry["claims"].values()
                  if c["locator"] == claim_obj["locator"] and c["status"] == "active"]
        return active[-1]


# ---------------------------------------------------------------- concepts

class TestConceptAliasResolution(TempLibrary):
    def test_alias_resolves_to_existing_concept_not_a_duplicate(self):
        concept.create_concept(self.library_root, "mi", "myocardial infarction")
        concept.add_alias(self.library_root, "mi", "MI", source="manual")

        found = concept.find_concept(self.library_root, "myocardial infarction")
        self.assertEqual(found["concept_id"], "mi")
        found2 = concept.find_concept(self.library_root, "MI")
        self.assertEqual(found2["concept_id"], "mi")

        with self.assertRaises(SlugError):
            concept.create_concept(self.library_root, "mi-2", "MI")  # would duplicate

        rows = concept.list_concepts(self.library_root)
        self.assertEqual(len(rows), 1)

    def test_add_alias_no_op_when_already_resolves_here(self):
        concept.create_concept(self.library_root, "mi", "myocardial infarction")
        concept.add_alias(self.library_root, "mi", "MI", source="manual")
        row = concept.add_alias(self.library_root, "mi", "MI", source="manual")  # again
        self.assertEqual(row["aliases"].count("MI"), 1)

    def test_add_alias_refuses_cross_concept_collision(self):
        concept.create_concept(self.library_root, "mi", "myocardial infarction")
        concept.create_concept(self.library_root, "stroke", "stroke")
        with self.assertRaises(SlugError):
            concept.add_alias(self.library_root, "stroke", "myocardial infarction", source="manual")


# ---------------------------------------------------------------- comparability / proposal

class TestConflictProposal(TempLibrary):
    def test_opposite_direction_comparable_context_proposes_conflict(self):
        self.add_paper("100")
        self.add_paper("101")
        c1 = self.extract_claim("100", claim(direction="decrease"))
        c2 = self.extract_claim("101", claim(direction="increase"))
        proposal = relation.propose_relation(c1, c2, "drug-x", "sbp")
        self.assertIsNotNone(proposal)
        self.assertEqual(proposal["type"], "potential_conflict")
        pmids = {sc["pmid"] for sc in proposal["supporting_claims"]}
        self.assertEqual(pmids, {"100", "101"})

    def test_mismatched_population_does_not_propose_conflict(self):
        self.add_paper("102")
        self.add_paper("103")
        c1 = self.extract_claim("102", claim(direction="decrease", population="adults with hypertension"))
        c2 = self.extract_claim("103", claim(direction="increase", population="children with hypertension"))
        proposal = relation.propose_relation(c1, c2, "drug-x", "sbp")
        self.assertIsNone(proposal)

    def test_mismatched_comparator_does_not_propose_conflict(self):
        self.add_paper("104")
        self.add_paper("105")
        c1 = self.extract_claim("104", claim(direction="decrease", comparator="placebo"))
        c2 = self.extract_claim("105", claim(direction="increase", comparator="standard of care"))
        proposal = relation.propose_relation(c1, c2, "drug-x", "sbp")
        self.assertIsNone(proposal)

    def test_unknown_field_never_passes_as_comparable(self):
        self.add_paper("106")
        self.add_paper("107")
        c1 = self.extract_claim("106", claim(direction="decrease", timepoint="unknown"))
        c2 = self.extract_claim("107", claim(direction="increase", timepoint="unknown"))
        proposal = relation.propose_relation(c1, c2, "drug-x", "sbp")
        self.assertIsNone(proposal)  # both "unknown" must NOT count as a match

    def test_same_direction_never_proposes_conflict(self):
        self.add_paper("108")
        self.add_paper("109")
        c1 = self.extract_claim("108", claim(direction="decrease"))
        c2 = self.extract_claim("109", claim(direction="decrease"))
        self.assertIsNone(relation.propose_relation(c1, c2, "drug-x", "sbp"))

    def test_no_significant_difference_is_inconclusive_not_oppositional(self):
        self.add_paper("110")
        self.add_paper("111")
        c1 = self.extract_claim("110", claim(direction="decrease"))
        c2 = self.extract_claim("111", claim(direction="no significant difference"))
        self.assertIsNone(relation.propose_relation(c1, c2, "drug-x", "sbp"))


# ---------------------------------------------------------------- review / contradicts

class TestContradictsRequiresReview(TempLibrary):
    def _make_conflict(self):
        self.add_paper("200")
        self.add_paper("201")
        c1 = self.extract_claim("200", claim(direction="decrease"))
        c2 = self.extract_claim("201", claim(direction="increase"))
        proposal = relation.propose_relation(c1, c2, "drug-x", "sbp")
        return relation.create_relation(
            self.library_root, proposal["type"], proposal["subject_concept_id"],
            proposal["object_concept_id"], proposal["supporting_claims"], proposal["source_version_ids"],
        )

    def test_create_relation_refuses_direct_contradicts(self):
        with self.assertRaises(SchemaError):
            relation.create_relation(self.library_root, "contradicts", "a", "b", [{"pmid": "1", "claim_id": "c-1"}])

    def test_review_to_contradicts_without_rationale_refused(self):
        row = self._make_conflict()
        with self.assertRaises(SchemaError):
            relation.review_relation(self.library_root, row["relation_id"], "contradicts", "reviewer", None)
        with self.assertRaises(SchemaError):
            relation.review_relation(self.library_root, row["relation_id"], "contradicts", "reviewer", "   ")

    def test_review_to_contradicts_with_rationale_succeeds(self):
        row = self._make_conflict()
        reviewed = relation.review_relation(
            self.library_root, row["relation_id"], "contradicts", "reviewer",
            "Both cohorts matched on baseline severity; opposite effect is a genuine disagreement.",
        )
        self.assertEqual(reviewed["type"], "contradicts")
        self.assertEqual(reviewed["review_state"], "reviewed")
        self.assertTrue(reviewed["rationale"])


# ---------------------------------------------------------------- staleness

class TestStaleEdgeInvalidation(TempLibrary):
    def test_superseding_a_supporting_claim_marks_relation_stale_on_refresh(self):
        self.add_paper("300")
        self.add_paper("301")
        c1 = self.extract_claim("300", claim(direction="decrease"))
        c2 = self.extract_claim("301", claim(direction="increase"))
        proposal = relation.propose_relation(c1, c2, "drug-x", "sbp")
        row = relation.create_relation(
            self.library_root, proposal["type"], proposal["subject_concept_id"],
            proposal["object_concept_id"], proposal["supporting_claims"], proposal["source_version_ids"],
        )
        self.assertFalse(row["stale"])

        # re-extract "300" with materially different content at the same locator -> supersedes c1
        self.extract_claim("300", claim(direction="decrease", effect_value="99"))

        report = relation.refresh_relations(self.library_root)
        self.assertIn(row["relation_id"], report["went_stale"])
        refreshed = relation.get_relation(self.library_root, row["relation_id"])
        self.assertTrue(refreshed["stale"])

    def test_refresh_is_idempotent_and_reports_only_new_staleness(self):
        self.add_paper("302")
        self.add_paper("303")
        c1 = self.extract_claim("302", claim(direction="decrease"))
        c2 = self.extract_claim("303", claim(direction="increase"))
        proposal = relation.propose_relation(c1, c2, "drug-x", "sbp")
        relation.create_relation(
            self.library_root, proposal["type"], proposal["subject_concept_id"],
            proposal["object_concept_id"], proposal["supporting_claims"], proposal["source_version_ids"],
        )
        self.extract_claim("302", claim(direction="decrease", effect_value="99"))
        r1 = relation.refresh_relations(self.library_root)
        self.assertEqual(len(r1["went_stale"]), 1)
        r2 = relation.refresh_relations(self.library_root)
        self.assertEqual(r2["went_stale"], [])  # already stale, nothing NEW went stale

    def test_reviewed_decision_survives_going_stale(self):
        self.add_paper("304")
        self.add_paper("305")
        c1 = self.extract_claim("304", claim(direction="decrease"))
        c2 = self.extract_claim("305", claim(direction="increase"))
        proposal = relation.propose_relation(c1, c2, "drug-x", "sbp")
        row = relation.create_relation(
            self.library_root, proposal["type"], proposal["subject_concept_id"],
            proposal["object_concept_id"], proposal["supporting_claims"], proposal["source_version_ids"],
        )
        reviewed = relation.review_relation(
            self.library_root, row["relation_id"], "contradicts", "reviewer", "genuine disagreement, reviewed"
        )
        self.assertEqual(reviewed["stale"], False)

        self.extract_claim("304", claim(direction="decrease", effect_value="99"))
        relation.refresh_relations(self.library_root)

        after = relation.get_relation(self.library_root, row["relation_id"])
        self.assertTrue(after["stale"])  # went stale...
        self.assertEqual(after["type"], "contradicts")  # ...but review decision intact
        self.assertEqual(after["review_state"], "reviewed")
        self.assertTrue(after["rationale"])


# ---------------------------------------------------------------- neighbors / practical queries

class TestNeighborsResolveToEvidence(TempLibrary):
    def test_neighbors_returns_edges_with_supporting_claim_trail(self):
        self.add_paper("400")
        self.add_paper("401")
        c1 = self.extract_claim("400", claim(direction="decrease"))
        c2 = self.extract_claim("401", claim(direction="increase"))
        proposal = relation.propose_relation(c1, c2, "drug-x", "sbp")
        relation.create_relation(
            self.library_root, proposal["type"], proposal["subject_concept_id"],
            proposal["object_concept_id"], proposal["supporting_claims"], proposal["source_version_ids"],
        )

        result = relation.neighbors(self.library_root, "sbp")
        self.assertEqual(len(result["incoming"]), 1)
        edge = result["incoming"][0]
        self.assertEqual(edge["type"], "potential_conflict")
        pmids = {sc["pmid"] for sc in edge["supporting_claims"]}
        self.assertEqual(pmids, {"400", "401"})
        claim_ids = {sc["claim_id"] for sc in edge["supporting_claims"]}
        self.assertEqual(claim_ids, {c1["claim_id"], c2["claim_id"]})

    def test_neighbors_on_unrelated_concept_returns_empty(self):
        result = relation.neighbors(self.library_root, "nonexistent-concept")
        self.assertEqual(result["outgoing"], [])
        self.assertEqual(result["incoming"], [])


if __name__ == "__main__":
    unittest.main()
