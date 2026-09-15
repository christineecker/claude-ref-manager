#!/usr/bin/env python3
"""Phase 4 gate fixtures for annotation pull + selective figure-vision
(PLAN.md §8 build-order row for phase 4, the annotate/vision subset).

Uses a synthetic scratch SQLite database matching PLAN.md §7's schema --
NEVER the real ~/Library/Application Support/Papers/*.db.

Run: python3 skills/ref-manager/scripts/tests/test_phase4_annotate.py
"""
from __future__ import annotations

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
import pull_annotations  # noqa: E402
import vision  # noqa: E402
from lib_atomic import atomic_write_json  # noqa: E402


def author(last, first):
    return {"last": last, "first": first, "raw": f"{last} {first}"}


def make_record(pmid, title, authors, doi=None):
    return {
        "pmid": pmid, "title": title, "abstract": "abs", "authors": authors,
        "journal": "J", "year": "2022", "doi": doi, "pmcid": None, "grants": [],
    }


def build_synthetic_papers_db(path: Path, rows: list[dict]) -> None:
    if path.exists():
        path.unlink()
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


def papers_item(pmid, annotations):
    return {
        "ext_ids": {"pmid": pmid, "doi": None, "pmcid": None},
        "article": {"title": "T"},
        "user_data": {"notes": None, "tags": [], "annotations": annotations},
        "files": [{"sha256": "filehash123"}],
        "deleted": False,
    }


