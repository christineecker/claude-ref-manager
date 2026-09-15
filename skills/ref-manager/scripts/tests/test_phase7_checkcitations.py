#!/usr/bin/env python3
"""Phase 7 (/ref:check-citations) gate fixtures (PLAN.md §8 build-order row
for phase 7, §5a's check-citations bullet).

Same fixture-injection pattern as phases 4/6: no live subagent judgment
inside a plain python test process, so a "calling agent's assertion-check
output" is hand-constructed and fed directly to check_citations.py's
validation/persistence layer.

Run: python3 skills/ref-manager/scripts/tests/test_phase7_checkcitations.py
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
import project  # noqa: E402
import init_repo  # noqa: E402
import check_citations  # noqa: E402
from lib_schema import SchemaError  # noqa: E402


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

    def claim_id_for(self, pmid):
        registry = json.loads((self.library_root / f"papers/{pmid}/claim_registry.json").read_text())
        return next(iter(registry["claims"]))


class TestFourVerdictKinds(TempLibrary):
    def test_supported_overstated_conflicting_unavailable_all_persist_distinctly(self):
        self.add_paper("900")
        r = self.extract("900", [claim(evidence_span="Drug A reduced blood pressure by 5 mmHg (95% CI 2-8).")])
        cid = self.claim_id_for("900")

        self.add_paper("901")
        self.extract("901", [claim(evidence_span="Drug A showed no significant change in blood pressure.",
                                    direction="no significant difference")])
        cid2 = self.claim_id_for("901")

        paragraph = (
            "Drug A definitively cures hypertension. Drug A lowers blood pressure modestly. "
            "Drug A has no effect on blood pressure. Drug A improves memory."
        )
        candidates = [
            {"pmid": "900", "claim_id": cid, "kind": "claim", "text": "evidence"},
            {"pmid": "901", "claim_id": cid2, "kind": "claim", "text": "evidence"},
        ]
        findings = [
            {"assertion_text": "Drug A definitively cures hypertension.", "verdict": "overstated",
             "evidence": [{"pmid": "900", "claim_id": cid}], "note": "evidence shows a modest reduction, not a cure"},
            {"assertion_text": "Drug A lowers blood pressure modestly.", "verdict": "supported",
             "evidence": [{"pmid": "900", "claim_id": cid}]},
            {"assertion_text": "Drug A has no effect on blood pressure.", "verdict": "conflicting",
             "evidence": [{"pmid": "901", "claim_id": cid2}], "note": "contradicts the other paper's finding"},
            {"assertion_text": "Drug A improves memory.", "verdict": "unavailable", "evidence": []},
        ]
        result = check_citations.persist_check(self.library_root, None, paragraph, findings,
                                                 candidates, None, export_bib=False)
        verdicts = {f["verdict"] for f in result["findings"]}
        self.assertEqual(verdicts, {"overstated", "supported", "conflicting", "unavailable"})
        self.assertEqual(result["manifest"]["verdict_counts"],
                          {"supported": 1, "overstated": 1, "conflicting": 1, "insufficient": 0, "unavailable": 1})


class TestEvidenceRequirements(TempLibrary):
    def test_non_unavailable_verdict_requires_evidence(self):
        with self.assertRaises(SchemaError):
            check_citations.persist_check(
                self.library_root, None, "Drug B works.",
                [{"assertion_text": "Drug B works.", "verdict": "supported", "evidence": []}],
                [], None, export_bib=False,
            )

    def test_unavailable_verdict_forbids_evidence(self):
        with self.assertRaises(SchemaError):
            check_citations.persist_check(
                self.library_root, None, "Drug B works.",
                [{"assertion_text": "Drug B works.", "verdict": "unavailable",
                  "evidence": [{"pmid": "1"}]}],
                [{"pmid": "1", "kind": "claim"}], None, export_bib=False,
            )

    def test_evidence_must_resolve_to_supplied_candidates(self):
        with self.assertRaises(SchemaError):
            check_citations.persist_check(
                self.library_root, None, "Drug B works.",
                [{"assertion_text": "Drug B works.", "verdict": "supported",
                  "evidence": [{"pmid": "999999"}]}],
                [{"pmid": "1", "kind": "claim"}], None, export_bib=False,
            )


class TestNeverRewritesInput(TempLibrary):
    def test_input_stored_verbatim_findings_reference_substrings(self):
        paragraph = "Drug C is effective. It has few side effects."
        self.add_paper("910")
        self.extract("910", [claim(evidence_span="Drug C reduced symptoms.")])
        cid = self.claim_id_for("910")
        candidates = [{"pmid": "910", "claim_id": cid, "kind": "claim", "text": "evidence"}]
        findings = [{"assertion_text": "Drug C is effective.", "verdict": "supported",
                     "evidence": [{"pmid": "910", "claim_id": cid}]}]
        result = check_citations.persist_check(self.library_root, None, paragraph, findings,
                                                 candidates, None, export_bib=False)
        stored = (self.library_root / "checks" / result["check_id"] / "input.md").read_text()
        self.assertEqual(stored, paragraph)

    def test_assertion_not_a_substring_of_paragraph_is_refused(self):
        with self.assertRaises(SchemaError):
            check_citations.persist_check(
                self.library_root, None, "Drug D is safe.",
                [{"assertion_text": "Drug D is totally safe with no risks whatsoever.",
                  "verdict": "supported", "evidence": [{"pmid": "1"}]}],
                [{"pmid": "1", "kind": "claim"}], None, export_bib=False,
            )


class TestMismatchedCitation(TempLibrary):
    def test_citation_mismatch_flagged_distinctly_from_uncited_assertion(self):
        self.add_paper("920")
        self.extract("920", [claim(evidence_span="Drug E showed no significant effect.",
                                    direction="no significant difference")])
        cid = self.claim_id_for("920")
        paragraph = "Drug E cures the disease [^920]. Drug E is inexpensive."
        candidates = [{"pmid": "920", "claim_id": cid, "kind": "claim", "text": "evidence"}]
        findings = [
            {"assertion_text": "Drug E cures the disease", "verdict": "overstated",
             "evidence": [{"pmid": "920", "claim_id": cid}],
             "existing_citation_pmid": "920", "citation_mismatch": True,
             "note": "cited evidence says no significant effect, not a cure"},
            {"assertion_text": "Drug E is inexpensive.", "verdict": "unavailable", "evidence": []},
        ]
        result = check_citations.persist_check(self.library_root, None, paragraph, findings,
                                                 candidates, None, export_bib=False)
        mismatch = next(f for f in result["findings"] if f.get("citation_mismatch"))
        uncited = next(f for f in result["findings"] if f["verdict"] == "unavailable")
        self.assertEqual(mismatch["existing_citation_pmid"], "920")
        self.assertNotIn("existing_citation_pmid", uncited)


class TestCaveat(TempLibrary):
    def test_report_carries_comprehensive_check_caveat(self):
        result = check_citations.persist_check(self.library_root, None, "Drug F helps.",
                                                 [{"assertion_text": "Drug F helps.", "verdict": "unavailable",
                                                   "evidence": []}], [], None, export_bib=False)
        self.assertIn("does not establish a comprehensive literature check", result["caveat"])
        self.assertEqual(result["manifest"]["caveat"], result["caveat"])


class TestBibliographyExportScope(TempLibrary):
    def test_export_only_includes_referenced_pmids(self):
        self.add_paper("930")
        self.extract("930", [claim(evidence_span="Drug G lowered fever.")])
        cid = self.claim_id_for("930")
        self.add_paper("931")  # in the library, but never referenced as evidence
        self.extract("931", [claim(evidence_span="Unrelated finding about drug H.")])

        paragraph = "Drug G lowered fever."
        candidates = [{"pmid": "930", "claim_id": cid, "kind": "claim", "text": "evidence"}]
        findings = [{"assertion_text": "Drug G lowered fever.", "verdict": "supported",
                     "evidence": [{"pmid": "930", "claim_id": cid}]}]
        result = check_citations.persist_check(self.library_root, None, paragraph, findings,
                                                 candidates, None, export_bib=True)
        csl = json.loads((self.library_root / "checks" / result["check_id"] / "references.csl.json").read_text())
        pmids_in_bib = {e["PMID"] for e in csl}
        self.assertEqual(pmids_in_bib, {"930"})
        self.assertTrue(result["manifest"]["bibliography_exported"])


class TestProjectScoping(TempLibrary):
    def test_project_scoped_check_persists_under_project(self):
        project.create(self.library_root, "thesis", None)
        result = check_citations.persist_check(self.library_root, "thesis", "Drug I helps.",
                                                 [{"assertion_text": "Drug I helps.", "verdict": "unavailable",
                                                   "evidence": []}], [], None, export_bib=False)
        self.assertTrue((self.library_root / "projects/thesis/checks" / result["check_id"] / "manifest.json").exists())

    def test_unscoped_check_persists_at_library_root(self):
        result = check_citations.persist_check(self.library_root, None, "Drug J helps.",
                                                 [{"assertion_text": "Drug J helps.", "verdict": "unavailable",
                                                   "evidence": []}], [], None, export_bib=False)
        self.assertTrue((self.library_root / "checks" / result["check_id"] / "manifest.json").exists())


class TestCitedPmidMerge(TempLibrary):
    def test_already_cited_pmid_pulled_in_even_if_not_in_candidates(self):
        self.add_paper("940")
        self.extract("940", [claim(evidence_span="Drug K improved outcomes in trial data.")])
        cid = self.claim_id_for("940")

        def claims_lookup(pmid):
            registry = json.loads((self.library_root / f"papers/{pmid}/claim_registry.json").read_text())
            return [{"pmid": pmid, "claim_id": k, "kind": "claim", "text": v["evidence_span"]}
                    for k, v in registry["claims"].items() if v["status"] == "active"]

        paragraph = "Some unrelated search terms here [^940]."
        merged = check_citations.merge_cited_pmid_candidates(paragraph, [], claims_lookup)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["pmid"], "940")
        self.assertTrue(merged[0]["cited_in_input"])


if __name__ == "__main__":
    unittest.main()
