#!/usr/bin/env python3
"""Phase 2 gate fixtures (PLAN.md §8 build-order row for phase 2).

Run: python3 skills/ref-manager/scripts/tests/test_phase2.py
"""
from __future__ import annotations

import json
import hashlib
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import add  # noqa: E402
import init_repo  # noqa: E402
import project  # noqa: E402
import person as person_mod  # noqa: E402
import search  # noqa: E402
import export  # noqa: E402
import pubmed_query  # noqa: E402
import publications  # noqa: E402
import report  # noqa: E402
import status  # noqa: E402
from lib_inventory import rows as inventory_rows  # noqa: E402
import queue as queue_mod  # noqa: E402
from lib_atomic import atomic_write_json  # noqa: E402
from lib_selector import resolve, SelectorError  # noqa: E402


def author(last, first, **extra):
    a = {"last": last, "first": first, "raw": f"{last} {first}"}
    a.update(extra)
    return a


class TempLibrary(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.library_root = self.tmp / "lib"
        for rel in init_repo.LIBRARY_DIRS:
            (self.library_root / rel).mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def add_paper(self, pmid, title, abstract, authors, year="2020", **extra):
        record = {"pmid": pmid, "title": title, "abstract": abstract, "authors": authors, "year": year}
        record.update(extra)
        return add.add_one(self.library_root, record)

    def set_authorship(self, pmid, **fields):
        path = self.library_root / "papers" / pmid / "authorship.json"
        doc = json.loads(path.read_text())
        doc.update(fields)
        atomic_write_json(path, doc)


# ---- selector grammar (§5c) ----

class TestSelectorReportsBeforeWork(TempLibrary):
    def test_resolve_reports_tier_and_status_counts(self):
        self.add_paper("1001", "Paper One", "abs", [author("Smith", "Jane")])
        result = resolve(self.library_root, pmids=["1001"])
        self.assertEqual(result["pmids"], ["1001"])
        self.assertEqual(result["report"]["by_extraction_tier"]["abstract"], 1)
        self.assertEqual(result["report"]["by_human_verification_state"], {"reviewed": 0, "unreviewed": 1})
        # Phase 11: retraction_status is real (from meta.json) as of phase 4,
        # not a placeholder -- a freshly-added paper has never been checked,
        # so it correctly reports "unknown", not a fabricated "none".
        self.assertEqual(result["report"]["by_retraction_errata_status"], {"unknown": 1})


class TestSelectorEmptyIsNamedError(TempLibrary):
    def test_empty_match_is_named_error_not_empty_result(self):
        project.create(self.library_root, "proj1", None)
        with self.assertRaises(SelectorError) as cm:
            resolve(self.library_root, project="proj1")
        self.assertIn("proj1", str(cm.exception))


# ---- /ref:search ----

class TestSearchScopeLabels(TempLibrary):
    def test_evidence_and_notes_carry_distinct_labels(self):
        self.add_paper("2001", "Herbal Discrimination Study", "about herbs and mass spectrometry", [author("Ahn", "SJ")])
        notes_path = self.library_root / "papers" / "2001" / "notes.md"
        notes_path.write_text("herbs are great for the chapter\n")

        results = search.run(self.library_root, "all", "herb")
        kinds = {r["kind"] for r in results}
        self.assertIn("evidence", kinds)
        self.assertIn("personal_note", kinds)
        # never conflated
        for r in results:
            self.assertIn(r["kind"], ("evidence", "personal_note", "project_relevance"))

    def test_evidence_search_matches_doi_and_author_fields(self):
        self.add_paper("2002", "Structured Search Paper", "about structured search", [author("Nakamura", "Ai")], doi="10.1234/abc.def")

        doi_results = search.run(self.library_root, "evidence", "10.1234/abc.def")
        self.assertEqual(len(doi_results), 1)
        self.assertEqual(doi_results[0]["field"], "doi")
        self.assertEqual(doi_results[0]["source_kind"], "metadata")

        author_results = search.run(self.library_root, "evidence", "Nakamura Ai")
        self.assertEqual(len(author_results), 1)
        self.assertEqual(author_results[0]["field"], "author")
        self.assertEqual(author_results[0]["lifecycle"], "abstract-only")

    def test_evidence_search_matches_grant_fields(self):
        self.add_paper("2007", "Grant Search Paper", "about grants", [author("Grant", "Greta")])
        funding_path = self.library_root / "papers" / "2007" / "funding.json"
        atomic_write_json(funding_path, {
            "pmid": "2007",
            "observations": [{
                "kind": "explicit_acknowledgement_verified",
                "source": "jats_funding_statement",
                "funder": "NIH",
                "award_number": "R01-ABC123",
                "text": "Supported by NIH R01-ABC123",
                "locator": "funding-group/funding-statement",
            }],
            "state": "explicit_acknowledgement_verified",
        })

        grant_results = search.run(self.library_root, "evidence", "R01-ABC123")
        self.assertEqual(len(grant_results), 1)
        self.assertEqual(grant_results[0]["field"], "grant")
        self.assertEqual(grant_results[0]["lifecycle"], "abstract-only")

    def test_all_scope_matches_saved_query_context(self):
        self.add_paper("2008", "Saved Query Paper", "about queries", [author("Query", "Quinn")])
        atomic_write_json(self.library_root / "queries" / "q1" / "query.yaml", {
            "slug": "q1",
            "runs": [{
                "run_id": "run-abc",
                "query": "cancer AND therapy",
                "source": "pubmed",
                "retrieved_at": "2026-01-01T00:00:00Z",
                "pmids": ["2008"],
            }],
        })

        hits = search.run(self.library_root, "all", "cancer AND therapy")
        saved = [r for r in hits if r["kind"] == "saved_query"]
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["slug"], "q1")
        self.assertEqual(saved[0]["lifecycle"], "query")


