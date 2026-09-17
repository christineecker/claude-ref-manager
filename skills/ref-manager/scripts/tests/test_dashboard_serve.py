#!/usr/bin/env python3
"""`/ref:dashboard serve` (LIBRARY_VIEWER_IMPLEMENTATION_PLAN.md §7.5).

Starts `dashboard.build_server()` on an ephemeral 127.0.0.1 port in a
background thread and drives it with `http.client`/`urllib.request`.

Run: python3 skills/ref-manager/scripts/tests/test_dashboard_serve.py
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import dashboard  # noqa: E402
import init_repo  # noqa: E402
import lib_atomic  # noqa: E402
import lib_inventory  # noqa: E402
import lint as lint_module  # noqa: E402
import list as list_cli  # noqa: E402, A004 -- same alias dashboard.py uses


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ServeFixture(unittest.TestCase):
    """One metadata-only paper and one PDF-backed paper, mirroring
    test_dashboard.py's fixture but scoped to what §7's routes need."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.library_root = self.tmp / "lib"
        for rel in init_repo.LIBRARY_DIRS:
            (self.library_root / rel).mkdir(parents=True, exist_ok=True)

        self._write_meta("11111", {"title": "Metadata only", "year": "2018", "journal": "Alpha Journal"})
        self._write_rich_paper("55555")

        self.httpd = dashboard.build_server(self.library_root, port=0)
        self.port = self.httpd.server_address[1]
        self.token = self.httpd.ref_token
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)
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
        (raw_dir / "response.json").write_text(json.dumps({"abstract": "The abstract.", "grants": []}))
        (pdir / "current.json").write_text(json.dumps({"version": "v1"}))
        (pdir / "notes.md").write_text(f"\n---\n{_now_iso()}\n\nFirst note.\n")
        return pdir

    # ---------------------------------------------------------------- http

    def _url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def _request(self, method, path, *, headers=None, body=None):
        headers = dict(headers or {})
        req = urllib.request.Request(self._url(path), method=method, data=body, headers=headers)
        try:
            resp = urllib.request.urlopen(req, timeout=5)
            return resp.status, resp.read(), dict(resp.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read(), dict(e.headers)

    def _auth_headers(self, extra=None):
        h = {"X-Ref-Token": self.token}
        h.update(extra or {})
        return h


class TestTokenChecks(ServeFixture):
    def test_rows_without_token_is_rejected(self):
        status, _body, _h = self._request("GET", "/api/rows")
        self.assertEqual(status, 403)

    def test_rows_with_wrong_token_is_rejected(self):
        status, _body, _h = self._request("GET", "/api/rows", headers={"X-Ref-Token": "wrong"})
        self.assertEqual(status, 403)

    def test_rows_with_correct_token_succeeds(self):
        status, body, _h = self._request("GET", "/api/rows", headers=self._auth_headers())
        self.assertEqual(status, 200)
        self.assertIsInstance(json.loads(body), list)

    def test_files_without_token_is_rejected(self):
        status, _body, _h = self._request("GET", "/files/55555/raw/hash1/source.pdf")
        self.assertEqual(status, 403)


class TestHostAndOriginChecks(ServeFixture):
    def test_get_with_wrong_host_is_rejected(self):
        status, _body, _h = self._request(
            "GET", "/api/rows", headers=dict(self._auth_headers(), Host="evil.example:1234")
        )
        self.assertEqual(status, 403)

    def test_get_with_correct_host_succeeds(self):
        status, _body, _h = self._request(
            "GET", "/api/rows", headers=dict(self._auth_headers(), Host=f"127.0.0.1:{self.port}")
        )
        self.assertEqual(status, 200)

    def test_get_with_localhost_host_succeeds(self):
        status, _body, _h = self._request(
            "GET", "/api/rows", headers=dict(self._auth_headers(), Host=f"localhost:{self.port}")
        )
        self.assertEqual(status, 200)

    def test_post_without_origin_is_rejected(self):
        body = json.dumps({"text": "hello"}).encode("utf-8")
        status, _body, _h = self._request(
            "POST", "/api/paper/55555/notes",
            headers=dict(self._auth_headers(), **{"Content-Type": "application/json"}),
            body=body,
        )
        self.assertEqual(status, 403)

    def test_post_with_wrong_origin_is_rejected(self):
        body = json.dumps({"text": "hello"}).encode("utf-8")
        status, _body, _h = self._request(
            "POST", "/api/paper/55555/notes",
            headers=dict(self._auth_headers(), Origin="http://evil.example", **{"Content-Type": "application/json"}),
            body=body,
        )
        self.assertEqual(status, 403)

    def test_post_with_correct_origin_succeeds(self):
        body = json.dumps({"text": "hello from origin test"}).encode("utf-8")
        status, resp_body, _h = self._request(
            "POST", "/api/paper/55555/notes",
            headers=dict(
                self._auth_headers(),
                Origin=f"http://127.0.0.1:{self.port}",
                **{"Content-Type": "application/json"},
            ),
            body=body,
        )
        self.assertEqual(status, 201, resp_body)


class TestFilesTraversal(ServeFixture):
    def test_dotdot_traversal_rejected(self):
        status, _body, _h = self._request(
            "GET", "/files/55555/raw/hash1/../../../../etc/passwd", headers=self._auth_headers()
        )
        self.assertIn(status, (400, 403, 404))

    def test_encoded_slash_rejected(self):
        # %2f is a smuggled slash trying to fake extra path segments.
        status, _body, _h = self._request(
            "GET", "/files/55555/raw%2fhash1%2fsource.pdf", headers=self._auth_headers()
        )
        self.assertIn(status, (400, 403, 404))

    def test_path_outside_allowlist_rejected(self):
        status, _body, _h = self._request(
            "GET", "/files/55555/meta.json", headers=self._auth_headers()
        )
        self.assertEqual(status, 403)

    def test_symlink_escape_rejected(self):
        outside = self.tmp / "secret.txt"
        outside.write_text("top secret")
        pdir = self.library_root / "papers" / "55555"
        link = pdir / "raw" / "hash1" / "escape.pdf"
        try:
            link.symlink_to(outside)
        except OSError:
            self.skipTest("symlinks unsupported in this environment")
        # doesn't match the allowlist regardless (must be named source.pdf)
        status, _body, _h = self._request(
            "GET", "/files/55555/raw/hash1/escape.pdf", headers=self._auth_headers()
        )
        self.assertIn(status, (403, 404))

        # even if it *did* match the allowlist name, a symlink pointing
        # outside papers/<pmid>/ must still be rejected by the resolve()
        # + startswith() check, not just the allowlist regex.
        link.unlink()
        link2 = pdir / "raw" / "hash1" / "source.pdf"
        link2.unlink()
        link2.symlink_to(outside)
        status2, _body2, _h2 = self._request(
            "GET", "/files/55555/raw/hash1/source.pdf", headers=self._auth_headers()
        )
        self.assertEqual(status2, 403)

    def test_allowed_pdf_is_served(self):
        status, body, headers = self._request(
            "GET", "/files/55555/raw/hash1/source.pdf", headers=self._auth_headers()
        )
        self.assertEqual(status, 200)
        self.assertEqual(body, b"%PDF-1.4 fake")

    def test_invalid_pmid_rejected(self):
        status, _body, _h = self._request(
            "GET", "/files/not-a-pmid/raw/hash1/source.pdf", headers=self._auth_headers()
        )
        self.assertEqual(status, 400)


class TestNotesPost(ServeFixture):
    def _post_note(self, pmid, payload, origin=None):
        body = json.dumps(payload).encode("utf-8")
        headers = dict(
            self._auth_headers(),
            Origin=origin or f"http://127.0.0.1:{self.port}",
            **{"Content-Type": "application/json"},
        )
        return self._request("POST", f"/api/paper/{pmid}/notes", headers=headers, body=body)

    def test_note_appends_exactly_one_entry_in_correct_format(self):
        notes_path = self.library_root / "papers" / "55555" / "notes.md"
        before = notes_path.read_text(encoding="utf-8")
        status, body, _h = self._post_note("55555", {"text": "a fresh observation"})
        self.assertEqual(status, 201, body)
        after = notes_path.read_text(encoding="utf-8")
        added = after[len(before):]
        # note.py's format: "\n---\n<iso stamp>\n\n<text>\n"
        self.assertRegex(added, r"^\n---\n[0-9T:\+\.\-]+\n\na fresh observation\n$")
        self.assertEqual(after.count("\n---\n"), before.count("\n---\n") + 1)

    def test_note_response_is_the_new_entry(self):
        status, body, _h = self._post_note("55555", {"text": "check response shape"})
        self.assertEqual(status, 201)
        entry = json.loads(body)
        self.assertIn("check response shape", entry["text"])
        self.assertIn("at", entry)

    def test_note_with_page_is_prefixed(self):
        status, body, _h = self._post_note("55555", {"text": "on this figure", "page": 3})
        self.assertEqual(status, 201, body)
        entry = json.loads(body)
        self.assertTrue(entry["text"].startswith("p. 3:"))

    def test_oversized_note_rejected(self):
        status, _body, _h = self._post_note("55555", {"text": "x" * (25 * 1024)})
        self.assertEqual(status, 413)

    def test_missing_pmid_dir_is_404(self):
        status, _body, _h = self._post_note("99999", {"text": "no such paper"})
        self.assertEqual(status, 404)

    def test_empty_text_rejected(self):
        status, _body, _h = self._post_note("55555", {"text": "   "})
        self.assertEqual(status, 400)

    def test_notes_append_holds_pmid_lock(self):
        """note.append() must hold pmid_lock() for the duration of the
        write -- verified by holding the lock ourselves first and checking
        the concurrent POST blocks until we release it."""
        results = []

        def do_post():
            results.append(self._post_note("55555", {"text": "while locked"}))

        with lib_atomic.pmid_lock(self.library_root, "55555"):
            t = threading.Thread(target=do_post)
            t.start()
            t.join(timeout=1)
            # the POST's handler thread should still be blocked waiting on
            # the lock we're holding -- it must not have completed yet.
            self.assertFalse(results, "note POST completed while pmid_lock was held externally")
        t.join(timeout=5)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][0], 201)


