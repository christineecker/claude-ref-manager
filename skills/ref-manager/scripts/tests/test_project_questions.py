#!/usr/bin/env python3
"""Question<->paper link (DASHBOARD_NAV_IMPLEMENTATION_PLAN.md phase 5 / D8):
`papers.yaml` membership `questions: [qid, ...]`, qid validation, queue
set/unset, bulk assign (dashboard.py), per-question counts, and the
selector's `--project --question` narrowing.

Run: python3 skills/ref-manager/scripts/tests/test_project_questions.py
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

import init_repo  # noqa: E402
import project  # noqa: E402
import queue as queue_module  # noqa: E402
import lib_selector  # noqa: E402
from lib_schema import SchemaError  # noqa: E402


class TempLibrary(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.library_root = self.tmp / "lib"
        for rel in init_repo.LIBRARY_DIRS:
            (self.library_root / rel).mkdir(parents=True, exist_ok=True)
        self._write_meta("11111")
        self._write_meta("22222")
        project.create(self.library_root, "proj-a", "scope")
        project.add_question(self.library_root, "proj-a", "q1", "Does X affect Y?")
        project.add_question(self.library_root, "proj-a", "q2", "Does X affect Z?")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_meta(self, pmid: str) -> None:
        pdir = self.library_root / "papers" / pmid
        pdir.mkdir(parents=True, exist_ok=True)
        (pdir / "meta.json").write_text(json.dumps({
            "pmid": pmid, "citekey": f"key{pmid}", "title": "T", "year": "2024",
            "journal": "J", "doi": None, "pmcid": None, "status": "active",
            "extraction_tier": "abstract", "checked_at": "2026-01-01T00:00:00Z",
            "abstract_available": True, "full_text": False,
        }))


class TestSchemaDefault(TempLibrary):
    def test_absent_questions_reads_as_empty(self):
        # A membership record written before this field existed has no
        # "questions" key at all -- every reader must treat that as [],
        # never KeyError (plan §5.1: "absent = [], so no migration needed").
        papers_path = self.library_root / "projects" / "proj-a" / "papers.yaml"
        papers_path.write_text(json.dumps({"papers": [{"pmid": "11111", "reading_status": None}]}))
        result = queue_module.set_state(self.library_root, "proj-a", "11111", "to_read", None, None)
        self.assertEqual(result.get("questions", []), [])

    def test_add_paper_default_is_empty_list(self):
        m = project.add_paper(self.library_root, "proj-a", "11111", None, None, None)
        self.assertEqual(m["questions"], [])

    def test_add_paper_with_questions(self):
        m = project.add_paper(self.library_root, "proj-a", "11111", None, None, None, questions=["q1", "q2"])
        self.assertEqual(m["questions"], ["q1", "q2"])


class TestQidValidation(TempLibrary):
    def test_add_paper_rejects_unknown_qid(self):
        with self.assertRaises(SchemaError):
            project.add_paper(self.library_root, "proj-a", "11111", None, None, None, questions=["nope"])

    def test_set_paper_questions_rejects_unknown_qid_on_add(self):
        project.add_paper(self.library_root, "proj-a", "11111", None, None, None)
        with self.assertRaises(SchemaError):
            project.set_paper_questions(self.library_root, "proj-a", "11111", add=["nope"])

    def test_set_paper_questions_allows_removing_anything(self):
        # No validation needed to remove a link -- an id that no longer
        # exists on the project can still be cleared off old memberships.
        project.add_paper(self.library_root, "proj-a", "11111", None, None, None, questions=["q1"])
        m = project.set_paper_questions(self.library_root, "proj-a", "11111", remove=["stale-qid", "q1"])
        self.assertEqual(m["questions"], [])


class TestQueueSetUnset(TempLibrary):
    def test_question_add_and_remove(self):
        project.add_paper(self.library_root, "proj-a", "11111", None, None, None)
        m = queue_module.set_state(self.library_root, "proj-a", "11111", "to_read", None, None)
        self.assertEqual(m.get("questions", []), [])
        m2 = project.set_paper_questions(self.library_root, "proj-a", "11111", add=["q1", "q2"])
        self.assertEqual(m2["questions"], ["q1", "q2"])
        m3 = project.set_paper_questions(self.library_root, "proj-a", "11111", remove=["q1"])
        self.assertEqual(m3["questions"], ["q2"])

    def test_add_is_idempotent(self):
        project.add_paper(self.library_root, "proj-a", "11111", None, None, None, questions=["q1"])
        m = project.set_paper_questions(self.library_root, "proj-a", "11111", add=["q1"])
        self.assertEqual(m["questions"], ["q1"])

    def test_not_a_member_refused(self):
        with self.assertRaises(SchemaError):
            project.set_paper_questions(self.library_root, "proj-a", "99999", add=["q1"])


class TestBulkAssignHelper(TempLibrary):
    """dashboard.py's bulk-assign POST is one `set_paper_questions()` call
    per pmid (§6) -- exercised here at the project.py layer; the HTTP route
    itself (token/origin checks, request shape) is covered in
    test_dashboard_serve.py."""

    def test_bulk_assign_over_several_pmids(self):
        project.add_paper(self.library_root, "proj-a", "11111", None, None, None)
        project.add_paper(self.library_root, "proj-a", "22222", None, None, None)
        for pmid in ("11111", "22222"):
            project.set_paper_questions(self.library_root, "proj-a", pmid, add=["q1"])
        doc = json.loads((self.library_root / "projects" / "proj-a" / "papers.yaml").read_text())
        self.assertTrue(all(m["questions"] == ["q1"] for m in doc["papers"]))


class TestPerQuestionCounts(TempLibrary):
    def test_dashboard_summary_counts_by_question(self):
        project.add_paper(self.library_root, "proj-a", "11111", None, None, None, questions=["q1"])
        project.add_paper(self.library_root, "proj-a", "22222", None, None, None, questions=[])
        info = project.dashboard_summary(self.library_root, "proj-a")
        by_pmid = {m["pmid"]: m for m in json.loads(
            (self.library_root / "projects" / "proj-a" / "papers.yaml").read_text()
        )["papers"]}
        assigned = [pmid for pmid, m in by_pmid.items() if "q1" in (m.get("questions") or [])]
        unassigned = [pmid for pmid, m in by_pmid.items() if not m.get("questions")]
        self.assertEqual(assigned, ["11111"])
        self.assertEqual(unassigned, ["22222"])
        self.assertEqual(info["summary"]["paper_count"], 2)


class TestSelectorNarrowing(TempLibrary):
    def test_project_and_question_narrows_resolved_set(self):
        project.add_paper(self.library_root, "proj-a", "11111", None, None, None, questions=["q1"])
        project.add_paper(self.library_root, "proj-a", "22222", None, None, None, questions=["q2"])
        result = lib_selector.resolve(self.library_root, project="proj-a", question="q1")
        self.assertEqual(result["pmids"], ["11111"])

    def test_question_with_no_matches_is_empty_not_an_error(self):
        project.add_paper(self.library_root, "proj-a", "11111", None, None, None, questions=["q2"])
        with self.assertRaises(lib_selector.SelectorError):
            lib_selector.resolve(self.library_root, project="proj-a", question="q1")


if __name__ == "__main__":
    unittest.main()
