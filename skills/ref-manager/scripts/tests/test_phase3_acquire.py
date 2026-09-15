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
import attach_figures  # noqa: E402
import convert  # noqa: E402
import fetch  # noqa: E402
import fetch_pmc_pdf  # noqa: E402
import funding_extract  # noqa: E402
import init_repo  # noqa: E402
import pdf_identify  # noqa: E402
import read_article  # noqa: E402
import url_identify  # noqa: E402
from lib_atomic import atomic_write_bytes, atomic_write_json  # noqa: E402

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


class TestConvertJatsRejectsNonXml(TempLibrary):
    def test_plain_text_is_refused_not_silently_mangled(self):
        # Verified live against the PubMed MCP get_full_text_article tool:
        # it returns pre-extracted plain text, not JATS XML. pandoc -f jats
        # does not error on non-XML input -- it silently falls back to
        # plain-text parsing and destroys heading/section structure with no
        # diagnostic. convert_jats must refuse this input explicitly.
        staging = self.tmp / "staging-badjats"
        staging.mkdir()
        result = convert.convert_jats("INTRODUCTION\n\nSome plain prose.\n", staging)
        self.assertEqual(result["status"], "error")
        self.assertIn("not well-formed XML", result["diagnostics"][0])
        self.assertFalse((staging / "source.md").exists())


class TestConvertPlainText(TempLibrary):
    def test_plain_text_written_through_with_loss_stated(self):
        staging = self.tmp / "staging-plain"
        staging.mkdir()
        text = "INTRODUCTION\n\nWomen living with HIV...\n\nMETHODS\n\n98 participants."
        result = convert.convert_plain_text(text, staging)
        self.assertEqual(result["status"], "ok")
        self.assertEqual((staging / "source.md").read_text(), text)
        self.assertTrue(any("not recoverable" in d for d in result["diagnostics"]))

    def test_html_converter_would_silently_lose_plain_text(self):
        # Regression guard for the bug this test file's sibling test caught:
        # trafilatura returns an EMPTY document (status "ok") on non-HTML
        # plain text, which is why fetch.py routes plain_text through
        # convert_plain_text instead of convert_html.
        staging = self.tmp / "staging-html-on-plain"
        staging.mkdir()
        result = convert.convert_html("INTRODUCTION\n\nSome plain prose with no tags.\n", staging)
        self.assertEqual(result["status"], "ok")
        self.assertEqual((staging / "source.md").read_text(), "")


class TestFetchPlainText(TempLibrary):
    def test_plain_text_source_commits_and_preserves_content(self):
        self.add_paper("34713412")
        text = "INTRODUCTION\n\nWomen living with HIV...\n"
        result = fetch.fetch_one(self.library_root, {
            "pmid": "34713412", "doi": None, "jats_xml": None,
            "publisher_html": None, "plain_text": text,
        }, unpaywall_email=None)
        self.assertEqual(result["result"], "acquired")
        self.assertEqual(result["source"], "plain_text")
        version_dirs = list((self.library_root / "papers" / "34713412" / "versions").iterdir())
        self.assertEqual(len(version_dirs), 1)
        self.assertEqual((version_dirs[0] / "source.md").read_text(), text)

    def test_refetch_identical_source_is_duplicate_noop(self):
        self.add_paper("34713413")
        record = {
            "pmid": "34713413", "doi": None, "jats_xml": None,
            "publisher_html": None, "plain_text": "INTRODUCTION\n\nSame source.\n",
        }
        first = fetch.fetch_one(self.library_root, record, unpaywall_email=None)
        second = fetch.fetch_one(self.library_root, record, unpaywall_email=None)
        paper_dir = self.library_root / "papers" / "34713413"
        version_dirs = [p for p in (paper_dir / "versions").iterdir() if p.is_dir()]

        self.assertEqual(first["result"], "acquired")
        self.assertEqual(second["result"], "duplicate_noop")
        self.assertEqual(second["version"], first["version"])
        self.assertEqual(len(version_dirs), 1)

    def test_refetch_changed_source_keeps_only_new_complete_fetch_version(self):
        self.add_paper("34713414")
        first = fetch.fetch_one(self.library_root, {
            "pmid": "34713414", "doi": None, "jats_xml": None,
            "publisher_html": None, "plain_text": "INTRODUCTION\n\nOld source.\n",
        }, unpaywall_email=None)
        second = fetch.fetch_one(self.library_root, {
            "pmid": "34713414", "doi": None, "jats_xml": None,
            "publisher_html": None, "plain_text": "INTRODUCTION\n\nNew source.\n",
        }, unpaywall_email=None)
        paper_dir = self.library_root / "papers" / "34713414"
        version_dirs = [p for p in (paper_dir / "versions").iterdir() if p.is_dir()]
        current = json.loads((paper_dir / "current.json").read_text())["version"]

        self.assertEqual(first["result"], "acquired")
        self.assertEqual(second["result"], "acquired")
        self.assertNotEqual(first["version"], second["version"])
        self.assertEqual(current, second["version"])
        self.assertEqual([p.name for p in version_dirs], [second["version"]])
        self.assertEqual((version_dirs[0] / "source.md").read_text(), "INTRODUCTION\n\nNew source.\n")


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

    def test_fetch_passes_pmcid_to_figure_downloader(self):
        self.add_paper("2005", doi="10.1002/aur.70084", pmcid="PMC12442529")
        record = {"pmid": "2005", "doi": "10.1002/aur.70084", "jats_xml": JATS_FIXTURE, "publisher_html": None}
        with mock.patch("fetch.download_figure_assets", return_value={
            "pmid": "2005", "figures": 1, "images_available": 1, "diagnostics": [],
        }) as downloader:
            result = fetch.fetch_one(self.library_root, record, unpaywall_email=None)
        self.assertEqual(result["result"], "acquired")
        args = downloader.call_args.args
        self.assertEqual(args[0], self.library_root)
        self.assertEqual(args[1], "2005")
        self.assertEqual(args[2], "10.1002/aur.70084")
        self.assertEqual(args[4], "PMC12442529")


