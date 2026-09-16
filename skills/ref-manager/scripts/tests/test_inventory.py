#!/usr/bin/env python3
"""lib_inventory.rows()/detail() (LIBRARY_VIEWER_IMPLEMENTATION_PLAN.md §4.5).

Run: python3 skills/ref-manager/scripts/tests/test_inventory.py
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import init_repo  # noqa: E402
import lib_inventory  # noqa: E402
import lint  # noqa: E402
import status  # noqa: E402


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stale_iso() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()


class InventoryFixture(unittest.TestCase):
    """One paper per source state (metadata-only, abstract-only, oa-pending,
    full-text, pdf-backed), plus a rich paper with PDF, figures, claims,
    notes, and membership in two projects."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.library_root = self.tmp / "lib"
        for rel in init_repo.LIBRARY_DIRS:
            (self.library_root / rel).mkdir(parents=True, exist_ok=True)

        self._write_meta("11111", {"title": "Metadata only"})  # metadata-only
        self._write_meta("22222", {"title": "Abstract only", "abstract_available": True})
        self._write_meta("33333", {"title": "OA pending", "abstract_available": True, "oa_location": "pmc"})
        self._write_meta("44444", {"title": "Full text", "abstract_available": True, "full_text": True})
        self._write_rich_paper("55555")

        for rel, slug in (("projects/proj-a/papers.yaml", "proj-a"), ("projects/proj-b/papers.yaml", "proj-b")):
            path = self.library_root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"papers": [
                {"pmid": "55555", "reading_status": "reading", "added_at": "2026-01-01T00:00:00+00:00"},
            ]}))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_meta(self, pmid: str, overrides: dict) -> Path:
        pdir = self.library_root / "papers" / pmid
        pdir.mkdir(parents=True, exist_ok=True)
        meta = {
            "pmid": pmid, "citekey": f"key{pmid}", "title": None, "year": "2024",
            "journal": "J", "doi": f"10.1/{pmid}", "pmcid": None, "status": "active",
            "extraction_tier": "abstract", "checked_at": _now_iso(),
            "abstract_available": False, "full_text": False,
        }
        meta.update(overrides)
        (pdir / "meta.json").write_text(json.dumps(meta))
        return pdir

    def _write_rich_paper(self, pmid: str) -> Path:
        pdir = self._write_meta(pmid, {
            "title": "Rich paper", "abstract_available": True, "full_text": True,
        })
        (pdir / "authorship.json").write_text(json.dumps({
            "pmid": pmid, "source": "pubmed", "authors": [
                {"first": "Ann", "last": "Author", "raw": "Author A"},
                {"first": "Bob", "last": "Coauthor", "raw": "Coauthor B"},
            ],
        }))

        raw_dir = pdir / "raw" / "hash1"
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / "source.pdf").write_bytes(b"%PDF-1.4 fake")
        (raw_dir / "response.json").write_text(json.dumps({
            "pmid": pmid, "abstract": "The abstract.", "grants": ["G1"],
        }))

        (pdir / "current.json").write_text(json.dumps({"version": "v1"}))
        version_dir = pdir / "versions" / "v1"
        version_dir.mkdir(parents=True, exist_ok=True)
        (version_dir / "source.md").write_text(
            "# Introduction\n\nBody text.\n\n"
            "## Sub Acknowledgments\n\n<div class=\"caption\">\n\nWe thank X.\n\n</div>\n\n"
            ":::\n\n"
            "# Conflicts of Interest\n\nNone declared.\n\n"
            "# Data Availability Statement\n\nData on request.\n\n"
            "# References\n\n1. Someone et al.\n"
        )
        (version_dir / "figures.json").write_text(json.dumps([
            {"id": "f1", "label": "FIGURE 1", "caption": "cap1", "asset_available": True, "source_locator": "f1.png"},
            {"id": "f2", "label": "FIGURE 2", "caption": "cap2", "asset_available": False, "source_locator": "f2.png"},
        ]))

        (pdir / "funding.json").write_text(json.dumps({
            "pmid": pmid, "state": "explicit_acknowledgement_verified", "observations": [
                {"funder": "Some Fund", "fundref_id": "10.13039/123", "award_number": "AW1",
                 "kind": "explicit_acknowledgement_verified", "source": "jats_funding_group"},
            ],
        }))

        (pdir / "claim_registry.json").write_text(json.dumps({"claims": {
            "c1": {
                "locator": "Results/p1", "evidence_tier": "full", "status": "active",
                "direction": "increase", "outcome": "score", "population": "adults",
                "evidence_span": "quoted evidence",
            },
            "c2": {
                "locator": "Results/p2", "evidence_tier": "full", "status": "superseded",
                "direction": "decrease", "outcome": "score", "population": "adults",
                "evidence_span": "old evidence",
            },
        }}))

        (pdir / "notes.md").write_text(
            f"\n---\n{_now_iso()}\n\nFirst note.\n"
            f"\n---\n{_now_iso()}\n\nSecond note.\n"
        )
        return pdir

    def rows_by_pmid(self) -> dict[str, dict]:
        return {r["pmid"]: r for r in lib_inventory.rows(self.library_root)}


