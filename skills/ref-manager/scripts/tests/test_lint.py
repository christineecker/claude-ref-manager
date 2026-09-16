#!/usr/bin/env python3
"""/ref:lint output shape + issue-bucket regression (MAINTENANCE_FEATURE_IMPLEMENTATION_PLAN.md Phase 3).

Run: python3 skills/ref-manager/scripts/tests/test_lint.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import init_repo  # noqa: E402

EXPECTED_BUCKETS = {
    "missing_meta", "missing_title", "missing_year", "missing_journal",
    "missing_abstract", "metadata_only", "abstract_only", "oa_pending",
    "missing_doi", "missing_current", "missing_claim_registry",
    "stale_retraction_check", "malformed_meta",
}


class TestLint(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.library_root = self.tmp / "lib"
        for rel in init_repo.LIBRARY_DIRS:
            (self.library_root / rel).mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_paper(self, pmid: str, meta: dict | None, malformed: bool = False,
                      current: bool = False, claim_registry: bool = False):
        paper_dir = self.library_root / "papers" / pmid
        paper_dir.mkdir(parents=True, exist_ok=True)
        if malformed:
            (paper_dir / "meta.json").write_text("not json{")
        elif meta is not None:
            (paper_dir / "meta.json").write_text(json.dumps(meta))
        if current:
            (paper_dir / "current.json").write_text("{}")
        if claim_registry:
            (paper_dir / "claim_registry.json").write_text("{}")

    def _run(self, *args):
        script = SCRIPTS / "lint.py"
        return subprocess.run(
            [sys.executable, str(script), "run", "--repo", str(self.library_root), *args],
            capture_output=True, text=True,
        )

    def test_json_report_shape(self):
        self._write_paper("11111", {
            "title": "t", "year": "2020", "journal": "j", "doi": "10.1/x",
            "abstract_available": True, "full_text": True,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }, current=True, claim_registry=True)

        proc = self._run("--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        report = json.loads(proc.stdout)

        self.assertIn("summary", report)
        self.assertIn("issues", report)
        self.assertIn("recommendations", report)
        self.assertEqual(set(report["issues"].keys()), EXPECTED_BUCKETS)
        self.assertEqual(report["summary"]["papers_total"], 1)
        self.assertEqual(report["summary"]["issues_total"], 0)
        self.assertFalse(report["summary"]["catalog_present"])

    def test_missing_meta_bucket(self):
        (self.library_root / "papers" / "22222").mkdir(parents=True)
        report = json.loads(self._run("--json").stdout)
        self.assertIn("22222", report["issues"]["missing_meta"])

    def test_malformed_meta_bucket_excludes_other_checks(self):
        self._write_paper("33333", None, malformed=True)
        report = json.loads(self._run("--json").stdout)
        self.assertIn("33333", report["issues"]["malformed_meta"])
        self.assertNotIn("33333", report["issues"]["missing_title"])

    def test_metadata_only_vs_abstract_only_vs_oa_pending(self):
        self._write_paper("40001", {"title": "t", "abstract_available": False, "full_text": False})
        self._write_paper("40002", {"title": "t", "abstract_available": True, "full_text": False})
        self._write_paper("40003", {
            "title": "t", "abstract_available": True, "full_text": False,
            "oa_location": "https://example.org/pdf",
        })
        report = json.loads(self._run("--json").stdout)
        self.assertIn("40001", report["issues"]["metadata_only"])
        self.assertIn("40002", report["issues"]["abstract_only"])
        self.assertIn("40003", report["issues"]["oa_pending"])
        self.assertNotIn("40003", report["issues"]["abstract_only"])

    def test_stale_retraction_check_respects_stale_days(self):
        old_ts = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
        self._write_paper("50001", {"title": "t", "checked_at": old_ts})
        report_default = json.loads(self._run("--json").stdout)
        self.assertIn("50001", report_default["issues"]["stale_retraction_check"])

        report_lenient = json.loads(self._run("--json", "--stale-days", "9999").stdout)
        self.assertNotIn("50001", report_lenient["issues"]["stale_retraction_check"])

    def test_recommendations_follow_issue_state(self):
        self._write_paper("60001", {"title": "t", "abstract_available": False, "full_text": False})
        report = json.loads(self._run("--json").stdout)
        self.assertTrue(any("index --rebuild" in r for r in report["recommendations"]))
        self.assertTrue(any("fetch" in r for r in report["recommendations"]))

    def test_human_output_is_default(self):
        self._write_paper("70001", {"title": "t"})
        proc = self._run()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("papers_total:", proc.stdout)
        self.assertIn("recommended next actions:", proc.stdout)

    def test_snapshot_writes_timestamped_report_under_maintenance_dir(self):
        self._write_paper("80001", {"title": "t"})
        proc = self._run("--snapshot")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("snapshot written:", proc.stdout)

        maintenance_dir = self.library_root / "maintenance"
        snapshots = list(maintenance_dir.glob("*.json"))
        self.assertEqual(len(snapshots), 1)
        snapshot_report = json.loads(snapshots[0].read_text())
        self.assertEqual(set(snapshot_report["issues"].keys()), EXPECTED_BUCKETS)

    def test_missing_repo_fails_loudly(self):
        script = SCRIPTS / "lint.py"
        proc = subprocess.run(
            [sys.executable, str(script), "run", "--repo", str(self.tmp / "nope")],
            capture_output=True, text=True,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("error:", proc.stderr)


if __name__ == "__main__":
    unittest.main()