class TestRowsMatchesInventory(ServeFixture):
    def test_api_rows_equals_lib_inventory_rows(self):
        status, body, _h = self._request("GET", "/api/rows", headers=self._auth_headers())
        self.assertEqual(status, 200)
        api_rows = {r["pmid"]: r for r in json.loads(body)}
        real_rows = {r["pmid"]: r for r in lib_inventory.rows(self.library_root)}
        self.assertEqual(api_rows, real_rows)


class TestLintAndMatrixRoutes(ServeFixture):
    """§7 live-mode gap fix: /api/lint and /api/matrix, so --serve mode's
    Summary health/needs-attention list and Coverage tab aren't empty."""

    def test_lint_without_token_is_rejected(self):
        status, _body, _h = self._request("GET", "/api/lint")
        self.assertEqual(status, 403)

    def test_lint_matches_lint_module(self):
        status, body, _h = self._request("GET", "/api/lint", headers=self._auth_headers())
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), lint_module.lint(self.library_root))

    def test_lint_shape_has_summary_issues_recommendations(self):
        status, body, _h = self._request("GET", "/api/lint", headers=self._auth_headers())
        report = json.loads(body)
        self.assertIn("summary", report)
        self.assertIn("issues", report)
        self.assertIn("recommendations", report)

    def test_matrix_without_token_is_rejected(self):
        status, _body, _h = self._request("GET", "/api/matrix")
        self.assertEqual(status, 403)

    def test_matrix_matches_list_cli(self):
        status, body, _h = self._request("GET", "/api/matrix", headers=self._auth_headers())
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertEqual(payload["columns"], list(list_cli.MATRIX_COLUMNS))
        expected_rows = [list_cli._matrix_row(r) for r in lib_inventory.rows(self.library_root)]
        self.assertEqual(payload["rows"], expected_rows)

    def test_matrix_row_has_expected_columns(self):
        status, body, _h = self._request("GET", "/api/matrix", headers=self._auth_headers())
        payload = json.loads(body)
        row = next(r for r in payload["rows"] if r["pmid"] == "55555")
        for col in list_cli.MATRIX_COLUMNS:
            self.assertIn(col, row)