class TestRowsSourceStates(InventoryFixture):
    def test_metadata_only(self):
        row = self.rows_by_pmid()["11111"]
        self.assertEqual(row["source_badge"], "metadata-only")
        self.assertFalse(row["has_pdf"])
        self.assertFalse(row["has_fulltext"])
        self.assertIn("metadata_only", row["lint_flags"])

    def test_abstract_only(self):
        row = self.rows_by_pmid()["22222"]
        self.assertEqual(row["source_badge"], "abstract-only")
        self.assertIn("abstract_only", row["lint_flags"])

    def test_oa_pending(self):
        row = self.rows_by_pmid()["33333"]
        self.assertEqual(row["source_badge"], "oa-pending")
        self.assertIn("oa_pending", row["lint_flags"])

    def test_full_text_without_pdf(self):
        row = self.rows_by_pmid()["44444"]
        self.assertEqual(row["source_badge"], "full-text")
        self.assertFalse(row["has_pdf"])

    def test_pdf_backed_rich_paper(self):
        row = self.rows_by_pmid()["55555"]
        self.assertEqual(row["source_badge"], "pdf-backed")
        self.assertTrue(row["has_pdf"])
        self.assertEqual(row["pdf_paths"], ["raw/hash1/source.pdf"])
        self.assertTrue(row["has_fulltext"])
        self.assertEqual(row["version_id"], "v1")


class TestRowsRichFields(InventoryFixture):
    def test_figures_counts(self):
        row = self.rows_by_pmid()["55555"]
        self.assertEqual(row["figures_total"], 2)
        self.assertEqual(row["figures_with_image"], 1)

    def test_claims_active_excludes_superseded(self):
        row = self.rows_by_pmid()["55555"]
        self.assertEqual(row["claims_active"], 1)

    def test_notes_count(self):
        row = self.rows_by_pmid()["55555"]
        self.assertEqual(row["notes_count"], 2)

    def test_authors_count_and_first_author(self):
        row = self.rows_by_pmid()["55555"]
        self.assertEqual(row["authors_count"], 2)
        self.assertEqual(row["first_author"], {"first": "Ann", "last": "Author", "raw": "Author A"})

    def test_project_membership_two_projects(self):
        row = self.rows_by_pmid()["55555"]
        slugs = sorted(p["slug"] for p in row["projects"])
        self.assertEqual(slugs, ["proj-a", "proj-b"])
        for p in row["projects"]:
            self.assertEqual(p["reading_status"], "reading")

    def test_retraction_status_defaults_unknown(self):
        row = self.rows_by_pmid()["55555"]
        self.assertEqual(row["retraction_status"], "unknown")

    def test_stale_check_false_for_recent_checked_at(self):
        row = self.rows_by_pmid()["55555"]
        self.assertFalse(row["stale_check"])
        self.assertEqual(row["days_since_check"], 0)


class TestRowsMalformedMeta(InventoryFixture):
    def test_missing_meta_yields_row_not_exception(self):
        pdir = self.library_root / "papers" / "66666"
        pdir.mkdir(parents=True)
        row = self.rows_by_pmid()["66666"]
        self.assertEqual(row["lint_flags"], ["missing_meta"])
        self.assertIsNone(row["title"])

    def test_malformed_meta_yields_row_not_exception(self):
        pdir = self.library_root / "papers" / "77777"
        pdir.mkdir(parents=True)
        (pdir / "meta.json").write_text("not json{")
        row = self.rows_by_pmid()["77777"]
        self.assertEqual(row["lint_flags"], ["malformed_meta"])
        self.assertIsNone(row["title"])


