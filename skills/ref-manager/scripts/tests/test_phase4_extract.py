#!/usr/bin/env python3
"""Phase 4 (claim extraction + verify/correction overlays) gate fixtures
(PLAN.md §8 build-order row for phase 4, extraction + verify subset).

Run: python3 skills/ref-manager/scripts/tests/test_phase4_extract.py
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
import person  # noqa: E402
import grant  # noqa: E402
import init_repo  # noqa: E402
from lib_schema import SchemaError  # noqa: E402


def author(last, first):
    return {"last": last, "first": first, "raw": f"{last} {first}"}


def claim(locator="Results/p1", population="adults", **overrides):
    c = {
        "locator": locator, "evidence_span": "quoted text here",
        "population": population, "intervention": "drug X", "comparator": "placebo",
        "outcome": "blood pressure", "timepoint": "12 weeks", "direction": "decrease",
        "effect_value": "5", "effect_measure": "mmHg", "uncertainty_interval": "95% CI 2-8",
        "study_design": "RCT", "cohort_identity": "unknown", "adjustment_context": "unknown",
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

    def add_paper(self, pmid, **overrides):
        record = {
            "pmid": pmid, "title": "A trial of drug X", "abstract": "abs",
            "authors": [author("Smith", "Jane"), author("Doe", "John"), author("Roe", "Ann")],
            "journal": "X", "year": "2022", "doi": f"10.1/{pmid}", "pmcid": None, "grants": [],
        }
        record.update(overrides)
        return add.add_one(self.library_root, record)

    def extract(self, pmid, claims, evidence_tier=None, source_hash=None, **kwargs):
        record = extractor_output(pmid, claims, **kwargs)
        record["evidence_tier"] = evidence_tier or "full"
        record["source_hash"] = source_hash or "deadbeef"
        return extract.extract_one(self.library_root, record, STAMPS)


# ---------------------------------------------------------------- extraction

class TestClaimsResolveToSources(TempLibrary):
    def test_every_claim_has_locator_and_evidence_span(self):
        self.add_paper("100")
        self.extract("100", [claim()])
        registry = json.loads((self.library_root / "papers/100/claim_registry.json").read_text())
        self.assertEqual(len(registry["claims"]), 1)
        c = next(iter(registry["claims"].values()))
        self.assertTrue(c["locator"])
        self.assertTrue(c["evidence_span"])


class TestStableClaimIds(TempLibrary):
    def test_unchanged_content_reuses_claim_id(self):
        self.add_paper("101")
        self.extract("101", [claim()])
        reg1 = json.loads((self.library_root / "papers/101/claim_registry.json").read_text())
        id1 = next(iter(reg1["claims"]))

        self.extract("101", [claim()])  # identical content, same locator
        reg2 = json.loads((self.library_root / "papers/101/claim_registry.json").read_text())
        self.assertEqual(len(reg2["claims"]), 1)
        self.assertIn(id1, reg2["claims"])
        self.assertEqual(reg2["claims"][id1]["status"], "active")

    def test_materially_different_content_supersedes(self):
        self.add_paper("102")
        self.extract("102", [claim()])
        reg1 = json.loads((self.library_root / "papers/102/claim_registry.json").read_text())
        old_id = next(iter(reg1["claims"]))

        self.extract("102", [claim(direction="increase", effect_value="9")])
        reg2 = json.loads((self.library_root / "papers/102/claim_registry.json").read_text())
        self.assertEqual(len(reg2["claims"]), 2)  # old retained + new
        self.assertEqual(reg2["claims"][old_id]["status"], "superseded")
        new_id = reg2["claims"][old_id]["superseded_by"]
        self.assertEqual(reg2["claims"][new_id]["supersedes"], old_id)
        self.assertEqual(reg2["claims"][new_id]["status"], "active")


class TestMultiPmidBatchIndependence(TempLibrary):
    def test_one_malformed_record_does_not_block_others(self):
        self.add_paper("103")
        self.add_paper("104")
        good = extractor_output("103", [claim()])
        good["evidence_tier"] = "full"
        bad = extractor_output("104", [{"locator": "x"}])  # missing required normalized fields... but
        # extract_one fills unknown defaults for missing normalized fields, so make it genuinely
        # malformed instead: no 'claims' key structure the script can't recover from.
        bad = {"pmid": "104", "study_type": "not-a-real-type", "claims": [claim()]}
        # study_type falls back to unknown (tested separately) -- force a real failure instead:
        broken = {"pmid": "999"}  # no meta.json for this pmid -> ValueError

        results = []
        for rec in (good, broken):
            try:
                results.append(("ok", extract.extract_one(self.library_root, rec, STAMPS)))
            except (SchemaError, ValueError) as e:
                results.append(("failed", str(e)))

        self.assertEqual(results[0][0], "ok")
        self.assertEqual(results[1][0], "failed")
        # the good one actually committed:
        self.assertTrue((self.library_root / "papers/103/claim_registry.json").exists())


class TestStudyTypeFallback(TempLibrary):
    def test_unrecognized_study_type_falls_back_to_unknown(self):
        self.add_paper("105")
        r = self.extract("105", [claim()], study_type="not-a-real-type", confidence="uncertain")
        self.assertEqual(r["study_type"], "unknown")

    def test_mixed_is_a_legitimate_value_not_forced_to_a_template(self):
        self.add_paper("106")
        r = self.extract("106", [claim()], study_type="mixed")
        self.assertEqual(r["study_type"], "mixed")


class TestRetractionStatus(TempLibrary):
    def test_known_retracted_stores_source_and_checked_at(self):
        self.add_paper("107")
        record = extractor_output("107", [claim()])
        record["evidence_tier"] = "full"
        record["retraction_status"] = {"status": "retracted", "source": "pubmed", "checked_at": "2026-01-01T00:00:00Z"}
        extract.extract_one(self.library_root, record, STAMPS)
        meta = json.loads((self.library_root / "papers/107/meta.json").read_text())
        self.assertEqual(meta["retraction_status"]["status"], "retracted")
        self.assertEqual(meta["retraction_status"]["source"], "pubmed")

    def test_failed_lookup_is_unknown_never_false_negative(self):
        self.add_paper("108")
        record = extractor_output("108", [claim()])
        record["evidence_tier"] = "full"
        # no retraction_status supplied at all -> must default to unknown, not "none"
        extract.extract_one(self.library_root, record, STAMPS)
        meta = json.loads((self.library_root / "papers/108/meta.json").read_text())
        self.assertEqual(meta["retraction_status"]["status"], "unknown")


class TestExtractionTierPromotion(TempLibrary):
    def test_abstract_then_full_promotes_monotonically(self):
        self.add_paper("109")
        self.extract("109", [claim()], evidence_tier="abstract")
        meta = json.loads((self.library_root / "papers/109/meta.json").read_text())
        self.assertEqual(meta["extraction_tier"], "abstract")

        self.extract("109", [claim(locator="Results/p2")], evidence_tier="full")
        meta = json.loads((self.library_root / "papers/109/meta.json").read_text())
        self.assertEqual(meta["extraction_tier"], "full")

        # a later thin (abstract-tier) rerun must not downgrade it back
        self.extract("109", [claim(locator="Abstract")], evidence_tier="abstract")
        meta = json.loads((self.library_root / "papers/109/meta.json").read_text())
        self.assertEqual(meta["extraction_tier"], "full")


# ---------------------------------------------------------------- verify.py

class TestCorrectionsOnUnchangedEvidence(TempLibrary):
    def test_correction_survives_unchanged_rerun(self):
        self.add_paper("200")
        self.extract("200", [claim()])
        reg = json.loads((self.library_root / "papers/200/claim_registry.json").read_text())
        claim_id = next(iter(reg["claims"]))

        verify.review_claim(self.library_root, "200", claim_id, "accept", "reviewer1", "looks right", None)
        self.extract("200", [claim()])  # unchanged content, same locator -> same claim_id

        corrections = verify.show(self.library_root, "200")
        self.assertEqual(len(corrections), 1)
        self.assertEqual(corrections[0]["status"], "active")
        self.assertEqual(corrections[0]["decision"], "accept")


class TestCorrectionPendingOnSupersession(TempLibrary):
    def test_correction_flips_to_pending_review_on_material_change(self):
        self.add_paper("201")
        self.extract("201", [claim()])
        reg = json.loads((self.library_root / "papers/201/claim_registry.json").read_text())
        claim_id = next(iter(reg["claims"]))

        verify.review_claim(self.library_root, "201", claim_id, "accept", "reviewer1", "ok", None)
        self.extract("201", [claim(direction="increase", effect_value="99")])  # materially different

        corrections = verify.show(self.library_root, "201")
        self.assertEqual(len(corrections), 1)
        self.assertEqual(corrections[0]["status"], "pending_review")


class TestRejectedClaimRetainedForAudit(TempLibrary):
    def test_rejected_flagged_excluded_but_not_deleted(self):
        self.add_paper("202")
        self.extract("202", [claim()])
        reg = json.loads((self.library_root / "papers/202/claim_registry.json").read_text())
        claim_id = next(iter(reg["claims"]))

        verify.review_claim(self.library_root, "202", claim_id, "reject", "reviewer1", "not supported", None)

        reg2 = json.loads((self.library_root / "papers/202/claim_registry.json").read_text())
        self.assertIn(claim_id, reg2["claims"])  # retained, not deleted
        self.assertTrue(reg2["claims"][claim_id]["excluded_from_synthesis"])
        corrections = verify.show(self.library_root, "202")
        self.assertEqual(corrections[0]["decision"], "reject")


class TestAuthorContributionRequiresEvidence(TempLibrary):
    def test_refused_without_evidence_statement(self):
        self.add_paper("203")
        with self.assertRaises(ValueError):
            verify.review_author_contribution(self.library_root, "203", 0, "shared_first", "", "reviewer1")
        with self.assertRaises(ValueError):
            verify.review_author_contribution(self.library_root, "203", 0, "shared_first", None, "reviewer1")

    def test_accepted_with_explicit_statement(self):
        self.add_paper("204")
        entry = verify.review_author_contribution(
            self.library_root, "204", 0, "shared_first",
            "Authors Smith and Doe contributed equally to this work.", "reviewer1",
        )
        self.assertEqual(entry["flag"], "shared_first")
        auth = json.loads((self.library_root / "papers/204/authorship.json").read_text())
        self.assertEqual(len(auth["contribution_flags"]), 1)


class TestGrantAliasNotCollapsed(TempLibrary):
    def test_two_distinct_awards_under_same_funder_stay_distinct(self):
        grant.create(self.library_root, "nih-r01-a", "NIH", "R01-AA11111", None, None, None)
        grant.create(self.library_root, "nih-r01-b", "NIH", "R01-BB22222", None, None, None)
        self.add_paper("205")
        self.add_paper("206")

        verify.review_grant_link(self.library_root, "205", "nih-r01-a", "accept", "reviewer1",
                                  "explicit ack", "acknowledgements", "R01-AA11111")
        verify.review_grant_link(self.library_root, "206", "nih-r01-b", "accept", "reviewer1",
                                  "explicit ack", "acknowledgements", "R01-BB22222")

        gA = json.loads((self.library_root / "grants/nih-r01-a.json").read_text())
        gB = json.loads((self.library_root / "grants/nih-r01-b.json").read_text())
        self.assertEqual(gA["approved_aliases"], ["R01-AA11111"])  # untouched by the review
        self.assertEqual(gB["approved_aliases"], ["R01-BB22222"])
        self.assertNotEqual(gA["award_number"], gB["award_number"])
        self.assertEqual(gA["publication_links"][0]["pmid"], "205")
        self.assertEqual(gB["publication_links"][0]["pmid"], "206")


class TestPersonIdentityReviewDelegates(TempLibrary):
    def test_accept_confirms_via_person_py(self):
        person.create(self.library_root, "jane-smith", "Jane Smith", None)
        self.add_paper("207")
        verify.review_person_identity(self.library_root, "207", "jane-smith", 0, "accept", "reviewer1", "matches ORCID")
        p = json.loads((self.library_root / "people/jane-smith.json").read_text())
        self.assertEqual(p["confirmed_publications"], [{"pmid": "207", "author_index": 0}])
        corrections = verify.show(self.library_root, "207")
        self.assertEqual(corrections[0]["target_type"], "person_identity")


if __name__ == "__main__":
    unittest.main()