class TestAttachFigures(TempLibrary):
    def test_pmc_candidate_url_uses_numeric_pmcid_and_jats_locator(self):
        candidates = attach_figures._candidate_urls(
            "10.1002/aur.70084", "AUR-18-1861-g001.jpg", "PMC12442529",
        )
        self.assertEqual(candidates[0], (
            "pmc",
            "AUR-18-1861-g001.jpg",
            "https://pmc.ncbi.nlm.nih.gov/articles/instance/12442529/bin/AUR-18-1861-g001.jpg",
        ))

    def test_download_auto_fetches_pmc_asset_and_updates_figures_json(self):
        paper_dir = self.library_root / "papers" / "2006"
        vdir = paper_dir / "versions" / "v-test"
        (vdir / "figures").mkdir(parents=True)
        atomic_write_json(paper_dir / "current.json", {"version": "v-test"})
        atomic_write_json(vdir / "figures.json", [{
            "id": "fig1", "label": "Figure 1", "caption": "Caption",
            "source_locator": "AUR-18-1861-g001.jpg",
            "sha256": None, "asset_available": False,
        }])

        with mock.patch("attach_figures._download", return_value=b"fake image bytes") as download:
            result = attach_figures.download_auto(
                self.library_root, "2006", "10.1002/aur.70084", pmcid="PMC12442529",
            )

        self.assertEqual(result["images_available"], 1)
        download.assert_called_once_with(
            "https://pmc.ncbi.nlm.nih.gov/articles/instance/12442529/bin/AUR-18-1861-g001.jpg"
        )
        figures = json.loads((vdir / "figures.json").read_text())
        self.assertTrue(figures[0]["asset_available"])
        self.assertIsNotNone(figures[0]["sha256"])
        self.assertEqual((vdir / "figures" / "AUR-18-1861-g001.jpg").read_bytes(), b"fake image bytes")


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


