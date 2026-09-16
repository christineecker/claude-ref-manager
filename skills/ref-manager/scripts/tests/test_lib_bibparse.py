#!/usr/bin/env python3
"""BibTeX/CSL-JSON entry parsing (MAINTENANCE_FEATURE_IMPLEMENTATION_PLAN.md Phase 4).

Run: python3 skills/ref-manager/scripts/tests/test_lib_bibparse.py
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import lib_bibparse  # noqa: E402


class TestParseBibText(unittest.TestCase):
    def test_single_entry_braces(self):
        entries = lib_bibparse.parse_bib_text(
            "@article{smith2020, title={A Study}, doi={10.1038/x}, year={2020}}"
        )
        self.assertEqual(len(entries), 1)
        e = entries[0]
        self.assertEqual(e["citekey"], "smith2020")
        self.assertEqual(e["entry_type"], "article")
        self.assertEqual(e["title"], "A Study")
        self.assertEqual(e["doi"], "10.1038/x")
        self.assertEqual(e["year"], "2020")

    def test_quoted_values(self):
        entries = lib_bibparse.parse_bib_text(
            '@article{k, title="A Study", journal="Nature"}'
        )
        self.assertEqual(entries[0]["title"], "A Study")
        self.assertEqual(entries[0]["journal"], "Nature")

    def test_bare_numeric_value(self):
        entries = lib_bibparse.parse_bib_text("@article{k, year=2020}")
        self.assertEqual(entries[0]["year"], "2020")

    def test_nested_braces_in_title_not_split_early(self):
        entries = lib_bibparse.parse_bib_text(
            "@article{k, title={A {Special} Study}, doi={10.1/x}}"
        )
        self.assertEqual(entries[0]["title"], "A {Special} Study")
        self.assertEqual(entries[0]["doi"], "10.1/x")

    def test_multiple_entries(self):
        entries = lib_bibparse.parse_bib_text(
            "@article{a, title={A}}\n@book{b, title={B}}\n"
        )
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["entry_type"], "article")
        self.assertEqual(entries[1]["entry_type"], "book")

    def test_comment_and_string_blocks_skipped(self):
        entries = lib_bibparse.parse_bib_text(
            "@comment{ignore this}\n@string{foo = {bar}}\n@article{a, title={A}}"
        )
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["citekey"], "a")

    def test_missing_optional_fields_are_none(self):
        entries = lib_bibparse.parse_bib_text("@article{a, title={A}}")
        self.assertIsNone(entries[0]["doi"])
        self.assertIsNone(entries[0]["pmid"])

    def test_pmid_field_extracted(self):
        entries = lib_bibparse.parse_bib_text("@article{a, title={A}, pmid={12345678}}")
        self.assertEqual(entries[0]["pmid"], "12345678")

    def test_empty_text_no_crash(self):
        self.assertEqual(lib_bibparse.parse_bib_text(""), [])

    def test_garbage_text_no_crash(self):
        self.assertEqual(lib_bibparse.parse_bib_text("not bibtex at all"), [])

    def test_unterminated_entry_dropped_not_raised(self):
        entries = lib_bibparse.parse_bib_text("@article{a, title={Unterminated")
        self.assertEqual(entries, [])

    def test_whitespace_collapsed_in_values(self):
        entries = lib_bibparse.parse_bib_text("@article{a, title={A   Study\nOver Lines}}")
        self.assertEqual(entries[0]["title"], "A Study Over Lines")


class TestParseCslJsonText(unittest.TestCase):
    def test_basic_array(self):
        entries = lib_bibparse.parse_csl_json_text(json.dumps([
            {"id": "a", "title": "A", "DOI": "10.1038/a", "container-title": "Nature",
             "issued": {"date-parts": [[2020, 5]]}},
        ]))
        self.assertEqual(len(entries), 1)
        e = entries[0]
        self.assertEqual(e["citekey"], "a")
        self.assertEqual(e["doi"], "10.1038/a")
        self.assertEqual(e["journal"], "Nature")
        self.assertEqual(e["year"], "2020")

    def test_single_object_not_array(self):
        entries = lib_bibparse.parse_csl_json_text(json.dumps({"id": "a", "title": "A"}))
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["citekey"], "a")

    def test_items_wrapper_object(self):
        entries = lib_bibparse.parse_csl_json_text(json.dumps({
            "items": [{"id": "a", "title": "A"}, {"id": "b", "title": "B"}],
        }))
        self.assertEqual(len(entries), 2)

    def test_pmid_from_note_field(self):
        entries = lib_bibparse.parse_csl_json_text(json.dumps([
            {"id": "a", "title": "A", "note": "PMID: 12345678\nOther note text"},
        ]))
        self.assertEqual(entries[0]["pmid"], "12345678")

    def test_pmid_from_explicit_field(self):
        entries = lib_bibparse.parse_csl_json_text(json.dumps([
            {"id": "a", "title": "A", "PMID": "87654321"},
        ]))
        self.assertEqual(entries[0]["pmid"], "87654321")

    def test_no_pmid_clue_is_none(self):
        entries = lib_bibparse.parse_csl_json_text(json.dumps([{"id": "a", "title": "A"}]))
        self.assertIsNone(entries[0]["pmid"])

    def test_invalid_json_no_crash(self):
        self.assertEqual(lib_bibparse.parse_csl_json_text("not json{"), [])

    def test_non_list_non_dict_json_no_crash(self):
        self.assertEqual(lib_bibparse.parse_csl_json_text("42"), [])

    def test_non_dict_items_skipped(self):
        entries = lib_bibparse.parse_csl_json_text(json.dumps(["not-a-dict", {"id": "a"}]))
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["citekey"], "a")


if __name__ == "__main__":
    unittest.main()
