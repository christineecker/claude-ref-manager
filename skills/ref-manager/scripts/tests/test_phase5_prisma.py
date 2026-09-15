#!/usr/bin/env python3
"""Phase 5 PRISMA-flow gate fixtures (PLAN.md §8 build-order row for phase 5,
the /ref:review --prisma subset).

Run: python3 skills/ref-manager/scripts/tests/test_phase5_prisma.py
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
import project  # noqa: E402
import screen  # noqa: E402
import pubmed_query  # noqa: E402
import prisma  # noqa: E402
import init_repo  # noqa: E402


def author(last, first):
    return {"last": last, "first": first, "raw": f"{last} {first}"}


class TempLibrary(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.library_root = self.tmp / "lib"
        for rel in init_repo.LIBRARY_DIRS:
            (self.library_root / rel).mkdir(parents=True, exist_ok=True)
        project.create(self.library_root, "thesis", "ch3")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def add_paper(self, pmid, full_text=None, **overrides):
        record = {
            "pmid": pmid, "title": f"Paper {pmid}", "abstract": "abs",
            "authors": [author("Ahn", "Su-Jin")], "journal": "X", "year": "2022",
            "doi": f"10.1/{pmid}", "pmcid": None, "grants": [],
        }
        record.update(overrides)
        add.add_one(self.library_root, record)
        if full_text is not None:
            meta_path = self.library_root / "papers" / pmid / "meta.json"
            meta = json.loads(meta_path.read_text())
            meta["full_text"] = full_text
            meta_path.write_text(json.dumps(meta))

    def save_query_run(self, slug, pmids, source="pubmed", query_text="cancer AND therapy"):
        return pubmed_query.new_run(self.library_root, slug, query_text, source, pmids, create=True)


class TestHappyPath(TempLibrary):
    def test_counts_reconcile(self):
        for pmid in ("1", "2", "3", "4"):
            self.add_paper(pmid, full_text=(pmid != "4"))
        self.save_query_run("q1", ["1", "2", "3", "4"])
        screen.decide(self.library_root, "thesis", "1", "included", "relevant", None)
        screen.decide(self.library_root, "thesis", "2", "included", "relevant", None)
        screen.decide(self.library_root, "thesis", "3", "excluded", "wrong population", None)
        screen.decide(self.library_root, "thesis", "4", "included", "relevant", None)

        result = prisma.run_prisma(self.library_root, "thesis", [("q1", None)], refresh=False)
        flow = result["manifest"]["flow"]

        self.assertEqual(flow["identified"]["total_raw"], 4)
        self.assertEqual(flow["duplicates_removed"], 0)
        self.assertEqual(flow["screened"], 4)
        self.assertEqual(flow["excluded"]["count"], 1)
        self.assertEqual(flow["excluded"]["by_reason"], {"wrong population": 1})
        self.assertEqual(flow["included"]["publications_count"], 3)
        self.assertEqual(flow["reports"]["sought"], 3)
        self.assertEqual(flow["reports"]["not_retrieved"], 1)
        self.assertIn("4", flow["reports"]["not_retrieved_pmids"])


class TestUnbalanceableScenario(TempLibrary):
    def test_screening_without_backing_query_run_is_unknown_not_forced(self):
        self.add_paper("10", full_text=True)
        self.save_query_run("q1", ["11", "12"])  # does NOT include PMID 10
        screen.decide(self.library_root, "thesis", "10", "included", "found elsewhere", None)

        result = prisma.run_prisma(self.library_root, "thesis", [("q1", None)], refresh=False)
        flow = result["manifest"]["flow"]

        self.assertIn("10", flow["unevidenced_screened_pmids"])
        # still counted as screened/included (it really was screened) -- but its
        # provenance relative to the identified set is explicitly flagged, not hidden
        self.assertEqual(flow["screened"], 1)
        self.assertEqual(flow["included"]["publications_count"], 1)

    def test_missing_query_reference_is_unresolved_not_zero(self):
        self.add_paper("20")
        result = prisma.run_prisma(self.library_root, "thesis", [("no-such-query", None)], refresh=False)
        flow = result["manifest"]["flow"]
        self.assertEqual(len(flow["unresolved_query_specs"]), 1)
        self.assertEqual(flow["unresolved_query_specs"][0]["query"], "no-such-query")
        # not silently treated as 0 identified records contributing to a "clean" report --
        # total_raw is 0 for what WAS resolved (nothing), but the unresolved ref is surfaced
        self.assertEqual(flow["identified"]["total_raw"], 0)

    def test_no_query_arg_reports_identified_as_unknown(self):
        self.add_paper("30")
        screen.decide(self.library_root, "thesis", "30", "included", "x", None)
        result = prisma.run_prisma(self.library_root, "thesis", [], refresh=False)
        flow = result["manifest"]["flow"]
        self.assertEqual(flow["identified"]["total_raw"], "unknown")
        self.assertEqual(flow["duplicates_removed"], "unknown")
        self.assertIsNotNone(flow["identified"]["note"])
        # other sections still render
        self.assertEqual(flow["screened"], 1)


class TestStudiesVsPublications(TempLibrary):
    def _write_studies_jsonl(self, records):
        p = self.library_root / "studies" / "studies.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("\n".join(json.dumps(r) for r in records) + "\n")

    def test_grouped_study_reduces_study_count_below_publication_count(self):
        for pmid in ("40", "41", "42"):
            self.add_paper(pmid, full_text=True)
        self.save_query_run("q1", ["40", "41", "42"])
        for pmid in ("40", "41", "42"):
            screen.decide(self.library_root, "thesis", pmid, "included", "x", None)
        self._write_studies_jsonl([
            {"study_id": "s1", "publications": ["40", "41"], "grouping_confidence": "confirmed", "review_state": "reviewed"},
        ])

        result = prisma.run_prisma(self.library_root, "thesis", [("q1", None)], refresh=False)
        flow = result["manifest"]["flow"]
        self.assertEqual(flow["included"]["publications_count"], 3)
        # 40+41 grouped into one study, 42 stands alone -> 2 studies total
        self.assertEqual(flow["included"]["studies_count"], 2)
        self.assertNotEqual(flow["included"]["studies_count"], flow["included"]["publications_count"])

    def test_studies_jsonl_absent_marks_studies_count_unavailable(self):
        self.add_paper("50", full_text=True)
        self.save_query_run("q1", ["50"])
        screen.decide(self.library_root, "thesis", "50", "included", "x", None)

        result = prisma.run_prisma(self.library_root, "thesis", [("q1", None)], refresh=False)
        flow = result["manifest"]["flow"]
        self.assertEqual(flow["included"]["studies_count"], "unknown")
        self.assertIsNotNone(flow["included"]["studies_note"])
        # must NOT silently default to publications_count
        self.assertNotEqual(flow["included"]["studies_count"], flow["included"]["publications_count"])


class TestFreezeAndRefresh(TempLibrary):
    def test_reused_without_refresh_changed_with_refresh(self):
        self.add_paper("60", full_text=True)
        self.save_query_run("q1", ["60"])
        screen.decide(self.library_root, "thesis", "60", "included", "x", None)

        r1 = prisma.run_prisma(self.library_root, "thesis", [("q1", None)], refresh=False)
        self.assertEqual(r1["status"], "created")
        snap1 = r1["snapshot_id"]

        r2 = prisma.run_prisma(self.library_root, "thesis", [("q1", None)], refresh=False)
        self.assertEqual(r2["status"], "reused_frozen_snapshot")
        self.assertEqual(r2["snapshot_id"], snap1)

        # change screening state, then refresh
        self.add_paper("61", full_text=True)
        pubmed_query.rerun(self.library_root, "q1", ["60", "61"])
        screen.decide(self.library_root, "thesis", "61", "included", "x", None)

        r3 = prisma.run_prisma(self.library_root, "thesis", [("q1", None)], refresh=True)
        self.assertEqual(r3["status"], "refreshed")
        self.assertNotEqual(r3["snapshot_id"], snap1)
        self.assertIn("61", r3["included_added"])


if __name__ == "__main__":
    unittest.main()
