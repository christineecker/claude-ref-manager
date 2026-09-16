#!/usr/bin/env python3
"""Phase 11 (/ref:audit, citation observations, cache invalidation,
/ref:report --citations) gate fixtures (PLAN.md §8 build-order row for
phase 11 — the LAST phase).

Run: python3 skills/ref-manager/scripts/tests/test_phase11_audit.py
"""
from __future__ import annotations

import csv
import io
import json
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import add  # noqa: E402
import extract  # noqa: E402
import compare  # noqa: E402
import summarize  # noqa: E402
import brief  # noqa: E402
import report  # noqa: E402
import init_repo  # noqa: E402
import audit  # noqa: E402
from lib_schema import SchemaError  # noqa: E402


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
            "pmid": pmid, "title": f"Paper {pmid}", "abstract": "abs",
            "authors": [author("Smith", "Jane")], "journal": "X", "year": "2022",
            "doi": f"10.1/{pmid}", "pmcid": None, "grants": [],
        }
        record.update(overrides)
        return add.add_one(self.library_root, record)

    def extract_one_claim(self, pmid):
        env = {
            "pmid": pmid, "study_type": "unknown", "study_type_confidence": "uncertain",
            "claims": [{
                "locator": "abstract", "evidence_span": "x", "evidence_tier": "abstract",
                "population": "unknown", "intervention": "unknown", "comparator": "unknown",
                "outcome": "unknown", "timepoint": "unknown", "direction": "not reported",
                "effect_value": "unknown", "effect_measure": "unknown",
                "uncertainty_interval": "unknown", "study_design": "unknown",
                "cohort_identity": "unknown", "adjustment_context": "unknown",
            }],
            "evidence_tier": "abstract", "source_hash": "h",
            "retraction_status": {"status": "unknown", "source": "pubmed", "checked_at": _now()},
        }
        return extract.extract_one(self.library_root, env,
                                    {"extractor": "ref-extractor", "model": "test", "prompt_version": "1"})


def _now():
    return datetime.now(timezone.utc).isoformat()


# ------------------------------------------------------------- retraction status

class TestRetractionAudit(TempLibrary):
    def test_successful_change_updates_and_reports_changed(self):
        self.add_paper("100")
        rec = audit.audit_retraction_status(
            self.library_root, "100",
            {"status": "retracted", "source": "pubmed", "checked_at": _now()}, None,
        )
        self.assertEqual(rec["audit_result"], "checked")
        self.assertTrue(rec["changed"])
        meta = json.loads((self.library_root / "papers/100/meta.json").read_text())
        self.assertEqual(meta["retraction_status"]["status"], "retracted")

    def test_failed_check_retains_prior_status_untouched(self):
        self.add_paper("101")
        audit.audit_retraction_status(
            self.library_root, "101",
            {"status": "retracted", "source": "pubmed", "checked_at": _now()}, None,
        )
        rec = audit.audit_retraction_status(self.library_root, "101", None, "network timeout")
        self.assertEqual(rec["audit_result"], "check_failed")
        self.assertEqual(rec["prior_status_retained"]["status"], "retracted")
        meta = json.loads((self.library_root / "papers/101/meta.json").read_text())
        self.assertEqual(meta["retraction_status"]["status"], "retracted")  # untouched

    def test_unchanged_successful_check_reports_not_changed(self):
        self.add_paper("102")
        audit.audit_retraction_status(
            self.library_root, "102", {"status": "none", "source": "pubmed", "checked_at": _now()}, None,
        )
        rec = audit.audit_retraction_status(
            self.library_root, "102", {"status": "none", "source": "pubmed", "checked_at": _now()}, None,
        )
        self.assertFalse(rec["changed"])


# ------------------------------------------------------------- citation observations

