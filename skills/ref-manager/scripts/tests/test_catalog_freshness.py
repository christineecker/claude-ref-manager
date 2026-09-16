#!/usr/bin/env python3
"""Catalog fingerprint staleness + atomic rebuild.

Run: python3 skills/ref-manager/scripts/tests/test_catalog_freshness.py
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import catalog  # noqa: E402
import init_repo  # noqa: E402
import lint  # noqa: E402
import status  # noqa: E402


class CatalogFreshnessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.lib = self.tmp / "lib"
        for rel in init_repo.LIBRARY_DIRS:
            (self.lib / rel).mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _paper(self, pmid: str, title: str = "T") -> Path:
        pdir = self.lib / "papers" / pmid
        pdir.mkdir(parents=True, exist_ok=True)
        (pdir / "meta.json").write_text(json.dumps({
            "pmid": pmid, "citekey": f"k{pmid}", "title": title, "status": "active",
            "extraction_tier": "abstract", "checked_at": "2026-01-01",
        }))
        return pdir

    def _bump_mtime(self, path: Path) -> None:
        st = path.stat()
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))

    def _index_leftovers(self) -> list[str]:
        return [p.name for p in (self.lib / "index").iterdir() if ".tmp" in p.name]

    def test_missing_catalog_is_stale(self):
        self._paper("1")
        self.assertIsNone(catalog.catalog_info(self.lib))
        self.assertTrue(catalog.is_stale(self.lib))

    def test_fresh_after_rebuild_and_meta_recorded(self):
        self._paper("1")
        catalog.rebuild(self.lib)
        self.assertFalse(catalog.is_stale(self.lib))
        info = catalog.catalog_info(self.lib)
        self.assertEqual(info["papers_indexed"], "1")
        self.assertIn("built_at", info)
        self.assertEqual(info["fingerprint"], catalog.fingerprint(self.lib))
        self.assertEqual(self._index_leftovers(), [])

    def test_edit_without_count_change_marks_stale(self):
        pdir = self._paper("1")
        catalog.rebuild(self.lib)
        (pdir / "meta.json").write_text(json.dumps({"pmid": "1", "title": "changed"}))
        self._bump_mtime(pdir / "meta.json")
        self.assertTrue(catalog.is_stale(self.lib))

    def test_new_claim_registry_marks_stale(self):
        pdir = self._paper("1")
        catalog.rebuild(self.lib)
        (pdir / "claim_registry.json").write_text(json.dumps({"claims": {}}))
        self.assertTrue(catalog.is_stale(self.lib))

    def test_new_source_version_marks_stale(self):
        pdir = self._paper("1")
        catalog.rebuild(self.lib)
        (pdir / "versions" / "v1").mkdir(parents=True)
        (pdir / "versions" / "v1" / "source.md").write_text("# Intro\n\nBody.\n")
        (pdir / "current.json").write_text(json.dumps({"version": "v1"}))
        self.assertTrue(catalog.is_stale(self.lib))

    def test_removed_paper_marks_stale(self):
        self._paper("1")
        self._paper("2")
        catalog.rebuild(self.lib)
        shutil.rmtree(self.lib / "papers" / "2")
        self.assertTrue(catalog.is_stale(self.lib))

    def test_unrelated_files_do_not_mark_stale(self):
        pdir = self._paper("1")
        catalog.rebuild(self.lib)
        (pdir / "raw").mkdir()
        (pdir / "raw" / "notes.txt").write_text("x")
        (self.lib / "papers" / ".DS_Store").write_text("x")
        self.assertFalse(catalog.is_stale(self.lib))

    def test_catalog_without_fingerprint_is_stale(self):
        self._paper("1")
        catalog.rebuild(self.lib)
        with sqlite3.connect(self.lib / "index" / "catalog.sqlite") as conn:
            conn.execute("DELETE FROM catalog_meta WHERE key = 'fingerprint'")
        self.assertTrue(catalog.is_stale(self.lib))

    def test_corrupt_catalog_is_stale(self):
        self._paper("1")
        (self.lib / "index" / "catalog.sqlite").write_bytes(b"not a database")
        self.assertIsNone(catalog.catalog_info(self.lib))
        self.assertTrue(catalog.is_stale(self.lib))

    def test_failed_rebuild_keeps_previous_catalog(self):
        self._paper("1")
        catalog.rebuild(self.lib)
        before = catalog.catalog_info(self.lib)

        self._paper("2")
        with mock.patch.object(catalog, "_populate", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                catalog.rebuild(self.lib)

        self.assertEqual(catalog.catalog_info(self.lib), before)
        self.assertEqual(self._index_leftovers(), [])
        self.assertTrue(catalog.is_stale(self.lib))

    def test_lint_reports_stale_catalog(self):
        pdir = self._paper("1")
        catalog.rebuild(self.lib)
        self.assertFalse(lint.lint(self.lib)["summary"]["catalog_stale"])

        (pdir / "claim_registry.json").write_text(json.dumps({"claims": {}}))
        report = lint.lint(self.lib)
        self.assertTrue(report["summary"]["catalog_present"])
        self.assertTrue(report["summary"]["catalog_stale"])
        self.assertIn("run /ref:index --rebuild", report["recommendations"])

    def test_status_health_flags_out_of_date_catalog(self):
        rows = [{"pmid": "1", "title": "T"}]
        counts = {"metadata_only": 0, "abstract_only": 0, "oa_pending": 0}
        state, attention, actions = status._health(rows, counts, 1, True, 1, catalog_stale=True)
        self.assertEqual(state, "not indexed")
        self.assertIn("catalog out of date (papers changed since last rebuild)", attention)
        self.assertIn("/ref:index --rebuild", actions)

        state, _, _ = status._health(rows, counts, 1, True, 1, catalog_stale=False)
        self.assertEqual(state, "healthy")


if __name__ == "__main__":
    unittest.main()
