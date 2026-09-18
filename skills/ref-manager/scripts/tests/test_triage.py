#!/usr/bin/env python3
"""PubMed search triage (PUBMED_TRIAGE_IMPLEMENTATION_PLAN.md §8).

No network: lib_eutils is exercised against tests/fixtures/pubmed_efetch.xml
and triage batches use a fake fetcher.

Run: python3 skills/ref-manager/scripts/tests/test_triage.py
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import init_repo  # noqa: E402
import lib_eutils  # noqa: E402
import project  # noqa: E402
import pubmed_query  # noqa: E402
import triage  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
PMIDS = [str(10000001 + i) for i in range(7)]


def fake_record(pmid: str, **extra) -> dict:
    rec = {
        "pmid": pmid, "title": f"Paper {pmid}", "abstract": f"Abstract {pmid}.",
        "authors": [{"last": "Doe", "first": "J", "raw": "Doe J"}], "journal": "J Test",
        "year": "2024", "doi": f"10.1/{pmid}", "pmcid": None, "grants": [],
        "publication_types": ["Journal Article"], "mesh_terms": [],
    }
    rec.update(extra)
    return rec


class FakeFetcher:
    def __init__(self, missing=(), fail=False):
        self.calls: list[list[str]] = []
        self.missing = set(missing)
        self.fail = fail

    def __call__(self, pmids):
        self.calls.append(list(pmids))
        if self.fail:
            raise lib_eutils.EutilsError("simulated NCBI outage")
        return [fake_record(p) for p in pmids if p not in self.missing], [p for p in pmids if p in self.missing]


class TriageFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "lib"
        for rel in init_repo.LIBRARY_DIRS:
            (self.root / rel).mkdir(parents=True, exist_ok=True)
        pubmed_query.new_run(self.root, "asd-ct", "autism AND cortical thickness", "pubmed", PMIDS[:5], True)
        project.create(self.root, "proj-a", None)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def init_loaded(self, project_slug=None, size=100):
        triage.init(self.root, "asd-ct", project_slug)
        triage.load_batch(self.root, "asd-ct", size, fetcher=FakeFetcher())

    def screening_lines(self, slug="proj-a"):
        p = self.root / "projects" / slug / "screening.jsonl"
        return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


class TestParsePubmedXml(unittest.TestCase):
    def setUp(self):
        self.records = lib_eutils.parse_pubmed_xml((FIXTURES / "pubmed_efetch.xml").read_bytes())
        self.by = {r["pmid"]: r for r in self.records}

    def test_structured_abstract_keeps_labels_and_flattens_markup(self):
        self.assertEqual(self.by["10000001"]["abstract"], "BACKGROUND: Cortical thickness differs.\n\nMETHODS: We pooled n = 12 studies.")

    def test_medline_date_year(self):
        self.assertEqual(self.by["10000001"]["year"], "2019")
        self.assertEqual(self.by["10000002"]["year"], "2021")

    def test_authors_including_collective_name(self):
        self.assertEqual(self.by["10000001"]["authors"], [
            {"last": "Smith", "first": "Jane A", "raw": "Smith Jane A"},
            {"last": "ENIGMA ASD Working Group", "first": None, "raw": "ENIGMA ASD Working Group"},
        ])
        self.assertEqual(self.by["10000002"]["authors"][0]["first"], "K")

    def test_ids_types_mesh_grants(self):
        r = self.by["10000001"]
        self.assertEqual((r["doi"], r["pmcid"]), ("10.1000/test.1", "PMC9000001"))
        self.assertEqual(r["journal"], "J Test Neurosci")
        self.assertIn("Review", r["publication_types"])
        self.assertEqual(r["mesh_terms"], ["Autism Spectrum Disorder", "Cerebral Cortex"])
        self.assertEqual(r["grants"], [{"agency": "NIMH NIH HHS", "grant_id": "R01 MH000001", "raw": "R01 MH000001 NIMH NIH HHS"}])

    def test_missing_abstract_and_ids_are_null(self):
        r = self.by["10000002"]
        self.assertIsNone(r["abstract"])
        self.assertIsNone(r["doi"])
        self.assertIsNone(r["pmcid"])
        self.assertEqual(r["title"], "Surface area and SHANK3.")
        self.assertEqual(r["journal"], "Test Reports")

    def test_refuses_entity_declarations(self):
        bomb = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><PubmedArticleSet>&a;</PubmedArticleSet>'
        with self.assertRaises(lib_eutils.EutilsError):
            lib_eutils.parse_pubmed_xml(bomb)

    def test_missing_email_is_an_actionable_error(self):
        with self.assertRaises(lib_eutils.EutilsError) as ctx:
            lib_eutils.ncbi_credentials({})
        self.assertIn("ncbi_email", str(ctx.exception))
        self.assertEqual(lib_eutils.ncbi_credentials({"unpaywall_email": "a@b.org"}), ("a@b.org", None))


class TestInitAndBatches(TriageFixture):
    def test_init_requires_saved_query_and_existing_project(self):
        with self.assertRaises(triage.TriageError):
            triage.init(self.root, "no-such-query")
        with self.assertRaises(triage.TriageError):
            triage.init(self.root, "asd-ct", "no-such-project")

    def test_init_is_idempotent_and_refuses_silent_relink(self):
        first = triage.init(self.root, "asd-ct")
        self.assertTrue(first["created"])
        self.assertEqual(first["found"], 5)
        self.assertFalse(triage.init(self.root, "asd-ct")["created"])
        with self.assertRaises(triage.TriageError):
            triage.init(self.root, "asd-ct", "proj-a")

    def test_batches_follow_display_order_and_skip_loaded(self):
        triage.init(self.root, "asd-ct")
        fetcher = FakeFetcher()
        r1 = triage.load_batch(self.root, "asd-ct", 2, fetcher=fetcher)
        r2 = triage.load_batch(self.root, "asd-ct", 2, fetcher=fetcher)
        self.assertEqual(fetcher.calls, [PMIDS[:2], PMIDS[2:4]])
        self.assertEqual((r1["batch"], r2["batch"], r2["remaining"]), (1, 2, 1))
        records, _ = triage.loaded_records(self.root, "asd-ct")
        self.assertEqual(sorted(records), PMIDS[:4])

    def test_missing_pmids_are_not_retried_forever(self):
        triage.init(self.root, "asd-ct")
        triage.load_batch(self.root, "asd-ct", 5, fetcher=FakeFetcher(missing={PMIDS[1]}))
        r = triage.load_batch(self.root, "asd-ct", 5, fetcher=FakeFetcher())
        self.assertEqual((r["loaded"], r["remaining"]), (0, 0))
        self.assertEqual(triage.view(self.root, "asd-ct", rows=[])["counts"]["missing"], 1)

    def test_failed_fetch_leaves_earlier_batches_intact(self):
        triage.init(self.root, "asd-ct")
        triage.load_batch(self.root, "asd-ct", 2, fetcher=FakeFetcher())
        before = sorted(p.name for p in (self.root / "queries" / "asd-ct" / "metadata").iterdir())
        with self.assertRaises(lib_eutils.EutilsError):
            triage.load_batch(self.root, "asd-ct", 2, fetcher=FakeFetcher(fail=True))
        after = sorted(p.name for p in (self.root / "queries" / "asd-ct" / "metadata").iterdir())
        self.assertEqual(before, after)

    def test_explicit_pmids_must_belong_to_the_search(self):
        triage.init(self.root, "asd-ct")
        with self.assertRaises(triage.TriageError):
            triage.load_batch(self.root, "asd-ct", pmids=["99999999"], fetcher=FakeFetcher())

    def test_saved_query_file_is_never_modified(self):
        qpath = self.root / "queries" / "asd-ct" / "query.yaml"
        before = qpath.read_bytes()
        self.init_loaded()
        triage.decide(self.root, "asd-ct", PMIDS[:2], "included")
        self.assertEqual(qpath.read_bytes(), before)


class TestLegacyLayoutMigration(TriageFixture):
    def make_legacy(self):
        """Rewind the fixture to the old queries/<slug>.yaml + triage/<slug>/ layout."""
        self.init_loaded("proj-a")
        triage.decide(self.root, "asd-ct", PMIDS[:1], "excluded")
        qdir = self.root / "queries" / "asd-ct"
        (self.root / "queries" / "asd-ct.yaml").write_bytes((qdir / "query.yaml").read_bytes())
        (qdir / "query.yaml").unlink()
        shutil.move(str(qdir), str(self.root / "triage" / "asd-ct"))

    def test_legacy_library_is_migrated_on_first_access(self):
        self.make_legacy()
        self.assertEqual(pubmed_query.list_queries(self.root), ["asd-ct"])
        qdir = self.root / "queries" / "asd-ct"
        self.assertTrue((qdir / "query.yaml").is_file())
        self.assertTrue((qdir / "triage.json").is_file())
        self.assertTrue((qdir / "decisions.jsonl").is_file())
        self.assertTrue((qdir / "metadata").is_dir())
        self.assertFalse((self.root / "queries" / "asd-ct.yaml").exists())
        self.assertFalse((self.root / "triage").exists())
        self.assertEqual(project.linked_triages(self.root, "proj-a"), ["asd-ct"])
        self.assertEqual(triage.view(self.root, "asd-ct", rows=[])["counts"]["decisions"]["excluded"], 1)

    def test_migration_never_overwrites_existing_targets(self):
        self.make_legacy()
        (self.root / "queries" / "asd-ct").mkdir()
        (self.root / "queries" / "asd-ct" / "triage.json").write_text('{"slug": "asd-ct", "project": null}')
        pubmed_query.list_queries(self.root)
        self.assertEqual(json.loads((self.root / "queries" / "asd-ct" / "triage.json").read_text())["project"], None)
        self.assertTrue((self.root / "triage" / "asd-ct" / "triage.json").is_file())


class TestDecisions(TriageFixture):
    def test_newest_wins_cleared_unsets_and_maybe_is_pending(self):
        self.init_loaded()
        triage.decide(self.root, "asd-ct", [PMIDS[0]], "pending")
        triage.decide(self.root, "asd-ct", [PMIDS[0]], "excluded", "off-topic")
        triage.decide(self.root, "asd-ct", [PMIDS[1]], "excluded")
        triage.decide(self.root, "asd-ct", [PMIDS[1]], "cleared")
        latest = triage.latest_decisions(self.root, "asd-ct")
        self.assertEqual(latest[PMIDS[0]]["decision"], "excluded")
        self.assertEqual(latest[PMIDS[0]]["reason"], "off-topic")
        self.assertNotIn(PMIDS[1], latest)
        self.assertEqual(latest[PMIDS[0]]["run_id"][:4], "run-")

    def test_include_adds_and_is_idempotent(self):
        self.init_loaded()
        r1 = triage.decide(self.root, "asd-ct", [PMIDS[0]], "included")[0]
        r2 = triage.decide(self.root, "asd-ct", [PMIDS[0]], "included")[0]
        self.assertEqual((r1["result"], r1["add"]), ("recorded", "added"))
        self.assertEqual(r2["add"], "already_present")
        meta = json.loads((self.root / "papers" / PMIDS[0] / "meta.json").read_text())
        self.assertEqual(meta["title"], f"Paper {PMIDS[0]}")
        raw = next((self.root / "papers" / PMIDS[0] / "raw").glob("*/response.json"))
        self.assertNotIn("mesh_terms", json.loads(raw.read_text()), "display-only fields stay out of the add envelope")

    def test_include_without_metadata_logs_nothing(self):
        triage.init(self.root, "asd-ct")
        r = triage.decide(self.root, "asd-ct", [PMIDS[0]], "included")[0]
        self.assertEqual(r["result"], "failed")
        self.assertFalse((self.root / "papers" / PMIDS[0]).exists())
        self.assertEqual(triage.latest_decisions(self.root, "asd-ct"), {})

    def test_one_failure_does_not_block_the_rest(self):
        self.init_loaded(size=2)
        results = triage.decide(self.root, "asd-ct", [PMIDS[0], "99999999", PMIDS[4], PMIDS[1]], "included")
        self.assertEqual([r["result"] for r in results], ["recorded", "failed", "failed", "recorded"])

    def test_exclude_after_include_leaves_library_untouched(self):
        self.init_loaded()
        triage.decide(self.root, "asd-ct", [PMIDS[0]], "included")
        pdir = self.root / "papers" / PMIDS[0]
        snapshot = {p.relative_to(pdir): p.read_bytes() for p in pdir.rglob("*") if p.is_file()}
        triage.decide(self.root, "asd-ct", [PMIDS[0]], "excluded")
        after = {p.relative_to(pdir): p.read_bytes() for p in pdir.rglob("*") if p.is_file()}
        self.assertEqual(snapshot, after)

    def test_linked_project_gets_screening_with_search_run(self):
        self.init_loaded("proj-a")
        triage.decide(self.root, "asd-ct", [PMIDS[0]], "included", "adult sample")
        triage.decide(self.root, "asd-ct", [PMIDS[1]], "cleared")
        lines = self.screening_lines()
        self.assertEqual([(x["pmid"], x["decision"]) for x in lines], [(PMIDS[0], "included"), (PMIDS[1], "pending")])
        self.assertTrue(lines[0]["search_run"].startswith("run-"))
        members = json.loads((self.root / "projects" / "proj-a" / "papers.yaml").read_text())["papers"]
        self.assertEqual({m["pmid"] for m in members}, {PMIDS[0], PMIDS[1]})

    def test_linking_later_replays_current_decisions_once(self):
        self.init_loaded()
        triage.decide(self.root, "asd-ct", [PMIDS[0]], "included")
        triage.decide(self.root, "asd-ct", [PMIDS[1]], "excluded", "wrong modality")
        triage.decide(self.root, "asd-ct", [PMIDS[2]], "pending")
        triage.decide(self.root, "asd-ct", [PMIDS[2]], "cleared")
        res = triage.link(self.root, "asd-ct", "proj-a")
        self.assertEqual(res["replayed"], 2)
        again = triage.link(self.root, "asd-ct", "proj-a")
        self.assertEqual(again["replayed"], 0)
        lines = self.screening_lines()
        self.assertEqual(sorted((x["pmid"], x["decision"]) for x in lines), [(PMIDS[0], "included"), (PMIDS[1], "excluded")])
        self.assertEqual(lines[[x["pmid"] for x in lines].index(PMIDS[1])]["reason"], "triage:asd-ct: wrong modality")
        self.assertEqual(project.show(self.root, "proj-a")["triages"], ["asd-ct"])
        self.assertEqual([t["slug"] for t in triage.list_triages(self.root, "proj-a")], ["asd-ct"])

    def test_prisma_counts_triage_screening(self):
        import prisma

        self.init_loaded("proj-a")
        triage.decide(self.root, "asd-ct", [PMIDS[0], PMIDS[1]], "included")
        triage.decide(self.root, "asd-ct", [PMIDS[2]], "excluded", "off-topic")
        flow = prisma.build_flow(self.root, "proj-a", [("asd-ct", None)])
        self.assertEqual(flow["identified"]["total_raw"], 5)
        self.assertEqual(flow["screened"], 3)
        self.assertEqual(flow["excluded"]["count"], 1)
        self.assertEqual(flow["excluded"]["by_reason"], {"off-topic": 1})

    def test_unlink_keeps_project_history(self):
        self.init_loaded("proj-a")
        triage.decide(self.root, "asd-ct", [PMIDS[0]], "excluded")
        triage.link(self.root, "asd-ct", None)
        self.assertIsNone(triage.load(self.root, "asd-ct")["project"])
        self.assertEqual(len(self.screening_lines()), 1)

    def test_concurrent_decisions_into_one_project(self):
        pmids = [str(20000000 + i) for i in range(20)]
        pubmed_query.new_run(self.root, "many", "q", "pubmed", pmids, True)
        triage.init(self.root, "many", "proj-a")
        triage.load_batch(self.root, "many", fetcher=FakeFetcher())
        threads = [threading.Thread(target=triage.decide, args=(self.root, "many", [p], "pending")) for p in pmids]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        members = json.loads((self.root / "projects" / "proj-a" / "papers.yaml").read_text())["papers"]
        self.assertEqual(sorted(m["pmid"] for m in members), pmids)
        self.assertEqual(len(triage.latest_decisions(self.root, "many")), 20)


class TestRerunSync(TriageFixture):
    def test_sync_reports_new_and_dropped_and_keeps_decisions(self):
        self.init_loaded()
        triage.decide(self.root, "asd-ct", [PMIDS[0]], "excluded")
        pubmed_query.rerun(self.root, "asd-ct", [PMIDS[5], PMIDS[1], PMIDS[2], PMIDS[3], PMIDS[4], PMIDS[6]])
        res = triage.sync(self.root, "asd-ct")
        self.assertEqual(res["new_pmids"], [PMIDS[5], PMIDS[6]])
        self.assertEqual(res["dropped_pmids"], [PMIDS[0]])
        self.assertEqual(triage.next_unloaded(self.root, "asd-ct")[0], [PMIDS[5], PMIDS[6]])

        v = triage.view(self.root, "asd-ct", rows=[])
        by = {p["pmid"]: p for p in v["papers"]}
        self.assertEqual([p["pmid"] for p in v["papers"]][:2], [PMIDS[5], PMIDS[1]])
        self.assertEqual(v["papers"][-1]["pmid"], PMIDS[0])
        self.assertFalse(by[PMIDS[0]]["in_latest_run"])
        self.assertEqual(by[PMIDS[0]]["decision"]["decision"], "excluded")
        self.assertIsNotNone(by[PMIDS[5]]["new_since"])
        self.assertIsNone(by[PMIDS[1]]["new_since"])
        self.assertEqual(v["counts"]["new"], 2)
        self.assertEqual(v["unsynced_runs"], [])


class TestAcquisition(TriageFixture):
    def test_pdf_job_attaches_or_queues_and_includes_undecided(self):
        self.init_loaded()
        triage.decide(self.root, "asd-ct", [PMIDS[2]], "excluded")
        outcomes = {PMIDS[0]: "attached", PMIDS[1]: "no_pdf", PMIDS[2]: "no_pmcid"}
        seen = []

        def fake_pdf(root, pmid):
            seen.append(pmid)
            self.assertTrue((root / "papers" / pmid / "meta.json").exists())
            return {"pmid": pmid, "result": outcomes[pmid]}

        progress = []
        results = triage.acquire_pdfs(self.root, "asd-ct", list(outcomes), pdf_fetcher=fake_pdf, progress=progress.append)
        self.assertEqual(seen, list(outcomes))
        self.assertEqual(len(progress), 3)
        self.assertEqual(sorted(triage.pending(self.root, "asd-ct")), [PMIDS[1], PMIDS[2]])
        self.assertEqual(triage.pending(self.root, "asd-ct")[PMIDS[1]]["why"], "no_pdf")
        latest = triage.latest_decisions(self.root, "asd-ct")
        self.assertEqual(latest[PMIDS[0]]["decision"], "included")
        self.assertEqual(latest[PMIDS[2]]["decision"], "excluded", "an existing decision is not overwritten")
        self.assertFalse(results[0].get("pending"))

    def test_pdf_fetcher_exception_is_per_pmid(self):
        self.init_loaded()

        def boom(root, pmid):
            if pmid == PMIDS[0]:
                raise RuntimeError("network down")
            return {"pmid": pmid, "result": "attached"}

        results = triage.acquire_pdfs(self.root, "asd-ct", [PMIDS[0], PMIDS[1]], pdf_fetcher=boom)
        self.assertEqual([r["result"] for r in results], ["failed", "attached"])
        self.assertEqual(list(triage.pending(self.root, "asd-ct")), [PMIDS[0]])

    def test_full_text_queue_and_clear(self):
        self.init_loaded()
        res = triage.queue_full_text(self.root, "asd-ct", [PMIDS[0], PMIDS[1]])
        self.assertEqual([r["result"] for r in res], ["queued", "queued"])
        self.assertTrue((self.root / "papers" / PMIDS[0] / "meta.json").exists())
        out = triage.clear_pending(self.root, "asd-ct", [PMIDS[0], "99999999"])
        self.assertEqual((out["cleared"], out["remaining"]), ([PMIDS[0]], [PMIDS[1]]))


class TestP3FollowUps(TriageFixture):
    """PUBMED_TRIAGE_IMPLEMENTATION_PLAN.md P3: PRISMA defaults to linked
    triages, --triage selector (export), per-project reason chips."""

    def test_prisma_defaults_to_linked_triages(self):
        import prisma

        self.init_loaded("proj-a")
        triage.decide(self.root, "asd-ct", [PMIDS[0]], "included")
        triage.decide(self.root, "asd-ct", [PMIDS[1]], "excluded", "wrong population")
        result = prisma.run_prisma(self.root, "proj-a", [], refresh=False)
        manifest = result["manifest"]
        self.assertEqual(manifest["query_source"], "linked_triages")
        self.assertEqual(manifest["query_specs"], [{"query": "asd-ct", "run": None}])
        flow = manifest["flow"]
        self.assertEqual(flow["identified"]["total_raw"], 5)
        self.assertEqual(flow["excluded"]["by_reason"], {"wrong population": 1})

    def test_prisma_explicit_query_wins_and_no_link_stays_unknown(self):
        import prisma

        project.create(self.root, "proj-b", None)
        self.init_loaded("proj-a")
        manifest = prisma.run_prisma(self.root, "proj-b", [], refresh=False)["manifest"]
        self.assertEqual(manifest["query_source"], "none")
        manifest = prisma.run_prisma(self.root, "proj-a", [("asd-ct", None)], refresh=True)["manifest"]
        self.assertEqual(manifest["query_source"], "explicit")

    def test_triage_selector(self):
        import lib_selector

        self.init_loaded()
        triage.decide(self.root, "asd-ct", PMIDS[:2], "included")
        triage.decide(self.root, "asd-ct", [PMIDS[2]], "excluded")  # never added -> not a library paper
        triage.decide(self.root, "asd-ct", [PMIDS[1]], "excluded")  # included then excluded: stays in library
        res = lib_selector.resolve(self.root, triage="asd-ct")
        self.assertEqual(res["pmids"], [PMIDS[0]])
        self.assertIn("--triage asd-ct", res["selector_expression"])
        res = lib_selector.resolve(self.root, triage="asd-ct", screened="excluded")
        self.assertEqual(res["pmids"], [PMIDS[1]])
        with self.assertRaises(lib_selector.SelectorError):
            lib_selector.resolve(self.root, triage="nope")
        with self.assertRaises(lib_selector.SelectorError):
            lib_selector.resolve(self.root, triage="asd-ct", screened="pending")  # matches nothing
        with self.assertRaises(lib_selector.SelectorError):
            lib_selector.resolve(self.root, pmids=[PMIDS[0]], screened="included")  # still needs a scope

    def test_export_papers_cli_accepts_triage(self):
        import subprocess

        self.init_loaded()
        triage.decide(self.root, "asd-ct", PMIDS[:2], "included")
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS / "export_papers.py"), "--triage", "asd-ct", "--repo", str(self.root),
             "--dry-run", "--pdfs", "none"],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(sorted(json.loads(proc.stdout)["manifest"]["pmids"]), sorted(PMIDS[:2]))

    def test_reason_chips_default_and_per_project(self):
        self.init_loaded()
        self.assertEqual(triage.view(self.root, "asd-ct")["reasons"], project.DEFAULT_SCREENING_REASONS)
        triage.link(self.root, "asd-ct", "proj-a")
        out = project.set_reasons(self.root, "proj-a", "excluded", ["  adult  sample only", "no MRI", "no MRI"])
        self.assertEqual(out["screening_reasons"]["excluded"], ["adult sample only", "no MRI"])
        reasons = triage.view(self.root, "asd-ct")["reasons"]
        self.assertEqual(reasons["excluded"], ["adult sample only", "no MRI"])
        self.assertEqual(reasons["pending"], project.DEFAULT_SCREENING_REASONS["pending"])
        triage.decide(self.root, "asd-ct", [PMIDS[0]], "excluded", "no MRI")
        self.assertEqual(self.screening_lines()[-1]["reason"], "no MRI")
        self.assertEqual(triage.view(self.root, "asd-ct")["papers"][0]["decision"]["reason"], "no MRI")

        project.set_reasons(self.root, "proj-a", "excluded", None)
        self.assertNotIn("screening_reasons", json.loads((self.root / "projects" / "proj-a" / "project.yaml").read_text()))
        with self.assertRaises(project.SchemaError):
            project.set_reasons(self.root, "proj-a", "maybe", ["x"])
        with self.assertRaises(project.SchemaError):
            project.set_reasons(self.root, "proj-a", "excluded", ["x" * 121])
        with self.assertRaises(project.SlugError):
            project.set_reasons(self.root, "missing", "excluded", ["x"])

    def test_set_reasons_cli(self):
        import subprocess

        script = str(SCRIPTS / "project.py")
        base = [sys.executable, script, "set-reasons", "--repo", str(self.root), "--slug", "proj-a", "--decision", "excluded"]
        proc = subprocess.run(base + ["--reason", "wrong age", "--reason", "animal study"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["screening_reasons"]["excluded"], ["wrong age", "animal study"])
        self.assertNotEqual(subprocess.run(base, capture_output=True, text=True).returncode, 0)
        proc = subprocess.run(base + ["--reset"], capture_output=True, text=True)
        self.assertEqual(json.loads(proc.stdout)["screening_reasons"]["excluded"], project.DEFAULT_SCREENING_REASONS["excluded"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
