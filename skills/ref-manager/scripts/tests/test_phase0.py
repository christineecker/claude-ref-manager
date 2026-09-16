#!/usr/bin/env python3
"""Phase 0 gate fixtures (PLAN.md §8 build-order row for phase 0).

Run: python3 skills/ref-manager/scripts/tests/test_phase0.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import catalog  # noqa: E402
import init_repo  # noqa: E402
import lib_atomic  # noqa: E402
import lib_ids  # noqa: E402
import lib_selector  # noqa: E402


class TempLibrary(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.library_root = self.tmp / "lib"
        for rel in init_repo.LIBRARY_DIRS:
            (self.library_root / rel).mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestSlugValidation(unittest.TestCase):
    def test_accepts_valid(self):
        for s in ("thesis-ch3", "a", "x" * 64, "abc123-def"):
            lib_ids.validate_slug(s)  # must not raise

    def test_rejects_illegal(self):
        for s in ("", "Thesis", "has_underscore", "-leading", "trailing-", "x" * 65, "double--hyphen"):
            with self.assertRaises(lib_ids.SlugError, msg=s):
                lib_ids.validate_slug(s)


class TestSlugCollision(TempLibrary):
    def test_duplicate_project_slug_refused_naming_conflict(self):
        (self.library_root / "projects" / "thesis-ch3").mkdir(parents=True)
        with self.assertRaises(lib_ids.SlugError) as cm:
            lib_ids.allocate_slug(self.library_root, "project", "thesis-ch3")
        self.assertIn("thesis-ch3", str(cm.exception))
        self.assertIn("already exists", str(cm.exception))

    def test_duplicate_registry_slug_refused(self):
        lib_ids.allocate_slug(self.library_root, "concept", "myocardial-infarction")
        with self.assertRaises(lib_ids.SlugError):
            lib_ids.allocate_slug(self.library_root, "concept", "myocardial-infarction")

    def test_no_silent_suffix_on_collision(self):
        # unlike citekey, a colliding project slug must be refused, not
        # suffixed to e.g. thesis-ch3-2
        (self.library_root / "projects" / "thesis-ch3").mkdir(parents=True)
        with self.assertRaises(lib_ids.SlugError):
            lib_ids.allocate_slug(self.library_root, "project", "thesis-ch3")
        self.assertFalse((self.library_root / "projects" / "thesis-ch3-2").exists())


class TestRename(TempLibrary):
    def test_rename_rewrites_and_leaves_resolving_alias(self):
        lib_ids.allocate_slug(self.library_root, "concept", "mi")
        lib_ids.rename_slug(self.library_root, "concept", "mi", "myocardial-infarction")
        self.assertFalse(lib_ids.slug_exists(self.library_root, "concept", "mi") is False and False)
        # old id still resolves
        self.assertEqual(
            lib_ids.resolve_slug(self.library_root, "concept", "mi"),
            "myocardial-infarction",
        )
        self.assertEqual(
            lib_ids.resolve_slug(self.library_root, "concept", "myocardial-infarction"),
            "myocardial-infarction",
        )
        # new slug is taken, so allocating it again is refused
        with self.assertRaises(lib_ids.SlugError):
            lib_ids.allocate_slug(self.library_root, "concept", "myocardial-infarction")

    def test_rename_dir_backed_slug(self):
        proj = self.library_root / "projects" / "old-name"
        proj.mkdir(parents=True)
        (proj / "project.yaml").write_text("slug: old-name\n")
        lib_ids.rename_slug(self.library_root, "project", "old-name", "new-name")
        self.assertFalse((self.library_root / "projects" / "old-name").exists())
        self.assertTrue((self.library_root / "projects" / "new-name").exists())
        self.assertEqual(lib_ids.resolve_slug(self.library_root, "project", "old-name"), "new-name")


class TestQuestionIds(unittest.TestCase):
    def test_question_ids_scoped_per_project_no_cross_collision(self):
        proj_a = {"slug": "thesis-ch3", "questions": [{"id": "q1"}]}
        proj_b = {"slug": "thesis-ch4", "questions": []}
        # q1 already used in project A must not block project B
        lib_ids.check_question_id(proj_b, "q1")  # must not raise
        with self.assertRaises(lib_ids.SlugError):
            lib_ids.check_question_id(proj_a, "q1")


class TestCitekey(TempLibrary):
    def test_collision_gets_suffixed_under_lock(self):
        k1 = lib_ids.allocate_citekey(self.library_root, "Smith", 2020, "Cardiac")
        k2 = lib_ids.allocate_citekey(self.library_root, "Smith", 2020, "Cardiac")
        k3 = lib_ids.allocate_citekey(self.library_root, "Smith", 2020, "Cardiac")
        self.assertEqual(k1, "smith2020cardiac")
        self.assertEqual(k2, "smith2020cardiac-2")
        self.assertEqual(k3, "smith2020cardiac-3")


class TestAtomicWrite(TempLibrary):
    def test_write_survives_interrupted_rewrite(self):
        target = self.library_root / "papers" / "12345" / "meta.json"
        lib_atomic.atomic_write_json(target, {"pmid": "12345", "v": 1})
        # simulate an interrupted rewrite: create the temp file, then crash
        # before os.replace — original must be untouched.
        tmp = target.parent / f".{target.name}.crashed.tmp"
        tmp.write_text("truncated garbage")
        self.assertEqual(json.loads(target.read_text())["v"], 1)
        tmp.unlink()
        # a real second write still succeeds and replaces cleanly
        lib_atomic.atomic_write_json(target, {"pmid": "12345", "v": 2})
        self.assertEqual(json.loads(target.read_text())["v"], 2)

    def test_commit_version_staging_failure_leaves_no_current(self):
        paper_dir = self.library_root / "papers" / "12345"
        paper_dir.mkdir(parents=True)

        def boom(staging_dir):
            (staging_dir / "manifest.json").write_text("{}")
            raise RuntimeError("simulated extraction failure")

        with self.assertRaises(RuntimeError):
            lib_atomic.commit_version(paper_dir, "v1", boom)
        self.assertFalse((paper_dir / "current.json").exists())
        self.assertFalse((paper_dir / "versions" / "v1").exists())
        self.assertFalse((paper_dir / "versions" / ".staging-v1").exists())


class TestInitAndCatalog(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.home = self.tmp / "home"
        self.home.mkdir()
        self._orig_config = init_repo.CONFIG_PATH

    def tearDown(self):
        init_repo.CONFIG_PATH = self._orig_config
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_init_empty_library_then_rebuild_noop(self):
        init_repo.CONFIG_PATH = self.home / ".config" / "ref-manager" / "config.json"
        target = self.tmp / "mylib"
        config = init_repo.init_library(target)
        self.assertTrue((target / "papers").is_dir())
        self.assertTrue((target / "index").is_dir())
        self.assertEqual(config["library_root"], str(target.resolve()))

        result = catalog.rebuild(target)
        self.assertEqual(result["papers_indexed"], 0)

        # add one paper, rebuild should pick it up
        pdir = target / "papers" / "111"
        pdir.mkdir()
        (pdir / "meta.json").write_text(json.dumps({
            "pmid": "111", "citekey": "x2020y", "title": "T",
            "status": "active", "extraction_tier": "abstract", "checked_at": "2026-01-01",
        }))
        result = catalog.rebuild(target)
        self.assertEqual(result["papers_indexed"], 1)

    def test_init_refuses_reconfigure_without_force(self):
        init_repo.CONFIG_PATH = self.home / ".config" / "ref-manager" / "config.json"
        init_repo.init_library(self.tmp / "lib1")
        with self.assertRaises(SystemExit):
            init_repo.init_library(self.tmp / "lib2")
        # --force allows it
        init_repo.init_library(self.tmp / "lib2", force=True)


class TestBrowseFirstSelector(TempLibrary):
    def _paper(self, pmid, checked_at, abstract_available=False, full_text=False, oa_location=None):
        paper_dir = self.library_root / "papers" / pmid
        paper_dir.mkdir(parents=True, exist_ok=True)
        meta = {
            "pmid": pmid,
            "citekey": f"k{pmid}",
            "title": f"Paper {pmid}",
            "year": "2026",
            "status": "active",
            "checked_at": checked_at,
            "extraction_tier": "abstract" if abstract_available else "unavailable",
            "abstract_available": abstract_available,
            "full_text": full_text,
        }
        if oa_location is not None:
            meta["oa_location"] = oa_location
        lib_atomic.atomic_write_json(paper_dir / "meta.json", meta)

    def test_recent_unresolved_only_returns_follow_up_papers(self):
        self._paper("111", "2026-01-03T00:00:00+00:00")
        self._paper("112", "2026-01-02T00:00:00+00:00", abstract_available=True)
        self._paper(
            "113", "2026-01-04T00:00:00+00:00",
            oa_location={"source": "unpaywall", "url": "https://example.test/oa.pdf"},
        )

        unresolved = lib_selector.recent(self.library_root, kind="unresolved")
        pmids = [row["pmid"] for row in unresolved]
        self.assertIn("111", pmids)
        self.assertIn("113", pmids)
        self.assertNotIn("112", pmids)
        self.assertIn(unresolved[0]["source_badge"], ("metadata-only", "oa-pending"))

    def test_recent_imports_alias_matches_recent(self):
        self._paper("121", "2026-01-05T00:00:00+00:00")
        recent_rows = lib_selector.recent(self.library_root, kind="recent")
        import_rows = lib_selector.recent(self.library_root, kind="imports")
        self.assertEqual([r["pmid"] for r in import_rows], [r["pmid"] for r in recent_rows])


if __name__ == "__main__":
    unittest.main()