class TestBadgeCountsAgreeAcrossCallers(InventoryFixture):
    """rows() badge counts == status.py counts == lint.py issue buckets."""

    def test_source_counts_match(self):
        rows = lib_inventory.rows(self.library_root)
        inventory_counts: dict[str, int] = {}
        for row in rows:
            if row["source_badge"] is None:
                continue
            key = row["source_badge"].replace("-", "_")
            inventory_counts[key] = inventory_counts.get(key, 0) + 1

        status_counts = status._source_counts(rows)
        for key, count in inventory_counts.items():
            self.assertEqual(status_counts.get(key), count)

        report = lint.lint(self.library_root)
        for bucket in ("metadata_only", "abstract_only", "oa_pending"):
            self.assertEqual(len(report["issues"][bucket]), inventory_counts.get(bucket, 0))


class TestDetail(InventoryFixture):
    def test_detail_unknown_pmid_raises(self):
        with self.assertRaises(FileNotFoundError):
            lib_inventory.detail(self.library_root, "00000")

    def test_authors_abstract_grants(self):
        d = lib_inventory.detail(self.library_root, "55555")
        self.assertEqual(len(d["authors"]), 2)
        self.assertEqual(d["abstract"], "The abstract.")
        self.assertEqual(d["grants"], ["G1"])

    def test_funding(self):
        d = lib_inventory.detail(self.library_root, "55555")
        self.assertEqual(d["funding"]["state"], "explicit_acknowledgement_verified")
        self.assertEqual(len(d["funding"]["observations"]), 1)
        obs = d["funding"]["observations"][0]
        self.assertEqual(obs["funder"], "Some Fund")
        self.assertEqual(obs["fundref_id"], "10.13039/123")
        self.assertEqual(obs["award_number"], "AW1")

    def test_section_parsing_nested_headings_and_div_blocks(self):
        d = lib_inventory.detail(self.library_root, "55555")
        # "## Sub Acknowledgments" is nested under "# Introduction" but still
        # matched by heading text; its <div>/:::-fenced body is cleaned.
        self.assertEqual(d["acknowledgements"], ["We thank X."])
        self.assertEqual(d["conflicts"], ["None declared."])
        self.assertEqual(d["data_availability"], ["Data on request."])

    def test_figures_detail(self):
        d = lib_inventory.detail(self.library_root, "55555")
        self.assertEqual(len(d["figures"]), 2)
        self.assertEqual(d["figures"][0]["label"], "FIGURE 1")
        self.assertTrue(d["figures"][0]["asset_available"])
        self.assertFalse(d["figures"][1]["asset_available"])

    def test_claims_detail_active_only(self):
        d = lib_inventory.detail(self.library_root, "55555")
        self.assertEqual(len(d["claims"]), 1)
        self.assertEqual(d["claims"][0]["locator"], "Results/p1")
        self.assertEqual(d["claims"][0]["evidence_span"], "quoted evidence")

    def test_notes_detail(self):
        d = lib_inventory.detail(self.library_root, "55555")
        self.assertEqual(len(d["notes"]), 2)
        self.assertEqual(d["notes"][0]["text"], "First note.")
        self.assertEqual(d["notes"][1]["text"], "Second note.")

    def test_files_checklist(self):
        d = lib_inventory.detail(self.library_root, "55555")
        by_path = {f["path"]: f for f in d["files"]}
        self.assertTrue(by_path["meta.json"]["exists"])
        self.assertTrue(by_path["claim_registry.json"]["exists"])
        self.assertTrue(by_path["versions/v1/source.md"]["exists"])


class TestCli(InventoryFixture):
    def _run(self, *args):
        import subprocess

        script = SCRIPTS / "lib_inventory.py"
        return subprocess.run(
            [sys.executable, str(script), *args],
            capture_output=True, text=True,
        )

    def test_rows_cli_prints_json(self):
        proc = self._run("rows", "--repo", str(self.library_root))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        rows = json.loads(proc.stdout)
        self.assertEqual(len(rows), 5)

    def test_detail_cli_prints_json(self):
        proc = self._run("detail", "--repo", str(self.library_root), "--pmid", "55555")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        detail = json.loads(proc.stdout)
        self.assertEqual(detail["pmid"], "55555")

    def test_detail_cli_unknown_pmid_fails_loudly(self):
        proc = self._run("detail", "--repo", str(self.library_root), "--pmid", "00000")
        self.assertNotEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()
