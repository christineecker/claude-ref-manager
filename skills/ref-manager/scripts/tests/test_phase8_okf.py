#!/usr/bin/env python3
"""Phase 8 (OKF view generation, researcher/grant graph relations) gate
fixtures -- the OKF/people-graph half built concurrently with another
agent's scientific concept/claim graph half (PLAN.md §8 build-order row
for phase 8).

Run: python3 skills/ref-manager/scripts/tests/test_phase8_okf.py
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import add  # noqa: E402
import person  # noqa: E402
import grant  # noqa: E402
import init_repo  # noqa: E402
import okf_emit  # noqa: E402
import graph_people  # noqa: E402
from lib_atomic import atomic_write_json  # noqa: E402

FIXED_NOW = "2026-01-01T00:00:00+00:00"


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
            "authors": [author("Smith", "Jane")],
            "journal": "X", "year": "2022", "doi": f"10.1/{pmid}", "pmcid": None, "grants": [],
        }
        record.update(overrides)
        return add.add_one(self.library_root, record)

    def write_concepts(self, rows):
        p = self.library_root / "graph" / "concepts.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")

    def write_relations(self, rows):
        p = self.library_root / "graph" / "relations.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


class TestOkfBasicGeneration(TempLibrary):
    def test_generates_valid_frontmatter_and_links(self):
        self.add_paper("100")
        self.add_paper("101")
        person.create(self.library_root, "jane-smith", "Jane Smith", None)
        person.confirm_publication(self.library_root, "jane-smith", "100", 0)
        grant.create(self.library_root, "nih-r01", "NIH", "R01-123", None, None, "study X")
        self.write_concepts([
            {"concept_id": "statins", "name": "Statins", "aliases": ["statin therapy"]},
        ])
        self.write_relations([
            {"relation_id": "rel-1", "type": "supports", "subject_concept_id": "statins",
             "object_concept_id": "ldl-reduction", "supporting_claim_ids": ["c-1"],
             "review_state": "unreviewed", "stale": False},
        ])

        result = okf_emit.emit(self.library_root, now=FIXED_NOW)
        self.assertEqual(result["papers"], 2)
        self.assertEqual(result["concepts"], 1)
        self.assertEqual(result["people"], 1)
        self.assertEqual(result["grants"], 1)
        self.assertTrue(result["relations_available"])

        concept_md = (self.library_root / "okf" / "concepts" / "statins.md").read_text()
        self.assertTrue(concept_md.startswith("---\n"))
        self.assertIn("type: \"Concept\"", concept_md)
        self.assertIn("[ldl-reduction](../concepts/ldl-reduction.md)", concept_md)

        person_md_files = list((self.library_root / "okf" / "people").glob("*.md"))
        self.assertEqual(len(person_md_files), 1)
        self.assertIn("PMID 100", person_md_files[0].read_text())

    def test_idempotent_regeneration(self):
        self.add_paper("200")
        okf_emit.emit(self.library_root, now=FIXED_NOW)
        snapshot1 = {
            p: p.read_bytes() for p in (self.library_root / "okf").rglob("*.md")
        }
        okf_emit.emit(self.library_root, now=FIXED_NOW)
        snapshot2 = {
            p: p.read_bytes() for p in (self.library_root / "okf").rglob("*.md")
        }
        self.assertEqual(snapshot1, snapshot2)


class TestOkfConceptDegradesWithoutRelations(TempLibrary):
    def test_no_relations_file_reports_unavailable_not_crash(self):
        self.write_concepts([{"concept_id": "orphan", "name": "Orphan Concept", "aliases": []}])
        result = okf_emit.emit(self.library_root, now=FIXED_NOW)
        self.assertFalse(result["relations_available"])
        md = (self.library_root / "okf" / "concepts" / "orphan.md").read_text()
        self.assertIn("No relations data available", md)


class TestPeopleGraphRelations(TempLibrary):
    def test_researcher_authored_publication_and_acknowledges_grant_distinct(self):
        self.add_paper("300")
        person.create(self.library_root, "a-researcher", "A Researcher", None)
        person.confirm_publication(self.library_root, "a-researcher", "300", 0)
        grant.create(self.library_root, "nsf-1", "NSF", "AWD-999", None, None, None)

        funding_path = self.library_root / "papers" / "300" / "funding.json"
        atomic_write_json(funding_path, {
            "pmid": "300", "state": "explicit_acknowledgement_verified",
            "observations": [
                {"kind": "explicit_acknowledgement_verified", "source": "jats_funding_group",
                 "funder": "NSF", "award_number": "AWD-999", "locator": "funding-group"},
            ],
        })

        result = graph_people.build(self.library_root)
        self.assertEqual(result["researcher_authored_publication"], 1)
        self.assertEqual(result["publication_acknowledges_grant"], 1)

        rows = [json.loads(l) for l in
                (self.library_root / "graph" / "people_relations.jsonl").read_text().splitlines()]
        types = {r["type"] for r in rows}
        self.assertEqual(types, {"researcher_authored_publication", "publication_acknowledges_grant"})
        # distinct records, never collapsed into one generic edge
        rap = [r for r in rows if r["type"] == "researcher_authored_publication"][0]
        pag = [r for r in rows if r["type"] == "publication_acknowledges_grant"][0]
        self.assertNotEqual(set(rap.keys()), set(pag.keys()) - {"relation_id", "type"})

    def test_unlinked_award_string_produces_no_edge(self):
        self.add_paper("301")
        funding_path = self.library_root / "papers" / "301" / "funding.json"
        atomic_write_json(funding_path, {
            "pmid": "301", "state": "possible_match",
            "observations": [
                {"kind": "possible_match", "source": "jats_acknowledgement_prose",
                 "funder": None, "award_number": "UNKNOWN-AWARD-NOT-IN-ANY-GRANT-RECORD",
                 "text": "supported by a grant", "locator": "sec"},
            ],
        })
        result = graph_people.build(self.library_root)
        self.assertEqual(result["publication_acknowledges_grant"], 0)

    def test_aim_and_lab_membership_report_unpopulated(self):
        result = graph_people.build(self.library_root)
        self.assertEqual(result["publication_supports_aim"], 0)
        self.assertEqual(result["researcher_lab_membership"], 0)
        self.assertIn("unpopulated", result["publication_supports_aim_note"])
        self.assertIn("unpopulated", result["researcher_lab_membership_note"])

    def test_idempotent(self):
        self.add_paper("302")
        person.create(self.library_root, "b-researcher", "B Researcher", None)
        person.confirm_publication(self.library_root, "b-researcher", "302", 0)
        graph_people.build(self.library_root)
        snap1 = (self.library_root / "graph" / "people_relations.jsonl").read_bytes()
        graph_people.build(self.library_root)
        snap2 = (self.library_root / "graph" / "people_relations.jsonl").read_bytes()
        self.assertEqual(snap1, snap2)


if __name__ == "__main__":
    unittest.main()