class TempLibrary(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.lib = self.tmp / "lib"
        init_repo.init_library(self.lib, force=True)
        self.db = self.tmp / "scratch-papers.db"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _add(self, pmid, doi=None):
        return add.add_one(self.lib, make_record(pmid, "Title", [author("Ahn", "S")], doi=doi))


class TestPullAnnotations(TempLibrary):
    def test_pull_produces_highlights_and_note(self):
        self._add("1001")
        annos = [
            {"id": "a1", "type": "highlight", "sha256": "filehash123", "page_start": 1,
             "rects": [[0, 0, 1, 1]], "text": "quoted span", "note": None, "has_note": False,
             "color_id": 2, "created": "2022-01-01T00:00:00Z", "modified": "2022-01-01T00:00:00Z"},
            {"id": "a2", "type": "highlight", "sha256": "filehash123", "page_start": 2,
             "rects": [[0, 0, 1, 1]], "text": "second span", "note": None, "has_note": False,
             "color_id": 3, "created": "2022-01-02T00:00:00Z", "modified": "2022-01-02T00:00:00Z"},
            {"id": "a3", "type": "note", "sha256": "filehash123", "page_start": 3,
             "position": {"x": 1, "y": 2}, "text": None, "note": "margin thought", "has_note": True,
             "color_id": None, "created": "2022-01-03T00:00:00Z", "modified": "2022-01-03T00:00:00Z"},
        ]
        build_synthetic_papers_db(self.db, [papers_item("1001", annos)])
        result = pull_annotations.pull(self.lib, "1001", self.db)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(sorted(result["added"]), ["a1", "a2", "a3"])

        doc = json.loads((self.lib / "papers/1001/annotations.json").read_text())
        self.assertEqual(len(doc["annotations"]), 3)
        self.assertEqual(doc["annotations"]["a3"]["type"], "note")
        self.assertEqual(doc["annotations"]["a3"]["note"], "margin thought")
        self.assertEqual(doc["annotations"]["a1"]["sha256"], "filehash123")

    def test_repeat_pull_is_idempotent(self):
        self._add("1002")
        annos = [{"id": "a1", "type": "highlight", "sha256": "h", "page_start": 1,
                   "rects": [], "text": "x", "note": None, "has_note": False, "color_id": 1,
                   "created": "t1", "modified": "t1"}]
        build_synthetic_papers_db(self.db, [papers_item("1002", annos)])
        pull_annotations.pull(self.lib, "1002", self.db)
        before = (self.lib / "papers/1002/annotations.json").read_text()
        result = pull_annotations.pull(self.lib, "1002", self.db)
        after = (self.lib / "papers/1002/annotations.json").read_text()
        self.assertEqual(result["added"], [])
        self.assertEqual(result["updated"], [])
        self.assertEqual(result["unchanged"], ["a1"])
        before_doc = json.loads(before)
        after_doc = json.loads(after)
        del before_doc["last_pulled_at"], after_doc["last_pulled_at"]
        self.assertEqual(before_doc, after_doc)  # annotation content identical; only the pull timestamp differs

    def test_upstream_edit_updates_in_place_and_preserves_local(self):
        self._add("1003")
        annos = [{"id": "a1", "type": "highlight", "sha256": "h", "page_start": 1,
                   "rects": [], "text": "original", "note": None, "has_note": False, "color_id": 1,
                   "created": "t1", "modified": "t1"}]
        build_synthetic_papers_db(self.db, [papers_item("1003", annos)])
        pull_annotations.pull(self.lib, "1003", self.db)

        # simulate future local per-annotation data existing
        path = self.lib / "papers/1003/annotations.json"
        doc = json.loads(path.read_text())
        doc["annotations"]["a1"]["local"] = {"reviewed": True}
        atomic_write_json(path, doc)

        annos[0]["text"] = "edited upstream"
        annos[0]["modified"] = "t2"
        build_synthetic_papers_db(self.db, [papers_item("1003", annos)])
        result = pull_annotations.pull(self.lib, "1003", self.db)
        self.assertEqual(result["updated"], ["a1"])

        doc = json.loads(path.read_text())
        self.assertEqual(doc["annotations"]["a1"]["text"], "edited upstream")
        self.assertEqual(doc["annotations"]["a1"]["local"], {"reviewed": True})

    def test_upstream_delete_is_tombstoned_not_removed(self):
        self._add("1004")
        annos = [{"id": "a1", "type": "highlight", "sha256": "h", "page_start": 1,
                   "rects": [], "text": "x", "note": None, "has_note": False, "color_id": 1,
                   "created": "t1", "modified": "t1"}]
        build_synthetic_papers_db(self.db, [papers_item("1004", annos)])
        pull_annotations.pull(self.lib, "1004", self.db)

        build_synthetic_papers_db(self.db, [papers_item("1004", [])])
        result = pull_annotations.pull(self.lib, "1004", self.db)
        self.assertEqual(result["tombstoned"], ["a1"])

        doc = json.loads((self.lib / "papers/1004/annotations.json").read_text())
        self.assertIn("a1", doc["annotations"])  # kept, not removed
        self.assertTrue(doc["annotations"]["a1"]["deleted_upstream"])
        self.assertIsNotNone(doc["annotations"]["a1"]["deleted_upstream_at"])

    def test_never_touches_notes_md(self):
        self._add("1005")
        note.append(self.lib, "1005", "my private thought")
        before = note.show(self.lib, "1005")
        annos = [{"id": "a1", "type": "highlight", "sha256": "h", "page_start": 1,
                   "rects": [], "text": "x", "note": None, "has_note": False, "color_id": 1,
                   "created": "t1", "modified": "t1"}]
        build_synthetic_papers_db(self.db, [papers_item("1005", annos)])
        pull_annotations.pull(self.lib, "1005", self.db)
        after = note.show(self.lib, "1005")
        self.assertEqual(before, after)

    def test_snapshot_unavailable_degrades_cleanly(self):
        self._add("1006")
        garbage = self.tmp / "not-a-real.db"
        garbage.write_text("not sqlite")
        result = pull_annotations.pull(self.lib, "1006", garbage)
        self.assertEqual(result["status"], "snapshot_unavailable")

    def test_no_matching_item(self):
        self._add("1007")
        build_synthetic_papers_db(self.db, [papers_item("9999999", [])])
        result = pull_annotations.pull(self.lib, "1007", self.db)
        self.assertEqual(result["status"], "no_matching_papers_item")


class TestVisionCache(TempLibrary):
    def _paper_with_figure(self, pmid, asset_available=True, fig_sha="figsha1"):
        add.add_one(self.lib, make_record(pmid, "T", [author("A", "B")]))
        version_dir = self.lib / "papers" / pmid / "versions" / "v1"
        version_dir.mkdir(parents=True)
        figures = [{
            "id": "fig1", "label": "Figure 1", "caption": "A bar chart",
            "source_locator": "fig1.jpg",
            "sha256": fig_sha if asset_available else None,
            "asset_available": asset_available,
        }]
        atomic_write_json(version_dir / "figures.json", figures)
        atomic_write_json(self.lib / "papers" / pmid / "current.json", {"version": "v1"})

    def test_cache_miss_then_hit(self):
        self._paper_with_figure("2001")
        r1 = vision.request(self.lib, "2001", "current", "fig1", "modelA", "describe this")
        self.assertEqual(r1["status"], "needs_description")
        self.assertEqual(r1["caption"], "A bar chart")

        stored = vision.store(self.lib, "2001", "current", "fig1", "modelA", "describe this", "It shows rising values.")
        self.assertEqual(stored["status"], "stored")
        self.assertEqual(stored["vision"]["kind"], "model_interpretation")

        r2 = vision.request(self.lib, "2001", "current", "fig1", "modelA", "describe this")
        self.assertEqual(r2["status"], "cache_hit")
        self.assertEqual(r2["vision"]["description"], "It shows rising values.")

    def test_different_prompt_is_cache_miss(self):
        self._paper_with_figure("2002")
        vision.store(self.lib, "2002", "current", "fig1", "modelA", "describe this", "desc A")
        r = vision.request(self.lib, "2002", "current", "fig1", "modelA", "a different prompt")
        self.assertEqual(r["status"], "needs_description")

    def test_different_model_is_cache_miss(self):
        self._paper_with_figure("2003")
        vision.store(self.lib, "2003", "current", "fig1", "modelA", "describe this", "desc A")
        r = vision.request(self.lib, "2003", "current", "fig1", "modelB", "describe this")
        self.assertEqual(r["status"], "needs_description")

    def test_description_stored_separately_from_caption(self):
        self._paper_with_figure("2004")
        vision.store(self.lib, "2004", "current", "fig1", "modelA", "describe this", "model says X")
        figures = json.loads((self.lib / "papers/2004/versions/v1/figures.json").read_text())
        fig = figures[0]
        self.assertEqual(fig["caption"], "A bar chart")
        self.assertEqual(fig["vision"][0]["description"], "model says X")
        self.assertNotEqual(fig["caption"], fig["vision"][0]["description"])

    def test_asset_unavailable_refuses(self):
        self._paper_with_figure("2005", asset_available=False)
        r = vision.request(self.lib, "2005", "current", "fig1", "modelA", "describe this")
        self.assertEqual(r["status"], "asset_unavailable")
        s = vision.store(self.lib, "2005", "current", "fig1", "modelA", "describe this", "x")
        self.assertEqual(s["status"], "asset_unavailable")

    def test_figure_not_found(self):
        self._paper_with_figure("2006")
        r = vision.request(self.lib, "2006", "current", "nope", "modelA", "describe this")
        self.assertEqual(r["status"], "figure_not_found")


if __name__ == "__main__":
    unittest.main()