class TestPaperDetailAndSnapshots(ServeFixture):
    def test_paper_detail_matches_inventory(self):
        status, body, _h = self._request("GET", "/api/paper/55555", headers=self._auth_headers())
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), lib_inventory.detail(self.library_root, "55555"))

    def test_unknown_paper_is_404(self):
        status, _body, _h = self._request("GET", "/api/paper/99999", headers=self._auth_headers())
        self.assertEqual(status, 404)

    def test_snapshots_empty_when_no_maintenance_dir(self):
        status, body, _h = self._request("GET", "/api/snapshots", headers=self._auth_headers())
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), [])


class TestIndexAndAssetsServedWithoutToken(ServeFixture):
    def test_index_served_without_token(self):
        status, body, headers = self._request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b'"live": true', body)
        self.assertIn("text/html", headers.get("Content-Type", ""))

    def test_app_js_served_without_token(self):
        status, body, _h = self._request("GET", "/app.js")
        self.assertEqual(status, 200)
        self.assertIn(b"apiFetch", body)

    def test_insights_js_served_without_token(self):
        status, body, _h = self._request("GET", "/insights.js")
        self.assertEqual(status, 200)
        self.assertIn(b"window.RefDashInsights", body)

    def test_vendored_pdfjs_served(self):
        status, body, _h = self._request("GET", "/vendor/pdfjs/pdf.min.js")
        self.assertEqual(status, 200)
        self.assertGreater(len(body), 1000)



