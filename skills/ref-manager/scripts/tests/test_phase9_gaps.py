#!/usr/bin/env python3
"""Phase 9 (/ref:gaps, /ref:hypothesize) gate fixtures (PLAN.md §8 build-order
row for phase 9, the gaps/hypothesize half).

Run: python3 skills/ref-manager/scripts/tests/test_phase9_gaps.py
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
import study  # noqa: E402
import init_repo  # noqa: E402
import gaps  # noqa: E402
import hypothesize  # noqa: E402


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
            "pmid": pmid, "title": f"Paper {pmid}", "abstract": "abs",
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
        extract.extract_one(self.library_root, record, STAMPS)
        registry = json.loads((self.library_root / "papers" / pmid / "claim_registry.json").read_text())
        active = [c for c in registry["claims"].values()
                  if c["locator"] == claim_obj["locator"] and c["status"] == "active"]
        return active[-1]


# ---------------------------------------------------------------- gaps: single_study_fragile

class TestSingleStudyFragile(TempLibrary):
    def test_lone_pmid_is_fragile(self):
        self.add_paper("1")
        c = self.extract_claim("1", claim())
        findings = gaps.single_study_fragile(self.library_root, ["1"])
        self.assertEqual([f["claim_id"] for f in findings], [c["claim_id"]])

    def test_paper_in_multi_pmid_study_group_not_fragile(self):
        self.add_paper("1")
        self.add_paper("2")
        self.extract_claim("1", claim())
        self.extract_claim("2", claim(locator="Results/p2"))
        study.create_study(self.library_root, "s1", ["1", "2"], "confirmed", "shared trial registration")
        findings = gaps.single_study_fragile(self.library_root, ["1", "2"])
        self.assertEqual(findings, [])

    def test_corroborated_via_non_conflict_relation_not_fragile(self):
        self.add_paper("1")
        self.add_paper("2")
        c1 = self.extract_claim("1", claim())
        c2 = self.extract_claim("2", claim(locator="Results/p2"))
        concept.create_concept(self.library_root, "drug-x", "drug X")
        concept.create_concept(self.library_root, "sbp", "systolic blood pressure")
        relation.create_relation(
            self.library_root, "supports", "drug-x", "sbp",
            [{"pmid": "1", "claim_id": c1["claim_id"]}, {"pmid": "2", "claim_id": c2["claim_id"]}],
        )
        findings = gaps.single_study_fragile(self.library_root, ["1", "2"])
        self.assertEqual(findings, [])


# ---------------------------------------------------------------- gaps: unresolved_conflicts

class TestUnresolvedConflicts(TempLibrary):
    def setUp(self):
        super().setUp()
        self.add_paper("1")
        self.add_paper("2")
        self.c1 = self.extract_claim("1", claim(direction="decrease"))
        self.c2 = self.extract_claim("2", claim(locator="Results/p2", direction="increase"))
        concept.create_concept(self.library_root, "drug-x", "drug X")
        concept.create_concept(self.library_root, "sbp", "systolic blood pressure")
        proposal = relation.propose_relation(self.c1, self.c2, "drug-x", "sbp")
        self.rel = relation.create_relation(
            self.library_root, proposal["type"], "drug-x", "sbp",
            proposal["supporting_claims"], proposal["source_version_ids"],
        )

    def test_unreviewed_potential_conflict_appears(self):
        findings = gaps.unresolved_conflicts(self.library_root)
        self.assertEqual([f["relation_id"] for f in findings], [self.rel["relation_id"]])

    def test_reviewed_contradicts_does_not_appear(self):
        relation.review_relation(self.library_root, self.rel["relation_id"], "contradicts",
                                  "christine", "genuinely opposite, comparable contexts")
        findings = gaps.unresolved_conflicts(self.library_root)
        self.assertEqual(findings, [])

    def test_stale_contradicts_reappears(self):
        relation.review_relation(self.library_root, self.rel["relation_id"], "contradicts",
                                  "christine", "genuinely opposite, comparable contexts")
        # re-extract paper 2 with materially different content -> supersedes c2
        self.extract_claim("2", claim(locator="Results/p2", direction="increase", effect_value="99"))
        relation.refresh_relations(self.library_root)
        findings = gaps.unresolved_conflicts(self.library_root)
        self.assertEqual([f["relation_id"] for f in findings], [self.rel["relation_id"]])
        self.assertTrue(findings[0]["stale"])


# ---------------------------------------------------------------- gaps: co_mentioned_ungrouped

class TestCoMentionedUngrouped(TempLibrary):
    def test_co_mention_without_edge_is_flagged(self):
        self.add_paper("1")
        c = self.extract_claim("1", claim(evidence_span="drug X reduced systolic blood pressure in this cohort"))
        concept.create_concept(self.library_root, "drug-x", "drug X")
        concept.create_concept(self.library_root, "sbp", "systolic blood pressure")
        findings = gaps.co_mentioned_ungrouped(self.library_root, ["1"])
        pairs = [{f["concept_a"], f["concept_b"]} for f in findings]
        self.assertIn({"drug-x", "sbp"}, pairs)
        self.assertEqual(findings[0]["claim_id"], c["claim_id"])

    def test_co_mention_with_existing_edge_not_flagged(self):
        self.add_paper("1")
        self.add_paper("2")
        c1 = self.extract_claim("1", claim(evidence_span="drug X reduced systolic blood pressure in this cohort"))
        c2 = self.extract_claim("2", claim(locator="Results/p2", direction="increase"))
        concept.create_concept(self.library_root, "drug-x", "drug X")
        concept.create_concept(self.library_root, "sbp", "systolic blood pressure")
        relation.create_relation(
            self.library_root, "supports", "drug-x", "sbp",
            [{"pmid": "1", "claim_id": c1["claim_id"]}, {"pmid": "2", "claim_id": c2["claim_id"]}],
        )
        findings = gaps.co_mentioned_ungrouped(self.library_root, ["1"])
        self.assertEqual(findings, [])


# ---------------------------------------------------------------- gaps: population_outcome_gap

class TestPopulationOutcomeGap(TempLibrary):
    def test_missing_combination_flagged_when_sibling_covered(self):
        self.add_paper("1")
        self.add_paper("2")
        self.add_paper("3")
        concept.create_concept(self.library_root, "drug-x", "drug X")
        c1 = self.extract_claim("1", claim(population="adults", outcome="systolic blood pressure"))
        c2 = self.extract_claim("2", claim(locator="Results/p2", population="children", outcome="systolic blood pressure"))
        c3 = self.extract_claim("3", claim(locator="Results/p3", population="adults", outcome="LDL cholesterol"))
        findings = gaps.population_outcome_gap(self.library_root, ["1", "2", "3"], "drug-x")
        missing = [(f["missing_population"], f["missing_outcome"]) for f in findings]
        self.assertIn(("children", "LDL cholesterol"), missing)
        f = next(f for f in findings if f["missing_population"] == "children" and f["missing_outcome"] == "LDL cholesterol")
        self.assertEqual(f["population_evidenced_by"], [c2["claim_id"]])
        self.assertEqual(f["outcome_evidenced_by"], [c3["claim_id"]])
        # the actually-covered combos never appear as gaps
        self.assertNotIn(("adults", "systolic blood pressure"), missing)


# ---------------------------------------------------------------- hypothesize

class TestHypothesizeSwansonABC(TempLibrary):
    def _edge(self, subject, obj, pmid_a, pmid_b, rel_type="supports"):
        self.add_paper(pmid_a)
        if pmid_b != pmid_a:
            self.add_paper(pmid_b)
        ca = self.extract_claim(pmid_a, claim(locator=f"Results/{pmid_a}"))
        cb = self.extract_claim(pmid_b, claim(locator=f"Results/{pmid_b}b"))
        for cid, name in ((subject, subject), (obj, obj)):
            if concept.find_concept(self.library_root, name) is None:
                concept.create_concept(self.library_root, cid, name)
        return relation.create_relation(
            self.library_root, rel_type, subject, obj,
            [{"pmid": pmid_a, "claim_id": ca["claim_id"]}, {"pmid": pmid_b, "claim_id": cb["claim_id"]}],
        )

    def test_independent_chain_surfaces_candidate(self):
        self._edge("a", "b", "1", "2")   # A-B backed by papers 1,2
        self._edge("b", "c", "3", "4")   # B-C backed by papers 3,4 -- different papers
        cands = hypothesize.candidates(self.library_root, "a")
        c_ids = [c["concept_c"] for c in cands]
        self.assertIn("c", c_ids)
        found = next(c for c in cands if c["concept_c"] == "c")
        self.assertEqual(found["chain_count"], 1)
        self.assertEqual(found["chains"][0]["concept_b"], "b")

    def test_same_paper_only_chain_excluded(self):
        self.add_paper("9")
        concept.create_concept(self.library_root, "a2", "a2")
        concept.create_concept(self.library_root, "b2", "b2")
        concept.create_concept(self.library_root, "c2", "c2")
        claim_x = self.extract_claim("9", claim(locator="Results/x"))
        ab = relation.create_relation(self.library_root, "supports", "a2", "b2",
                                       [{"pmid": "9", "claim_id": claim_x["claim_id"]}])
        bc = relation.create_relation(self.library_root, "supports", "b2", "c2",
                                       [{"pmid": "9", "claim_id": claim_x["claim_id"]}])
        cands = hypothesize.candidates(self.library_root, "a2")
        self.assertEqual([c for c in cands if c["concept_c"] == "c2"], [])

    def test_existing_direct_edge_excludes_candidate(self):
        self._edge("p", "q", "10", "11")
        self._edge("q", "r", "12", "13")
        self._edge("p", "r", "14", "15")  # direct P-R edge already exists
        cands = hypothesize.candidates(self.library_root, "p")
        self.assertEqual([c for c in cands if c["concept_c"] == "r"], [])

    def test_finalize_zero_results_reads_not_found_not_novel(self):
        self._edge("m", "n", "20", "21")
        self._edge("n", "o", "22", "23")
        cands = hypothesize.candidates(self.library_root, "m")
        cand = next(c for c in cands if c["concept_c"] == "o")
        check = {"query": '"m" AND "o"', "retrieved_at": "2026-01-01T00:00:00Z", "result_pmids": []}
        record = hypothesize.finalize(cand, check)
        self.assertIn("not found by this search", record["pubmed_note"].lower())
        self.assertIn("not proof of novelty", record["pubmed_note"].lower())
        self.assertNotIn("novel finding", record["pubmed_note"].lower())
        self.assertNotIn("confirmed gap", record["pubmed_note"].lower())
        self.assertIn("m", record["limitations"])
        self.assertIn("o", record["limitations"])

    def test_finalize_nonzero_results_is_informative_not_disqualifying(self):
        self._edge("x1", "y1", "30", "31")
        self._edge("y1", "z1", "32", "33")
        cands = hypothesize.candidates(self.library_root, "x1")
        cand = next(c for c in cands if c["concept_c"] == "z1")
        check = {"query": '"x1" AND "z1"', "retrieved_at": "2026-01-01T00:00:00Z", "result_pmids": ["999", "998"]}
        record = hypothesize.finalize(cand, check)
        self.assertIn("2 pubmed result", record["pubmed_note"].lower())
        self.assertIn("library-coverage gap", record["pubmed_note"].lower())
        # still present, not dropped
        self.assertEqual(record["concept_c"], "z1")


if __name__ == "__main__":
    unittest.main()