class TestStatusDashboard(TempLibrary):
    def test_recent_papers_show_source_badges(self):
        self.add_paper("2101", "Badge Paper", "abs", [author("Badge", "Bea")])
        paper_dir = self.library_root / "papers" / "2101"
        file_hash = hashlib.sha256(b"pdf-bytes").hexdigest()
        raw_dir = paper_dir / "raw" / file_hash
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / "source.pdf").write_bytes(b"pdf-bytes")

        buf = StringIO()
        with redirect_stdout(buf):
            status._print_recent_papers(inventory_rows(self.library_root))
        output = buf.getvalue()
        self.assertIn("[pdf-backed]", output)

    def test_recent_papers_show_figure_badges_when_assets_exist(self):
        self.add_paper("2108", "Figure Badge Paper", "abs", [author("Figure", "Fay")])
        paper_dir = self.library_root / "papers" / "2108"
        file_hash = hashlib.sha256(b"pdf-bytes").hexdigest()
        raw_dir = paper_dir / "raw" / file_hash
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / "source.pdf").write_bytes(b"pdf-bytes")
        current = paper_dir / "current.json"
        current.write_text(json.dumps({"version": "v-fig"}))
        version_dir = paper_dir / "versions" / "v-fig"
        version_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(version_dir / "figures.json", [{"id": "fig1", "asset_available": True}])

        buf = StringIO()
        with redirect_stdout(buf):
            status._print_recent_papers(inventory_rows(self.library_root))
        output = buf.getvalue()
        self.assertIn("[pdf-backed+figures]", output)


class TestProjectListSummary(TempLibrary):
    def test_list_projects_includes_paper_and_reading_counts(self):
        project.create(self.library_root, "proj1", "scope text")
        self.add_paper("2102", "Project Source Paper", "abs", [author("Alpha", "A")])
        self.add_paper("2103", "Project Source Paper 2", "abs", [author("Beta", "B")])
        project.add_paper(self.library_root, "proj1", "2102", "relevant", 1, "read")
        project.add_paper(self.library_root, "proj1", "2103", "relevant", 2, "to_read")

        projects = project.list_projects(self.library_root)
        self.assertEqual(projects[0]["papers"], 2)
        self.assertEqual(projects[0]["reading"]["read"], 1)
        self.assertEqual(projects[0]["reading"]["to_read"], 1)

    def test_list_projects_includes_source_counts(self):
        project.create(self.library_root, "proj1", "scope text")
        self.add_paper("2102", "Project Source Paper", "abs", [author("Alpha", "A")])
        self.add_paper("2103", "Project Source Paper 2", "abs", [author("Beta", "B")])
        project.add_paper(self.library_root, "proj1", "2102", "relevant", 1, "read")
        project.add_paper(self.library_root, "proj1", "2103", "relevant", 2, "to_read")
        paper_dir = self.library_root / "papers" / "2102"
        raw_dir = paper_dir / "raw" / hashlib.sha256(b"pdf-bytes").hexdigest()
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / "source.pdf").write_bytes(b"pdf-bytes")
        result = project.list_projects(self.library_root)
        self.assertEqual(result[0]["source"]["pdf_backed"], 1)
        self.assertEqual(result[0]["source"]["abstract_only"], 1)

    def test_show_project_includes_summary(self):
        project.create(self.library_root, "proj2", "scope text")
        project.add_paper(self.library_root, "proj2", "2104", "relevant", 1, "reading")
        result = project.show(self.library_root, "proj2")
        self.assertEqual(result["summary"]["paper_count"], 1)
        self.assertEqual(result["summary"]["reading"]["reading"], 1)
        self.assertEqual(result["summary"]["question_count"], 0)
        self.assertIn("source", result["summary"])


