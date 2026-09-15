#!/usr/bin/env python3
"""/ref:status output modes (UX_BACKLOG.md deferred item).

Run: python3 skills/ref-manager/scripts/tests/test_status_verbosity.py
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


class TestStatusVerbosity(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.library_root = self.tmp / "lib"
        for rel in init_repo.LIBRARY_DIRS:
            (self.library_root / rel).mkdir(parents=True, exist_ok=True)
        paper_dir = self.library_root / "papers" / "11111"
        paper_dir.mkdir(parents=True)
        (paper_dir / "meta.json").write_text(json.dumps({
            "pmid": "11111", "citekey": "a2020t", "title": "t", "status": "active",
            "checked_at": "2026-01-01T00:00:00+00:00", "extraction_tier": "abstract",
            "abstract_available": True,
        }))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, *args):
        script = SCRIPTS / "status.py"
        env_home = self.tmp / "home"
        (env_home / ".config" / "ref-manager").mkdir(parents=True, exist_ok=True)
        (env_home / ".config" / "ref-manager" / "config.json").write_text(
            json.dumps({"library_root": str(self.library_root)})
        )
        import os
        env = dict(os.environ, HOME=str(env_home))
        return subprocess.run(
            [sys.executable, str(script), *args], capture_output=True, text=True, env=env,
        )

    def test_default_is_normal(self):
        default = self._run()
        normal = self._run("--verbosity", "normal")
        self.assertEqual(default.stdout, normal.stdout)

    def test_quick_omits_breakdowns_and_recent_papers(self):
        proc = self._run("--verbosity", "quick")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("status:", proc.stdout)
        self.assertIn("needs attention:", proc.stdout)
        self.assertIn("suggested next actions:", proc.stdout)
        self.assertNotIn("papers by extraction tier:", proc.stdout)
        self.assertNotIn("recent papers:", proc.stdout)

    def test_normal_includes_breakdowns(self):
        proc = self._run("--verbosity", "normal")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("papers by extraction tier:", proc.stdout)
        self.assertIn("recent papers:", proc.stdout)

    def test_verbose_includes_everything_normal_has(self):
        proc = self._run("--verbosity", "verbose")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("papers by extraction tier:", proc.stdout)
        self.assertIn("recent papers:", proc.stdout)

    def test_invalid_verbosity_rejected(self):
        proc = self._run("--verbosity", "nonsense")
        self.assertNotEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()