class TestCitationObservations(TempLibrary):
    def test_two_runs_append_not_overwrite(self):
        self.add_paper("200")
        audit.audit_citation_observation(
            self.library_root, "200",
            {"source": "pmc_elink", "query": "200[uid]", "count": 3, "coverage": "citing articles indexed in PMC"},
            False, None,
        )
        audit.audit_citation_observation(
            self.library_root, "200",
            {"source": "pmc_elink", "query": "200[uid]", "count": 7, "coverage": "citing articles indexed in PMC"},
            False, None,
        )
        entries = json.loads((self.library_root / "papers/200/citations.json").read_text())
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["count"], 3)
        self.assertEqual(entries[1]["count"], 7)

    def test_failed_lookup_after_prior_observation_does_not_add_zero(self):
        self.add_paper("201")
        audit.audit_citation_observation(
            self.library_root, "201",
            {"source": "pmc_elink", "query": "201[uid]", "count": 9, "coverage": "citing articles indexed in PMC"},
            False, None,
        )
        audit.audit_citation_observation(self.library_root, "201", None, False, "elink timeout")
        entries = json.loads((self.library_root / "papers/201/citations.json").read_text())
        self.assertEqual(len(entries), 2)
        self.assertNotIn("count", entries[1])
        self.assertEqual(entries[1]["status"], "check_failed")
        # the most recent REAL observation is still the prior real count, not zero/absent
        latest = audit.latest_real_observation(self.library_root, "201")
        self.assertEqual(latest["count"], 9)

    def test_cli_main_rejects_result_with_no_recognized_key(self):
        # Regression: found live -- a real observation submitted under the
        # wrong key (e.g. "result", mirroring the retraction mode's own
        # field name) silently fell through to a "check_failed" entry via
        # r.get("observation"), indistinguishable from a genuinely failed
        # lookup. The CLI layer (main(), not audit_citation_observation()
        # directly) must refuse this loudly instead.
        import io
        import contextlib
        import sys as _sys

        self.add_paper("209")
        results_file = self.tmp / "bad-results.json"
        results_file.write_text(json.dumps([
            {"pmid": "209", "result": {"source": "pmc_elink", "query": "x", "count": 3, "coverage": "c"}},
        ]))
        argv = ["audit.py", "citations", "--repo", str(self.library_root), "--results-file", str(results_file)]
        old_argv = _sys.argv
        _sys.argv = argv
        stderr = io.StringIO()
        try:
            with contextlib.redirect_stderr(stderr):
                rc = audit.main()
        finally:
            _sys.argv = old_argv
        self.assertNotEqual(rc, 0)
        self.assertIn("malformed", stderr.getvalue())
        citations_path = self.library_root / "papers/209/citations.json"
        self.assertFalse(citations_path.exists())

    def test_no_pmcid_is_distinct_marker_not_silence(self):
        self.add_paper("202")
        rec = audit.audit_citation_observation(self.library_root, "202", None, True, None)
        self.assertEqual(rec["entry"]["status"], "no_pmcid")
        self.assertIn("reason", rec["entry"])
        self.assertIsNone(audit.latest_real_observation(self.library_root, "202"))

    def test_check_failed_entry_never_looks_like_zero(self):
        with self.assertRaises(SchemaError):
            from lib_schema import validate_citation_observation
            validate_citation_observation({"retrieved_at": _now(), "status": "check_failed", "count": 0})


# ------------------------------------------------------------- cache invalidation propagation

