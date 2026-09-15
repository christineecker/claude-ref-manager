#!/usr/bin/env python3
"""Phase 6 (retrieval, synthesis validation, briefs) gate fixtures
(PLAN.md §8 build-order row for phase 6).

No live retrieval-synthesis subagent access inside a plain python test
process (same constraint every prior phase's tests have): retrieval/
citation-validation/brief persistence are tested directly; a synthesizer's
output is simulated as a hand-constructed answer string, same as every
other phase's "fixture-injection instead of a live subagent call" pattern.

Run: python3 skills/ref-manager/scripts/tests/test_phase6_ask.py
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import add  # noqa: E402
import extract  # noqa: E402
import project  # noqa: E402
import init_repo  # noqa: E402
import catalog  # noqa: E402
import ask_retrieve  # noqa: E402
import validate_citations  # noqa: E402
import brief  # noqa: E402
import verify  # noqa: E402


def author(last, first):
    return {"last": last, "first": first, "raw": f"{last} {first}"}


STAMPS = {"extractor": "ref-extractor", "model": "test", "prompt_version": "1"}


def claim(locator="Results/p1", **overrides):
    c = {
        "locator": locator, "evidence_span": "quoted evidence text here",
        "population": "adults", "intervention": "drug X", "comparator": "placebo",
        "outcome": "blood pressure", "timepoint": "12 weeks", "direction": "decrease",
        "effect_value": "5", "effect_measure": "mmHg", "uncertainty_interval": "95% CI 2-8",
        "study_design": "RCT", "cohort_identity": "unknown", "adjustment_context": "unknown",
    }
    c.update(overrides)
    return c


class TempLibrary(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.library_root = self.tmp / "lib"
        for rel in init_repo.LIBRARY_DIRS:
            (self.library_root / rel).mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def add_paper(self, pmid, title=None, **overrides):
        record = {
            "pmid": pmid, "title": title or f"Paper {pmid}", "abstract": "abs",
            "authors": [author("Smith", "Jane")], "journal": "X", "year": "2022",
            "doi": f"10.1/{pmid}", "pmcid": None, "grants": [],
        }
        record.update(overrides)
        return add.add_one(self.library_root, record)

    def extract(self, pmid, claims, evidence_tier="full", **kwargs):
        record = {
            "pmid": pmid, "study_type": kwargs.pop("study_type", "rct"),
            "study_type_confidence": "confident", "claims": claims,
            "evidence_tier": evidence_tier, "source_hash": "deadbeef",
        }
        record.update(kwargs)
        return extract.extract_one(self.library_root, record, STAMPS)


# ---------------------------------------------------------------- catalog

class TestCatalogIndexesClaimsAndPassages(TempLibrary):
    def test_rebuild_populates_fts_and_direct_query_finds_known_term(self):
        self.add_paper("500")
        self.extract("500", [claim(
            locator="Results/p1",
            evidence_span="Aspirin significantly reduced myocardial infarction risk in this cohort.",
        )])
        result = catalog.rebuild(self.library_root)
        self.assertEqual(result["claims_indexed"], 1)

        db_path = self.library_root / "index" / "catalog.sqlite"
        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT pmid FROM claims_fts WHERE claims_fts MATCH ?", ('"aspirin"',)
        ).fetchall()
        conn.close()
        self.assertEqual([r[0] for r in rows], ["500"])

    def test_passages_indexed_from_current_version_source_md(self):
        self.add_paper("501")
        version_dir = self.library_root / "papers" / "501" / "versions" / "v-fixture"
        version_dir.mkdir(parents=True)
        (version_dir / "source.md").write_text(
            "# Introduction\n\nThis paper studies exercise and blood pressure outcomes.\n\n"
            "# Results\n\nExercise reduced systolic blood pressure significantly.\n"
        )
        (self.library_root / "papers" / "501" / "current.json").write_text(
            json.dumps({"version": "v-fixture"})
        )
        result = catalog.rebuild(self.library_root)
        self.assertEqual(result["passages_indexed"], 2)


# ---------------------------------------------------------------- retrieval

class TestRetrieval(TempLibrary):
    def test_project_selector_constrains_candidates(self):
        self.add_paper("600", title="Statins and cholesterol")
        self.extract("600", [claim(evidence_span="Statins reduced LDL cholesterol substantially.")])
        self.add_paper("601", title="Exercise and outcomes")
        self.extract("601", [claim(evidence_span="Exercise reduced cardiovascular event rates.")])

        project.create(self.library_root, "proj-a", None)
        project.add_paper(self.library_root, "proj-a", "600", "core", 1, None)

        resolution = {"pmids": ["600"], "selector_expression": "--project proj-a", "report": {}}
        result = ask_retrieve.retrieve(self.library_root, "cholesterol statins", resolution=resolution)
        pmids = {c["pmid"] for c in result["candidates"]}
        self.assertEqual(pmids, {"600"})

    def test_insufficient_coverage_reported_explicitly(self):
        self.add_paper("610")
        self.extract("610", [claim(evidence_span="Something about a completely unrelated topic entirely.")])
        result = ask_retrieve.retrieve(self.library_root, "quantum computing nanotechnology")
        self.assertTrue(result["report"]["insufficient_coverage"])
        self.assertEqual(result["candidates"], [])

    def test_evidence_tier_and_retraction_status_present_on_every_candidate(self):
        self.add_paper("620")
        self.extract("620", [claim(evidence_span="Metformin improved glycemic control in this trial.")])
        result = ask_retrieve.retrieve(self.library_root, "metformin glycemic control")
        self.assertTrue(result["candidates"])
        for c in result["candidates"]:
            self.assertIn("evidence_tier", c)
            self.assertIn("retraction_status", c)
            self.assertIsNotNone(c["retraction_status"])

    def test_candidate_budget_truncation_reported(self):
        for i in range(5):
            pmid = f"63{i}"
            self.add_paper(pmid)
            self.extract(pmid, [claim(evidence_span=f"Aspirin reduced inflammation markers in study {i}.")])
        result = ask_retrieve.retrieve(self.library_root, "aspirin inflammation", candidate_budget=2)
        self.assertLessEqual(len(result["candidates"]), 2)
        self.assertTrue(result["report"]["truncated_by_candidate_budget"])

    def test_rejected_claim_excluded_from_candidates(self):
        self.add_paper("640")
        r = self.extract("640", [claim(evidence_span="Vitamin D supplementation reduced fracture risk.")])
        registry = json.loads((self.library_root / "papers/640/claim_registry.json").read_text())
        claim_id = next(iter(registry["claims"]))
        verify.review_claim(self.library_root, "640", claim_id, "reject", "reviewer", "underpowered", None)
        result = ask_retrieve.retrieve(self.library_root, "vitamin D fracture risk")
        self.assertEqual(result["candidates"], [])


# ---------------------------------------------------------------- citations

class TestCitationValidation(TempLibrary):
    def test_citation_to_supplied_pmid_resolves(self):
        candidates = [{"pmid": "700", "kind": "claim"}]
        result = validate_citations.validate("Statins lower LDL [^700].", candidates)
        self.assertEqual(result["resolved"], ["700"])
        self.assertTrue(result["all_resolved"])

    def test_citation_to_unsupplied_pmid_is_flagged(self):
        candidates = [{"pmid": "700", "kind": "claim"}]
        result = validate_citations.validate("Statins lower LDL [^700]. Also see [^999].", candidates)
        self.assertEqual(result["unresolved"], ["999"])
        self.assertFalse(result["all_resolved"])


# ---------------------------------------------------------------- briefs

class TestBrief(TempLibrary):
    def _candidates_for(self, pmid, claim_id):
        return [{"pmid": pmid, "claim_id": claim_id, "kind": "claim", "text": "evidence"}]

    def test_frozen_snapshot_persists_and_reuses_without_refresh(self):
        self.add_paper("800")
        r = self.extract("800", [claim(evidence_span="Drug X lowered blood pressure.")])
        registry = json.loads((self.library_root / "papers/800/claim_registry.json").read_text())
        claim_id = next(iter(registry["claims"]))
        candidates = self._candidates_for("800", claim_id)

        first = brief.save_brief(self.library_root, None, "bp-question", "does drug X lower BP?",
                                  None, candidates, "Drug X lowered BP [^800].", None, refresh=False)
        self.assertEqual(first["status"], "created")

        second = brief.save_brief(self.library_root, None, "bp-question", "does drug X lower BP?",
                                   None, candidates, "different text should be ignored", None, refresh=False)
        self.assertEqual(second["status"], "reused_frozen_brief")
        self.assertEqual(second["answer"], "Drug X lowered BP [^800].")

    def test_refresh_reports_withdrawn_evidence_after_claim_rejected(self):
        self.add_paper("810")
        self.extract("810", [claim(evidence_span="Drug Y improved outcomes.")])
        registry = json.loads((self.library_root / "papers/810/claim_registry.json").read_text())
        claim_id = next(iter(registry["claims"]))
        candidates = self._candidates_for("810", claim_id)

        brief.save_brief(self.library_root, None, "drugy-question", "does drug Y help?",
                          None, candidates, "Drug Y helped [^810].", None, refresh=False)

        verify.review_claim(self.library_root, "810", claim_id, "reject", "reviewer", "flawed", None)

        refreshed = brief.save_brief(self.library_root, None, "drugy-question", "does drug Y help?",
                                      None, [], "no evidence now", None, refresh=True)
        self.assertEqual(refreshed["status"], "refreshed")
        withdrawn_ids = {w["claim_id"] for w in refreshed["withdrawn_evidence"]}
        self.assertIn(claim_id, withdrawn_ids)

    def test_user_edit_survives_unchanged_refresh_and_flags_on_changed_evidence(self):
        self.add_paper("820")
        self.extract("820", [claim(evidence_span="Drug Z reduced symptoms.")])
        registry = json.loads((self.library_root / "papers/820/claim_registry.json").read_text())
        claim_id = next(iter(registry["claims"]))
        candidates = self._candidates_for("820", claim_id)

        brief.save_brief(self.library_root, None, "drugz-question", "does drug Z help?",
                          None, candidates, "Drug Z helped [^820].", None, refresh=False)
        edit = brief.edit_brief(self.library_root, None, "drugz-question", "I think this needs more caveats.")
        self.assertFalse(edit["stale"])

        # refresh with the SAME evidence set -> edit survives, not stale
        unchanged = brief.save_brief(self.library_root, None, "drugz-question", "does drug Z help?",
                                      None, candidates, "Drug Z helped [^820].", None, refresh=True)
        self.assertFalse(unchanged["user_edit"]["stale"])
        self.assertEqual(unchanged["user_edit"]["revision"], "I think this needs more caveats.")

        # refresh with a DIFFERENT evidence set -> edit survives but flags stale
        other_candidates = [{"pmid": "820", "claim_id": "some-other-claim-id", "kind": "claim", "text": "x"}]
        changed = brief.save_brief(self.library_root, None, "drugz-question", "does drug Z help?",
                                    None, other_candidates, "different finding [^820].", None, refresh=True)
        self.assertTrue(changed["user_edit"]["stale"])
        self.assertEqual(changed["user_edit"]["revision"], "I think this needs more caveats.")

    def test_project_scoped_brief_location(self):
        project.create(self.library_root, "thesis", None)
        candidates = []
        brief.save_brief(self.library_root, "thesis", "q1", "some question", None, candidates,
                          "an answer", None, refresh=False)
        self.assertTrue((self.library_root / "projects/thesis/briefs/q1/latest.json").exists())


if __name__ == "__main__":
    unittest.main()
