#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""`/ref:dashboard` -- HTML dashboard over the paper library
(LIBRARY_VIEWER_IMPLEMENTATION_PLAN.md §6-§7). Two subcommands:

`build` (§6, static mode) renders `dashboard_assets/index.html` (template)
with the library's `rows()`, a lint report, the coverage matrix, and the
lint snapshot history inlined as one escaped JSON blob, plus one
`reports/dashboard/details/<pmid>.js` per paper
(`window.__paperDetail(pmid, detail())`), loaded on demand via
`<script src>` because file:// pages can't `fetch()` local files
(§6 rationale). `app.js`/`insights.js`/`app.css` are copied verbatim alongside
`index.html`. Build is atomic (`lib_atomic.py` conventions): render into
`reports/.dashboard-staging-<ts>/`, then swap it for `reports/dashboard/`
via two directory renames -- a failed build never touches the previous
dashboard, and a rebuild replaces it in one visible step.

`serve` (§7, the default `/ref:dashboard` mode) runs a `127.0.0.1`-only
`ThreadingHTTPServer` with a live JSON API, an in-page pdf.js viewer with
text-layer highlighting, and notes -- both write straight through
`note.py append()` / `highlight.py add()`/`remove()` (each holds
`pmid_lock()`). Both modes are read-only except those two write paths --
plus the PDF upload (`POST /api/paper/<pmid>/pdf`), which goes through
`attach.attach_pdf_bytes()` (the same commit path as `/ref:attach`) and the
"Add papers" intake (`POST /api/intake`, `POST /api/intake/pdf`), which goes
through `intake_pipeline.py` (add.py / attach.py / fetch.py commit paths) --
nothing else in this module or its handler ever writes to the library.

`/api/health`, `/api/summary` and `/api/knowledge` are read-only models
from `dashboard_insights.py` (DASHBOARD_IMPROVEMENTS_IMPLEMENTATION_PLAN.md
§3-§5, DASHBOARD_FEATURE_REQUESTS.md).
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import http.server
import json
import mimetypes
import os
import re
import secrets
import shutil
import sys
import threading
import urllib.parse
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

import attach as attach_module
import dashboard_insights
import highlight as highlight_module
import intake_pipeline
import lib_intake
import lib_inventory
import lint as lint_module
import list as list_cli  # noqa: A004 -- reuse the /ref:list coverage-matrix cell semantics (§6.1)
import note as note_module
import triage as triage_module
from lib_ids import SlugError, validate_slug
from lib_atomic import now_iso

ASSETS_DIR = Path(__file__).resolve().parent / "dashboard_assets"

# ---------------------------------------------------------------- serve (§7)

# `lib_ids.py` mints slugs/citekeys/opaque ids but has no PMID rule of its
# own -- the actual PMID shape check lives in `lib_intake.py` (used by
# `/ref:import` to classify a raw PMID string). Reused here rather than
# duplicated so a "valid pmid" means the same thing everywhere (§7.3).
_PMID_RE = lib_intake.PMID_RE

# §7.1's allowlist, exactly: raw/<hash>/source.pdf, reader/article.pdf,
# versions/<v>/figures/*. `<hash>`/`<v>`/the figure filename are each
# constrained to a single path segment (no "/") by `_decode_path_segments`
# below; the regexes below are a second, independent check on the shape of
# that segment (§7.3: "both checks, not just one").
_FILE_ALLOWLIST_PATTERNS = (
    re.compile(r"^raw/[^/]+/source\.pdf$"),
    re.compile(r"^reader/article\.pdf$"),
    re.compile(r"^versions/[^/]+/figures/[^/]+$"),
)

MAX_NOTE_TEXT_BYTES = 20 * 1024  # §7.3 "note text length cap (e.g. 20 KB)"
MAX_BODY_BYTES = 24 * 1024  # a little headroom over MAX_NOTE_TEXT_BYTES for the JSON envelope

MAX_HIGHLIGHT_TEXT_BYTES = 4 * 1024
MAX_HIGHLIGHT_NOTE_BYTES = 4 * 1024
MAX_HIGHLIGHT_RECTS = 60  # a multi-paragraph selection wraps many lines, one rect each
HIGHLIGHT_COLORS = ("yellow", "green", "red")

# PUBMED_TRIAGE_IMPLEMENTATION_PLAN.md §6.4
MAX_TRIAGE_BODY_BYTES = 64 * 1024
MAX_TRIAGE_PMIDS = 500
MAX_TRIAGE_REASON_BYTES = 500
MAX_TRIAGE_JOBS = 2
TRIAGE_JOB_KINDS = ("pdf", "full_text")

# DASHBOARD_IMPROVEMENTS_IMPLEMENTATION_PLAN.md §5 (drop-in PDF upload)
MAX_PDF_BYTES = 64 * 1024 * 1024
MAX_UPLOAD_NAME = 200

# "Add papers" intake panel: text items go through one background job,
# dropped PDFs one synchronous request each (intake_pipeline.py).
MAX_INTAKE_BODY_BYTES = 64 * 1024
MAX_INTAKE_ITEMS = 100

# Keys a shared view link may carry (§1); `serve --view` accepts only these.
VIEW_PARAM_KEYS = ("tab", "q", "project", "issue", "source", "missing", "sort", "insight", "center", "hops")


def _valid_pmid(pmid: str) -> bool:
    return bool(_PMID_RE.match(pmid))


def _host_allowed(headers, port: int) -> bool:
    """DNS-rebinding defense (§7.3): only our own loopback host:port."""
    host = headers.get("Host", "")
    return host in (f"127.0.0.1:{port}", f"localhost:{port}")