class TestCacheInvalidation(TempLibrary):
    def test_compare_refresh_reports_retraction_status_change(self):
        self.add_paper("300")
        compare.run_compare(self.library_root, "b1", None,
                             {"selector_expression": "300", "pmids": ["300"],
                              "report": {"count": 1}}, refresh=False)
        audit.audit_retraction_status(
            self.library_root, "300",
            {"status": "retracted", "source": "pubmed", "checked_at": _now()}, None,
        )
        result = compare.run_compare(self.library_root, "b1", None,
                                      {"selector_expression": "300", "pmids": ["300"],
                                       "report": {"count": 1}}, refresh=True)
        self.assertEqual(result["retraction_status_changes"],
                          [{"pmid": "300", "prior_status": "unknown", "current_status": "retracted"}])
        # prior frozen version's content (rows) still exists on disk, never destroyed
        self.assertIn("rows", result)

    def test_summarize_refresh_reports_retraction_status_change(self):
        self.add_paper("301")
        self.extract_one_claim("301")
        candidates = summarize.build_candidates(self.library_root, ["301"])
        summarize.run_summarize(self.library_root, "s1", None,
                                 {"selector_expression": "301", "pmids": ["301"], "report": {"count": 1}},
                                 "first answer", None, None, refresh=False)
        audit.audit_retraction_status(
            self.library_root, "301",
            {"status": "erratum", "source": "pubmed", "checked_at": _now()}, None,
        )
        result = summarize.run_summarize(self.library_root, "s1", None,
                                          {"selector_expression": "301", "pmids": ["301"], "report": {"count": 1}},
                                          "revised answer", None, None, refresh=True)
        self.assertEqual(result["retraction_status_changes"],
                          [{"pmid": "301", "prior_status": "unknown", "current_status": "erratum"}])

    def test_brief_refresh_reports_retraction_status_change(self):
        self.add_paper("302")
        self.extract_one_claim("302")
        candidates = summarize.build_candidates(self.library_root, ["302"])
        brief.save_brief(self.library_root, None, "q1", "does X work?", None, candidates,
                          "first answer", None, refresh=False)
        audit.audit_retraction_status(
            self.library_root, "302",
            {"status": "retracted", "source": "pubmed", "checked_at": _now()}, None,
        )
        result = brief.save_brief(self.library_root, None, "q1", "does X work?", None, candidates,
                                   "revised answer", None, refresh=True)
        self.assertEqual(result["retraction_status_changes"],
                          [{"pmid": "302", "prior_status": "unknown", "current_status": "retracted"}])

    def test_no_change_reports_empty_list(self):
        self.add_paper("303")
        compare.run_compare(self.library_root, "b2", None,
                             {"selector_expression": "303", "pmids": ["303"],
                              "report": {"count": 1}}, refresh=False)
        result = compare.run_compare(self.library_root, "b2", None,
                                      {"selector_expression": "303", "pmids": ["303"],
                                       "report": {"count": 1}}, refresh=True)
        self.assertEqual(result["retraction_status_changes"], [])

    def test_propagate_finds_referencing_artifact(self):
        self.add_paper("304")
        compare.run_compare(self.library_root, "b3", None,
                             {"selector_expression": "304", "pmids": ["304"],
                              "report": {"count": 1}}, refresh=False)
        result = audit.propagate_status_changes(self.library_root, ["304"])
        self.assertEqual(len(result["potentially_stale_artifacts"]), 1)
        self.assertEqual(result["potentially_stale_artifacts"][0]["kind"], "compare")


# ------------------------------------------------------------- /ref:report --citations

class TestReportCitations(TempLibrary):
    def _confirmed_person(self, pmid):
        import person as person_mod
        if not (self.library_root / "people" / "researcher.json").exists():
            person_mod.create(self.library_root, "researcher", "Jane Smith", None)
        person_mod.confirm_publication(self.library_root, "researcher", pmid, 0)

    def test_every_count_has_source_and_date_unknown_never_zero(self):
        self.add_paper("400", year="2022")
        self._confirmed_person("400")
        self.add_paper("401", year="2022")
        self._confirmed_person("401")
        audit.audit_citation_observation(
            self.library_root, "400",
            {"source": "pmc_elink", "query": "400[uid]", "count": 4, "coverage": "citing articles indexed in PMC"},
            False, None,
        )
        manifest = report.generate(self.library_root, "researcher", "2020-01-01", "2026-01-01",
                                    "rep1", include_citations=True)
        self.assertTrue(manifest["includes_citations"])
        self.assertIn("not a total citation count", manifest["citation_coverage_note"])
        csv_text = (self.library_root / "reports/rep1/publications.csv").read_text()
        self.assertIn("400,", csv_text)
        self.assertIn(",4,pmc_elink,", csv_text)  # real observation

        # report.py's fieldnames now include author_role/extraction_tier/
        # abstract_available/full_text/checked_at before citation_count, so
        # parse with csv.DictReader (also robust to commas inside titles)
        # rather than a naive split(",") on column index (§9.2).
        reader = csv.DictReader(io.StringIO(csv_text))
        rows_by_pmid = {row["pmid"]: row for row in reader}
        row_401 = rows_by_pmid["401"]
        self.assertEqual(row_401["citation_count"], "")  # None, never "0"

    def test_stale_observation_flagged(self):
        self.add_paper("402", year="2022")
        self._confirmed_person("402")
        old_time = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
        entry = {"source": "pmc_elink", "query": "402[uid]", "count": 2,
                  "coverage": "citing articles indexed in PMC", "retrieved_at": old_time}
        from lib_atomic import atomic_write_json
        atomic_write_json(self.library_root / "papers/402/citations.json", [entry])
        manifest = report.generate(self.library_root, "researcher", "2020-01-01", "2026-01-01",
                                    "rep2", include_citations=True, stale_days=180)
        md = (self.library_root / "reports/rep2/report.md").read_text()
        self.assertIn("| yes |", md)  # flagged stale


if __name__ == "__main__":
    unittest.main()