class TestTriageRoutes(ServeFixture):
    """PUBMED_TRIAGE_IMPLEMENTATION_PLAN.md §6.4 / §8 item 11."""

    PMIDS = ["30000001", "30000002", "30000003"]

    def setUp(self):
        super().setUp()
        import project
        import pubmed_query
        import triage

        self.triage = triage
        pubmed_query.new_run(self.library_root, "asd-ct", "autism", "pubmed", self.PMIDS, True)
        project.create(self.library_root, "proj-a", None)
        triage.init(self.library_root, "asd-ct")

        def fetcher(pmids):
            return [{"pmid": p, "title": f"T{p}", "abstract": "A.", "authors": [{"last": "Doe", "first": "J", "raw": "Doe J"}],
                     "journal": "J", "year": "2024", "doi": None, "pmcid": "PMC1" if p == "30000001" else None,
                     "grants": [], "publication_types": [], "mesh_terms": []} for p in pmids], []

        self.httpd.triage_fetcher = fetcher
        self.httpd.triage_pdf_fetcher = lambda root, pmid: {"pmid": pmid, "result": "attached" if pmid == "30000001" else "no_pmcid"}
        triage.load_batch(self.library_root, "asd-ct", 2, fetcher=fetcher)

    def _post(self, path, payload, *, origin=None, token=True):
        headers = {"Content-Type": "application/json", "Origin": origin or f"http://127.0.0.1:{self.port}"}
        if token:
            headers["X-Ref-Token"] = self.token
        return self._request("POST", path, headers=headers, body=json.dumps(payload).encode("utf-8"))

    def _get_json(self, path):
        status, body, _h = self._request("GET", path, headers=self._auth_headers())
        self.assertEqual(status, 200, body)
        return json.loads(body)

    def _wait_job(self, job_id):
        import time

        for _ in range(100):
            job = self._get_json(f"/api/jobs/{job_id}")
            if job["state"] != "running":
                return job
            time.sleep(0.05)
        self.fail("job did not finish")

    def test_list_and_view(self):
        self.assertEqual([t["slug"] for t in self._get_json("/api/triages")], ["asd-ct"])
        v = self._get_json("/api/triage/asd-ct")
        self.assertEqual((v["counts"]["found"], v["counts"]["loaded"], v["remaining"]), (3, 2, 1))
        self.assertEqual(v["projects"], ["proj-a"])

    def test_token_origin_and_validation(self):
        self.assertEqual(self._request("GET", "/api/triage/asd-ct")[0], 403)
        self.assertEqual(self._post("/api/triage/asd-ct/decisions", {"pmids": ["30000001"], "decision": "included"}, token=False)[0], 403)
        self.assertEqual(self._post("/api/triage/asd-ct/decisions", {"pmids": ["30000001"], "decision": "included"}, origin="http://evil.example")[0], 403)
        self.assertEqual(self._request("GET", "/api/triage/Bad_Slug", headers=self._auth_headers())[0], 400)
        self.assertEqual(self._request("GET", "/api/triage/nope", headers=self._auth_headers())[0], 404)
        self.assertEqual(self._post("/api/triage/asd-ct/decisions", {"pmids": ["abc"], "decision": "included"})[0], 400)
        self.assertEqual(self._post("/api/triage/asd-ct/decisions", {"pmids": ["30000001"], "decision": "maybe"})[0], 400)
        self.assertEqual(self._post("/api/triage/asd-ct/decisions", {"pmids": ["1"] * 501, "decision": "pending"})[0], 400)
        self.assertEqual(self._post("/api/triage/asd-ct/batch", {})[0], 400)
        self.assertEqual(self._post("/api/triage/asd-ct/jobs", {"kind": "delete", "pmids": ["30000001"]})[0], 400)
        self.assertEqual(self._post("/api/triage/asd-ct/project", {"project": "missing-project"})[0], 409)
        self.assertEqual(self._request("GET", "/api/jobs/zzz", headers=self._auth_headers())[0], 400)

    def test_decision_include_adds_paper(self):
        status, body, _h = self._post("/api/triage/asd-ct/decisions", {"pmids": ["30000001", "30000003"], "decision": "included"})
        self.assertEqual(status, 200)
        results = json.loads(body)["results"]
        self.assertEqual([r["result"] for r in results], ["recorded", "failed"])  # 30000003's metadata isn't loaded
        self.assertTrue((self.library_root / "papers" / "30000001" / "meta.json").exists())

    def test_project_link_replays(self):
        self._post("/api/triage/asd-ct/decisions", {"pmids": ["30000002"], "decision": "excluded"})
        status, body, _h = self._post("/api/triage/asd-ct/project", {"project": "proj-a"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["replayed"], 1)
        self.assertEqual(self._get_json("/api/triage/asd-ct")["triage"]["project"], "proj-a")

    def test_batch_job_loads_remaining(self):
        status, body, _h = self._post("/api/triage/asd-ct/batch", {"confirm": True})
        self.assertEqual(status, 202)
        job = self._wait_job(json.loads(body)["job_id"])
        self.assertEqual(job["state"], "done")
        self.assertEqual(job["outcome"]["loaded"], 1)
        self.assertEqual(self._get_json("/api/triage/asd-ct")["remaining"], 0)

    def test_pdf_job_and_full_text_queue(self):
        status, body, _h = self._post("/api/triage/asd-ct/jobs", {"kind": "pdf", "pmids": ["30000001", "30000002"]})
        self.assertEqual(status, 202)
        job = self._wait_job(json.loads(body)["job_id"])
        self.assertEqual([r["result"] for r in job["results"]], ["attached", "no_pmcid"])
        self.assertEqual(list(self.triage.pending(self.library_root, "asd-ct")), ["30000002"])

        status, body, _h = self._post("/api/triage/asd-ct/jobs", {"kind": "full_text", "pmids": ["30000001"]})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["results"][0]["result"], "queued")
        self.assertEqual(self._get_json("/api/triage/asd-ct")["counts"]["pending"], 2)

