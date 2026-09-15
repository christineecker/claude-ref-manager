#!/usr/bin/env python3
"""Phase 3 (acquisition + conversion + funding + local attach) gate fixtures
(PLAN.md §8 build-order row for phase 3, the acquisition-side subset).

Run: python3 skills/ref-manager/scripts/tests/test_phase3_acquire.py
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(SCRIPTS))

import add  # noqa: E402
import attach  # noqa: E402
import convert  # noqa: E402
import fetch  # noqa: E402
import funding_extract  # noqa: E402
import init_repo  # noqa: E402
from lib_atomic import atomic_write_bytes  # noqa: E402

JATS_FIXTURE = (FIXTURES / "sample.jats.xml").read_text()
HTML_FIXTURE = (FIXTURES / "sample.html").read_text()


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

    def add_paper(self, pmid, **overrides):
        record = {
            "pmid": pmid, "title": "Discrimination of three herbs", "abstract": "abs",
            "authors": [author("Ahn", "Su-Jin")], "journal": "X", "year": "2022",
            "doi": "10.1080/x", "pmcid": "PMC1", "grants": [],
        }
        record.update(overrides)
        return add.add_one(self.library_root, record)


# ---- convert.py ----

class TestConvertJats(TempLibrary):
    def test_real_pandoc_conversion_and_figures(self):
        staging = self.tmp / "staging-jats"
        staging.mkdir()
        result = convert.convert_jats(JATS_FIXTURE, staging)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["converter"], "pandoc-jats")
        self.assertTrue((staging / "source.md").exists())
        md = (staging / "source.md").read_text()
        self.assertIn("Herbs are useful", md)
        self.assertEqual(len(result["figures"]), 1)
        self.assertEqual(result["figures"][0]["source_locator"], "fig1.jpg")
        self.assertFalse(result["figures"][0]["asset_available"])


class TestConvertHtml(TempLibrary):
    def test_real_trafilatura_conversion(self):
        staging = self.tmp / "staging-html"
        staging.mkdir()
        result = convert.convert_html(HTML_FIXTURE, staging)
        self.assertEqual(result["status"], "ok")
        self.assertTrue((staging / "source.md").exists())
        md = (staging / "source.md").read_text()
        self.assertIn("herb discrimination", md)
        self.assertNotIn("Subscribe", md)  # nav boilerplate stripped


class TestConvertPdfUnavailable(TempLibrary):
    def test_anydoc_absent_reports_unavailable_not_crash(self):
        staging = self.tmp / "staging-pdf"
        staging.mkdir()
        fake_pdf = self.tmp / "fake.pdf"
        fake_pdf.write_bytes(b"%PDF-1.4 not a real pdf")
        with mock.patch("shutil.which", return_value=None):
            result = convert.convert_pdf(fake_pdf, staging)
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("anydoc not installed", result["diagnostics"][0])


# ---- funding_extract.py ----

class TestFundingExtraction(unittest.TestCase):
    def test_explicit_funding_group(self):
        obs, state = funding_extract.extract_funding_observations(JATS_FIXTURE)
        self.assertEqual(state, "explicit_acknowledgement_verified")
        self.assertEqual(obs[0]["funder"], "National Research Foundation of Korea")
        self.assertEqual(obs[0]["award_number"], "2020R1A2C1")

    def test_no_funding_info_is_unknown_not_false_negative(self):
        xml = "<article><body><sec><title>Intro</title><p>hi</p></sec></body></article>"
        obs, state = funding_extract.extract_funding_observations(xml)
        self.assertEqual(obs, [])
        self.assertEqual(state, "unknown")

    def test_prose_only_acknowledgement_is_possible_match(self):
        xml = (
            "<article><body><sec sec-type='funding'><title>Acknowledgements</title>"
            "<p>We thank our colleagues for support during this project.</p>"
            "</sec></body></article>"
        )
        obs, state = funding_extract.extract_funding_observations(xml)
        self.assertEqual(state, "possible_match")
        self.assertEqual(obs[0]["kind"], "possible_match")


# ---- fetch.py ----

class TestFetchJats(TempLibrary):
    def test_fetch_with_jats_commits_version_and_funding(self):
        self.add_paper("2001")
        record = {"pmid": "2001", "doi": "10.1080/x", "jats_xml": JATS_FIXTURE, "publisher_html": None}
        result = fetch.fetch_one(self.library_root, record, unpaywall_email=None)
        self.assertEqual(result["result"], "acquired")
        self.assertEqual(result["source"], "pmc_jats")
        paper_dir = self.library_root / "papers" / "2001"
        self.assertTrue((paper_dir / "current.json").exists())
        version = json.loads((paper_dir / "current.json").read_text())["version"]
        self.assertTrue((paper_dir / "versions" / version / "source.md").exists())
        funding = json.loads((paper_dir / "funding.json").read_text())
        self.assertEqual(funding["state"], "explicit_acknowledgement_verified")


class TestFetchAbstractOnly(TempLibrary):
    def test_no_source_available_is_not_a_failure(self):
        self.add_paper("2002", doi=None)
        record = {"pmid": "2002", "doi": None, "jats_xml": None, "publisher_html": None}
        result = fetch.fetch_one(self.library_root, record, unpaywall_email=None)
        self.assertEqual(result["result"], "abstract_only")
        meta = json.loads((self.library_root / "papers" / "2002" / "meta.json").read_text())
        self.assertFalse(meta["full_text"])


class TestFetchBatchIsolation(TempLibrary):
    def test_one_missing_record_does_not_block_others(self):
        self.add_paper("2003")
        good = {"pmid": "2003", "doi": None, "jats_xml": None, "publisher_html": None}
        bad = {"pmid": "9999999", "doi": None, "jats_xml": None, "publisher_html": None}
        results = []
        for rec in (bad, good):
            try:
                results.append(fetch.fetch_one(self.library_root, rec, unpaywall_email=None))
            except ValueError as e:
                results.append({"pmid": rec["pmid"], "result": "failed", "error": str(e)})
        by_pmid = {r["pmid"]: r for r in results}
        self.assertEqual(by_pmid["9999999"]["result"], "failed")
        self.assertEqual(by_pmid["2003"]["result"], "abstract_only")


class TestFetchUnpaywall(TempLibrary):
    def test_unpaywall_oa_location_recorded_not_treated_as_failure(self):
        self.add_paper("2004")
        record = {"pmid": "2004", "doi": "10.1080/x", "jats_xml": None, "publisher_html": None}
        fake_doc = {"best_oa_location": {"url_for_pdf": "https://example.com/oa.pdf"}}
        with mock.patch("fetch._unpaywall_lookup", return_value=fake_doc):
            result = fetch.fetch_one(self.library_root, record, unpaywall_email="test@example.com")
        self.assertEqual(result["result"], "oa_location_found")
        self.assertEqual(result["pdf_url"], "https://example.com/oa.pdf")
        meta = json.loads((self.library_root / "papers" / "2004" / "meta.json").read_text())
        self.assertEqual(meta["oa_location"]["url"], "https://example.com/oa.pdf")


# ---- attach.py ----

class TestAttach(TempLibrary):
    def setUp(self):
        super().setUp()
        self.add_paper("3001", title="Discrimination of three herbs using spectrometry",
                        doi="10.1080/realdoi")
        self.pdf_path = self.tmp / "match.pdf"
        # No real PDF library available; emulate what pdftotext -f1 -l2 <pdf> -
        # would extract by monkeypatching the extraction step directly, since
        # producing a real PDF with matching text needs pandoc's LaTeX engine
        # which isn't guaranteed present in CI. attach.py's own function is
        # exercised directly either way.
        self.pdf_path.write_bytes(b"%PDF-1.4 fake bytes for hashing purposes only")

    def test_duplicate_hash_is_noop(self):
        with mock.patch("attach._pdf_head_text", return_value="... 10.1080/realdoi ..."):
            first = attach.attach_one(self.library_root, "3001", self.pdf_path, force=False)
            second = attach.attach_one(self.library_root, "3001", self.pdf_path, force=False)
        self.assertEqual(first["result"], "attached")
        self.assertEqual(second["result"], "duplicate_noop")

    def test_identity_mismatch_is_refused_not_silent(self):
        with mock.patch("attach._pdf_head_text", return_value="completely unrelated content about rocks"):
            result = attach.attach_one(self.library_root, "3001", self.pdf_path, force=False)
        self.assertEqual(result["result"], "refused")
        self.assertIn("§6", result["reason"])

    def test_force_overrides_refusal(self):
        with mock.patch("attach._pdf_head_text", return_value="unrelated"):
            result = attach.attach_one(self.library_root, "3001", self.pdf_path, force=True)
        self.assertEqual(result["result"], "attached")

    def test_doi_match_verifies_identity(self):
        with mock.patch("attach._pdf_head_text", return_value="Some paper. DOI: 10.1080/realdoi. More text."):
            result = attach.attach_one(self.library_root, "3001", self.pdf_path, force=False)
        self.assertEqual(result["result"], "attached")
        self.assertIn("DOI", result["identity_check"])

    def test_batch_one_bad_path_does_not_block_other(self):
        with mock.patch("attach._pdf_head_text", return_value="... 10.1080/realdoi ..."):
            outcomes = []
            for pmid, path in (("9999999", self.tmp / "nope.pdf"), ("3001", self.pdf_path)):
                try:
                    outcomes.append(attach.attach_one(self.library_root, pmid, path, force=False))
                except ValueError as e:
                    outcomes.append({"pmid": pmid, "result": "failed", "error": str(e)})
        by_pmid = {o["pmid"]: o for o in outcomes}
        self.assertEqual(by_pmid["9999999"]["result"], "failed")
        self.assertEqual(by_pmid["3001"]["result"], "attached")


# ---- interrupted staged commit recovers (§3a) ----

class TestInterruptedCommitRecovers(TempLibrary):
    def test_crash_mid_write_leaves_prior_current_json_intact(self):
        from lib_atomic import commit_version

        paper_dir = self.library_root / "papers" / "4001"
        paper_dir.mkdir(parents=True)

        def good_write(staging):
            atomic_write_bytes(staging / "source.md", b"first version")

        commit_version(paper_dir, "v-good", good_write)
        prior = json.loads((paper_dir / "current.json").read_text())
        self.assertEqual(prior["version"], "v-good")

        def crashing_write(staging):
            atomic_write_bytes(staging / "source.md", b"partial")
            raise RuntimeError("simulated crash mid-write")

        with self.assertRaises(RuntimeError):
            commit_version(paper_dir, "v-bad", crashing_write)

        # current.json must still point at the prior valid version
        after = json.loads((paper_dir / "current.json").read_text())
        self.assertEqual(after["version"], "v-good")
        # the failed staging dir must not have been promoted
        self.assertFalse((paper_dir / "versions" / "v-bad").exists())
        self.assertFalse((paper_dir / "versions" / ".staging-v-bad").exists())


if __name__ == "__main__":
    unittest.main()
