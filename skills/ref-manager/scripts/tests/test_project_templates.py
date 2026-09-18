#!/usr/bin/env python3
"""Project starter templates (UX_BACKLOG.md deferred item).

Run: python3 skills/ref-manager/scripts/tests/test_project_templates.py
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
import project  # noqa: E402
from lib_schema import SchemaError  # noqa: E402


class TempLibrary(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.library_root = self.tmp / "lib"
        for rel in init_repo.LIBRARY_DIRS:
            (self.library_root / rel).mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestCreateWithTemplate(TempLibrary):
    def test_no_template_omits_field(self):
        proj = project.create(self.library_root, "p1", None)
        self.assertNotIn("template", proj)

    def test_valid_template_stamped(self):
        proj = project.create(self.library_root, "p1", "scope", template="thesis-chapter")
        self.assertEqual(proj["template"], "thesis-chapter")

    def test_unknown_template_refused(self):
        with self.assertRaises(SchemaError):
            project.create(self.library_root, "p1", None, template="not-a-real-template")

    def test_scope_and_questions_never_prefilled_by_template(self):
        # A template names a workflow; it never invents the user's actual
        # research content (scope/questions stay whatever was passed in).
        proj = project.create(self.library_root, "p1", None, template="systematic-review")
        self.assertIsNone(proj["scope"])
        self.assertEqual(proj["questions"], [])


class TestCli(TempLibrary):
    def _run(self, *args):
        script = SCRIPTS / "project.py"
        return subprocess.run(
            [sys.executable, str(script), *args], capture_output=True, text=True,
        )

    def test_templates_subcommand_needs_no_repo(self):
        proc = self._run("templates")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertIn("systematic-review", payload)
        self.assertIn("thesis-chapter", payload)

    def test_create_with_template_prints_next_steps(self):
        proc = self._run(
            "create", "--repo", str(self.library_root), "--slug", "tdcs-review",
            "--template", "systematic-review",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["template"], "systematic-review")
        self.assertTrue(any("tdcs-review" in step for step in payload["next_steps"]))
        self.assertTrue(any(step.startswith("/ref:query-pubmed") for step in payload["next_steps"]))

    def test_create_without_template_has_no_next_steps(self):
        proc = self._run("create", "--repo", str(self.library_root), "--slug", "plain")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertNotIn("next_steps", payload)
        self.assertNotIn("template", payload)

    def test_unknown_template_rejected_by_argparse(self):
        proc = self._run(
            "create", "--repo", str(self.library_root), "--slug", "x",
            "--template", "nonsense",
        )
        self.assertNotEqual(proc.returncode, 0)

    def test_repo_required_for_non_templates_actions(self):
        proc = self._run("list")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("--repo is required", proc.stderr)


if __name__ == "__main__":
    unittest.main()
