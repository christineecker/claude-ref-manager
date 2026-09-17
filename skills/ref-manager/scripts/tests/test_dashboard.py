#!/usr/bin/env python3
"""`/ref:dashboard` static build (LIBRARY_VIEWER_IMPLEMENTATION_PLAN.md §6.3).

Run: python3 skills/ref-manager/scripts/tests/test_dashboard.py
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import dashboard  # noqa: E402
import init_repo  # noqa: E402
import lib_inventory  # noqa: E402


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class DashboardFixture(unittest.TestCase):
    """Same shape as test_inventory.py's/test_list.py's fixture: one paper
    per source state plus a rich pdf-backed paper with figures, claims,
    notes, and project membership, so the dashboard build exercises the
    real rows()/detail() output."""

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

    def _write_rich_paper(self, pmid: str, title: str = "Rich paper") -> Path:
        pdir = self._write_meta(pmid, {
            "title": title, "year": "2019", "journal": "Delta Journal",
            "abstract_available": True, "full_text": True, "extraction_tier": "full",
        })
        (pdir / "authorship.json").write_text(json.dumps({
            "authors": [{"first": "Ann", "last": "Author", "raw": "Author A"}],
        }))
        raw_dir = pdir / "raw" / "hash1"
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / "source.pdf").write_bytes(b"%PDF-1.4 fake")
        (raw_dir / "response.json").write_text(json.dumps({"abstract": "The abstract.", "grants": []}))

        (pdir / "current.json").write_text(json.dumps({"version": "v1"}))
        version_dir = pdir / "versions" / "v1"
        version_dir.mkdir(parents=True, exist_ok=True)
        (version_dir / "source.md").write_text("# Introduction\n\nBody text.\n")
        (version_dir / "figures.json").write_text(json.dumps([
            {"id": "f1", "label": "FIGURE 1", "caption": "cap1", "asset_available": True},
        ]))
        (pdir / "funding.json").write_text(json.dumps({
            "state": "explicit_acknowledgement_verified",
            "observations": [{"funder": "Some Fund", "fundref_id": "10.13039/123", "award_number": "AW1", "kind": "x"}],
        }))
        (pdir / "claim_registry.json").write_text(json.dumps({"claims": {
            "c1": {"locator": "Results/p1", "evidence_tier": "full", "status": "active",
                   "direction": "increase", "outcome": "score", "population": "adults",
                   "evidence_span": "quoted evidence"},
        }}))
        (pdir / "notes.md").write_text(f"\n---\n{_now_iso()}\n\nFirst note.\n")
        return pdir

    def _index_html(self) -> str:
        return (self.library_root / "reports" / "dashboard" / "index.html").read_text(encoding="utf-8")

    def _embedded_data(self) -> dict:
        html = self._index_html()
        m = re.search(
            r'<script id="dashboard-data" type="application/json">\s*(.*?)\s*</script>',
            html, re.S,
        )
        self.assertIsNotNone(m, "could not find embedded dashboard-data script tag")
        return json.loads(m.group(1))


class TestBuildProducesIndexAndDetails(DashboardFixture):
    def test_build_writes_index_and_per_paper_details(self):
        index_path = dashboard.build(self.library_root)
        self.assertTrue(index_path.exists())
        details_dir = self.library_root / "reports" / "dashboard" / "details"
        for pmid in ("11111", "22222", "55555"):
            self.assertTrue((details_dir / f"{pmid}.js").exists())
        self.assertEqual(sorted(p.stem for p in details_dir.glob("*.js")), ["11111", "22222", "55555"])

    def test_embedded_rows_round_trip_against_inventory(self):
        dashboard.build(self.library_root)
        data = self._embedded_data()
        embedded_by_pmid = {r["pmid"]: r for r in data["rows"]}
        real_rows = {r["pmid"]: r for r in lib_inventory.rows(self.library_root)}
        self.assertEqual(set(embedded_by_pmid), set(real_rows))
        for pmid, real in real_rows.items():
            self.assertEqual(embedded_by_pmid[pmid], real)

    def test_detail_file_round_trips_against_inventory(self):
        dashboard.build(self.library_root)
        detail_js = (self.library_root / "reports" / "dashboard" / "details" / "55555.js").read_text(encoding="utf-8")
        m = re.match(r'window\.__paperDetail\("55555",\s*(.*)\);\s*\Z', detail_js, re.S)
        self.assertIsNotNone(m)
        embedded_detail = json.loads(m.group(1))
        real_detail = lib_inventory.detail(self.library_root, "55555")
        self.assertEqual(embedded_detail, real_detail)

    def test_matrix_and_lint_embedded(self):
        dashboard.build(self.library_root)
        data = self._embedded_data()
        self.assertIn("lint", data)
        self.assertIn("issues", data["lint"])
        self.assertEqual(
            data["matrix_columns"],
            ["meta", "abstract", "fulltext", "pdf", "figures", "claims", "indexed", "retraction"],
        )
        self.assertEqual(len(data["matrix"]), 3)

    def test_projects_embedded(self):
        dashboard.build(self.library_root)
        data = self._embedded_data()
        self.assertEqual(len(data["projects"]), 1)
        self.assertEqual(data["projects"][0]["slug"], "proj-a")
        self.assertEqual([p["pmid"] for p in data["projects"][0]["papers"]], ["55555"])

    def test_app_js_and_css_copied(self):
        dashboard.build(self.library_root)
        out_dir = self.library_root / "reports" / "dashboard"
        self.assertTrue((out_dir / "app.js").exists())
        self.assertTrue((out_dir / "app.css").exists())


class TestRebuildIsAtomic(DashboardFixture):
    def test_rebuild_replaces_directory(self):
        dashboard.build(self.library_root)
        details_dir = self.library_root / "reports" / "dashboard" / "details"
        self.assertEqual(len(list(details_dir.glob("*.js"))), 3)

        # add a paper, rebuild -- the old dashboard's contents must be gone
        self._write_meta("99999", {"title": "New paper", "year": "2021", "journal": "New Journal"})
        dashboard.build(self.library_root)
        self.assertEqual(len(list(details_dir.glob("*.js"))), 4)
        self.assertTrue((details_dir / "99999.js").exists())

    def test_no_stray_staging_directories_left_behind(self):
        dashboard.build(self.library_root)
        dashboard.build(self.library_root)
        reports_dir = self.library_root / "reports"
        stray = [p for p in reports_dir.iterdir() if p.name.startswith(".dashboard-")]
        self.assertEqual(stray, [])

    def test_failed_build_leaves_previous_dashboard_untouched(self):
        dashboard.build(self.library_root)
        before = self._index_html()

        real_build_into = dashboard._build_into

        def _boom(staging, library_root):
            real_build_into(staging, library_root)
            raise RuntimeError("simulated failure partway through a rebuild")

        dashboard._build_into = _boom
        try:
            with self.assertRaises(RuntimeError):
                dashboard.build(self.library_root)
        finally:
            dashboard._build_into = real_build_into

        after = self._index_html()
        self.assertEqual(before, after)
        reports_dir = self.library_root / "reports"
        stray = [p for p in reports_dir.iterdir() if p.name.startswith(".dashboard-")]
        self.assertEqual(stray, [])


class TestHtmlEscaping(DashboardFixture):
    """§6.3: titles/abstracts containing `</script>` and `<img onerror>`
    must be neutralised -- embedded JSON has `</` escaped to `<\\/`, and
    app.js never inserts untrusted data via innerHTML (checked directly
    below since a headless browser isn't available in this test env)."""

    def setUp(self):
        super().setUp()
        pdir = self.library_root / "papers" / "55555"
        meta = json.loads((pdir / "meta.json").read_text())
        meta["title"] = 'Evil title </script><script>alert(1)</script>'
        (pdir / "meta.json").write_text(json.dumps(meta))
        response = json.loads((pdir / "raw" / "hash1" / "response.json").read_text())
        response["abstract"] = '<img src=x onerror="alert(1)">Abstract body'
        (pdir / "raw" / "hash1" / "response.json").write_text(json.dumps(response))

    def test_no_raw_closing_script_tag_in_index_html(self):
        dashboard.build(self.library_root)
        html = self._index_html()
        # the only literal "</script" occurrences must be the real tag
        # boundaries (app.js, dashboard-data closer) -- never one that
        # originated from a paper's title/abstract breaking out early.
        data = self._embedded_data()  # raises if the tag boundary was broken
        titles = [r["title"] for r in data["rows"] if r["pmid"] == "55555"]
        self.assertEqual(titles, ['Evil title </script><script>alert(1)</script>'])

    def test_embedded_json_has_escaped_closing_tags(self):
        dashboard.build(self.library_root)
        html = self._index_html()
        m = re.search(
            r'<script id="dashboard-data" type="application/json">\s*(.*?)\s*</script>',
            html, re.S,
        )
        raw_json_text = m.group(1)
        self.assertNotIn("</script>", raw_json_text)
        self.assertIn('<\\/script>', raw_json_text)

    def test_detail_js_round_trips_dangerous_strings(self):
        dashboard.build(self.library_root)
        detail_js = (self.library_root / "reports" / "dashboard" / "details" / "55555.js").read_text(encoding="utf-8")
        m = re.match(r'window\.__paperDetail\("55555",\s*(.*)\);\s*\Z', detail_js, re.S)
        embedded_detail = json.loads(m.group(1))
        self.assertIn("onerror", embedded_detail["abstract"])

    def test_app_js_never_uses_innerhtml(self):
        app_js = (SCRIPTS / "dashboard_assets" / "app.js").read_text(encoding="utf-8")
        self.assertNotIn("innerHTML", app_js)


class TestViewerUxWiring(DashboardFixture):
    """LIBRARY_VIEWER_IMPROVEMENT_IMPLEMENTATION_PLAN.md P0.5: baseline
    smoke coverage for the refresh/error-handling/keyboard/focus/paging/
    view-preset features added on top of the original dashboard. There is
    no headless browser in this test environment, so these are structural
    checks -- the markup and wiring a real browser would need are present
    and internally consistent -- rather than simulated clicks/keypresses.
    HTTP-level behavior (routes, status codes) is covered by
    test_dashboard_serve.py; JSON round-tripping is covered above."""

    def setUp(self):
        super().setUp()
        self.app_js = (SCRIPTS / "dashboard_assets" / "app.js").read_text(encoding="utf-8")
        self.index_html = (SCRIPTS / "dashboard_assets" / "index.html").read_text(encoding="utf-8")
        self.app_css = (SCRIPTS / "dashboard_assets" / "app.css").read_text(encoding="utf-8")

    # P0.1/P0.2 -- refresh re-fetches every live endpoint independently and
    # reports (rather than silently swallowing) a partial failure.
    def test_refresh_uses_allsettled_across_all_four_endpoints(self):
        self.assertIn("Promise.allSettled(REFRESH_ENDPOINTS", self.app_js)
        for path in ("/api/rows", "/api/snapshots", "/api/lint", "/api/matrix"):
            self.assertIn(path, self.app_js)

    def test_fetch_wrapper_checks_status_before_parsing(self):
        self.assertIn("function fetchJSON(path)", self.app_js)
        self.assertIn("if (!r.ok)", self.app_js)

    def test_error_banner_exists_and_is_wired(self):
        self.assertIn('id="errbanner"', self.index_html)
        self.assertIn("function showError(", self.app_js)
        self.assertIn("function clearError(", self.app_js)

    def test_active_tab_rerendered_after_refresh(self):
        self.assertIn("function rerenderActiveTab()", self.app_js)
        self.assertIn("rerenderActiveTab();", self.app_js)

    # P0.3 -- keyboard shortcuts.
    def test_keyboard_shortcuts_wired(self):
        self.assertIn('e.key === "/"', self.app_js)
        self.assertIn('e.key === "j" || e.key === "ArrowDown"', self.app_js)
        self.assertIn('e.key === "k" || e.key === "ArrowUp"', self.app_js)
        self.assertIn('e.key === "n"', self.app_js)
        self.assertIn('e.key === "p"', self.app_js)
        self.assertIn('e.key === "Escape"', self.app_js)

    # P0.4 -- drawer focus behavior.
    def test_drawer_focus_management_wired(self):
        self.assertIn("lastFocusedBeforeDrawer = document.activeElement", self.app_js)
        self.assertIn("function drawerFocusables()", self.app_js)
        self.assertIn('if (e.key !== "Tab") return;', self.app_js)
        self.assertIn("lastFocusedBeforeDrawer.focus()", self.app_js)

    # P1.1 -- saved views/presets, localStorage-only.
    def test_saved_views_persist_to_local_storage_only(self):
        for id_ in ("viewselect", "view-apply", "view-save", "view-rename", "view-delete"):
            self.assertIn('id="' + id_ + '"', self.index_html)
        self.assertIn('localStorage.setItem(VIEWS_KEY', self.app_js)
        self.assertNotIn("apiFetch(\"/api/views", self.app_js)  # never a server round-trip

    # P1.2 -- maintenance diff by paper.
    def test_maintenance_has_per_paper_diff(self):
        self.assertIn('id="changes-by-paper"', self.index_html)
        self.assertIn("byPmid[pmid].added.push(bucket)", self.app_js)

    # P1.3 -- project-focused mode.
    def test_project_panel_has_coverage_metrics_and_commands(self):
        self.assertIn("full text coverage", self.app_js)
        self.assertIn("claim extraction coverage", self.app_js)
        self.assertIn("View in Papers", self.app_js)

    # P1.4 -- expanded batch actions.
    def test_action_bar_has_fetch_pdf_and_audit_commands(self):
        for id_ in ("cmd-fetchpdf", "cmd-audit"):
            self.assertIn('id="' + id_ + '"', self.index_html)
        self.assertIn("function needsFetchPdf(row)", self.app_js)
        self.assertIn("function needsAudit(row)", self.app_js)

    # P2.1/P2.2 -- pagination for the papers table and coverage matrix.
    def test_table_and_matrix_are_paginated(self):
        self.assertIn("var PAGE_SIZE = 100;", self.app_js)
        self.assertIn("var MATRIX_PAGE_SIZE = 200;", self.app_js)
        self.assertIn('id="pager"', self.index_html)
        self.assertIn('id="matrix-pager"', self.index_html)

    # P2.3 -- mobile card layout.
    def test_mobile_card_layout_present(self):
        self.assertIn("@media (max-width:680px)", self.app_css)
        self.assertIn('"data-label"', self.app_js)

    # P2.4 -- accessibility.
    def test_accessibility_affordances_present(self):
        self.assertIn('aria-live="polite"', self.index_html)
        self.assertIn('wrap.setAttribute("aria-hidden", "true")', self.app_js)

    # Rows carry the fields the new client-side predicates need
    # (needsFetchPdf/needsAudit/project quick-commands) -- a schema
    # regression in lib_inventory.rows() would break those silently
    # in the browser with no test failure anywhere else.
    def test_rows_carry_fields_new_predicates_depend_on(self):
        dashboard.build(self.library_root)
        data = self._embedded_data()
        for row in data["rows"]:
            self.assertIn("has_pdf", row)
            self.assertIn("lint_flags", row)
            self.assertIn("stale_check", row)


class TestDashboardImprovementsWiring(DashboardFixture):
    """DASHBOARD_IMPROVEMENTS_IMPLEMENTATION_PLAN.md / DASHBOARD_FEATURE_REQUESTS.md:
    structural checks, same approach as TestViewerUxWiring (no headless browser)."""

    def setUp(self):
        super().setUp()
        self.app_js = (SCRIPTS / "dashboard_assets" / "app.js").read_text(encoding="utf-8")
        self.index_html = (SCRIPTS / "dashboard_assets" / "index.html").read_text(encoding="utf-8")

    def test_build_embeds_summary_and_knowledge(self):
        dashboard.build(self.library_root)
        data = self._embedded_data()
        self.assertEqual(data["summary"]["paper_count"], 3)
        self.assertTrue(all("pmids" in a for a in data["summary"]["top_actions"]))
        self.assertEqual(set(data["knowledge"]["papers"]), {"11111", "22222", "55555"})
        self.assertEqual(data["knowledge"]["claims"][0]["outcome"], "score")

    def test_shareable_url_state(self):  # FR-01
        for fn in ("function encodeViewState()", "function decodeViewState(", "function applyViewState(", "function syncUrl()"):
            self.assertIn(fn, self.app_js)
        self.assertIn("history.replaceState(null, \"\", location.pathname", self.app_js)
        for id_ in ("view-link", "view-cmd"):
            self.assertIn('id="' + id_ + '"', self.index_html)
        self.assertEqual(
            re.search(r"var VIEW_PARAM_KEYS = \[(.*?)\];", self.app_js).group(1).replace('"', "").replace(" ", "").split(","),
            list(dashboard.VIEW_PARAM_KEYS),
        )

    def test_bulk_export_and_commands(self):  # FR-02/FR-03
        for id_ in ("exp-pmids", "exp-csv", "copy-cmds", "selsummary"):
            self.assertIn('id="' + id_ + '"', self.index_html)
        for fn in ("function buildSelectedPMIDList()", "function buildSelectedCSV()", "function copyAllCommands()"):
            self.assertIn(fn, self.app_js)

    def test_next_actions_and_health(self):  # FR-04/FR-05/FR-06
        self.assertIn('id="next-actions"', self.index_html)
        self.assertIn('id="api-health"', self.index_html)
        self.assertIn("function renderNextActions()", self.app_js)
        self.assertIn('"/api/summary?detail=pmids"', self.app_js)
        self.assertIn('apiFetch("/api/health")', self.app_js)

    def test_pdf_upload_ui(self):  # FR-07/FR-08
        self.assertIn('"/pdf"', self.app_js)
        self.assertIn('body.needs === "replace"', self.app_js)
        self.assertIn('body.needs === "force"', self.app_js)
        self.assertIn("function pdfDropZone(row)", self.app_js)

    def test_triage_reason_chips_and_export(self):  # PUBMED_TRIAGE_IMPLEMENTATION_PLAN.md P3
        self.assertIn('id="t-reasons"', self.index_html)
        self.assertIn('id="t-export"', self.index_html)
        self.assertIn("function renderTriReasons(n)", self.app_js)
        self.assertIn("if (reason) body.reason = reason;", self.app_js)
        self.assertIn('"/ref:export-papers --triage "', self.app_js)

    def test_insight_views(self):  # FR-09..FR-17
        self.assertIn('id="tab-insights"', self.index_html)
        for fn in ("renderEvidenceMap", "renderGaps", "renderTimeline", "renderGraph", "renderClusters", "renderSynthesis"):
            self.assertIn("function " + fn + "(body, scope)", self.app_js)


class TestCli(DashboardFixture):
    def _run(self, *args):
        import subprocess

        script = SCRIPTS / "dashboard.py"
        return subprocess.run(
            [sys.executable, str(script), *args],
            capture_output=True, text=True,
        )

    def test_build_cli(self):
        proc = self._run("build", "--repo", str(self.library_root))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("dashboard written:", proc.stdout)
        self.assertTrue((self.library_root / "reports" / "dashboard" / "index.html").exists())

    def test_missing_repo_fails_loudly(self):
        proc = self._run("build", "--repo", str(self.tmp / "nope"))
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("error:", proc.stderr)


if __name__ == "__main__":
    unittest.main()
