#!/usr/bin/env python3
"""Phase 3 gate fixtures for the Papers.app integration half (§7, §7a, §7b).

Uses a synthetic scratch SQLite database matching PLAN.md §7's schema —
NEVER the real ~/Library/Application Support/Papers/*.db.

Run: python3 skills/ref-manager/scripts/tests/test_phase3_papers.py
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import add  # noqa: E402
import init_repo  # noqa: E402
import note  # noqa: E402
import export_papers  # noqa: E402
import open_in_papers  # noqa: E402
import papers_snapshot  # noqa: E402
from lib_selector import SelectorError  # noqa: E402


def author(last, first):
    return {"last": last, "first": first, "raw": f"{last} {first}"}


def make_record(pmid, title, authors, year="2021", doi=None, abstract="abstract text"):
    return {
        "pmid": pmid, "title": title, "abstract": abstract, "authors": authors,
        "journal": "J Test", "year": year, "doi": doi, "pmcid": None, "grants": [],
    }


def build_synthetic_papers_db(path: Path, rows: list[dict]) -> None:
    con = sqlite3.connect(str(path))
    con.execute("CREATE TABLE items (id TEXT PRIMARY KEY, collection_id TEXT, json TEXT)")
    con.execute("CREATE TABLE fulltext (sha256 TEXT PRIMARY KEY, text TEXT)")
    con.execute("CREATE TABLE collections (id TEXT PRIMARY KEY, name TEXT)")
    con.execute("CREATE TABLE actions_queue (id INTEGER PRIMARY KEY, payload TEXT)")
    con.execute("CREATE TABLE sync_meta (k TEXT PRIMARY KEY, v TEXT)")
    for i, row in enumerate(rows):
        con.execute("INSERT INTO items (id, collection_id, json) VALUES (?, NULL, ?)",
                    (f"item-{i}", json.dumps(row)))
    con.commit()
    con.close()


def attach_pdf(library_root: Path, pmid: str, content: bytes = b"%PDF-1.4 fake") -> str:
    """Fabricate an acquired PDF the way /ref:fetch or /ref:attach would
    (their real implementation is being built concurrently by another
    agent) — acquisitions.json + raw/<hash>/source.pdf, per this file's
    ASSUMPTION in export_papers.py's module docstring."""
    sha = hashlib.sha256(content).hexdigest()
    paper_dir = library_root / "papers" / pmid
    raw_dir = paper_dir / "raw" / sha
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "source.pdf").write_bytes(content)
    (paper_dir / "acquisitions.json").write_text(json.dumps([
        {"media_type": "pdf", "availability": "available", "hash": sha, "origin": "test"}
    ]))
    return sha


