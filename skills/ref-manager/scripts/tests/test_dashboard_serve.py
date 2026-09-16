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

if __name__ == "__main__":
    unittest.main()