class TestFetchPmcPdf(TempLibrary):
    def test_no_pmcid_is_normal_result(self):
        self.add_paper("3101", pmcid=None)
        result = fetch_pmc_pdf.fetch_pmc_pdf_one(self.library_root, "3101")
        self.assertEqual(result["result"], "no_pmcid")

    def test_pmc_pdf_download_attaches_through_attach_pipeline(self):
        self.add_paper("3102", doi="10.1080/realdoi", pmcid="PMC123")
        fake_pdf = b"%PDF-1.4 fake pmc pdf"
        with (
            mock.patch("fetch_pmc_pdf._oa_pdf_link", return_value=("ftp://example.test/paper.pdf", [])),
            mock.patch("fetch_pmc_pdf._urlopen_bytes", return_value=fake_pdf),
            mock.patch("attach._pdf_head_text", return_value="... 10.1080/realdoi ..."),
        ):
            result = fetch_pmc_pdf.fetch_pmc_pdf_one(self.library_root, "3102")

        self.assertEqual(result["result"], "attached")
        self.assertEqual(result["source"], "pmc_oa_pdf")
        self.assertEqual(result["pmcid"], "PMC123")
        paper_dir = self.library_root / "papers" / "3102"
        raw_pdf = next((paper_dir / "raw").glob("*/source.pdf"))
        self.assertEqual(raw_pdf.read_bytes(), fake_pdf)
        attachment = json.loads((raw_pdf.parent / "attachment.json").read_text())
        self.assertEqual(attachment["attached_from"], "pmc_oa:ftp://example.test/paper.pdf")

    def test_oa_pdf_link_extracts_pdf_href(self):
        xml = b"""<?xml version="1.0"?>
        <OA><records><record id="PMC123">
          <link format="tgz" href="ftp://example.test/package.tgz"/>
          <link format="pdf" href="/ftp://example.test/paper.pdf"/>
        </record></records></OA>"""
        with mock.patch("fetch_pmc_pdf._urlopen_bytes", return_value=xml):
            href, diagnostics = fetch_pmc_pdf._oa_pdf_link("PMC123")
        self.assertEqual(href, "ftp://example.test/paper.pdf")
        self.assertEqual(diagnostics, [])

    def test_no_pdf_reports_jats_full_text_when_available(self):
        self.add_paper("3103", pmcid="PMC12442529")
        with (
            mock.patch("fetch_pmc_pdf._oa_pdf_link", return_value=(None, ["PMC OA PDF unavailable"])),
            mock.patch("fetch_pmc_pdf._pmc_jats_available", return_value=(True, None)),
        ):
            result = fetch_pmc_pdf.fetch_pmc_pdf_one(self.library_root, "3103")

        self.assertEqual(result["result"], "no_pdf")
        self.assertTrue(result["full_text_available"])
        self.assertEqual(result["full_text_source"], "pmc_jats")
        self.assertIn("/ref:fetch", result["note"])

    def test_pmc_jats_available_recognizes_efetch_article_xml(self):
        xml = b"<?xml version='1.0'?><pmc-articleset><article/></pmc-articleset>"
        with mock.patch("fetch_pmc_pdf._urlopen_bytes", return_value=xml):
            available, diagnostic = fetch_pmc_pdf._pmc_jats_available("PMC123")
        self.assertTrue(available)
        self.assertIsNone(diagnostic)


