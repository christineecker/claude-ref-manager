#!/usr/bin/env python3
"""`/ref:list` filters and output formats (LIBRARY_VIEWER_IMPLEMENTATION_PLAN.md §5).

Run: python3 skills/ref-manager/scripts/tests/test_list.py
"""
from __future__ import annotations

import csv
import io
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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stale_iso() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()


class ListFixture(unittest.TestCase):
    """One paper per source state plus a rich pdf-backed paper with figures,
    claims, notes, and project membership -- same shape as test_inventory.py's
    fixture so /ref:list exercises the real rows() output."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.library_root = self.tmp / "lib"
        for rel in init_repo.LIBRARY_DIRS:
            (self.library_root / rel).mkdir(parents=True, exist_ok=True)

        self._write_meta("11111", {"title": "Metadata only", "year": "2018", "journal": "Alpha Journal"})
        self._write_meta("22222", {
            "title": "Abstract only", "year": "2020", "journal": "Beta Journal",
            "abstract_available": True,
        })
        self._write_meta("33333", {
            "title": "OA pending", "year": "2021", "journal": "Alpha Journal",
            "abstract_available": True, "oa_location": "pmc",
        })
        self._write_meta("44444", {
            "title": "Full text", "year": "2023", "journal": "Gamma Journal",
            "abstract_available": True, "full_text": True, "extraction_tier": "full",
            "checked_at": _stale_iso(),
            "retraction_status": {"status": "retracted", "source": "pubmed", "checked_at": _now_iso()},
        })
        self._write_rich_paper("55555")

        proj_path = self.library_root / "projects" / "proj-a" / "papers.yaml"
        proj_path.parent.mkdir(parents=True, exist_ok=True)
        proj_path.write_text(json.dumps({"papers": [
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
            "title": "Rich paper", "year": "2019", "journal": "Delta Journal",
            "abstract_available": True, "full_text": True, "extraction_tier": "full",
        })
        raw_dir = pdir / "raw" / "hash1"
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / "source.pdf").write_bytes(b"%PDF-1.4 fake")

        (pdir / "current.json").write_text(json.dumps({"version": "v1"}))
        version_dir = pdir / "versions" / "v1"
        version_dir.mkdir(parents=True, exist_ok=True)
        (version_dir / "source.md").write_text("# Introduction\n\nBody text.\n")
        (version_dir / "figures.json").write_text(json.dumps([
            {"id": "f1", "label": "FIGURE 1", "caption": "cap1", "asset_available": True},
        ]))
        (pdir / "claim_registry.json").write_text(json.dumps({"claims": {
            "c1": {"locator": "Results/p1", "evidence_tier": "full", "status": "active",
                   "direction": "increase", "outcome": "score", "population": "adults",
                   "evidence_span": "quoted evidence"},
        }}))
        (pdir / "notes.md").write_text(f"\n---\n{_now_iso()}\n\nFirst note.\n")
        return pdir

    def _run(self, *args):
        script = SCRIPTS / "list.py"
        return subprocess.run(
            [sys.executable, str(script), "--repo", str(self.library_root), *args],
            capture_output=True, text=True,
        )


class TestNoFiltersListsEverything(ListFixture):
    def test_default_lists_all_papers(self):
        proc = self._run()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for pmid in ("11111", "22222", "33333", "44444", "55555"):
            self.assertIn(pmid, proc.stdout)

    def test_empty_library_gives_explicit_message_not_silence(self):
        empty_root = self.tmp / "empty"
        for rel in init_repo.LIBRARY_DIRS:
            (empty_root / rel).mkdir(parents=True, exist_ok=True)
        script = SCRIPTS / "list.py"
        proc = subprocess.run(
            [sys.executable, str(script), "--repo", str(empty_root)],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(proc.stdout.strip())
        self.assertIn("no papers", proc.stdout.lower())


class TestFilterCombinations(ListFixture):
    def test_source_filter(self):
        proc = self._run("--source", "pdf-backed", "--format", "pmids")
        self.assertEqual(proc.stdout.split(), ["55555"])

    def test_source_filter_multiple_badges(self):
        proc = self._run("--source", "metadata-only,oa-pending", "--format", "pmids")
        self.assertEqual(sorted(proc.stdout.split()), ["11111", "33333"])

    def test_source_filter_unknown_badge_errors(self):
        proc = self._run("--source", "not-a-badge")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("error:", proc.stderr)

    def test_has_pdf(self):
        proc = self._run("--has", "pdf", "--format", "pmids")
        self.assertEqual(proc.stdout.split(), ["55555"])

    def test_has_claims_and_figures_combined(self):
        proc = self._run("--has", "claims,figures", "--format", "pmids")
        self.assertEqual(proc.stdout.split(), ["55555"])

    def test_missing_fulltext(self):
        # has_fulltext is derived from current.json + versions/<v>/source.md,
        # not from meta.json's full_text flag -- 44444 sets full_text=True in
        # meta but never writes current.json, so it counts as missing too.
        proc = self._run("--missing", "fulltext", "--format", "pmids")
        self.assertEqual(sorted(proc.stdout.split()), ["11111", "22222", "33333", "44444"])

    def test_tier_filter(self):
        proc = self._run("--tier", "full", "--format", "pmids")
        self.assertEqual(sorted(proc.stdout.split()), ["44444", "55555"])

    def test_year_range_filter(self):
        proc = self._run("--year", "2019..2021", "--format", "pmids")
        self.assertEqual(sorted(proc.stdout.split()), ["22222", "33333", "55555"])

    def test_year_exact_filter(self):
        proc = self._run("--year", "2018", "--format", "pmids")
        self.assertEqual(proc.stdout.split(), ["11111"])

    def test_journal_substring_filter_case_insensitive(self):
        proc = self._run("--journal", "alpha", "--format", "pmids")
        self.assertEqual(sorted(proc.stdout.split()), ["11111", "33333"])

    def test_retracted_filter(self):
        proc = self._run("--retracted", "--format", "pmids")
        self.assertEqual(proc.stdout.split(), ["44444"])

    def test_stale_days_filter(self):
        proc = self._run("--stale-days", "180", "--format", "pmids")
        self.assertEqual(proc.stdout.split(), ["44444"])

    def test_issue_filter(self):
        proc = self._run("--issue", "abstract_only", "--format", "pmids")
        self.assertEqual(proc.stdout.split(), ["22222"])

    def test_issue_unknown_bucket_errors(self):
        proc = self._run("--issue", "not_a_bucket")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("error:", proc.stderr)

    def test_project_filter_reuses_selector(self):
        proc = self._run("--project", "proj-a", "--format", "pmids")
        self.assertEqual(proc.stdout.split(), ["55555"])

    def test_project_and_reading_status_combined(self):
        proc = self._run("--project", "proj-a", "--reading-status", "reading", "--format", "pmids")
        self.assertEqual(proc.stdout.split(), ["55555"])

    def test_reading_status_without_project_is_a_usage_error(self):
        proc = self._run("--reading-status", "reading")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("error:", proc.stderr)

    def test_unknown_project_is_a_usage_error(self):
        proc = self._run("--project", "no-such-project")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("error:", proc.stderr)

    def test_combined_filters_narrow_further(self):
        proc = self._run("--source", "metadata-only,abstract-only,oa-pending", "--journal", "alpha", "--format", "pmids")
        self.assertEqual(sorted(proc.stdout.split()), ["11111", "33333"])


class TestEmptyResultMessage(ListFixture):
    def test_impossible_filter_combo_gives_explicit_message(self):
        proc = self._run("--source", "pdf-backed", "--tier", "abstract")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("no papers matched", proc.stdout.lower())

    def test_empty_result_is_not_silent_for_table_csv_json(self):
        for fmt in ("table", "csv", "json"):
            proc = self._run("--source", "pdf-backed", "--tier", "abstract", "--format", fmt)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(proc.stdout.strip(), f"format={fmt} printed nothing")

    def test_empty_result_pmids_format_is_silent_by_design(self):
        proc = self._run("--source", "pdf-backed", "--tier", "abstract", "--format", "pmids")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, "")


class TestPmidsFormat(ListFixture):
    def test_pmids_format_is_space_separated_with_no_other_noise(self):
        proc = self._run("--format", "pmids")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        stripped = proc.stdout.strip()
        self.assertNotIn("\n", stripped)
        pmids = stripped.split(" ")
        self.assertEqual(sorted(pmids), ["11111", "22222", "33333", "44444", "55555"])
        # every token is a bare pmid -- no headers, labels, or punctuation
        for pmid in pmids:
            self.assertTrue(pmid.isdigit())

    def test_pmids_format_directly_consumable_by_tier_filter(self):
        proc = self._run("--tier", "full", "--format", "pmids")
        pmids = proc.stdout.strip().split(" ")
        self.assertEqual(sorted(pmids), ["44444", "55555"])


class TestFormats(ListFixture):
    def test_csv_format_is_parseable(self):
        proc = self._run("--source", "pdf-backed", "--format", "csv")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        rows = list(csv.reader(io.StringIO(proc.stdout)))
        self.assertEqual(rows[0][0], "pmid")
        self.assertEqual(rows[1][0], "55555")

    def test_json_format_is_parseable_and_respects_columns(self):
        proc = self._run("--source", "pdf-backed", "--columns", "pmid,title", "--format", "json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(len(data), 1)
        self.assertEqual(set(data[0].keys()), {"pmid", "title"})
        self.assertEqual(data[0]["pmid"], "55555")

    def test_columns_unknown_column_errors(self):
        proc = self._run("--columns", "not_a_column")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("error:", proc.stderr)

    def test_sort_by_year_descending(self):
        proc = self._run("--format", "json", "--columns", "pmid,year", "--sort", "year")
        data = json.loads(proc.stdout)
        years = [row["year"] for row in data]
        self.assertEqual(years, sorted(years, reverse=True))

    def test_sort_by_title_ascending(self):
        proc = self._run("--format", "json", "--columns", "pmid,title", "--sort", "title")
        data = json.loads(proc.stdout)
        titles = [(row["title"] or "").lower() for row in data]
        self.assertEqual(titles, sorted(titles))


class TestMatrix(ListFixture):
    def test_matrix_columns_present_and_stable_order(self):
        proc1 = self._run("--matrix", "--format", "json")
        proc2 = self._run("--matrix", "--format", "json")
        self.assertEqual(proc1.returncode, 0, proc1.stderr)
        data1 = json.loads(proc1.stdout)
        data2 = json.loads(proc2.stdout)
        expected_keys = {"pmid", "meta", "abstract", "fulltext", "pdf", "figures", "claims", "indexed", "retraction"}
        for row in data1:
            self.assertEqual(set(row.keys()), expected_keys)
        # stable across independent runs: same pmid order, same column set
        self.assertEqual([r["pmid"] for r in data1], [r["pmid"] for r in data2])

    def test_matrix_table_column_header_order_is_fixed(self):
        proc = self._run("--matrix", "--format", "table")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        header = proc.stdout.splitlines()[0].split()
        self.assertEqual(
            header,
            ["pmid", "meta", "abstract", "fulltext", "pdf", "figures", "claims", "indexed", "retraction"],
        )

    def test_matrix_reflects_pdf_backed_rich_paper(self):
        proc = self._run("--matrix", "--format", "json", "--source", "pdf-backed")
        data = json.loads(proc.stdout)
        self.assertEqual(len(data), 1)
        row = data[0]
        self.assertTrue(row["meta"])
        self.assertTrue(row["abstract"])
        self.assertTrue(row["fulltext"])
        self.assertTrue(row["pdf"])
        self.assertTrue(row["figures"])
        self.assertTrue(row["claims"])
        self.assertFalse(row["indexed"])  # no catalog built in this fixture
        self.assertFalse(row["retraction"])  # retraction_status defaults to unknown

    def test_matrix_marks_metadata_only_paper_missing_almost_everything(self):
        proc = self._run("--matrix", "--format", "json", "--source", "metadata-only")
        data = json.loads(proc.stdout)
        row = data[0]
        self.assertTrue(row["meta"])
        self.assertFalse(row["abstract"])
        self.assertFalse(row["fulltext"])
        self.assertFalse(row["pdf"])


class TestMissingRepoFailsLoudly(ListFixture):
    def test_missing_repo(self):
        script = SCRIPTS / "list.py"
        proc = subprocess.run(
            [sys.executable, str(script), "--repo", str(self.tmp / "nope")],
            capture_output=True, text=True,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("error:", proc.stderr)


if __name__ == "__main__":
    unittest.main()