class TestHealthSummaryKnowledgeRoutes(ServeFixture):
    """DASHBOARD_IMPROVEMENTS_IMPLEMENTATION_PLAN.md §4 + FR-09..FR-17's payload."""

    def _get(self, path):
        status, body, _h = self._request("GET", path, headers=self._auth_headers())
        return status, json.loads(body)

    def test_new_routes_require_token(self):
        for path in ("/api/health", "/api/summary", "/api/knowledge"):
            self.assertEqual(self._request("GET", path)[0], 403, path)

    def test_health_reports_every_data_source(self):
        status, h = self._get("/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(h["ok"])
        self.assertIn(h["status"], ("ok", "degraded"))
        self.assertEqual(set(h["data_sources"]), {"rows", "lint", "matrix", "snapshots"})
        self.assertTrue(all(v == "ok" for v in h["data_sources"].values()))
        self.assertEqual(h["counts"]["rows"], 2)
        self.assertIsInstance(h["warnings"], list)
        self.assertEqual(h["library_root"], str(self.library_root))

    def test_health_degrades_per_source_without_failing(self):
        import dashboard_insights

        def boom():
            raise RuntimeError("lint exploded")

        body, status = dashboard_insights.health(self.library_root, {
            "rows": lambda: lib_inventory.rows(self.library_root), "lint": boom,
        })
        self.assertEqual(status, 200)
        self.assertFalse(body["ok"])
        self.assertEqual(body["status"], "degraded")
        self.assertIn("lint exploded", body["data_sources"]["lint"])

        body, status = dashboard_insights.health(self.library_root, {"rows": boom})
        self.assertEqual((status, body["status"]), (503, "down"))

    def test_summary_matches_inventory_and_lint(self):
        status, s = self._get("/api/summary")
        self.assertEqual(status, 200)
        report = lint_module.lint(self.library_root)
        self.assertEqual(s["paper_count"], 2)
        self.assertEqual(s["issues_total"], report["summary"]["issues_total"])
        self.assertEqual(sum(s["coverage"].values()), 2)
        buckets = {b["bucket"]: b["count"] for b in s["top_issue_buckets"]}
        self.assertEqual(buckets, {k: len(v) for k, v in report["issues"].items() if v})
        scores = [a["score"] for a in s["top_actions"]]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertTrue(s["top_actions"])
        for a in s["top_actions"]:
            self.assertIn("why", a)
            self.assertIn("suggested_command", a)
            self.assertNotIn("pmids", a)  # compact unless ?detail=pmids
        issue_types = {a["type"] for a in s["top_actions"]}
        self.assertTrue(issue_types <= set(report["issues"]) | {"catalog_stale"})

    def test_summary_detail_and_scopes(self):
        _status, s = self._get("/api/summary?detail=pmids")
        report = lint_module.lint(self.library_root)
        for a in s["top_actions"]:
            if a["type"] != "catalog_stale":
                self.assertTrue(set(a["pmids"]) <= set(report["issues"][a["type"]]))
        _status, by_issue = self._get("/api/summary?scope=issue")
        self.assertEqual(by_issue["issues"], {k: sorted(v) for k, v in report["issues"].items() if v})
        _status, by_project = self._get("/api/summary?scope=project")
        self.assertEqual(by_project["projects"], [])
        self.assertEqual(self._request("GET", "/api/summary?scope=nope", headers=self._auth_headers())[0], 400)

    def test_knowledge_payload(self):
        pdir = self.library_root / "papers" / "55555"
        (pdir / "claim_registry.json").write_text(json.dumps({"claims": {
            "c1": {"claim_id": "c1", "status": "active", "population": "adults", "intervention": "exercise",
                   "outcome": "mood", "direction": "increase", "evidence_tier": "full", "study_type": "rct"},
            "c2": {"claim_id": "c2", "status": "superseded", "outcome": "old"},
            "c3": {"claim_id": "c3", "status": "active", "outcome": "unknown", "direction": "not reported",
                   "excluded_from_synthesis": True},
        }}))
        (self.library_root / "graph").mkdir(exist_ok=True)
        (self.library_root / "graph" / "concepts.jsonl").write_text(json.dumps(
            {"concept_id": "exercise", "name": "Exercise", "aliases": ["physical activity"]}) + "\n")
        status, k = self._get("/api/knowledge")
        self.assertEqual(status, 200)
        self.assertEqual(set(k["papers"]), {"11111", "55555"})
        self.assertEqual(len(k["claims"]), 1)
        c = k["claims"][0]
        self.assertEqual((c["pmid"], c["intervention"], c["dir"], c["tier"]), ("55555", "exercise", "up", "full"))
        self.assertEqual(k["concepts"][0]["aliases"], ["physical activity"])
        self.assertEqual(k["papers"]["55555"]["notes_count"], 1)
        self.assertIn("timepoint", c)
        self.assertTrue(k["meta"]["cache_key"])

    def _relation(self, **overrides):
        rel = {"relation_id": "rel-1", "type": "potential_conflict", "subject_concept_id": "exercise",
               "object_concept_id": "mood", "supporting_claims": [{"pmid": "55555", "claim_id": "c1"}],
               "source_version_ids": [], "review_state": "unreviewed", "rationale": None, "stale": False}
        rel.update(overrides)
        (self.library_root / "graph").mkdir(exist_ok=True)
        (self.library_root / "graph" / "relations.jsonl").write_text(json.dumps(rel) + "\n")

    def test_knowledge_relation_fields(self):
        self._relation()
        _status, k = self._get("/api/knowledge")
        r = k["relations"][0]
        self.assertEqual((r["claim_ids"], r["pmids"], r["rationale"], r["reviewed_at"]), (["c1"], ["55555"], None, None))
        self.assertEqual(r["supporting"], [{"pmid": "55555", "claim_id": "c1"}])

    def test_knowledge_memo_refreshes_after_relation_review(self):
        import dashboard_insights

        self._relation()
        _s, first = self._get("/api/knowledge")
        _s, again = self._get("/api/knowledge")
        self.assertEqual(first["generated_at"], again["generated_at"])  # served from the memo
        self._relation(type="contradicts", review_state="reviewed", rationale="different follow-up",
                       reviewed_at="2026-09-17T10:00:00+00:00")
        _s, after = self._get("/api/knowledge")
        self.assertNotEqual(first["meta"]["cache_key"], after["meta"]["cache_key"])
        self.assertEqual((after["relations"][0]["type"], after["relations"][0]["rationale"]),
                         ("contradicts", "different follow-up"))
        _s, forced = self._get("/api/knowledge?refresh=1")
        self.assertNotEqual(after["generated_at"], forced["generated_at"])
        rows = lib_inventory.rows(self.library_root)
        self.assertEqual(dashboard_insights.knowledge_signature(self.library_root, rows), forced["meta"]["cache_key"])

    def _review_batch(self, *, project=None, grade=None):
        bdir = (self.library_root / "projects" / project / "reviews" / "b1") if project else (self.library_root / "reviews" / "b1")
        (bdir / "appraisals").mkdir(parents=True, exist_ok=True)
        (bdir / "manifest.json").write_text(json.dumps({"batch": "b1", "project": project, "pmids": ["55555", "11111"],
                                                         "resolved_at": "2026-09-17T00:00:00+00:00", "selector_expression": "x"}))
        (bdir / "grade.json").write_text(json.dumps(grade or {
            "baseline": "high", "baseline_reason": "study_types=['rct']", "downgrades_applied": 1, "certainty": "moderate",
            "factors": {"imprecision": {"downgrade": True, "not_assessed": False, "reason": "no intervals"}}}))
        (bdir / "appraisals" / "55555.json").write_text(json.dumps({"pmid": "55555", "checklist": "RoB2", "study_type": "rct", "domains": {
            "randomization": {"rating": "high", "claim_ids": ["c1"], "note": "", "review_status": "model_draft"},
            "outcome_measurement": {"rating": "insufficient_information", "claim_ids": [], "note": "", "review_status": "model_draft"}}}))
        (bdir / "appraisals" / "11111.json").write_text(json.dumps({"pmid": "11111", "checklist": None, "insufficient_information": True}))
        return bdir

    def test_knowledge_reviews_overlay(self):
        self._review_batch(project="proj")
        (self.library_root / "papers" / "55555" / "corrections.json").write_text(json.dumps([{
            "target_type": "appraisal", "target_id": "55555:RoB2:randomization", "decision": "accept"}]))
        _s, k = self._get("/api/knowledge")
        self.assertEqual(len(k["reviews"]), 1)
        rv = k["reviews"][0]
        self.assertEqual((rv["batch"], rv["project"], rv["grade"]["certainty"], rv["grade"]["downgrades_applied"]), ("b1", "proj", "moderate", 1))
        a = rv["appraisals"]["55555"]
        self.assertEqual((a["checklist"], a["assessed"], a["high_risk"]), ("RoB2", True, True))
        self.assertEqual(a["review_status"], {"human_confirmed": 1, "model_draft": 1})  # correction merged at read time
        b = rv["appraisals"]["11111"]
        self.assertEqual((b["insufficient_information"], b["assessed"], b["high_risk"]), (True, False, False))

    def test_knowledge_cache_key_tracks_reviews(self):
        import dashboard_insights

        rows = lib_inventory.rows(self.library_root)
        before = dashboard_insights.knowledge_signature(self.library_root, rows)
        bdir = self._review_batch()
        created = dashboard_insights.knowledge_signature(self.library_root, rows)
        (bdir / "grade.json").write_text(json.dumps({"certainty": "low", "factors": {}}))
        regraded = dashboard_insights.knowledge_signature(self.library_root, rows)
        (self.library_root / "papers" / "55555" / "corrections.json").write_text("[]")
        corrected = dashboard_insights.knowledge_signature(self.library_root, rows)
        self.assertEqual(len({before, created, regraded, corrected}), 4)

    def test_knowledge_cache_key_tracks_claims_and_concepts(self):
        import dashboard_insights

        rows = lib_inventory.rows(self.library_root)
        before = dashboard_insights.knowledge_signature(self.library_root, rows)
        (self.library_root / "graph").mkdir(exist_ok=True)
        (self.library_root / "graph" / "concepts.jsonl").write_text(json.dumps({"concept_id": "x", "name": "X"}) + "\n")
        mid = dashboard_insights.knowledge_signature(self.library_root, rows)
        (self.library_root / "papers" / "11111" / "claim_registry.json").write_text(json.dumps({"claims": {}}))
        after = dashboard_insights.knowledge_signature(self.library_root, rows)
        (self.library_root / "papers" / "11111" / "authorship.json").write_text(json.dumps({"authors": [{"last": "Smith"}]}))
        authors = dashboard_insights.knowledge_signature(self.library_root, rows)
        self.assertEqual(len({before, mid, after, authors}), 4)


class TestNextActionRanking(unittest.TestCase):
    def test_weights_and_project_scoping(self):
        import dashboard_insights

        rows = [{"pmid": str(i), "projects": [{"slug": "p"}] if i < 3 else []} for i in range(6)]
        report = {"summary": {"catalog_stale": True}, "issues": {
            "metadata_only": ["0", "1", "2", "3", "4", "5"],
            "missing_doi": ["0"],
        }}
        actions = dashboard_insights.next_actions(rows, report, include_pmids=True, limit=None)
        by_id = {a["id"]: a for a in actions}
        self.assertEqual(by_id["metadata_only"]["score"], 5 * 6 * 1.25)
        self.assertEqual(by_id["metadata_only@p"]["pmids"], ["0", "1", "2"])
        self.assertEqual(by_id["metadata_only@p"]["score"], 5 * 3 * 1.5)
        self.assertTrue(by_id["metadata_only@p"]["suggested_command"].startswith("/ref:fetch 0 1 2"))
        self.assertEqual(actions[0]["id"], "metadata_only")
        self.assertEqual([a["rank"] for a in actions], list(range(1, len(actions) + 1)))
        self.assertIn("catalog_stale", by_id)

    def test_same_papers_and_command_listed_once(self):
        import dashboard_insights

        rows = [{"pmid": "1", "projects": []}, {"pmid": "2", "projects": []}]
        actions = dashboard_insights.next_actions(rows, {"summary": {}, "issues": {
            "metadata_only": ["1", "2"], "missing_current": ["1", "2"]}})
        self.assertEqual(len(actions), 1)
        self.assertIn("also", actions[0]["why"])

    def test_single_project_bucket_is_not_listed_twice(self):
        import dashboard_insights

        rows = [{"pmid": "1", "projects": [{"slug": "p"}]}]
        actions = dashboard_insights.next_actions(rows, {"summary": {}, "issues": {"oa_pending": ["1"]}})
        self.assertEqual([a["id"] for a in actions], ["oa_pending@p"])

    def test_direction_classes(self):
        import dashboard_insights

        f = dashboard_insights.direction_class
        self.assertEqual([f("increase"), f("Decrease"), f("no significant difference"), f("not reported"), f("U-shaped")],
                         ["up", "down", "null", None, "other"])


class TestPdfUpload(ServeFixture):
    """FR-07/FR-08: POST /api/paper/<pmid>/pdf."""

    PDF = b"%PDF-1.4\n% dashboard upload test\n%%EOF\n"

    def _upload(self, pmid, data, *, query="", content_type="application/pdf", origin=True, token=True):
        headers = {"Content-Type": content_type, "X-Filename": "new%20version.pdf"}
        if token:
            headers["X-Ref-Token"] = self.token
        if origin:
            headers["Origin"] = f"http://127.0.0.1:{self.port}"
        return self._request("POST", f"/api/paper/{pmid}/pdf{query}", headers=headers, body=data)

    def test_security_and_validation(self):
        self.assertEqual(self._upload("11111", self.PDF, origin=False)[0], 403)
        self.assertEqual(self._upload("11111", self.PDF, token=False)[0], 403)
        self.assertEqual(self._upload("abc", self.PDF)[0], 400)
        self.assertEqual(self._upload("99999", self.PDF)[0], 404)
        self.assertEqual(self._upload("11111", self.PDF, content_type="text/plain")[0], 415)
        self.assertEqual(self._upload("11111", b"<html>not a pdf</html>")[0], 415)
        self.assertFalse((self.library_root / "papers" / "11111" / "raw").exists())

    def test_oversized_upload_rejected_before_reading(self):
        headers = {"Content-Type": "application/pdf", "X-Ref-Token": self.token,
                   "Origin": f"http://127.0.0.1:{self.port}", "Content-Length": str(dashboard.MAX_PDF_BYTES + 1)}
        import http.client

        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.putrequest("POST", "/api/paper/11111/pdf")
        for k, v in headers.items():
            conn.putheader(k, v)
        conn.endheaders()
        self.assertEqual(conn.getresponse().status, 413)
        conn.close()

    def test_identity_refusal_then_forced_attach(self):
        status, body, _h = self._upload("11111", self.PDF)
        self.assertEqual(status, 422, body)
        self.assertEqual(json.loads(body)["needs"], "force")
        status, body, _h = self._upload("11111", self.PDF, query="?force=1")
        self.assertEqual(status, 201, body)
        result = json.loads(body)
        self.assertEqual(result["result"], "attached")
        self.assertEqual(result["pdf_paths"], [f"raw/{result['sha256']}/source.pdf"])
        attachment = json.loads((self.library_root / "papers" / "11111" / "raw" / result["sha256"] / "attachment.json").read_text())
        self.assertEqual(attachment["attached_from"], "dashboard_upload:new version.pdf")
        status, body, _h = self._upload("11111", self.PDF, query="?force=1")
        self.assertEqual((status, json.loads(body)["result"]), (200, "duplicate_noop"))

    def test_replace_needs_confirmation_and_keeps_old_pdf(self):
        pdir = self.library_root / "papers" / "55555"
        before_current = (pdir / "current.json").read_text()
        status, body, _h = self._upload("55555", self.PDF, query="?force=1")
        self.assertEqual(status, 409)
        self.assertEqual(json.loads(body)["needs"], "replace")
        status, body, _h = self._upload("55555", self.PDF, query="?force=1&replace=1")
        self.assertEqual(status, 201, body)
        result = json.loads(body)
        self.assertTrue((pdir / "raw" / "hash1" / "source.pdf").exists())
        self.assertEqual(result["pdf_paths"][0], f"raw/{result['sha256']}/source.pdf")
        self.assertIn("raw/hash1/source.pdf", result["pdf_paths"])
        if result["conversion_status"] != "ok":
            self.assertIsNone(result["version"])
            self.assertEqual((pdir / "current.json").read_text(), before_current)
        row = {r["pmid"]: r for r in lib_inventory.rows(self.library_root)}["55555"]
        self.assertEqual(row["pdf_paths"][0], result["pdf_paths"][0])


class TestViewQuery(unittest.TestCase):
    def test_view_query_allowlist(self):
        self.assertEqual(dashboard.view_query("?tab=insights&q=autism&issue=oa_pending"),
                         "tab=insights&q=autism&issue=oa_pending")
        with self.assertRaises(ValueError):
            dashboard.view_query("q=x&token=secret")


if __name__ == "__main__":
    unittest.main()