def _origin_allowed(headers, port: int) -> bool:
    origin = headers.get("Origin")
    if not origin:
        return False
    return origin in (f"http://127.0.0.1:{port}", f"http://localhost:{port}")


def _decode_path_segments(raw_path: str) -> list[str] | None:
    """Split a still-percent-encoded URL path on literal '/' separators and
    percent-decode each segment on its own. Returns None if decoding a
    segment reveals a '/' inside it -- an encoded slash (%2f/%2F) smuggled in
    to fake extra path structure past the allowlist check (§7.3, §7.5)."""
    segments = raw_path.split("/")
    out = []
    for seg in segments:
        decoded = urllib.parse.unquote(seg)
        if "/" in decoded:
            return None
        out.append(decoded)
    return out


class _DashboardHandler(http.server.BaseHTTPRequestHandler):
    """Set on a per-server subclass by `build_server()`: `library_root`
    (Path) and `token` (str, §7.3's per-run random token)."""

    library_root: Path
    token: str
    server_version = "RefDashboard/1.0"

    # -------------------------------------------------------------- helpers

    def _send_bytes(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, obj: object, status: int = 200) -> None:
        self._send_bytes(json.dumps(obj).encode("utf-8"), "application/json; charset=utf-8", status=status)

    def _reject(self, status: int, message: str) -> None:
        self._send_json({"error": message}, status=status)

    def _check_token(self) -> bool:
        """Required (as a header, never a query param) on every /api and
        /files request (§7.3). A GET of `/` itself needs no token -- the
        browser doesn't have it yet; it reads it from `location.search`
        (put there by the launch URL) before making its first API call."""
        supplied = self.headers.get("X-Ref-Token", "")
        if not supplied or not hmac.compare_digest(supplied, self.token):
            self._reject(403, "missing or invalid X-Ref-Token")
            return False
        return True

    # ------------------------------------------------------------------ GET

    def do_GET(self) -> None:  # noqa: N802 -- stdlib method name
        port = self.server.server_address[1]
        if not _host_allowed(self.headers, port):
            self._reject(403, "invalid Host header")
            return

        path = urllib.parse.urlsplit(self.path).path
        if path in ("/", "/index.html"):
            self._serve_index()
        elif path in ("/app.js", "/insights.js"):
            self._serve_static_file(ASSETS_DIR / path[1:], "application/javascript")
        elif path == "/app.css":
            self._serve_static_file(ASSETS_DIR / "app.css", "text/css")
        elif path == "/icon.svg":
            self._serve_static_file(ASSETS_DIR / "icon.svg", "image/svg+xml")
        elif path == "/vendor/pdfjs/pdf.min.js":
            self._serve_static_file(ASSETS_DIR / "vendor" / "pdfjs" / "pdf.min.js", "application/javascript")
        elif path == "/vendor/pdfjs/pdf.worker.min.js":
            self._serve_static_file(ASSETS_DIR / "vendor" / "pdfjs" / "pdf.worker.min.js", "application/javascript")
        elif path == "/vendor/pdf-lib/pdf-lib.min.js":
            self._serve_static_file(ASSETS_DIR / "vendor" / "pdf-lib" / "pdf-lib.min.js", "application/javascript")
        elif path == "/api/rows":
            if self._check_token():
                self._send_json(lib_inventory.rows(self.library_root))
        elif path == "/api/lint":
            if self._check_token():
                self._send_json(lint_module.lint(self.library_root))
        elif path == "/api/matrix":
            if self._check_token():
                self._serve_matrix()
        elif path == "/api/snapshots":
            if self._check_token():
                self._send_json(_read_snapshots(self.library_root))
        elif path == "/api/health":
            if self._check_token():
                self._serve_health()
        elif path == "/api/summary":
            if self._check_token():
                self._serve_summary()
        elif path == "/api/knowledge":
            if self._check_token():
                query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
                force = (query.get("refresh") or [""])[0] == "1"
                self._send_json(dashboard_insights.knowledge_cached(
                    self.library_root, lib_inventory.rows(self.library_root), force=force))
        elif path.startswith("/api/paper/") and path.endswith("/highlights"):
            if self._check_token():
                self._serve_highlights(path[len("/api/paper/"):-len("/highlights")].rstrip("/"))
        elif path.startswith("/api/paper/"):
            if self._check_token():
                self._serve_detail(path[len("/api/paper/"):])
        elif path.startswith("/files/"):
            if self._check_token():
                self._serve_file(path[len("/files/"):])
        elif path == "/api/triages":
            if self._check_token():
                self._send_json(triage_module.list_triages(self.library_root))
        elif path.startswith("/api/triage/"):
            if self._check_token():
                self._serve_triage(path[len("/api/triage/"):].rstrip("/"))
        elif path.startswith("/api/jobs/"):
            if self._check_token():
                self._serve_job(path[len("/api/jobs/"):].rstrip("/"))
        else:
            self._reject(404, "not found")

    def _serve_index(self) -> None:
        template = (ASSETS_DIR / "index.html").read_text(encoding="utf-8")
        data = {
            "live": True,
            "library_root": str(self.library_root),
            "generated_at": now_iso(),
        }
        rendered = template.replace("/*__DASHBOARD_DATA__*/", _escape_for_script_tag(data))
        self._send_bytes(rendered.encode("utf-8"), "text/html; charset=utf-8")

    def _serve_static_file(self, path: Path, content_type: str) -> None:
        try:
            body = path.read_bytes()
        except OSError:
            self._reject(404, "not found")
            return
        self._send_bytes(body, content_type)

    def _serve_matrix(self) -> None:
        """`/api/matrix`: the coverage matrix, the same cells the static build inlines."""
        self._send_json(_matrix(lib_inventory.rows(self.library_root)))

    def _serve_health(self) -> None:
        root = self.library_root
        cache: dict = {}

        def rows():
            cache["rows"] = lib_inventory.rows(root)
            return cache["rows"]

        body, status = dashboard_insights.health(root, {
            "rows": rows,  # health() runs loaders in this order, so matrix() sees the cached rows
            "lint": lambda: lint_module.lint(root),
            "matrix": lambda: _matrix(cache.get("rows") or lib_inventory.rows(root)),
            "snapshots": lambda: _read_snapshots(root),
        })
        self._send_json(body, status=status)

    def _serve_summary(self) -> None:
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        include_pmids = (query.get("detail") or [None])[0] == "pmids"
        rows = lib_inventory.rows(self.library_root)
        sources = {"rows": "ok", "lint": "ok", "snapshots": "ok"}
        try:
            report = lint_module.lint(self.library_root)
        except Exception as e:  # noqa: BLE001 -- degrade, don't fail the summary
            report = {"summary": {}, "issues": {}}
            sources["lint"] = f"error: {type(e).__name__}: {e}"
        try:
            snapshots = _read_snapshots(self.library_root)
        except Exception as e:  # noqa: BLE001
            snapshots = []
            sources["snapshots"] = f"error: {type(e).__name__}: {e}"
        self._send_json(dashboard_insights.summary(
            rows, report, snapshots, include_pmids=include_pmids, data_sources=sources,
        ))

    def _serve_detail(self, raw_pmid: str) -> None:
        pmid = urllib.parse.unquote(raw_pmid.rstrip("/"))
        if not _valid_pmid(pmid):
            self._reject(400, "invalid pmid")
            return
        try:
            detail = lib_inventory.detail(self.library_root, pmid)
        except FileNotFoundError:
            self._reject(404, "pmid not found")
            return
        self._send_json(detail)

    def _serve_highlights(self, raw_pmid: str) -> None:
        pmid = urllib.parse.unquote(raw_pmid)
        if not _valid_pmid(pmid):
            self._reject(400, "invalid pmid")
            return
        if not (self.library_root / "papers" / pmid).is_dir():
            self._reject(404, "pmid not found")
            return
        self._send_json(highlight_module.load(self.library_root, pmid))

    def _serve_file(self, raw_rel: str) -> None:
        segments = _decode_path_segments(raw_rel)
        if not segments or len(segments) < 2 or not all(segments):
            self._reject(400, "invalid path")
            return
        pmid, *rest = segments
        if not _valid_pmid(pmid):
            self._reject(400, "invalid pmid")
            return
        rel_path = "/".join(rest)
        if not any(p.match(rel_path) for p in _FILE_ALLOWLIST_PATTERNS):
            self._reject(403, "path not allowed")
            return

        papers_dir = self.library_root / "papers" / pmid
        candidate = papers_dir / rel_path
        try:
            resolved = candidate.resolve(strict=True)
            base = papers_dir.resolve(strict=True)
        except OSError:
            self._reject(404, "not found")
            return
        if resolved == base or not str(resolved).startswith(str(base) + os.sep):
            self._reject(403, "path escapes the paper directory")
            return
        if not resolved.is_file():
            self._reject(404, "not found")
            return

        content_type = mimetypes.guess_type(str(resolved))[0] or "application/octet-stream"
        try:
            body = resolved.read_bytes()
        except OSError:
            self._reject(404, "not found")
            return
        self._send_bytes(body, content_type)

    # ----------------------------------------------------------------- POST

    def _read_json_body(self, max_bytes: int) -> object | None:
        """Returns the parsed JSON body, or None after sending an error
        response (Content-Length missing/oversized, or invalid JSON)."""
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self._reject(411, "Content-Length required")
            return None
        if length < 0 or length > max_bytes:
            self._reject(413, "request body too large")
            return None
        raw_body = self.rfile.read(length)
        try:
            return json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            self._reject(400, "invalid JSON body")
            return None

    def do_POST(self) -> None:  # noqa: N802 -- stdlib method name
        port = self.server.server_address[1]
        if not _host_allowed(self.headers, port):
            self._reject(403, "invalid Host header")
            return
        if not _origin_allowed(self.headers, port):
            self._reject(403, "invalid or missing Origin header")
            return

        path = urllib.parse.urlsplit(self.path).path
        if path.startswith("/api/paper/") and path.endswith("/notes"):
            if self._check_token():
                self._post_note(path[len("/api/paper/"):-len("/notes")].rstrip("/"))
        elif path.startswith("/api/paper/") and path.endswith("/highlights"):
            if self._check_token():
                self._post_highlight(path[len("/api/paper/"):-len("/highlights")].rstrip("/"))
        elif path.startswith("/api/paper/") and path.endswith("/pdf"):
            if self._check_token():
                self._post_pdf(path[len("/api/paper/"):-len("/pdf")].rstrip("/"))
        elif path.startswith("/api/triage/"):
            if self._check_token():
                self._post_triage(path[len("/api/triage/"):].rstrip("/"))
        elif path == "/api/intake":
            if self._check_token():
                self._post_intake()
        elif path == "/api/intake/pdf":
            if self._check_token():
                self._post_intake_pdf()
        else:
            self._reject(404, "not found")

    # --------------------------------------------------------------- intake

    def _post_intake(self) -> None:
        """`{items: [str], fulltext: bool}` -> 202 `{job_id}`; poll /api/jobs/<id>.
        Each item's result lands in the job's `results` as it finishes."""
        payload = self._read_json_body(MAX_INTAKE_BODY_BYTES)
        if payload is None:
            return
        if not isinstance(payload, dict):
            self._reject(400, "body must be an object")
            return
        items = payload.get("items")
        if not isinstance(items, list) or not items or len(items) > MAX_INTAKE_ITEMS:
            self._reject(400, f"items must be a non-empty list of at most {MAX_INTAKE_ITEMS} strings")
            return
        if not all(isinstance(i, str) and i.strip() and len(i) <= 2000 for i in items):
            self._reject(400, "every item must be a non-empty string")
            return
        fulltext = payload.get("fulltext", True) is not False
        root = self.library_root
        fetcher = self.server.intake_fetcher  # type: ignore[attr-defined]
        resolver = self.server.intake_resolver  # type: ignore[attr-defined]
        pdf_fetcher = self.server.intake_pdf_fetcher  # type: ignore[attr-defined]
        jats_fetcher = self.server.intake_jats_fetcher  # type: ignore[attr-defined]
        cleaned = list(dict.fromkeys(i.strip() for i in items))

        def work(progress):
            for raw in cleaned:
                try:
                    res = intake_pipeline.intake_text(root, raw, fulltext=fulltext, fetcher=fetcher,
                                                      resolver=resolver, pdf_fetcher=pdf_fetcher,
                                                      jats_fetcher=jats_fetcher)
                except Exception as e:  # noqa: BLE001 -- one bad item must not sink the batch
                    res = {"input": raw, "status": "failed", "steps": [], "error": str(e)}
                progress(res)

        self._start_job("intake:" + secrets.token_hex(4), "intake", len(cleaned), work)

    def _post_intake_pdf(self) -> None:
        """Raw application/pdf body (+ X-Filename) -> intake_pipeline.intake_pdf.
        `?pmid=` answers a `needs_pmid` result, `?replace=1` / `?force=1` the
        `needs_replace` / `needs_force` ones."""
        content_type = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if content_type != "application/pdf":
            self._reject(415, "Content-Type must be application/pdf")
            return
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self._reject(411, "Content-Length required")
            return
        if length <= 0:
            self._reject(400, "empty upload")
            return
        if length > MAX_PDF_BYTES:
            self._reject(413, f"PDF larger than {MAX_PDF_BYTES // (1024 * 1024)} MB")
            return
        data = self.rfile.read(length)
        if len(data) != length or not data.startswith(b"%PDF-"):
            self._reject(415, "not a PDF file (missing %PDF- header)")
            return
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        pmid = (query.get("pmid") or [""])[0].strip()
        if pmid and not _valid_pmid(pmid):
            self._reject(400, "invalid pmid")
            return
        replace = (query.get("replace") or [""])[0] == "1"
        force = (query.get("force") or [""])[0] == "1"
        name = urllib.parse.unquote(self.headers.get("X-Filename") or "")
        name = re.sub(r"[\x00-\x1f/\\]", "_", name).strip()[:MAX_UPLOAD_NAME] or "upload.pdf"
        try:
            res = intake_pipeline.intake_pdf(
                self.library_root, data, name, pmid_override=pmid or None, replace=replace, force=force,
                fetcher=self.server.intake_fetcher,  # type: ignore[attr-defined]
                resolver=self.server.intake_resolver,  # type: ignore[attr-defined]
            )
        except Exception as e:  # noqa: BLE001 -- surfaced to the page, never kills the server
            self._send_json({"input": name, "kind": "pdf", "status": "failed", "steps": [], "error": str(e)}, status=500)
            return
        self._send_json(res, status=200 if res["status"] in ("done", "exists") else 422)

    def do_DELETE(self) -> None:  # noqa: N802 -- stdlib method name
        port = self.server.server_address[1]
        if not _host_allowed(self.headers, port):
            self._reject(403, "invalid Host header")
            return
        if not _origin_allowed(self.headers, port):
            self._reject(403, "invalid or missing Origin header")
            return

        path = urllib.parse.urlsplit(self.path).path
        prefix = "/api/paper/"
        segments = path[len(prefix):].split("/") if path.startswith(prefix) else []
        # <pmid>/highlights/<id>, nothing else is deletable.
        if len(segments) != 3 or segments[1] != "highlights" or not segments[0] or not segments[2]:
            self._reject(404, "not found")
            return
        if not self._check_token():
            return
        self._delete_highlight(urllib.parse.unquote(segments[0]), urllib.parse.unquote(segments[2]))

    def _post_note(self, raw_pmid: str) -> None:
        pmid = urllib.parse.unquote(raw_pmid)
        if not _valid_pmid(pmid):
            self._reject(400, "invalid pmid")
            return

        payload = self._read_json_body(MAX_BODY_BYTES)
        if payload is None:
            return
        if not isinstance(payload, dict) or not isinstance(payload.get("text"), str):
            self._reject(400, "body must be {text: str, page?: int}")
            return
        text = payload["text"]
        if not text.strip():
            self._reject(400, "text must not be empty")
            return
        if len(text.encode("utf-8")) > MAX_NOTE_TEXT_BYTES:
            self._reject(413, "note text too long")
            return
        page = payload.get("page")
        if page is not None and (isinstance(page, bool) or not isinstance(page, int)):
            self._reject(400, "page must be an integer")
            return

        final_text = f"p. {page}: {text}" if page is not None else text

        try:
            note_module.append(self.library_root, pmid, final_text)
        except FileNotFoundError:
            self._reject(404, "pmid not found")
            return

        detail = lib_inventory.detail(self.library_root, pmid)
        entry = detail["notes"][-1] if detail.get("notes") else {"at": None, "text": final_text}
        self._send_json(entry, status=201)

    def _post_highlight(self, raw_pmid: str) -> None:
        pmid = urllib.parse.unquote(raw_pmid)
        if not _valid_pmid(pmid):
            self._reject(400, "invalid pmid")
            return

        payload = self._read_json_body(MAX_BODY_BYTES)
        if payload is None:
            return
        if not isinstance(payload, dict):
            self._reject(400, "body must be an object")
            return

        page = payload.get("page")
        if isinstance(page, bool) or not isinstance(page, int) or page < 1:
            self._reject(400, "page must be a positive integer")
            return

        text = payload.get("text")
        if not isinstance(text, str) or not text.strip():
            self._reject(400, "text must be a non-empty string")
            return
        if len(text.encode("utf-8")) > MAX_HIGHLIGHT_TEXT_BYTES:
            self._reject(413, "highlight text too long")
            return

        color = payload.get("color")
        if color not in HIGHLIGHT_COLORS:
            self._reject(400, f"color must be one of {HIGHLIGHT_COLORS}")
            return

        rects = payload.get("rects")
        if not isinstance(rects, list) or not rects or len(rects) > MAX_HIGHLIGHT_RECTS:
            self._reject(400, f"rects must be a non-empty list of at most {MAX_HIGHLIGHT_RECTS} boxes")
            return
        clean_rects = []
        for r in rects:
            if not isinstance(r, dict) or set(r) != {"x", "y", "w", "h"}:
                self._reject(400, "each rect must be {x, y, w, h}")
                return
            values = {}
            for k, v in r.items():
                if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0:
                    self._reject(400, "rect coordinates must be non-negative numbers")
                    return
                values[k] = float(v)
            clean_rects.append(values)

        note = payload.get("note")
        if note is not None:
            if not isinstance(note, str):
                self._reject(400, "note must be a string")
                return
            if len(note.encode("utf-8")) > MAX_HIGHLIGHT_NOTE_BYTES:
                self._reject(413, "highlight note too long")
                return
            note = note.strip() or None

        try:
            entry = highlight_module.add(
                self.library_root, pmid, page=page, rects=clean_rects, text=text.strip(), color=color, note=note,
            )
        except FileNotFoundError:
            self._reject(404, "pmid not found")
            return
        self._send_json(entry, status=201)

    def _post_pdf(self, raw_pmid: str) -> None:
        """Drop-in PDF attach/replace (§5, FR-07/FR-08). Raw `application/pdf`
        body; `?replace=1` is required when the paper already has a PDF (the
        old one is kept -- raw/<sha256>/ is content-addressed), `?force=1`
        accepts a PDF whose DOI/title identity check failed. Conversion
        failures never repoint current.json (`commit_failed_conversion`)."""
        pmid = urllib.parse.unquote(raw_pmid)
        if not _valid_pmid(pmid):
            self._reject(400, "invalid pmid")
            return
        paper_dir = self.library_root / "papers" / pmid
        if not (paper_dir / "meta.json").is_file():
            self._reject(404, "pmid not found")
            return
        content_type = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if content_type != "application/pdf":
            self._reject(415, "Content-Type must be application/pdf")
            return
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self._reject(411, "Content-Length required")
            return
        if length <= 0:
            self._reject(400, "empty upload")
            return
        if length > MAX_PDF_BYTES:
            self._reject(413, f"PDF larger than {MAX_PDF_BYTES // (1024 * 1024)} MB")
            return
        data = self.rfile.read(length)
        if len(data) != length or not data.startswith(b"%PDF-"):
            self._reject(415, "not a PDF file (missing %PDF- header)")
            return

        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        replace = (query.get("replace") or [""])[0] == "1"
        force = (query.get("force") or [""])[0] == "1"
        name = urllib.parse.unquote(self.headers.get("X-Filename") or "")
        name = re.sub(r"[\x00-\x1f/\\]", "_", name).strip()[:MAX_UPLOAD_NAME] or "upload.pdf"

        sha = hashlib.sha256(data).hexdigest()
        if (paper_dir / "raw" / sha / "source.pdf").exists():
            self._send_json({"pmid": pmid, "result": "duplicate_noop", "sha256": sha})
            return
        if lib_inventory._pdf_paths(paper_dir) and not replace:
            self._send_json({"error": "this paper already has a PDF -- confirm to add this one as the new active PDF",
                             "needs": "replace"}, status=409)
            return
        try:
            result = attach_module.attach_pdf_bytes(
                self.library_root, pmid, data, f"dashboard_upload:{name}", force, commit_failed_conversion=False,
            )
        except ValueError as e:
            self._reject(404, str(e))
            return
        if result["result"] == "refused":
            self._send_json({"error": result["reason"], "needs": "force", "sha256": result["sha256"]}, status=422)
            return
        result["pdf_paths"] = lib_inventory._pdf_paths(paper_dir)
        self._send_json(result, status=201)

    def _delete_highlight(self, pmid: str, highlight_id: str) -> None:
        if not _valid_pmid(pmid):
            self._reject(400, "invalid pmid")
            return
        if not re.fullmatch(r"[0-9a-f]{1,64}", highlight_id):
            self._reject(400, "invalid highlight id")
            return
        if highlight_module.remove(self.library_root, pmid, highlight_id):
            self._send_bytes(b"", "application/json", status=204)
        else:
            self._reject(404, "highlight not found")

    # --------------------------------------------------------------- triage

    def _triage_slug(self, raw: str) -> str | None:
        """Validates the slug and that its triage exists; sends the error
        response itself and returns None otherwise."""
        slug = urllib.parse.unquote(raw)
        try:
            validate_slug(slug)
        except SlugError:
            self._reject(400, "invalid triage slug")
            return None
        if not triage_module.exists(self.library_root, slug):
            self._reject(404, "triage not found")
            return None
        return slug

    def _serve_triage(self, rest: str) -> None:
        if "/" in rest or not rest:
            self._reject(404, "not found")
            return
        slug = self._triage_slug(rest)
        if slug is None:
            return
        try:
            payload = triage_module.view(self.library_root, slug)
        except triage_module.TriageError as e:
            self._reject(409, str(e))
            return
        projects_dir = self.library_root / "projects"
        payload["projects"] = sorted(
            d.name for d in projects_dir.iterdir() if (d / "project.yaml").is_file()
        ) if projects_dir.is_dir() else []
        self._send_json(payload)

    def _serve_job(self, job_id: str) -> None:
        if not re.fullmatch(r"[0-9a-f]{16}", job_id):
            self._reject(400, "invalid job id")
            return
        registry = self.server.triage_jobs  # type: ignore[attr-defined]
        with registry["lock"]:
            job = registry["jobs"].get(job_id)
            snapshot = json.loads(json.dumps(job)) if job else None
        if snapshot is None:
            self._reject(404, "job not found")
            return
        self._send_json(snapshot)

    def _payload_pmids(self, payload: dict) -> list[str] | None:
        pmids = payload.get("pmids")
        if not isinstance(pmids, list) or not pmids or len(pmids) > MAX_TRIAGE_PMIDS:
            self._reject(400, f"pmids must be a non-empty list of at most {MAX_TRIAGE_PMIDS}")
            return None
        if not all(isinstance(p, str) and _valid_pmid(p) for p in pmids):
            self._reject(400, "invalid pmid in pmids")
            return None
        return list(dict.fromkeys(pmids))

    def _post_triage(self, rest: str) -> None:
        parts = rest.split("/")
        if len(parts) != 2 or parts[1] not in ("decisions", "project", "batch", "jobs"):
            self._reject(404, "not found")
            return
        slug = self._triage_slug(parts[0])
        if slug is None:
            return
        payload = self._read_json_body(MAX_TRIAGE_BODY_BYTES)
        if payload is None:
            return
        if not isinstance(payload, dict):
            self._reject(400, "body must be an object")
            return
        action = parts[1]
        try:
            if action == "decisions":
                self._post_triage_decisions(slug, payload)
            elif action == "project":
                self._post_triage_project(slug, payload)
            elif action == "batch":
                self._post_triage_batch(slug, payload)
            else:
                self._post_triage_job(slug, payload)
        except (triage_module.TriageError, SlugError) as e:
            self._reject(409, str(e))

    def _post_triage_decisions(self, slug: str, payload: dict) -> None:
        pmids = self._payload_pmids(payload)
        if pmids is None:
            return
        decision = payload.get("decision")
        if decision not in triage_module.DECISIONS:
            self._reject(400, f"decision must be one of {triage_module.DECISIONS}")
            return
        reason = payload.get("reason")
        if reason is not None and (not isinstance(reason, str) or len(reason.encode("utf-8")) > MAX_TRIAGE_REASON_BYTES):
            self._reject(400, f"reason must be a string of at most {MAX_TRIAGE_REASON_BYTES} bytes")
            return
        results = triage_module.decide(self.library_root, slug, pmids, decision, reason, origin="dashboard")
        self._send_json({"results": results})

    def _post_triage_project(self, slug: str, payload: dict) -> None:
        project = payload.get("project")
        if project is not None and not isinstance(project, str):
            self._reject(400, "project must be a slug or null")
            return
        if project:
            try:
                validate_slug(project)
            except SlugError:
                self._reject(400, "invalid project slug")
                return
        self._send_json(triage_module.link(self.library_root, slug, project or None))

    def _start_job(self, slug: str, kind: str, total: int, work) -> None:
        registry = self.server.triage_jobs  # type: ignore[attr-defined]
        with registry["lock"]:
            running = [j for j in registry["jobs"].values() if j["state"] == "running"]
            if any(j["slug"] == slug and j["kind"] == kind for j in running):
                self._reject(409, f"a {kind} job for this triage is already running")
                return
            if len(running) >= MAX_TRIAGE_JOBS:
                self._reject(429, "too many jobs running -- try again when one finishes")
                return
            job_id = secrets.token_hex(8)
            job = {"id": job_id, "slug": slug, "kind": kind, "state": "running",
                   "total": total, "done": 0, "results": [], "error": None,
                   "started_at": now_iso()}
            registry["jobs"][job_id] = job

        def progress(result: dict) -> None:
            with registry["lock"]:
                job["results"].append(result)
                job["done"] = len(job["results"])

        def run() -> None:
            try:
                outcome = work(progress)
                with registry["lock"]:
                    if isinstance(outcome, dict):
                        job["outcome"] = outcome
                    job["state"] = "done"
            except Exception as e:  # noqa: BLE001 -- surfaced to the page, never kills the server
                with registry["lock"]:
                    job["state"] = "failed"
                    job["error"] = str(e)

        threading.Thread(target=run, daemon=True, name=f"triage-{kind}-{job_id}").start()
        self._send_json({"job_id": job_id}, status=202)

    def _post_triage_batch(self, slug: str, payload: dict) -> None:
        if payload.get("confirm") is not True:
            self._reject(400, "loading a batch needs {confirm: true}")
            return
        size = payload.get("size", triage_module.BATCH_SIZE)
        if isinstance(size, bool) or not isinstance(size, int) or not 1 <= size <= triage_module.BATCH_SIZE:
            self._reject(400, f"size must be an integer between 1 and {triage_module.BATCH_SIZE}")
            return
        root = self.library_root
        fetcher = self.server.triage_fetcher  # type: ignore[attr-defined]

        def work(progress):
            return triage_module.load_batch(root, slug, size, fetcher=fetcher)

        self._start_job(slug, "batch", size, work)

    def _post_triage_job(self, slug: str, payload: dict) -> None:
        kind = payload.get("kind")
        if kind not in TRIAGE_JOB_KINDS:
            self._reject(400, f"kind must be one of {TRIAGE_JOB_KINDS}")
            return
        pmids = self._payload_pmids(payload)
        if pmids is None:
            return
        root = self.library_root
        if kind == "full_text":
            # Only queues work for Claude -- nothing slow, so no job.
            self._send_json({"results": triage_module.queue_full_text(root, slug, pmids)})
            return
        pdf_fetcher = self.server.triage_pdf_fetcher  # type: ignore[attr-defined]

        def work(progress):
            triage_module.acquire_pdfs(root, slug, pmids, pdf_fetcher=pdf_fetcher, progress=progress)

        self._start_job(slug, "pdf", len(pmids), work)

    def log_message(self, format: str, *args) -> None:  # noqa: A002 -- stdlib signature
        pass  # keep the terminal clean; the one line serve() prints is the launch URL


