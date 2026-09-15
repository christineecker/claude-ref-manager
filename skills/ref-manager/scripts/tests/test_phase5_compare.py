#!/usr/bin/env python3
"""Phase 5 (study/dataset/method grouping, /ref:compare, /ref:methods)
gate fixtures (PLAN.md §8 build-order row for phase 5, compare subset).

Run: python3 skills/ref-manager/scripts/tests/test_phase5_compare.py
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import add  # noqa: E402
import extract  # noqa: E402
import project  # noqa: E402
import study  # noqa: E402
import compare  # noqa: E402
import methods  # noqa: E402
import init_repo  # noqa: E402
from lib_ids import SlugError  # noqa: E402
from lib_selector import resolve, SelectorError  # noqa: E402


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

    def extract(self, pmid, claims, evidence_tier="full", **kwargs):
        record = {"pmid": pmid, "study_type": kwargs.pop("study_type", "rct"),
                   "study_type_confidence": "confident", "claims": claims,
                   "evidence_tier": evidence_tier, "source_hash": "deadbeef"}
        return extract.extract_one(self.library_root, record, STAMPS)

    def resolve(self, **kwargs):
        return resolve(self.library_root, **kwargs)


# --------------------------------------------------------------- study.py

class TestStudyGrouping(TempLibrary):
    def test_create_study_requires_evidence(self):
        self.add_paper("1")
        with self.assertRaises(SlugError):
            study.create_study(self.library_root, "s1", ["1"], "confirmed", "")

    def test_study_id_collision_refused(self):
        self.add_paper("1")
        self.add_paper("2")
        study.create_study(self.library_root, "s1", ["1"], "confirmed", "same trial registration")
        with self.assertRaises(SlugError):
            study.create_study(self.library_root, "s1", ["2"], "confirmed", "different reason")

    def test_dataset_reuse_does_not_imply_study(self):
        self.add_paper("1")
        self.add_paper("2")
        study.create_dataset(self.library_root, "nhanes-2018", "NHANES 2018", ["1", "2"])
        self.assertIsNone(study.study_for_pmid(self.library_root, "1"))
        self.assertIsNone(study.study_for_pmid(self.library_root, "2"))


# ------------------------------------------------------------- compare.py

class TestCompareCellSemantics(TempLibrary):
    def test_not_extracted_when_no_claims(self):
        self.add_paper("1")
        rows = compare.build_rows(self.library_root, ["1"], None)
        self.assertEqual(rows[0]["cells"]["1"]["population"]["value"], "not_extracted")
        self.assertEqual(rows[0]["cells"]["1"]["sample_size"]["value"], "not_extracted")

    def test_not_reported_when_claim_field_unknown(self):
        self.add_paper("1")
        self.extract("1", [claim(comparator="unknown")])
        rows = compare.build_rows(self.library_root, ["1"], None)
        self.assertEqual(rows[0]["cells"]["1"]["comparator"]["value"], "not_reported")

    def test_claim_backed_cell_references_claim_id(self):
        self.add_paper("1")
        self.extract("1", [claim(population="adults with hypertension")])
        rows = compare.build_rows(self.library_root, ["1"], None)
        cell = rows[0]["cells"]["1"]["population"]
        self.assertEqual(cell["value"], ["adults with hypertension"])
        self.assertTrue(cell["claim_ids"])

    def test_sample_size_and_limitations_always_not_extracted(self):
        # structurally unmapped by the claim schema (§4a) -- true even with claims present
        self.add_paper("1")
        self.extract("1", [claim()])
        rows = compare.build_rows(self.library_root, ["1"], None)
        self.assertEqual(rows[0]["cells"]["1"]["sample_size"]["value"], "not_extracted")
        self.assertEqual(rows[0]["cells"]["1"]["limitations"]["value"], "not_extracted")


class TestCompareSelectorEquivalence(TempLibrary):
    def test_bare_pmid_list_and_project_selector_produce_identical_rows(self):
        self.add_paper("1")
        self.add_paper("2")
        self.extract("1", [claim(population="A")])
        self.extract("2", [claim(population="B")])

        project.create(self.library_root, "proj1", None)
        project.add_paper(self.library_root, "proj1", "1", None, None, None)
        project.add_paper(self.library_root, "proj1", "2", None, None, None)

        bare = self.resolve(pmids=["1", "2"])
        via_project = self.resolve(project="proj1")
        self.assertEqual(bare["pmids"], via_project["pmids"])

        rows_bare = compare.build_rows(self.library_root, bare["pmids"], None)
        rows_project = compare.build_rows(self.library_root, via_project["pmids"], "proj1")
        # relevance cell legitimately differs (project-scoped), strip it before comparing
        def strip_relevance(rows):
            return [
                {**r, "cells": {p: {k: v for k, v in c.items() if k != "relevance"} for p, c in r["cells"].items()}}
                for r in rows
            ]
        self.assertEqual(strip_relevance(rows_bare), strip_relevance(rows_project))


class TestCompareStudyGroupingVsDatasetReuse(TempLibrary):
    def test_shared_study_groups_into_one_row(self):
        self.add_paper("1")
        self.add_paper("2")
        study.create_study(self.library_root, "trial-x", ["1", "2"], "confirmed", "same NCT number")
        rows = compare.build_rows(self.library_root, ["1", "2"], None)
        self.assertEqual(len(rows), 1)
        self.assertEqual(sorted(rows[0]["pmids"]), ["1", "2"])
        self.assertEqual(rows[0]["study"]["confidence"], "confirmed")

    def test_shared_dataset_alone_does_not_group(self):
        self.add_paper("1")
        self.add_paper("2")
        study.create_dataset(self.library_root, "cohort-y", "Cohort Y", ["1", "2"])
        rows = compare.build_rows(self.library_root, ["1", "2"], None)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r["study"] is None for r in rows))

    def test_uncertain_confidence_visible_not_hidden(self):
        self.add_paper("1")
        self.add_paper("2")
        study.create_study(self.library_root, "maybe-same", ["1", "2"], "uncertain", "same first author, unclear if same cohort")
        rows = compare.build_rows(self.library_root, ["1", "2"], None)
        self.assertEqual(rows[0]["study"]["confidence"], "uncertain")


class TestCompareFreezeAndRefresh(TempLibrary):
    def _args(self, **over):
        base = dict(pmids=None, project=None, question=None, screened=None, read=False,
                    queue=None, query=None, run=None, search=None, from_file=None,
                    study=None, concept=None, tier="any", exclude=None,
                    repo=str(self.library_root), batch="t1", refresh=False,
                    edit_pmid=None, edit_column=None, edit_value=None)
        base.update(over)
        return SimpleNamespace(**base)

    def test_manifest_records_selector_and_pmids(self):
        self.add_paper("1")
        resolution = self.resolve(pmids=["1"])
        result = compare.run_compare(self.library_root, "t1", None, resolution, refresh=False)
        self.assertIn("--pmid 1", result["manifest"]["selector_expression"])
        self.assertEqual(result["manifest"]["pmids"], ["1"])

    def test_rerun_without_refresh_reuses_frozen_table(self):
        self.add_paper("1")
        resolution = self.resolve(pmids=["1"])
        compare.run_compare(self.library_root, "t1", None, resolution, refresh=False)
        result2 = compare.run_compare(self.library_root, "t1", None, None, refresh=False)
        self.assertEqual(result2["status"], "reused_frozen_table")

    def test_refresh_after_adding_paper_reports_added_not_silent(self):
        self.add_paper("1")
        project.create(self.library_root, "proj1", None)
        project.add_paper(self.library_root, "proj1", "1", None, None, None)
        r1 = self.resolve(project="proj1")
        compare.run_compare(self.library_root, "t1", "proj1", r1, refresh=False)

        self.add_paper("2")
        project.add_paper(self.library_root, "proj1", "2", None, None, None)
        r2 = self.resolve(project="proj1")
        result = compare.run_compare(self.library_root, "t1", "proj1", r2, refresh=True)
        self.assertEqual(result["status"], "refreshed")
        self.assertEqual(result["added"], ["2"])

    def test_rows_include_provenance_metadata(self):
        self.add_paper("3")
        resolution = self.resolve(pmids=["3"])
        result = compare.run_compare(self.library_root, "t2", None, resolution, refresh=False)
        row = result["rows"][0]
        self.assertEqual(row["provenance"]["3"]["extraction_tier"], "abstract")
        self.assertIn("checked_at", row["provenance"]["3"])


class TestCompareUserEdits(TempLibrary):
    def test_edit_survives_refresh_when_evidence_unchanged(self):
        self.add_paper("1")
        resolution = self.resolve(pmids=["1"])
        compare.run_compare(self.library_root, "t1", None, resolution, refresh=False)
        compare.edit_cell(self.library_root, "t1", None, "1", "population", "manually corrected")

        result = compare.run_compare(self.library_root, "t1", None, resolution, refresh=True)
        cell = next(r for r in result["rows"] if "1" in r["cells"])["cells"]["1"]["population"]
        self.assertEqual(cell["user_edit"]["value"], "manually corrected")
        self.assertFalse(cell["user_edit"]["stale"])

    def test_edit_flagged_stale_when_evidence_changed(self):
        self.add_paper("1")
        resolution = self.resolve(pmids=["1"])
        compare.run_compare(self.library_root, "t1", None, resolution, refresh=False)
        compare.edit_cell(self.library_root, "t1", None, "1", "population", "manually corrected")

        self.extract("1", [claim(population="new extracted population")])
        result = compare.run_compare(self.library_root, "t1", None, resolution, refresh=True)
        cell = next(r for r in result["rows"] if "1" in r["cells"])["cells"]["1"]["population"]
        self.assertTrue(cell["user_edit"]["stale"])


# ------------------------------------------------------------- methods.py

class TestMethods(TempLibrary):
    def test_unreported_field_is_not_reported_not_inferred(self):
        self.add_paper("1")
        self.extract("1", [claim(study_design="unknown", adjustment_context="unknown")])
        rows = methods.run(self.library_root, ["1"])
        m = rows[0]["per_paper"][0]
        self.assertEqual(m["study_design"], "not_reported")
        self.assertEqual(m["instruments"], "not_reported")
        self.assertEqual(m["software"], "not_reported")

    def test_linked_method_record_surfaces(self):
        self.add_paper("1")
        study.create_method(self.library_root, "elisa-panel", "ELISA cytokine panel", ["1"],
                             context="serum samples", source_locator="Methods p3")
        rows = methods.run(self.library_root, ["1"])
        linked = rows[0]["per_paper"][0]["linked_methods"]
        self.assertEqual(linked[0]["method_id"], "elisa-panel")


if __name__ == "__main__":
    unittest.main()