class Phase3PapersTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.lib = self.tmp / "lib"
        init_repo.init_library(self.lib, force=True)
        self.db = self.tmp / "scratch-papers.db"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _add(self, pmid, title, authors, **kw):
        return add.add_one(self.lib, make_record(pmid, title, authors, **kw))

    def test_three_paper_batch_bib_and_manifest(self):
        # unicode author, title with & and %, and a no-PDF abstract-tier paper
        self._add("1001", "Effects of A & B on C (50% response)", [author("Schulte-Rüther", "Maria")], doi="10.1/x1")
        self._add("1002", "Second paper", [author("Smith", "Jane")], doi="10.1/x2")
        self._add("1003", "Third, abstract only", [author("Doe", "Jo")], doi="10.1/x3")
        attach_pdf(self.lib, "1001")
        attach_pdf(self.lib, "1002")
        build_synthetic_papers_db(self.db, [])

        dest = self.tmp / "dest"
        args = _args(pmids=["1001", "1002", "1003"], repo=str(self.lib), to=str(dest),
                     layout="flat", pdfs="copy", papers_db=str(self.db))
        from lib_selector import resolve_from_args
        resolution = resolve_from_args(self.lib, args)
        result = export_papers.run_export_papers(self.lib, args, resolution)

        manifest = result["manifest"]
        self.assertEqual(sorted(manifest["missing_pdfs"]), ["1003"])
        bib = (dest / "references.bib").read_text()
        self.assertIn("Schulte-Rüther", bib)
        self.assertIn(r"\& B on C (50\% response)", bib)
        self.assertEqual(bib.count("local-url"), 2)  # 1001, 1002 have PDFs; 1003 doesn't
        self.assertTrue((dest / f"{manifest['per_paper']['1001']['citekey']}.pdf").exists())
        self.assertIsNone(manifest["per_paper"]["1003"]["pdf_path"])

    def test_layout_papers_collision_suffix(self):
        self._add("2001", "Paper one", [author("Kim", "A"), author("Zhang", "B")], year="2020")
        self._add("2002", "Paper two", [author("Lee", "C"), author("Zhang", "B")], year="2020")
        attach_pdf(self.lib, "2001")
        attach_pdf(self.lib, "2002")
        build_synthetic_papers_db(self.db, [])
        dest = self.tmp / "dest"
        args = _args(pmids=["2001", "2002"], repo=str(self.lib), to=str(dest), layout="papers",
                     pdfs="copy", papers_db=str(self.db))
        from lib_selector import resolve_from_args
        resolution = resolve_from_args(self.lib, args)
        result = export_papers.run_export_papers(self.lib, args, resolution)
        paths = {p["pdf_path"] for p in result["manifest"]["per_paper"].values()}
        self.assertEqual(len(paths), 2)
        self.assertTrue(any(p.endswith("-2.pdf") for p in paths))

    def test_reexport_reuses_pdf_rewrites_bib(self):
        self._add("3001", "Original title", [author("Kim", "A")])
        attach_pdf(self.lib, "3001")
        build_synthetic_papers_db(self.db, [])
        dest = self.tmp / "dest"
        from lib_selector import resolve_from_args
        args = _args(pmids=["3001"], repo=str(self.lib), to=str(dest), layout="flat",
                     pdfs="copy", papers_db=str(self.db))
        r1 = export_papers.run_export_papers(self.lib, args, resolve_from_args(self.lib, args))
        pdf_path = dest / r1["manifest"]["per_paper"]["3001"]["pdf_path"]
        mtime1 = pdf_path.stat().st_mtime_ns

        # mutate meta.json title, re-export with unchanged PDF
        meta_path = self.lib / "papers" / "3001" / "meta.json"
        meta = json.loads(meta_path.read_text())
        meta["title"] = "Updated title"
        meta_path.write_text(json.dumps(meta))

        r2 = export_papers.run_export_papers(self.lib, args, resolve_from_args(self.lib, args))
        self.assertEqual(pdf_path.stat().st_mtime_ns, mtime1)
        bib = (dest / "references.bib").read_text()
        self.assertIn("Updated title", bib)

    def test_foreign_file_never_overwritten(self):
        self._add("4001", "Foreign clash", [author("Kim", "A")])
        attach_pdf(self.lib, "4001")
        build_synthetic_papers_db(self.db, [])
        dest = self.tmp / "dest"
        dest.mkdir(parents=True)
        from lib_selector import resolve_from_args
        args = _args(pmids=["4001"], repo=str(self.lib), to=str(dest), layout="flat",
                     pdfs="copy", papers_db=str(self.db))
        resolution = resolve_from_args(self.lib, args)
        citekey_probe = export_papers.to_csl(self.lib, "4001")["id"]
        foreign_path = dest / f"{citekey_probe}.pdf"
        foreign_path.write_bytes(b"NOT OURS")
        foreign_mtime = foreign_path.stat().st_mtime_ns

        result = export_papers.run_export_papers(self.lib, args, resolution)
        self.assertEqual(foreign_path.stat().st_mtime_ns, foreign_mtime)
        self.assertEqual(foreign_path.read_bytes(), b"NOT OURS")
        self.assertTrue(result["manifest"]["foreign_conflicts"])

    def test_snapshot_unavailable_degrades_gracefully(self):
        self._add("5001", "Solo paper", [author("Kim", "A")])
        dest = self.tmp / "dest"
        from lib_selector import resolve_from_args
        garbage_db = self.tmp / "does-not-exist.db"
        args = _args(pmids=["5001"], repo=str(self.lib), to=str(dest), layout="flat",
                     pdfs="none", papers_db=str(garbage_db))
        resolution = resolve_from_args(self.lib, args)
        result = export_papers.run_export_papers(self.lib, args, resolution)
        self.assertFalse(result["manifest"]["duplicate_detection_available"])
        self.assertTrue((dest / "references.bib").exists())

    def test_note_push_then_refused_then_forced(self):
        self._add("6001", "Noted paper", [author("Kim", "A")])
        note.append(self.lib, "6001", "Great methodology.")
        build_synthetic_papers_db(self.db, [])
        dest = self.tmp / "dest"
        from lib_selector import resolve_from_args
        args = _args(pmids=["6001"], repo=str(self.lib), to=str(dest), layout="flat",
                     pdfs="none", papers_db=str(self.db), notes=True, batch="b1")
        resolution = resolve_from_args(self.lib, args)
        r1 = export_papers.run_export_papers(self.lib, args, resolution)
        self.assertEqual(r1["note_statuses"]["6001"], "pushed")
        bib1 = (dest / "references.bib").read_text()
        self.assertIn("note =", bib1)

        # second export without force: refused
        args2 = _args(pmids=["6001"], repo=str(self.lib), to=str(dest), layout="flat",
                      pdfs="none", papers_db=str(self.db), notes=True, batch="b2", refresh=True)
        r2 = export_papers.run_export_papers(self.lib, args2, resolve_from_args(self.lib, args2))
        self.assertIn("refused", r2["note_statuses"]["6001"])

        # forced: overwrites
        args3 = _args(pmids=["6001"], repo=str(self.lib), to=str(dest), layout="flat",
                      pdfs="none", papers_db=str(self.db), notes=True, notes_force=True, batch="b3", refresh=True)
        r3 = export_papers.run_export_papers(self.lib, args3, resolve_from_args(self.lib, args3))
        self.assertEqual(r3["note_statuses"]["6001"], "pushed")

    def test_empty_selector_is_named_error(self):
        from lib_selector import resolve_from_args
        args = _args(pmids=[], repo=str(self.lib), project="no-such-project", to=str(self.tmp / "x"),
                     papers_db=None)
        with self.assertRaises(SelectorError):
            resolve_from_args(self.lib, args)

    def test_open_no_pdf_acquired_reports_clearly(self):
        self._add("7001", "No pdf yet", [author("Kim", "A")])
        pdf = export_papers.resolve_pdf(self.lib, "7001")
        self.assertIsNone(pdf)

    def test_duplicate_detected_against_scratch_db(self):
        self._add("8001", "Dup paper", [author("Kim", "A")], doi="10.1/dup")
        build_synthetic_papers_db(self.db, [
            {"ext_ids": {"pmid": "8001", "doi": "10.1/dup"}, "article": {"title": "Dup paper"},
             "user_data": {}, "files": [], "deleted": False},
        ])
        dest = self.tmp / "dest"
        from lib_selector import resolve_from_args
        args = _args(pmids=["8001"], repo=str(self.lib), to=str(dest), layout="flat",
                     pdfs="none", papers_db=str(self.db), skip_known=True)
        resolution = resolve_from_args(self.lib, args)
        result = export_papers.run_export_papers(self.lib, args, resolution)
        self.assertIn("8001", result["manifest"]["already_known"])
        self.assertIn("8001", result["manifest"]["skipped_known"])
        self.assertNotIn("8001", result["manifest"]["pmids"])


class _NS:
    def __init__(self, **kw):
        defaults = dict(
            pmids=[], project=None, question=None, screened=None, read=False, queue=None,
            query=None, run=None, search=None, from_file=None, study=None, concept=None,
            tier="any", exclude=None, to=None, layout=None, pdfs="copy", notes=False,
            notes_force=False, tags=None, tags_from=None, skip_known=False, force=False,
            collection=None, dry_run=False, refresh=False, papers_db=None, batch=None,
        )
        defaults.update(kw)
        for k, v in defaults.items():
            setattr(self, k, v)


def _args(**kw):
    return _NS(**kw)


if __name__ == "__main__":
    unittest.main()