def build_server(library_root: Path, *, port: int = 0) -> http.server.ThreadingHTTPServer:
    """Construct (but don't start) the loopback dashboard server. Exposed
    separately from `serve()` so tests can start/stop it on an ephemeral
    port without going through `serve_forever()`/`webbrowser.open()`."""
    token = secrets.token_urlsafe(24)

    class _BoundHandler(_DashboardHandler):
        pass

    _BoundHandler.library_root = library_root
    _BoundHandler.token = token

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), _BoundHandler)
    httpd.ref_token = token  # type: ignore[attr-defined]
    # Triage jobs live in memory only -- the files on disk are the truth,
    # a restart just forgets progress bars (PUBMED_TRIAGE_IMPLEMENTATION_PLAN.md §6.4).
    httpd.triage_jobs = {"lock": threading.Lock(), "jobs": {}}  # type: ignore[attr-defined]
    # None = the real NCBI efetch / PMC OA downloaders; tests swap in fakes.
    httpd.triage_fetcher = None  # type: ignore[attr-defined]
    httpd.triage_pdf_fetcher = None  # type: ignore[attr-defined]
    # Same idea for the intake panel (intake_pipeline.py): None = real NCBI/PMC.
    httpd.intake_fetcher = None  # type: ignore[attr-defined]
    httpd.intake_resolver = None  # type: ignore[attr-defined]
    httpd.intake_pdf_fetcher = None  # type: ignore[attr-defined]
    httpd.intake_jats_fetcher = None  # type: ignore[attr-defined]
    return httpd


