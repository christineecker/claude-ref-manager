#!/usr/bin/env python3
"""`/ref:repair-fulltext` resume-state read/merge regression.

Run: python3 skills/ref-manager/scripts/tests/test_repair_state.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import init_repo  # noqa: E402


class TestRepairState(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.library_root = self.tmp / "lib"
        for rel in init_repo.LIBRARY_DIRS:
            (self.library_root / rel).mkdir(parents=True, exist_ok=True)
        self.state_path = self.library_root / "maintenance" / "repair-fulltext-state.json"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, *args):
        script = SCRIPTS / "repair_state.py"
        return subprocess.run(
            [sys.executable, str(script), "--repo", str(self.library_root), *args],
            capture_output=True, text=True,
        )

    def test_read_missing_state_returns_empty_object(self):
        proc = self._run("read")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout), {})
        self.assertFalse(self.state_path.exists())

    def test_merge_creates_state_file_atomically(self):
        entries = {"11111": {"result": "acquired", "attempted_at": "2026-09-16T00:00:00Z"}}
        proc = self._run("merge", "--entries", json.dumps(entries))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout), entries)
        self.assertEqual(json.loads(self.state_path.read_text()), entries)

    def test_merge_is_cumulative_and_overwrites_same_pmid(self):
        self._run("merge", "--entries", json.dumps(
            {"11111": {"result": "failed", "attempted_at": "2026-09-16T00:00:00Z"}}
        ))
        self._run("merge", "--entries", json.dumps(
            {"22222": {"result": "acquired", "attempted_at": "2026-09-16T01:00:00Z"}}
        ))
        proc = self._run("merge", "--entries", json.dumps(
            {"11111": {"result": "acquired", "attempted_at": "2026-09-16T02:00:00Z"}}
        ))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        state = json.loads(proc.stdout)
        self.assertEqual(state["11111"]["result"], "acquired")
        self.assertEqual(state["11111"]["attempted_at"], "2026-09-16T02:00:00Z")
        self.assertEqual(state["22222"]["result"], "acquired")

    def test_read_after_merge_round_trips(self):
        entries = {"33333": {"result": "abstract_only", "attempted_at": "2026-09-16T00:00:00Z"}}
        self._run("merge", "--entries", json.dumps(entries))
        proc = self._run("read")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout), entries)

    def test_merge_rejects_invalid_json_entries(self):
        proc = self._run("merge", "--entries", "not json{")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("error:", proc.stderr)

    def test_merge_entries_from_stdin(self):
        entries = {"44444": {"result": "failed", "attempted_at": "2026-09-16T00:00:00Z"}}
        script = SCRIPTS / "repair_state.py"
        proc = subprocess.run(
            [sys.executable, str(script), "merge", "--repo", str(self.library_root), "--entries", "-"],
            input=json.dumps(entries), capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout), entries)

    def test_missing_repo_fails_loudly(self):
        script = SCRIPTS / "repair_state.py"
        proc = subprocess.run(
            [sys.executable, str(script), "read", "--repo", str(self.tmp / "nope")],
            capture_output=True, text=True,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("error:", proc.stderr)


if __name__ == "__main__":
    unittest.main()
