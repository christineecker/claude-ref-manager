#!/usr/bin/env python3
"""Phase 10 (/ref:summarize, advanced /ref:review appraisal) gate fixtures
(PLAN.md §8 build-order row for phase 10).

Run: python3 skills/ref-manager/scripts/tests/test_phase10_summarize_review.py
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
import verify  # noqa: E402
import concept  # noqa: E402
import relation  # noqa: E402
import summarize  # noqa: E402
import appraise  # noqa: E402
import init_repo  # noqa: E402
from lib_selector import resolve  # noqa: E402


def author(last, first):
    return {"last": last, "first": first, "raw": f"{last} {first}"}


def claim(locator="Results/p1", population="adults", **overrides):
    c = {
        "locator": locator, "evidence_span": "quoted text here",
        "population": population, "intervention": "drug X", "comparator": "placebo",
        "outcome": "blood pressure", "timepoint": "12 weeks", "direction": "decrease",
        "effect_value": "5", "effect_measure": "mmHg", "uncertainty_interval": "95% CI 2-8",
        "study_design": "randomized controlled trial", "cohort_identity": "unknown",
        "adjustment_context": "unknown",
    }
    c.update(overrides)
    return c


def extractor_output(pmid, claims, study_type="rct", confidence="confident"):
    return {"pmid": pmid, "study_type": study_type, "study_type_confidence": confidence, "claims": claims}


STAMPS = {"extractor": "ref-extractor", "model": "test", "prompt_version": "1"}


class TempLibrary(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.library_root = self.tmp / "lib"
        for rel in init_repo.LIBRARY_DIRS:
            (self.library_root / rel).mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def add_paper(self, pmid, tier="full", **overrides):
        record = {
            "pmid": pmid, "title": f"Paper {pmid}", "abstract": "abs",
            "authors": [author("Smith", "Jane")], "journal": "X", "year": "2022",
            "doi": f"10.1/{pmid}", "pmcid": None, "grants": [],
        }
        record.update(overrides)
        result = add.add_one(self.library_root, record)
        if tier == "full":
            meta_path = self.library_root / "papers" / pmid / "meta.json"
            meta = json.loads(meta_path.read_text())
            meta["extraction_tier"] = "full"
            meta_path.write_text(json.dumps(meta))
        return result

    def extract(self, pmid, claims, evidence_tier="full", source_hash="deadbeef", **kwargs):
        record = extractor_output(pmid, claims, **kwargs)
        record["evidence_tier"] = evidence_tier
        record["source_hash"] = source_hash
        return extract.extract_one(self.library_root, record, STAMPS)

    def resolve(self, **kwargs):
        return resolve(self.library_root, **kwargs)


# ---------------------------------------------------------------- summarize

class TestSummarizeOnePaperSameCodePath(TempLibrary):
    def test_one_paper_and_multi_paper_use_same_function(self):
        self.add_paper("1")
        self.extract("1", [claim()])
        self.add_paper("2")
        self.extract("2", [claim(population="children")])

        one = summarize.build_candidates(self.library_root, ["1"])
        many = summarize.build_candidates(self.library_root, ["1", "2"])
        self.assertEqual(len(one), 1)
        self.assertEqual(len(many), 2)
        # same function, same candidate shape either way
        self.assertEqual(set(one[0].keys()), set(many[0].keys()))

    def test_run_summarize_persists_one_paper_set(self):
        self.add_paper("1")
        self.extract("1", [claim()])
        resolution = self.resolve(pmids=["1"])
        result = summarize.run_summarize(
            self.library_root, "batch1", None, resolution,
            "This paper found X.", None, [], refresh=False,
        )
        self.assertEqual(result["status"], "created")
        self.assertEqual(result["manifest"]["pmids"], ["1"])


class TestSummarizeFreezeRefresh(TempLibrary):
    def test_reused_unless_refresh(self):
        self.add_paper("1")
        self.extract("1", [claim()])
        resolution = self.resolve(pmids=["1"])
        summarize.run_summarize(self.library_root, "b1", None, resolution, "first answer", None, [], False)

        # second call without resolution/refresh reuses frozen
        result = summarize.run_summarize(self.library_root, "b1", None, None, "", None, [], False)
        self.assertEqual(result["status"], "reused_frozen_summary")
        self.assertEqual(result["summary"], "first answer")

    def test_refresh_reports_withdrawn_evidence(self):
        self.add_paper("1")
        c = claim()
        self.extract("1", [c])
        resolution = self.resolve(pmids=["1"])
        first = summarize.run_summarize(self.library_root, "b2", None, resolution, "answer v1", None, [], False)
        claim_id = json.loads((self.library_root / "papers/1/claim_registry.json").read_text())
        claim_id = next(iter(claim_id["claims"]))

        verify.review_claim(self.library_root, "1", claim_id, "reject", "user", "bad claim", None)

        resolution2 = self.resolve(pmids=["1"])
        second = summarize.run_summarize(self.library_root, "b2", None, resolution2, "answer v2", None, [], True)
        self.assertEqual(second["status"], "refreshed")
        withdrawn_ids = [w["claim_id"] for w in second["withdrawn_evidence"]]
        self.assertIn(claim_id, withdrawn_ids)


# ------------------------------------------------------------------ appraise

class TestWhollyAbstractTierRefused(TempLibrary):
    def test_wholly_abstract_tier_is_refused_before_appraisal(self):
        self.add_paper("1", tier="abstract")
        self.extract("1", [claim()], evidence_tier="abstract")
        resolution = self.resolve(pmids=["1"])
        result = appraise.run_review(self.library_root, "r1", None, resolution, False)
        self.assertEqual(result["status"], "refused")
        self.assertIn("abstract-tier", result["reason"])

    def test_mixed_set_appraises_full_and_flags_abstract(self):
        self.add_paper("1", tier="full")
        self.extract("1", [claim()], evidence_tier="full")
        self.add_paper("2", tier="abstract")
        self.extract("2", [claim()], evidence_tier="abstract")
        resolution = self.resolve(pmids=["1", "2"])
        result = appraise.run_review(self.library_root, "r2", None, resolution, False)
        self.assertEqual(result["status"], "created")
        self.assertIsNotNone(result["appraisals"]["1"].get("checklist"))
        self.assertTrue(result["appraisals"]["2"].get("insufficient_information"))


class TestChecklistSelectionByStudyType(TempLibrary):
    def _appraise_one(self, pmid, study_type, claims):
        self.add_paper(pmid, tier="full")
        self.extract(pmid, claims, evidence_tier="full", study_type=study_type)
        return appraise.draft_appraisal_for_pmid(self.library_root, pmid)

    def test_rct_gets_rob2(self):
        a = self._appraise_one("10", "rct", [claim(study_design="a randomized double-blind trial")])
        self.assertEqual(a["checklist"], "RoB2")
        self.assertEqual(set(a["domains"].keys()), set(appraise.ROB2_DOMAINS))

    def test_cohort_gets_newcastle_ottawa(self):
        a = self._appraise_one("11", "cohort", [claim(adjustment_context="age, sex, BMI")])
        self.assertEqual(a["checklist"], "Newcastle-Ottawa")
        self.assertEqual(set(a["domains"].keys()), {"selection", "comparability", "outcome_exposure"})

    def test_meta_analysis_gets_amstar2(self):
        a = self._appraise_one("12", "meta_analysis",
                                [claim(evidence_span="a systematic search following PRISMA guidance was performed")])
        self.assertEqual(a["checklist"], "AMSTAR-2")
        self.assertIn("adequate_literature_search", a["items"])

    def test_molecular_gets_general_note_not_forced_checklist(self):
        a = self._appraise_one("13", "molecular", [claim()])
        self.assertIsNone(a["checklist"])
        self.assertIn("no standard checklist", a["note"])


class TestDomainsTraceToEvidence(TempLibrary):
    def test_every_rated_domain_has_claim_ids_insufficient_has_none(self):
        self.add_paper("20", tier="full")
        self.extract("20", [claim(study_design="randomized controlled trial")], evidence_tier="full", study_type="rct")
        a = appraise.draft_appraisal_for_pmid(self.library_root, "20")
        rand = a["domains"]["randomization_process"]
        self.assertEqual(rand["rating"], "low")
        self.assertTrue(rand["claim_ids"])

        deviations = a["domains"]["deviations_from_intended_interventions"]
        self.assertEqual(deviations["rating"], "insufficient_information")
        self.assertEqual(deviations["claim_ids"], [])


class TestGradeCertainty(TempLibrary):
    def test_downgrading_factors_shown_including_not_assessed(self):
        self.add_paper("30", tier="full")
        self.extract("30", [claim(uncertainty_interval="unknown")], evidence_tier="full", study_type="rct")
        resolution = self.resolve(pmids=["30"])
        result = appraise.run_review(self.library_root, "g1", None, resolution, False)
        grade = result["grade"]
        self.assertIn("imprecision", grade["factors"])
        self.assertTrue(grade["factors"]["imprecision"]["downgrade"])
        # no relation-graph data -> inconsistency not_assessed
        self.assertTrue(grade["factors"]["inconsistency"]["not_assessed"])
        # publication bias is always not_assessed at this scope
        self.assertTrue(grade["factors"]["publication_bias"]["not_assessed"])
        self.assertIn(grade["certainty"], ("very_low", "low", "moderate", "high"))

    def test_inconsistency_downgrade_from_relation_graph(self):
        self.add_paper("31", tier="full")
        self.extract("31", [claim(direction="decrease")], evidence_tier="full", study_type="rct")
        self.add_paper("32", tier="full")
        self.extract("32", [claim(direction="increase")], evidence_tier="full", study_type="rct")

        concept.create_concept(self.library_root, "drug-x", "drug X")
        concept.create_concept(self.library_root, "bp", "blood pressure")
        c1 = next(iter(json.loads((self.library_root / "papers/31/claim_registry.json").read_text())["claims"].values()))
        c2 = next(iter(json.loads((self.library_root / "papers/32/claim_registry.json").read_text())["claims"].values()))
        proposal = relation.propose_relation(c1, c2, "drug-x", "bp")
        self.assertIsNotNone(proposal)
        relation.create_relation(self.library_root, proposal["type"], "drug-x", "bp",
                                  proposal["supporting_claims"], proposal["source_version_ids"])

        resolution = self.resolve(pmids=["31", "32"])
        result = appraise.run_review(self.library_root, "g2", None, resolution, False)
        self.assertTrue(result["grade"]["factors"]["inconsistency"]["downgrade"])


class TestAppraisalReviewDistinguishable(TempLibrary):
    def test_reviewed_domain_shows_human_status(self):
        self.add_paper("40", tier="full")
        self.extract("40", [claim(study_design="randomized controlled trial")], evidence_tier="full", study_type="rct")
        draft = appraise.draft_appraisal_for_pmid(self.library_root, "40")
        self.assertEqual(draft["domains"]["randomization_process"]["review_status"], "model_draft")

        verify.review_appraisal(self.library_root, "40", "RoB2", "randomization_process",
                                 "accept", "reviewer1", "confirmed, trial explicitly randomized", None)

        redrawn = appraise.draft_appraisal_for_pmid(self.library_root, "40")
        self.assertEqual(redrawn["domains"]["randomization_process"]["review_status"], "human_confirmed")
        # untouched domain remains a draft
        self.assertEqual(redrawn["domains"]["measurement_of_outcome"]["review_status"], "model_draft")


class TestPrismaStillWorksAfterExtension(TempLibrary):
    def test_prisma_unaffected_by_appraise_module(self):
        import prisma
        import project as project_mod
        import screen

        self.add_paper("50", tier="full")
        project_mod.create(self.library_root, "proj1", None)
        screen.decide(self.library_root, "proj1", "50", "included", "relevant", None)
        result = prisma.run_prisma(self.library_root, "proj1", [], refresh=False)
        self.assertIn("included", result["manifest"]["flow"])


if __name__ == "__main__":
    unittest.main()
