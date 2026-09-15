#!/usr/bin/env python3
"""Phase 9 gate fixtures for /ref:related (PLAN.md §8 build-order row for
phase 9, the snowballing subset).

Run: python3 skills/ref-manager/scripts/tests/test_phase9_related.py
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
import init_repo  # noqa: E402
import related  # noqa: E402
from lib_atomic import atomic_write_json, atomic_write_text, commit_version  # noqa: E402


def author(last, first):
    return {"last": last, "first": first, "raw": f"{last} {first}"}


class TempLibrary(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.library_root = self.tmp / "lib"
        for rel in init_repo.LIBRARY_DIRS:
            (self.library_root / rel).mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def add_paper(self, pmid):
        return add.add_one(self.library_root, {
            "pmid": pmid, "title": f"Paper {pmid}", "abstract": "abs",
            "authors": [author("A", "B")], "journal": "J", "year": "2022",
            "doi": None, "pmcid": None, "grants": [],
        })

    def commit_source_md(self, pmid, text):
        paper_dir = self.library_root / "papers" / pmid

        def write_fn(staging):
            atomic_write_text(staging / "source.md", text)

        commit_version(paper_dir, "v-test1", write_fn)


class TestForward(TempLibrary):
    def test_candidates_persist_with_query_and_timestamp(self):
        self.add_paper("100")
        report = related.forward(self.library_root, "100", "pubmed_pubmed", ["200", "201"], {})
        summary = related.persist(self.library_root, "100", report["rows"])
        self.assertEqual(summary["total_candidates"], 2)
        rows = related._load(self.library_root, "100")
        for r in rows:
            self.assertEqual(r["method"], "find_related_articles:pubmed_pubmed")
            self.assertIn("source_pmid", r["query"])
            self.assertTrue(r["retrieved_at"])

    def test_already_in_library_vs_not_yet_added(self):
        self.add_paper("100")
        self.add_paper("200")  # 200 is already in the library, 201 is not
        report = related.forward(self.library_root, "100", "pubmed_pubmed", ["200", "201"], {})
        for r in report["rows"]:
            r["already_in_library"] = related._already_in_library(self.library_root, r["candidate"], True)
        summary = related.persist(self.library_root, "100", report["rows"])
        self.assertEqual(summary["already_in_library"], 1)
        self.assertEqual(summary["not_yet_added"], 1)
        rows = {r["candidate"]: r for r in related._load(self.library_root, "100")}
        self.assertTrue(rows["200"]["already_in_library"])
        self.assertFalse(rows["201"]["already_in_library"])
        # neither candidate silently became a real library record beyond what add_paper did
        self.assertFalse((self.library_root / "papers" / "201").exists())

    def test_zero_results_reported_not_implied_complete(self):
        self.add_paper("100")
        report = related.forward(self.library_root, "100", "pubmed_pubmed", [], {})
        self.assertTrue(report["zero_results"])
        self.assertIn("not evidence of no related work", report["note"])

    def test_rerun_does_not_duplicate(self):
        self.add_paper("100")
        report = related.forward(self.library_root, "100", "pubmed_pubmed", ["200"], {})
        related.persist(self.library_root, "100", report["rows"])
        report2 = related.forward(self.library_root, "100", "pubmed_pubmed", ["200"], {})
        summary2 = related.persist(self.library_root, "100", report2["rows"])
        self.assertEqual(summary2["total_candidates"], 1)  # not 2


class TestBackward(TempLibrary):
    def test_extracts_raw_candidates_from_references_section(self):
        self.add_paper("300")
        self.commit_source_md("300", (
            "# Introduction\n\nSome text.\n\n"
            "# References\n\n"
            "1. Smith J, et al. A study of things. Journal of Things. 2019.\n"
            "2. Doe A, et al. Another study of things. Journal of Things. 2020.\n"
        ))
        report = related.backward(self.library_root, "300")
        self.assertTrue(report["available"])
        self.assertEqual(len(report["candidates"]), 2)
        for c in report["candidates"]:
            self.assertFalse(c["resolved"])
            self.assertEqual(c["direction"], "backward")
            self.assertEqual(c["method"], "reference_list")
        self.assertIn("Smith J", report["candidates"][0]["candidate"])

    def test_no_full_text_reports_unavailable(self):
        self.add_paper("301")
        report = related.backward(self.library_root, "301")
        self.assertFalse(report["available"])
        self.assertIn("no committed full-text", report["reason"])

    def test_full_text_without_references_heading_reports_not_found(self):
        self.add_paper("302")
        self.commit_source_md("302", "# Introduction\n\nJust body text, no bibliography.\n")
        report = related.backward(self.library_root, "302")
        self.assertFalse(report["available"])
        self.assertIn("no References", report["reason"])


if __name__ == "__main__":
    unittest.main()