class TestReadArticle(TempLibrary):
    def test_render_current_source_with_downloaded_figures(self):
        self.add_paper("3201", title="Readable paper", pmcid="PMC3201")
        paper_dir = self.library_root / "papers" / "3201"
        vdir = paper_dir / "versions" / "v-read"
        (vdir / "figures").mkdir(parents=True)
        atomic_write_json(paper_dir / "current.json", {"version": "v-read"})
        atomic_write_bytes(vdir / "source.md", b"# Introduction\n\nA useful result.\n")
        atomic_write_bytes(vdir / "figures" / "fig1.jpg", b"fake image bytes")
        atomic_write_json(vdir / "figures.json", [{
            "id": "fig1", "label": "Figure 1", "caption": "A useful picture.",
            "source_locator": "fig1.jpg", "sha256": "abc", "asset_available": True,
        }])

        result = read_article.render_one(self.library_root, "3201")

        self.assertEqual(result["result"], "rendered")
        self.assertEqual(result["figures"], 1)
        self.assertEqual(result["images_available"], 1)
        html = (paper_dir / "reader" / "article.html").read_text()
        self.assertIn("Readable paper", html)
        self.assertIn("<h1>Readable paper</h1>", html)
        self.assertIn("<h1>Introduction</h1>", html)
        self.assertIn("../versions/v-read/figures/fig1.jpg", html)
        self.assertIn("A useful picture.", html)
        manifest = json.loads((paper_dir / "reader" / "manifest.json").read_text())
        self.assertEqual(manifest["version"], "v-read")

    def test_render_reports_no_full_text_without_source_md(self):
        self.add_paper("3202")
        paper_dir = self.library_root / "papers" / "3202"
        (paper_dir / "versions" / "v-claims").mkdir(parents=True)
        atomic_write_json(paper_dir / "current.json", {"version": "v-claims"})

        result = read_article.render_one(self.library_root, "3202")

        self.assertEqual(result["result"], "no_full_text")
        self.assertIn("source.md", result["reason"])

    def test_quarto_source_rewrites_inline_figure_paths(self):
        figures = [{
            "id": "fig1", "label": "Figure 1", "caption": "Caption",
            "source_locator": "AUR-18-1861-g002.jpg",
            "sha256": "abc", "asset_available": True,
        }]
        source = (
            '<figure id="fig1"><p><img src="AUR-18-1861-g002.jpg" /></p></figure>\n'
            "![same](AUR-18-1861-g002.jpg)\n"
        )

        qmd, rewrites = read_article._quarto_source(
            {"pmid": "3203", "title": "T"}, "v-read", source, figures,
        )

        self.assertEqual(rewrites, 2)
        self.assertIn('../versions/v-read/figures/AUR-18-1861-g002.jpg', qmd)
        self.assertNotIn('src="AUR-18-1861-g002.jpg"', qmd)
        self.assertNotIn('](AUR-18-1861-g002.jpg)', qmd)

    def test_table_image_refs_are_inserted_after_live_tables(self):
        html = "<html><body><table><tr><td>A</td></tr></table><p>after</p></body></html>"

        updated, inserted = read_article._insert_table_image_refs(html, ["tables/table-1.png"])

        self.assertEqual(inserted, 1)
        self.assertIn("<table><tr><td>A</td></tr></table>", updated)
        self.assertIn('<figure class="table-snapshot"><img src="tables/table-1.png"', updated)
        self.assertLess(updated.index("</table>"), updated.index("table-snapshot"))


class TestPdfIdentify(TempLibrary):
    def test_extracts_doi_pmid_and_pmcid_from_pdf_text(self):
        pdf = self.tmp / "paper.pdf"
        pdf.write_bytes(b"%PDF fake")
        text = (
            "Title of the Real Paper\n"
            "DOI: 10.1002/aur.70084.\n"
            "PMID: 40665956\n"
            "PMCID: PMC12442529\n"
        )
        with mock.patch("pdf_identify._extract_pdf_text", return_value=(text, None)):
            result = pdf_identify.identify_pdf(pdf)

        self.assertEqual(result["result"], "identified_clues")
        self.assertEqual(result["doi"], "10.1002/aur.70084")
        self.assertEqual(result["pmid"], "40665956")
        self.assertEqual(result["pmcid"], "PMC12442529")
        self.assertIn("Title of the Real Paper", result["title_guess"])

    def test_no_clues_is_normal_result(self):
        pdf = self.tmp / "paper.pdf"
        pdf.write_bytes(b"%PDF fake")
        with mock.patch("pdf_identify._extract_pdf_text", return_value=("Only prose.", None)):
            result = pdf_identify.identify_pdf(pdf)

        self.assertEqual(result["result"], "no_clues")
        self.assertIsNone(result["doi"])
        self.assertIsNone(result["pmid"])


class TestUrlIdentify(unittest.TestCase):
    def test_pubmed_url_extracts_pmid(self):
        result = url_identify.identify_url("https://pubmed.ncbi.nlm.nih.gov/40665956/")
        self.assertEqual(result["pmid"], "40665956")
        self.assertEqual(result["source"], "pubmed_url")

    def test_pmc_url_extracts_pmcid(self):
        result = url_identify.identify_url("https://pmc.ncbi.nlm.nih.gov/articles/PMC12442529/")
        self.assertEqual(result["pmcid"], "PMC12442529")
        self.assertEqual(result["source"], "pmc_url")

    def test_doi_url_extracts_doi(self):
        result = url_identify.identify_url("https://doi.org/10.1002/aur.70084")
        self.assertEqual(result["doi"], "10.1002/aur.70084")
        self.assertEqual(result["source"], "doi_url")

    def test_publisher_url_with_encoded_doi_extracts_doi(self):
        result = url_identify.identify_url("https://example.org/article/10.1002%2Faur.70084?x=1")
        self.assertEqual(result["doi"], "10.1002/aur.70084")
        self.assertEqual(result["source"], "doi_in_url")


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
