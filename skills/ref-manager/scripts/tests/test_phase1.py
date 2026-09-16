#!/usr/bin/env python3
"""Phase 1 gate fixtures (PLAN.md §8 build-order row for phase 1).

Run: python3 skills/ref-manager/scripts/tests/test_phase1.py
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
import project  # noqa: E402
import queue as queue_mod  # noqa: E402
import note  # noqa: E402
import person  # noqa: E402
import grant  # noqa: E402
import report  # noqa: E402
from lib_ids import SlugError  # noqa: E402
from lib_schema import SchemaError  # noqa: E402


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


# ---- /ref:add ----

class TestAddMissingAbstract(TempLibrary):
    def test_missing_abstract_creates_unavailable_not_error(self):
        record = {
            "pmid": "1001", "title": "A Study of Nothing", "abstract": None,
            "authors": [author("Alpha", "A")], "year": "2021",
        }
        result = add.add_one(self.library_root, record)
        self.assertEqual(result["result"], "added")
        self.assertEqual(result["extraction_tier"], "unavailable")
        meta = json.loads((self.library_root / "papers" / "1001" / "meta.json").read_text())
        self.assertEqual(meta["extraction_tier"], "unavailable")
        self.assertFalse(meta["abstract_available"])


class TestAddDuplicate(TempLibrary):
    def test_duplicate_add_is_noop_same_citekey(self):
        record = {
            "pmid": "1002", "title": "Cardiac Outcomes", "abstract": "some abstract",
            "authors": [author("Smith", "Jane")], "year": "2020",
        }
        r1 = add.add_one(self.library_root, record)
        r2 = add.add_one(self.library_root, record)
        self.assertEqual(r1["result"], "added")
        self.assertEqual(r2["result"], "already_present")
        self.assertEqual(r1["citekey"], r2["citekey"])
        # only one raw snapshot / meta write
        raw_dirs = list((self.library_root / "papers" / "1002" / "raw").iterdir())
        self.assertEqual(len(raw_dirs), 1)


class TestAddCitekeyCollision(TempLibrary):
    def test_two_different_pmids_same_citekey_base_get_suffixed(self):
        r1 = add.add_one(self.library_root, {
            "pmid": "2001", "title": "Cardiac Repair Mechanisms", "abstract": "x",
            "authors": [author("Smith", "Jane")], "year": "2020",
        })
        r2 = add.add_one(self.library_root, {
            "pmid": "2002", "title": "Cardiac Signaling Pathways", "abstract": "y",
            "authors": [author("Smith", "Jane")], "year": "2020",
        })
        self.assertEqual(r1["citekey"], "smith2020cardiac")
        self.assertEqual(r2["citekey"], "smith2020cardiac-2")
        # both records kept, neither silently merged
        self.assertTrue((self.library_root / "papers" / "2001").is_dir())
        self.assertTrue((self.library_root / "papers" / "2002").is_dir())


class TestAddPreservesRawOrderAndGrants(TempLibrary):
    def test_author_order_and_grant_strings_survive_ingest(self):
        authors = [author("Zed", "Zoe"), author("Alpha", "Amy"), author("Middle", "Max")]
        grants = [{"agency": "NIH", "grant_id": "R01-AB12345", "raw": "NIH R01-AB12345 (Doe)"}]
        record = {
            "pmid": "3001", "title": "Order Preservation Test", "abstract": "abs",
            "authors": authors, "year": "2019", "grants": grants,
        }
        add.add_one(self.library_root, record)
        authorship = json.loads((self.library_root / "papers" / "3001" / "authorship.json").read_text())
        self.assertEqual([a["last"] for a in authorship["authors"]], ["Zed", "Alpha", "Middle"])
        funding = json.loads((self.library_root / "papers" / "3001" / "funding.json").read_text())
        self.assertEqual(funding["observations"][0]["grant"]["raw"], "NIH R01-AB12345 (Doe)")
        self.assertEqual(funding["state"], "indexed_funding_association")


class TestAddIdentityWarnings(TempLibrary):
    def test_same_doi_different_title_warns(self):
        add.add_one(self.library_root, {
            "pmid": "3002", "title": "First Title", "abstract": "abs",
            "authors": [author("Smith", "Jane")], "year": "2020", "doi": "10.1/dup",
        })
        result = add.add_one(self.library_root, {
            "pmid": "3003", "title": "Second Title", "abstract": "abs",
            "authors": [author("Smith", "Jane")], "year": "2020", "doi": "10.1/dup",
        })
        self.assertIn("warnings", result)
        self.assertTrue(any("shares doi" in w for w in result["warnings"]))
        self.assertTrue(any("metadata mismatch" in w for w in result["warnings"]))

    def test_same_title_different_doi_warns(self):
        add.add_one(self.library_root, {
            "pmid": "3004", "title": "Shared Title", "abstract": "abs",
            "authors": [author("Smith", "Jane")], "year": "2020", "doi": "10.1/a",
        })
        result = add.add_one(self.library_root, {
            "pmid": "3005", "title": "Shared Title", "abstract": "abs",
            "authors": [author("Smith", "Jane")], "year": "2020", "doi": "10.1/b",
        })
        self.assertIn("warnings", result)
        self.assertTrue(any("shares title" in w for w in result["warnings"]))


# ---- /ref:project ----

class TestProjectIndependentMembership(TempLibrary):
    def test_paper_in_two_projects_independent_state(self):
        add.add_one(self.library_root, {
            "pmid": "4001", "title": "Shared Paper", "abstract": "abs",
            "authors": [author("Lee", "Kim")], "year": "2022",
        })
        project.create(self.library_root, "thesis-ch3", "chapter 3")
        project.create(self.library_root, "thesis-ch4", "chapter 4")
        project.add_paper(self.library_root, "thesis-ch3", "4001", "core evidence", 1, "reading")
        project.add_paper(self.library_root, "thesis-ch4", "4001", "background only", 3, "to_read")

        queue_mod.set_state(self.library_root, "thesis-ch3", "4001", "read", None, None)

        m3 = project.show(self.library_root, "thesis-ch3")["papers"]["papers"][0]
        m4 = project.show(self.library_root, "thesis-ch4")["papers"]["papers"][0]
        self.assertEqual(m3["reading_status"], "read")
        self.assertEqual(m4["reading_status"], "to_read")
        self.assertEqual(m3["relevance"], "core evidence")
        self.assertEqual(m4["relevance"], "background only")


class TestProjectQuestionScoping(TempLibrary):
    def test_same_question_id_in_two_projects(self):
        project.create(self.library_root, "thesis-ch3", None)
        project.create(self.library_root, "thesis-ch4", None)
        project.add_question(self.library_root, "thesis-ch3", "q1", "Does X affect Y?")
        project.add_question(self.library_root, "thesis-ch4", "q1", "Does A affect B?")  # must not collide
        p3 = json.loads((self.library_root / "projects" / "thesis-ch3" / "project.yaml").read_text())
        p4 = json.loads((self.library_root / "projects" / "thesis-ch4" / "project.yaml").read_text())
        self.assertEqual(p3["questions"][0]["text"], "Does X affect Y?")
        self.assertEqual(p4["questions"][0]["text"], "Does A affect B?")

    def test_duplicate_question_id_within_same_project_refused(self):
        project.create(self.library_root, "thesis-ch3", None)
        project.add_question(self.library_root, "thesis-ch3", "q1", "first")
        with self.assertRaises(SlugError):
            project.add_question(self.library_root, "thesis-ch3", "q1", "second")


class TestProjectSlugCollision(TempLibrary):
    def test_duplicate_project_slug_refused(self):
        project.create(self.library_root, "thesis-ch3", None)
        with self.assertRaises(SlugError):
            project.create(self.library_root, "thesis-ch3", None)


# ---- /ref:queue ----

class TestQueueRequiresMembership(TempLibrary):
    def test_set_on_non_member_errors(self):
        project.create(self.library_root, "thesis-ch3", None)
        with self.assertRaises(SchemaError):
            queue_mod.set_state(self.library_root, "thesis-ch3", "9999", "read", None, None)


# ---- /ref:note ----

class TestNoteAppendAndShow(TempLibrary):
    def test_append_then_show(self):
        add.add_one(self.library_root, {
            "pmid": "5001", "title": "Note Target", "abstract": "abs",
            "authors": [author("Doe", "Jo")], "year": "2018",
        })
        note.append(self.library_root, "5001", "worth re-reading for methods section")
        text = note.show(self.library_root, "5001")
        self.assertIn("worth re-reading for methods section", text)


# ---- /ref:person, /ref:grant ----

class TestPersonAndGrant(TempLibrary):
    def test_person_create_and_collision(self):
        person.create(self.library_root, "jane-smith", "Smith, Jane", "0000-0001-2345-6789")
        with self.assertRaises(SlugError):
            person.create(self.library_root, "jane-smith", "Smith, Jane Q", None)

    def test_grant_create_and_alias(self):
        grant.create(self.library_root, "r01-ab12345", "NIH", "R01-AB12345", "Cardiac Study", "jane-smith", "aim 1")
        g = grant.add_alias(self.library_root, "r01-ab12345", "5R01AB012345")
        self.assertIn("5R01AB012345", g["approved_aliases"])
        self.assertIn("R01-AB12345", g["approved_aliases"])


if __name__ == "__main__":
    unittest.main()
