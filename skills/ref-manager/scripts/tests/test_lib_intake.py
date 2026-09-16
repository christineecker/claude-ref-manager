#!/usr/bin/env python3
"""Spike tests for the shared intake resolver (UX_BACKLOG.md #4).

Run: python3 skills/ref-manager/scripts/tests/test_lib_intake.py
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
import lib_intake  # noqa: E402


class TempLibrary(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.library_root = self.tmp / "lib"
        for rel in init_repo.LIBRARY_DIRS:
            (self.library_root / rel).mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_meta(self, pmid: str, **fields):
        paper_dir = self.library_root / "papers" / pmid
        paper_dir.mkdir(parents=True, exist_ok=True)
        meta = {"pmid": pmid, "title": "t", "year": "2020"}
        meta.update(fields)
        (paper_dir / "meta.json").write_text(json.dumps(meta))


class TestClassifyItem(unittest.TestCase):
    def test_bare_pmid(self):
        r = lib_intake.classify_item("12345678")
        self.assertEqual(r["kind"], "pmid")
        self.assertEqual(r["pmid"], "12345678")

    def test_bare_doi(self):
        r = lib_intake.classify_item("10.1038/s41586-026-00001-2")
        self.assertEqual(r["kind"], "doi")
        self.assertEqual(r["doi"], "10.1038/s41586-026-00001-2")

    def test_doi_not_confused_with_pmid(self):
        # numeric-looking DOI suffix must never fall through to bare-PMID
        r = lib_intake.classify_item("10.1000/182")
        self.assertEqual(r["kind"], "doi")

    def test_pubmed_url(self):
        r = lib_intake.classify_item("https://pubmed.ncbi.nlm.nih.gov/12345678/")
        self.assertEqual(r["kind"], "url")
        self.assertEqual(r["pmid"], "12345678")

    def test_doi_url(self):
        r = lib_intake.classify_item("https://doi.org/10.1038/s41586-026-00001-2")
        self.assertEqual(r["kind"], "url")
        self.assertEqual(r["doi"], "10.1038/s41586-026-00001-2")

    def test_url_with_no_clues(self):
        r = lib_intake.classify_item("https://example.com/some/article")
        self.assertEqual(r["kind"], "url")
        self.assertEqual(r["result"], "no_clues")

    def test_unknown_input(self):
        r = lib_intake.classify_item("not-a-real-anything")
        self.assertEqual(r["kind"], "unknown")
        self.assertEqual(r["result"], "no_clues")

    def test_missing_path_is_unknown_not_crash(self):
        r = lib_intake.classify_item("/no/such/path/here.pdf")
        self.assertEqual(r["kind"], "unknown")


class TestClassifyItemFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_bib_file_parsed_into_entries(self):
        bib = self.tmp / "refs.bib"
        bib.write_text('@article{x2020, title={t}, doi={10.1038/x}}')
        r = lib_intake.classify_item(str(bib))
        self.assertEqual(r["kind"], "bib_file")
        self.assertEqual(r["result"], "identified_entries")
        self.assertEqual(len(r["entries"]), 1)
        self.assertEqual(r["entries"][0]["doi"], "10.1038/x")

    def test_empty_bib_file_is_no_clues(self):
        bib = self.tmp / "empty.bib"
        bib.write_text("")
        r = lib_intake.classify_item(str(bib))
        self.assertEqual(r["kind"], "bib_file")
        self.assertEqual(r["result"], "no_clues")

    def test_csl_json_file_parsed_into_entries(self):
        csl = self.tmp / "refs.csl.json"
        csl.write_text(json.dumps([{"id": "x", "title": "t", "DOI": "10.1038/x"}]))
        r = lib_intake.classify_item(str(csl))
        self.assertEqual(r["kind"], "csl_file")
        self.assertEqual(r["result"], "identified_entries")
        self.assertEqual(r["entries"][0]["doi"], "10.1038/x")

    def test_empty_csl_json_file_is_no_clues(self):
        csl = self.tmp / "empty.csl.json"
        csl.write_text("[]")
        r = lib_intake.classify_item(str(csl))
        self.assertEqual(r["kind"], "csl_file")
        self.assertEqual(r["result"], "no_clues")

    def test_pdf_dir_expands_non_recursive(self):
        (self.tmp / "a.pdf").write_bytes(b"%PDF-1.4 fake")
        (self.tmp / "b.pdf").write_bytes(b"%PDF-1.4 fake")
        sub = self.tmp / "nested"
        sub.mkdir()
        (sub / "c.pdf").write_bytes(b"%PDF-1.4 fake")

        r = lib_intake.classify_item(str(self.tmp))
        self.assertEqual(r["kind"], "pdf_dir")
        self.assertEqual(len(r["pdfs"]), 2)  # nested/c.pdf excluded

    def test_empty_pdf_dir_is_no_clues(self):
        empty = self.tmp / "empty"
        empty.mkdir()
        r = lib_intake.classify_item(str(empty))
        self.assertEqual(r["kind"], "pdf_dir")
        self.assertEqual(r["result"], "no_clues")


class TestClassifyAll(unittest.TestCase):
    def test_expands_pdf_dir_into_flat_pdf_entries(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            (tmp / "a.pdf").write_bytes(b"%PDF-1.4 fake")
            (tmp / "b.pdf").write_bytes(b"%PDF-1.4 fake")
            results = lib_intake.classify_all([str(tmp)])
            self.assertEqual(len(results), 2)
            self.assertTrue(all(r["kind"] == "pdf" for r in results))
            self.assertTrue(all(r.get("from_dir") == str(tmp) for r in results))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_duplicate_pmid_across_inputs_flagged(self):
        results = lib_intake.classify_all(["12345678", "12345678"])
        self.assertNotIn("status", results[0])
        self.assertEqual(results[1]["status"], "duplicate_in_batch")
        self.assertEqual(results[1]["duplicate_of"], "12345678")

    def test_pmid_and_pubmed_url_same_paper_flagged_as_duplicate(self):
        results = lib_intake.classify_all(
            ["12345678", "https://pubmed.ncbi.nlm.nih.gov/12345678/"]
        )
        self.assertEqual(results[1]["status"], "duplicate_in_batch")

    def test_unrelated_inputs_not_flagged(self):
        results = lib_intake.classify_all(["12345678", "10.1038/s41586-026-00001-2"])
        self.assertNotIn("status", results[0])
        self.assertNotIn("status", results[1])

    def test_two_unknown_inputs_are_not_falsely_deduped(self):
        results = lib_intake.classify_all(["garbage-one", "garbage-two"])
        self.assertNotIn("status", results[0])
        self.assertNotIn("status", results[1])

    def test_expands_bib_file_into_flat_bib_entry_items(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            bib = tmp / "refs.bib"
            bib.write_text(
                "@article{a2020, title={A}, doi={10.1038/a}}\n"
                "@article{b2021, title={B}, year={2021}}\n"
            )
            results = lib_intake.classify_all([str(bib)])
            self.assertEqual(len(results), 2)
            self.assertTrue(all(r["kind"] == "bib_entry" for r in results))
            self.assertEqual(results[0]["doi"], "10.1038/a")
            self.assertEqual(results[0]["result"], "identified_clues")
            self.assertIsNone(results[1]["doi"])
            self.assertEqual(results[1]["result"], "no_clues")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_expands_csl_file_into_flat_csl_entry_items(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            csl = tmp / "refs.csl.json"
            csl.write_text(json.dumps([
                {"id": "a", "title": "A", "PMID": "12345678"},
                {"id": "b", "title": "B"},
            ]))
            results = lib_intake.classify_all([str(csl)])
            self.assertEqual(len(results), 2)
            self.assertTrue(all(r["kind"] == "csl_entry" for r in results))
            self.assertEqual(results[0]["pmid"], "12345678")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_bib_entry_with_pmid_matching_earlier_pmid_flagged_duplicate(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            bib = tmp / "refs.bib"
            bib.write_text('@article{a2020, title={A}, pmid={12345678}}')
            results = lib_intake.classify_all(["12345678", str(bib)])
            self.assertNotIn("status", results[0])
            self.assertEqual(results[1]["status"], "duplicate_in_batch")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestFindExistingByIdentity(TempLibrary):
    def test_pmid_hit(self):
        self._write_meta("111")
        pmid = lib_intake.find_existing_by_identity(self.library_root, ("pmid", "111"))
        self.assertEqual(pmid, "111")

    def test_pmid_miss(self):
        pmid = lib_intake.find_existing_by_identity(self.library_root, ("pmid", "999"))
        self.assertIsNone(pmid)

    def test_doi_hit_case_insensitive(self):
        self._write_meta("111", doi="10.1038/S41586-026-00001-2")
        pmid = lib_intake.find_existing_by_identity(
            self.library_root, ("doi", "10.1038/s41586-026-00001-2")
        )
        self.assertEqual(pmid, "111")

    def test_pmcid_hit(self):
        self._write_meta("111", pmcid="PMC1234567")
        pmid = lib_intake.find_existing_by_identity(self.library_root, ("pmcid", "PMC1234567"))
        self.assertEqual(pmid, "111")

    def test_url_identity_never_matched_against_library(self):
        self._write_meta("111")
        pmid = lib_intake.find_existing_by_identity(
            self.library_root, ("url", "https://example.com/x")
        )
        self.assertIsNone(pmid)

    def test_empty_library_no_crash(self):
        pmid = lib_intake.find_existing_by_identity(self.library_root, ("doi", "10.1/x"))
        self.assertIsNone(pmid)


class TestResolveBatch(TempLibrary):
    def test_flags_already_imported_pmid(self):
        self._write_meta("11111")
        results = lib_intake.resolve_batch(self.library_root, ["11111"])
        self.assertEqual(results[0]["status"], "already_imported")
        self.assertEqual(results[0]["existing_pmid"], "11111")

    def test_flags_already_imported_doi(self):
        self._write_meta("11111", doi="10.1038/x")
        results = lib_intake.resolve_batch(self.library_root, ["10.1038/x"])
        self.assertEqual(results[0]["status"], "already_imported")
        self.assertEqual(results[0]["existing_pmid"], "11111")

    def test_new_pmid_not_flagged(self):
        results = lib_intake.resolve_batch(self.library_root, ["22222"])
        self.assertNotIn("status", results[0])

    def test_within_batch_duplicate_takes_priority_over_library_check(self):
        self._write_meta("11111")
        results = lib_intake.resolve_batch(self.library_root, ["11111", "11111"])
        self.assertEqual(results[0]["status"], "already_imported")
        self.assertEqual(results[1]["status"], "duplicate_in_batch")

    def test_bib_entry_doi_flags_already_imported(self):
        self._write_meta("11111", doi="10.1038/a")
        bib = self.tmp / "refs.bib"
        bib.write_text('@article{a2020, title={A}, doi={10.1038/a}}')
        results = lib_intake.resolve_batch(self.library_root, [str(bib)])
        self.assertEqual(results[0]["kind"], "bib_entry")
        self.assertEqual(results[0]["status"], "already_imported")
        self.assertEqual(results[0]["existing_pmid"], "11111")


class TestCli(TempLibrary):
    def test_classify_subcommand_prints_json(self):
        import subprocess

        script = SCRIPTS / "lib_intake.py"
        proc = subprocess.run(
            [sys.executable, str(script), "classify", "--repo", str(self.library_root), "12345678"],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload[0]["kind"], "pmid")


if __name__ == "__main__":
    unittest.main()