class TestQueueSummary(TempLibrary):
    def test_queue_show_includes_reading_summary(self):
        project.create(self.library_root, "proj3", "scope text")
        project.add_paper(self.library_root, "proj3", "2105", "relevant", 1, "read")
        project.add_paper(self.library_root, "proj3", "2106", "relevant", 2, "to_screen")

        result = queue_mod.show(self.library_root, "proj3", None)
        self.assertEqual(result["summary"]["read"], 1)
        self.assertEqual(result["summary"]["to_screen"], 1)
        self.assertEqual(len(result["papers"]), 2)

    def test_queue_show_includes_source_summary(self):
        project.create(self.library_root, "proj4", "scope text")
        self.add_paper("2107", "Queue Source Paper", "abs", [author("Gamma", "G")])
        project.add_paper(self.library_root, "proj4", "2107", "relevant", 1, "read")
        paper_dir = self.library_root / "papers" / "2107"
        raw_dir = paper_dir / "raw" / hashlib.sha256(b"pdf-bytes").hexdigest()
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / "source.pdf").write_bytes(b"pdf-bytes")

        result = queue_mod.show(self.library_root, "proj4", None)
        self.assertEqual(result["source"]["pdf_backed"], 1)


# ---- /ref:export ----

class TestExportBibAndCsl(TempLibrary):
    def test_bibtex_and_csl_render_same_source_with_escaping(self):
        self.add_paper("3001", "Salt & Pepper: A Study", "abs one", [author("Ampersand", "Ann")], doi="10.1/x")
        self.add_paper("3002", "Second Paper", "abs two", [author("Beta", "Bob")], doi="10.1/y")

        result = export.run_export(
            self.library_root, "batch1",
            resolve(self.library_root, pmids=["3001", "3002"]), refresh=False,
        )
        self.assertEqual(result["status"], "created")

        bib = (self.library_root / "exports" / "batch1" / "references.bib").read_text()
        csl = json.loads((self.library_root / "exports" / "batch1" / "references.csl.json").read_text())

        self.assertEqual(len(csl), 2)
        self.assertIn(r"Salt \& Pepper", bib)
        self.assertIn("doi = {10.1/x}", bib)
        self.assertEqual(csl[0]["title"], "Salt & Pepper: A Study")  # CSL-JSON keeps it literal


class TestExportFreezeAndRefresh(TempLibrary):
    def test_rerun_without_refresh_reuses_frozen_batch(self):
        self.add_paper("4001", "Frozen Set Paper", "abs", [author("One", "A")])
        res1 = resolve(self.library_root, pmids=["4001"])
        r1 = export.run_export(self.library_root, "frozen1", res1, refresh=False)
        self.assertEqual(r1["status"], "created")

        # a second paper now matches a broader selector, but batch is frozen
        self.add_paper("4002", "Second Frozen Set Paper", "abs", [author("Two", "B")])
        r2 = export.run_export(self.library_root, "frozen1", None, refresh=False)
        self.assertEqual(r2["status"], "reused_frozen_batch")
        self.assertEqual(r2["manifest"]["pmids"], ["4001"])

        res3 = resolve(self.library_root, pmids=["4001", "4002"])
        r3 = export.run_export(self.library_root, "frozen1", res3, refresh=True)
        self.assertEqual(r3["status"], "refreshed")
        self.assertEqual(r3["added"], ["4002"])


# ---- saved query runs (D15) ----

class TestSavedQueryRerunAppendsHistory(TempLibrary):
    def test_rerun_appends_and_preserves_prior_run(self):
        r1 = pubmed_query.new_run(self.library_root, "q1", "(herb) AND (mass spectrometry)", "pubmed", ["1", "2"], create=True)
        r2 = pubmed_query.rerun(self.library_root, "q1", ["2", "3"])
        doc = pubmed_query.show(self.library_root, "q1")
        self.assertEqual(len(doc["runs"]), 2)
        self.assertEqual(doc["runs"][0]["pmids"], ["1", "2"])  # untouched
        self.assertEqual(doc["runs"][1]["pmids"], ["2", "3"])
        self.assertEqual(doc["runs"][1]["query"], doc["runs"][0]["query"])  # exact stored expr, not re-derived
        self.assertEqual(r2["added"], ["3"])
        self.assertEqual(r2["removed"], ["1"])


# ---- author roles ----