def view_query(raw: str) -> str:
    """Validate a `serve --view` string (a copied dashboard link's query, with
    or without a leading `?`) down to `VIEW_PARAM_KEYS`; raises ValueError
    naming any other key -- a token in a pasted link is never replayed."""
    pairs = urllib.parse.parse_qsl(raw.strip().lstrip("?"), keep_blank_values=False)
    bad = sorted({k for k, _v in pairs if k not in VIEW_PARAM_KEYS})
    if bad:
        raise ValueError(f"unsupported view parameter(s): {', '.join(bad)} (allowed: {', '.join(VIEW_PARAM_KEYS)})")
    return urllib.parse.urlencode(pairs)


def serve(library_root: Path, *, port: int = 0, open_browser: bool = False, triage: str | None = None,
          view: str | None = None) -> None:
    httpd = build_server(library_root, port=port)
    actual_port = httpd.server_address[1]
    url = f"http://127.0.0.1:{actual_port}/?token={httpd.ref_token}"  # type: ignore[attr-defined]
    if view:
        url += "&" + view
    if triage:
        url += f"#triage/{triage}"
    print(f"dashboard serving at {url}", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


def _matrix(rows: list[dict]) -> dict:
    """Coverage matrix over `rows()`, reusing `list.py`'s cell semantics
    (§1.2 "one inventory") for both the live API and the static build."""
    return {"columns": list(list_cli.MATRIX_COLUMNS), "rows": [list_cli._matrix_row(r) for r in rows]}


def _escape_for_script_tag(payload: object) -> str:
    """`json.dumps` with `</` neutralised so embedding inside an inline
    `<script>` tag can't be broken out of by a `</script>` (or any other
    closing tag) hiding in the data
    (LIBRARY_VIEWER_IMPLEMENTATION_PLAN.md §6.3)."""
    return json.dumps(payload, indent=2).replace("</", "<\\/")


def _read_snapshots(library_root: Path) -> list[dict]:
    """`maintenance/*.json` in filename (timestamp) order -- `lint.py`'s
    `_write_snapshot()` names them `<UTC-timestamp>.json` and each file is
    exactly `lint()`'s return shape (`summary`/`issues`/`recommendations`)."""
    maintenance_dir = library_root / "maintenance"
    if not maintenance_dir.is_dir():
        return []
    out = []
    for path in sorted(maintenance_dir.glob("*.json")):
        try:
            report = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(report, dict) or "issues" not in report:
            continue
        out.append({
            "stamp": path.stem,
            "summary": report.get("summary", {}),
            "issues": report.get("issues", {}),
        })
    return out


def _build_into(staging: Path, library_root: Path) -> None:
    """Populate `staging` with the full dashboard. Raises (and leaves
    `staging` for the caller to clean up) rather than promoting anything
    on any failure -- see `build()`'s atomicity contract."""
    rows = lib_inventory.rows(library_root)
    report = lint_module.lint(library_root)
    matrix = _matrix(rows)
    snapshots = _read_snapshots(library_root)

    data = {
        "generated_at": now_iso(),
        "library_root": str(library_root),
        "rows": rows,
        "lint": report,
        "matrix_columns": matrix["columns"],
        "matrix": matrix["rows"],
        "snapshots": snapshots,
        "summary": dashboard_insights.summary(rows, report, snapshots, include_pmids=True),
        "knowledge": dashboard_insights.knowledge(library_root, rows),
    }

    template = (ASSETS_DIR / "index.html").read_text(encoding="utf-8")
    if "/*__DASHBOARD_DATA__*/" not in template:
        raise RuntimeError("dashboard_assets/index.html is missing the /*__DASHBOARD_DATA__*/ placeholder")
    rendered = template.replace("/*__DASHBOARD_DATA__*/", _escape_for_script_tag(data))

    staging.mkdir(parents=True, exist_ok=True)
    (staging / "index.html").write_text(rendered, encoding="utf-8")
    shutil.copyfile(ASSETS_DIR / "app.js", staging / "app.js")
    shutil.copyfile(ASSETS_DIR / "insights.js", staging / "insights.js")
    shutil.copyfile(ASSETS_DIR / "app.css", staging / "app.css")
    shutil.copyfile(ASSETS_DIR / "icon.svg", staging / "icon.svg")

    details_dir = staging / "details"
    details_dir.mkdir(parents=True, exist_ok=True)
    for row in rows:
        pmid = row["pmid"]
        try:
            detail = lib_inventory.detail(library_root, pmid)
        except FileNotFoundError:
            continue  # meta.json missing/malformed -- rows() already flagged it
        payload = json.dumps(detail).replace("</", "<\\/")
        (details_dir / f"{pmid}.js").write_text(
            f"window.__paperDetail({json.dumps(pmid)}, {payload});\n",
            encoding="utf-8",
        )


def build(library_root: Path, *, open_browser: bool = False) -> Path:
    """Atomically (re)write `<library_root>/reports/dashboard/`. Returns
    the path to the built `index.html`."""
    reports_dir = library_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    final = reports_dir / "dashboard"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    staging = reports_dir / f".dashboard-staging-{stamp}"
    if staging.exists():
        shutil.rmtree(staging)

    try:
        _build_into(staging, library_root)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    if not final.exists():
        os.replace(staging, final)
    else:
        # os.rename/replace only swaps onto an *empty* directory, so a
        # non-empty existing dashboard is moved aside first; the second
        # rename is what actually promotes the new build, and on failure
        # the old dashboard is restored from the aside copy (§6: "Rebuild
        # replaces the directory atomically").
        old = reports_dir / f".dashboard-old-{stamp}"
        os.replace(final, old)
        try:
            os.replace(staging, final)
        except BaseException:
            os.replace(old, final)
            raise
        shutil.rmtree(old, ignore_errors=True)

    index_path = final / "index.html"
    if open_browser:
        webbrowser.open(f"file://{index_path}")
    return index_path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    build_ap = sub.add_parser("build", help="render the static dashboard")
    build_ap.add_argument("--repo", required=True)
    build_ap.add_argument("--open", action="store_true", help="open the built dashboard in the default browser")

    serve_ap = sub.add_parser("serve", help="serve the dashboard live over 127.0.0.1 (§7)")
    serve_ap.add_argument("--repo", required=True)
    serve_ap.add_argument("--port", type=int, default=0, help="0 = OS-assigned ephemeral port")
    serve_ap.add_argument("--open", action="store_true", help="open the dashboard in the default browser")
    serve_ap.add_argument("--triage", help="open straight on this saved search's Triage tab")
    serve_ap.add_argument("--view", help="open a shared dashboard view (the query part of a copied link, e.g. 'tab=papers&q=autism')")

    args = ap.parse_args()
    library_root = Path(args.repo).expanduser().resolve()
    if not library_root.is_dir():
        print(f"error: no library at {library_root}", file=sys.stderr)
        return 1

    if args.cmd == "build":
        index_path = build(library_root, open_browser=args.open)
        print(f"dashboard written: {index_path}")
        return 0
    if args.cmd == "serve":
        if args.triage:
            try:
                validate_slug(args.triage)
            except SlugError as e:
                print(f"error: {e}", file=sys.stderr)
                return 1
            if not triage_module.exists(library_root, args.triage):
                print(f"error: no triage for {args.triage!r} -- run /ref:triage {args.triage}", file=sys.stderr)
                return 1
        view = None
        if args.view:
            try:
                view = view_query(args.view)
            except ValueError as e:
                print(f"error: {e}", file=sys.stderr)
                return 1
        serve(library_root, port=args.port, open_browser=args.open, triage=args.triage, view=view)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