class TestAuthorRoles(TempLibrary):
    def test_sole_author_counted_once(self):
        self.add_paper("5001", "Solo Paper", "abs", [author("Solo", "Sam")])
        p = person_mod.create(self.library_root, "sam-solo", "Sam Solo", None)
        person_mod.confirm_publication(self.library_root, "sam-solo", "5001", 0)
        roles = publications.roles(self.library_root, "sam-solo", None)
        self.assertEqual(len(roles), 1)
        self.assertEqual(roles[0]["role"], "sole")

    def test_incomplete_list_yields_unresolved_not_guessed(self):
        self.add_paper("5002", "Group Paper", "abs", [author("First", "F"), author("Last", "L")])
        self.set_authorship("5002", complete=False)
        person_mod.create(self.library_root, "first-f", "F First", None)
        person_mod.confirm_publication(self.library_root, "first-f", "5002", 0)
        roles = publications.roles(self.library_root, "first-f", None)
        self.assertEqual(roles[0]["role"], "unresolved")


# ---- coauthor declaration (§3c) ----

class TestCoauthorDedupAndGapsAndGroups(TempLibrary):
    def test_coauthor_export(self):
        # paper A: subject + a coauthor who will be a CONFIRMED identity elsewhere
        self.add_paper("6001", "Paper A", "abs", [
            author("Subject", "Sue"), author("Known", "Ken"),
        ], year="2021")
        self.set_authorship("6001", complete=True)

        # paper B: subject + same-named person who is NOT confirmed for this pmid
        # (ambiguous — must be listed separately, not merged into coauthors)
        self.add_paper("6002", "Paper B", "abs", [
            author("Subject", "Sue"), author("Known", "Ken"),
        ], year="2022")

        # paper C: subject + an unlinked coauthor (exact-name fallback) + a group author
        self.add_paper("6003", "Paper C", "abs", [
            author("Subject", "Sue"), author("Loose", "Lou", affiliation="Acme U"),
            author("Consortium", "", raw="The Big Consortium", is_group=True),
        ], year="2023")
        self.set_authorship("6003", complete=False)  # incomplete -> gap

        subject = person_mod.create(self.library_root, "sue-subject", "Sue Subject", None)
        person_mod.confirm_publication(self.library_root, "sue-subject", "6001", 0)
        person_mod.confirm_publication(self.library_root, "sue-subject", "6002", 0)
        person_mod.confirm_publication(self.library_root, "sue-subject", "6003", 0)

        ken = person_mod.create(self.library_root, "ken-known", "Known Ken", None)
        person_mod.confirm_publication(self.library_root, "ken-known", "6001", 1)
        # NOTE: Ken is NOT confirmed as author-index 1 on paper 6002 -> ambiguous there

        result = publications.coauthors(self.library_root, "sue-subject", "2021", "2023")

        names = {r["name"] for r in result["coauthors"]}
        methods = {r["identity_method"] for r in result["coauthors"]}
        self.assertIn("confirmed_identity", methods)   # Ken via paper 6001
        self.assertIn("exact_name", methods)            # Lou via paper 6003
        self.assertIn("group", methods)                 # Consortium via paper 6003
        self.assertIn("The Big Consortium", names)       # group reported as the group, not expanded

        # Ken's paper-6002 appearance is ambiguous (same name, not confirmed there)
        cand_names = {c["name"] for c in result["unconfirmed_candidates"]}
        self.assertIn("Known Ken", cand_names)
        # ambiguous appearance never silently counted in the main coauthor row's pmids
        ken_row = next(r for r in result["coauthors"] if r["identity_method"] == "confirmed_identity")
        self.assertNotIn("6002", ken_row["pmids"])

        # affiliation captured
        lou_row = next(r for r in result["coauthors"] if r["name"] == "Loose Lou")
        self.assertEqual(lou_row["affiliation"], "Acme U")

        # incomplete-author-list paper surfaces as a gap, not silently dropped
        gap_pmids = {g["pmid"] for g in result["gaps"]}
        self.assertIn("6003", gap_pmids)


# ---- /ref:report ----

class TestReportReproducible(TempLibrary):
    def test_rerun_with_same_inputs_reproduces_content(self):
        self.add_paper("7001", "Reported Paper", "abs", [author("Rep", "Ray")], year="2022")
        person_mod.create(self.library_root, "ray-rep", "Ray Rep", None)
        person_mod.confirm_publication(self.library_root, "ray-rep", "7001", 0)

        report.generate(self.library_root, "ray-rep", "2020", "2023", "test-report")
        csv1 = (self.library_root / "reports" / "test-report" / "publications.csv").read_text()
        md1 = (self.library_root / "reports" / "test-report" / "report.md").read_text()

        report.generate(self.library_root, "ray-rep", "2020", "2023", "test-report")
        csv2 = (self.library_root / "reports" / "test-report" / "publications.csv").read_text()
        md2 = (self.library_root / "reports" / "test-report" / "report.md").read_text()

        self.assertEqual(csv1, csv2)
        self.assertEqual(md1, md2)


if __name__ == "__main__":
    unittest.main()
