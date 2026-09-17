#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""`/ref:triage` -- screen a saved PubMed search (PUBMED_TRIAGE_IMPLEMENTATION_PLAN.md).

One triage per saved query (T2): `triage/<slug>/` sits beside
`queries/<slug>.yaml`, never inside it, so saved runs stay immutable (D15).

  triage/<slug>/triage.json              {slug, project|null, created_at, project_linked_at,
                                          synced_run_ids, batch_size}
  triage/<slug>/metadata/batch-NNNN.json one efetch batch: {batch, loaded_at, source,
                                          records[add.py envelope + display fields], missing}
  triage/<slug>/decisions.jsonl          append-only {pmid, decision, reason, timestamp,
                                          run_id, origin}; newest line per PMID wins
  triage/<slug>/pending.json             {pmid: {kind, why, queued_at}} -- full-text work
                                          only Claude can do (MCP / WebFetch)

Decision rules (§5): included -> add.add_one() first (T4), then the linked
project's screen.decide(), then the triage log. excluded never touches the
library. `cleared` un-sets a decision and mirrors to a project as `pending`.
A project is optional (T3); linking one later replays every current decision
into its screening log.

Project -> triages is derived by scanning triage/*/triage.json; project.yaml
is not changed (§4.1).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import add as add_module
import lib_eutils
import lib_inventory
import project as project_module
import screen as screen_module
from lib_atomic import atomic_write_json, triage_lock, now_iso, read_json
from lib_ids import SlugError, validate_slug
from lib_schema import SchemaError

DECISIONS = ("included", "excluded", "pending", "cleared")
BATCH_SIZE = 100
ENVELOPE_KEYS = ("pmid", "title", "abstract", "authors", "journal", "year", "doi", "pmcid", "grants")
# fetch_pmc_pdf_one results that mean "no PDF here -- Claude has to try the full-text ladder"
PDF_TO_PENDING = ("no_pdf", "no_pmcid", "refused", "failed")


class TriageError(Exception):
    pass


def _dir(library_root: Path, slug: str) -> Path:
    validate_slug(slug)
    return library_root / "triage" / slug


def _query_doc(library_root: Path, slug: str) -> dict:
    validate_slug(slug)
    p = library_root / "queries" / f"{slug}.yaml"
    if not p.exists():
        raise TriageError(f"saved query {slug!r} does not exist -- run /ref:search-pubmed --slug {slug} --create first")
    return json.loads(p.read_text())


def _require_project(library_root: Path, project: str) -> None:
    validate_slug(project)
    if not (library_root / "projects" / project / "project.yaml").exists():
        raise TriageError(f"project {project!r} does not exist -- create it with /ref:project create {project}")


def exists(library_root: Path, slug: str) -> bool:
    return (_dir(library_root, slug) / "triage.json").exists()


def load(library_root: Path, slug: str) -> dict:
    p = _dir(library_root, slug) / "triage.json"
    if not p.exists():
        raise TriageError(f"no triage for {slug!r} -- run /ref:triage {slug} to create one")
    return json.loads(p.read_text())


# ------------------------------------------------------------ runs / order


def display_order(runs: list[dict]) -> list[str]:
    """Latest run's PubMed order, then PMIDs only earlier runs returned
    (newest earlier run first)."""
    seen, order = set(), []
    for run in reversed(runs):
        for pmid in run.get("pmids", []):
            if pmid not in seen:
                seen.add(pmid)
                order.append(pmid)
    return order


def first_seen(runs: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for i, run in enumerate(runs):
        for pmid in run.get("pmids", []):
            out.setdefault(pmid, i)
    return out


def _run_for(runs: list[dict], pmid: str) -> str | None:
    for run in reversed(runs):
        if pmid in run.get("pmids", []):
            return run["run_id"]
    return None


# ------------------------------------------------------------ create / sync


def init(library_root: Path, slug: str, project: str | None = None) -> dict:
    runs = _query_doc(library_root, slug).get("runs", [])
    if project:
        _require_project(library_root, project)
    d = _dir(library_root, slug)
    with triage_lock(library_root, slug):
        if (d / "triage.json").exists():
            existing = json.loads((d / "triage.json").read_text())
            if project and existing.get("project") != project:
                raise TriageError(
                    f"triage {slug!r} already exists (project: {existing.get('project')}) -- "
                    f"use /ref:triage {slug} --project {project} to link it"
                )
            created = False
        else:
            now = now_iso()
            atomic_write_json(d / "triage.json", {
                "slug": slug, "project": project, "created_at": now,
                "project_linked_at": now if project else None,
                "synced_run_ids": [], "batch_size": BATCH_SIZE,
            })
            created = True
    result = sync(library_root, slug)
    result["created"] = created
    result["found"] = len(display_order(runs))
    return result


def sync(library_root: Path, slug: str) -> dict:
    """Record runs appended since the last sync (e.g. by /ref:update-queries)
    and report which PMIDs they brought in or dropped."""
    runs = _query_doc(library_root, slug).get("runs", [])
    d = _dir(library_root, slug)
    with triage_lock(library_root, slug):
        tri = load(library_root, slug)
        synced = set(tri.get("synced_run_ids", []))
        new_runs = [r for r in runs if r["run_id"] not in synced]
        previous = [r for r in runs if r["run_id"] in synced]
        before = {p for r in previous for p in r.get("pmids", [])}
        new_pmids: list[str] = []
        for r in new_runs:
            for p in r.get("pmids", []):
                if p not in before and p not in new_pmids:
                    new_pmids.append(p)
        dropped = []
        if previous and runs:
            latest = set(runs[-1].get("pmids", []))
            dropped = sorted(set(previous[-1].get("pmids", [])) - latest)
        tri["synced_run_ids"] = [r["run_id"] for r in runs]
        atomic_write_json(d / "triage.json", tri)
    # A first sync (fresh triage) reports nothing as "new".
    return {
        "slug": slug, "new_runs": [r["run_id"] for r in new_runs],
        "new_pmids": new_pmids if previous else [], "dropped_pmids": dropped,
    }


# ------------------------------------------------------------ metadata batches


def _batch_files(library_root: Path, slug: str) -> list[Path]:
    return sorted((_dir(library_root, slug) / "metadata").glob("batch-*.json"))


def loaded_records(library_root: Path, slug: str) -> tuple[dict[str, dict], set[str]]:
    """(pmid -> record, PMIDs efetch returned nothing for) across all batches."""
    records: dict[str, dict] = {}
    missing: set[str] = set()
    for f in _batch_files(library_root, slug):
        doc = json.loads(f.read_text())
        for rec in doc.get("records", []):
            records[rec["pmid"]] = rec
            missing.discard(rec["pmid"])
        missing.update(p for p in doc.get("missing", []) if p not in records)
    return records, missing


def next_unloaded(library_root: Path, slug: str, size: int = BATCH_SIZE) -> tuple[list[str], int]:
    runs = _query_doc(library_root, slug).get("runs", [])
    records, missing = loaded_records(library_root, slug)
    todo = [p for p in display_order(runs) if p not in records and p not in missing]
    return todo[:size], len(todo)


def _default_fetcher(pmids: list[str]) -> tuple[list[dict], list[str]]:
    email, api_key = lib_eutils.ncbi_credentials()
    return lib_eutils.efetch_pubmed(pmids, email=email, api_key=api_key)


def load_batch(library_root: Path, slug: str, size: int = BATCH_SIZE,
               pmids: list[str] | None = None, fetcher=None) -> dict:
    """Fetch metadata for the next `size` unloaded PMIDs (or an explicit
    list) and write one batch file. Nothing is written if the fetch fails,
    so earlier batches stay valid."""
    load(library_root, slug)
    runs = _query_doc(library_root, slug).get("runs", [])
    if pmids is None:
        pmids, _ = next_unloaded(library_root, slug, size)
    else:
        found = set(display_order(runs))
        stray = [p for p in pmids if p not in found]
        if stray:
            raise TriageError(f"PMIDs not in saved search {slug!r}: {', '.join(stray[:5])}")
    if not pmids:
        return {"slug": slug, "batch": None, "loaded": 0, "missing": [], "remaining": 0}

    records, missing = (fetcher or _default_fetcher)(pmids)
    d = _dir(library_root, slug) / "metadata"
    with triage_lock(library_root, slug):
        n = len(_batch_files(library_root, slug)) + 1
        while (d / f"batch-{n:04d}.json").exists():
            n += 1
        atomic_write_json(d / f"batch-{n:04d}.json", {
            "batch": n, "loaded_at": now_iso(), "source": "ncbi_efetch",
            "records": records, "missing": missing,
        })
    _, remaining = next_unloaded(library_root, slug, 0)
    return {"slug": slug, "batch": n, "loaded": len(records), "missing": missing, "remaining": remaining}


# ------------------------------------------------------------ decisions


def latest_decisions(library_root: Path, slug: str) -> dict[str, dict]:
    p = _dir(library_root, slug) / "decisions.jsonl"
    out: dict[str, dict] = {}
    if not p.exists():
        return out
    for line in p.read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        if rec["decision"] == "cleared":
            out.pop(rec["pmid"], None)
        else:
            out[rec["pmid"]] = rec
    return out


def _envelope(rec: dict) -> dict:
    return {k: rec.get(k) for k in ENVELOPE_KEYS}


def _in_library(library_root: Path, pmid: str) -> bool:
    return (library_root / "papers" / pmid / "meta.json").exists()


def _ensure_added(library_root: Path, pmid: str, records: dict[str, dict]) -> str:
    if _in_library(library_root, pmid):
        return "already_present"
    rec = records.get(pmid)
    if rec is None:
        raise TriageError("metadata not loaded yet -- load its batch first")
    return add_module.add_one(library_root, _envelope(rec))["result"]


def _append_decision(library_root: Path, slug: str, record: dict) -> None:
    d = _dir(library_root, slug)
    with triage_lock(library_root, slug):
        d.mkdir(parents=True, exist_ok=True)
        with (d / "decisions.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, sort_keys=True) + "\n")


def decide(library_root: Path, slug: str, pmids: list[str], decision: str,
           reason: str | None = None, origin: str = "cli") -> list[dict]:
    if decision not in DECISIONS:
        raise TriageError(f"decision must be one of {DECISIONS}")
    tri = load(library_root, slug)
    runs = _query_doc(library_root, slug).get("runs", [])
    found = set(display_order(runs))
    records, _ = loaded_records(library_root, slug)
    reason = (reason or "").strip() or f"triage:{slug}"
    project = tri.get("project")

    results = []
    for pmid in pmids:
        out = {"pmid": pmid, "decision": decision}
        try:
            if pmid not in found:
                raise TriageError(f"not part of saved search {slug!r}")
            if decision == "included":
                out["add"] = _ensure_added(library_root, pmid, records)
            run_id = _run_for(runs, pmid)
            if project:
                screen_module.decide(
                    library_root, project, pmid,
                    "pending" if decision == "cleared" else decision, reason, run_id,
                )
            _append_decision(library_root, slug, {
                "pmid": pmid, "decision": decision, "reason": reason,
                "timestamp": now_iso(), "run_id": run_id, "origin": origin,
            })
            out["result"] = "recorded"
        except (TriageError, SchemaError, SlugError, ValueError, KeyError, OSError) as e:
            out["result"] = "failed"
            out["error"] = str(e)
        results.append(out)
    return results


def link(library_root: Path, slug: str, project: str | None) -> dict:
    tri = load(library_root, slug)
    if project:
        _require_project(library_root, project)
    if tri.get("project") == project:
        return {"slug": slug, "project": project, "replayed": 0, "failed": []}

    replayed, failed = 0, []
    if project:
        runs = _query_doc(library_root, slug).get("runs", [])
        for pmid, rec in latest_decisions(library_root, slug).items():
            try:
                screen_module.decide(
                    library_root, project, pmid, rec["decision"],
                    f"triage:{slug}: {rec.get('reason') or ''}".rstrip(": "),
                    rec.get("run_id") or _run_for(runs, pmid),
                )
                replayed += 1
            except (SchemaError, ValueError, OSError) as e:
                failed.append({"pmid": pmid, "error": str(e)})

    with triage_lock(library_root, slug):
        tri = load(library_root, slug)
        tri["project"] = project
        tri["project_linked_at"] = now_iso() if project else None
        atomic_write_json(_dir(library_root, slug) / "triage.json", tri)
    return {"slug": slug, "project": project, "replayed": replayed, "failed": failed}


# ------------------------------------------------------------ pending full text


def pending(library_root: Path, slug: str) -> dict[str, dict]:
    return read_json(_dir(library_root, slug) / "pending.json", {})


def queue_pending(library_root: Path, slug: str, items: dict[str, str], kind: str = "full_text") -> dict:
    """items: pmid -> why."""
    p = _dir(library_root, slug) / "pending.json"
    with triage_lock(library_root, slug):
        doc = read_json(p, {})
        for pmid, why in items.items():
            doc[pmid] = {"kind": kind, "why": why, "queued_at": now_iso()}
        atomic_write_json(p, doc)
    return doc


def clear_pending(library_root: Path, slug: str, pmids: list[str]) -> dict:
    p = _dir(library_root, slug) / "pending.json"
    with triage_lock(library_root, slug):
        doc = read_json(p, {})
        cleared = [x for x in pmids if doc.pop(x, None) is not None]
        atomic_write_json(p, doc)
    return {"cleared": cleared, "remaining": sorted(doc)}


def _prepare_for_fetch(library_root: Path, slug: str, pmid: str, records: dict[str, dict]) -> str | None:
    """Acquisition needs papers/<pmid>/meta.json. An undecided paper is
    included (which adds it); a paper with another decision is added
    without changing that decision."""
    if _in_library(library_root, pmid):
        return None
    if pmid not in latest_decisions(library_root, slug):
        res = decide(library_root, slug, [pmid], "included", origin="acquire")[0]
        if res["result"] != "recorded":
            raise TriageError(res.get("error", "could not add"))
        return res.get("add")
    return _ensure_added(library_root, pmid, records)


def acquire_pdfs(library_root: Path, slug: str, pmids: list[str], pdf_fetcher=None, progress=None) -> list[dict]:
    """PMC OA PDFs for `pmids`; anything without one goes to pending."""
    if pdf_fetcher is None:
        from fetch_pmc_pdf import fetch_pmc_pdf_one as pdf_fetcher
    load(library_root, slug)
    records, _ = loaded_records(library_root, slug)
    results = []
    for pmid in pmids:
        out = {"pmid": pmid}
        try:
            added = _prepare_for_fetch(library_root, slug, pmid, records)
            if added:
                out["add"] = added
            res = pdf_fetcher(library_root, pmid)
            out["result"] = res.get("result", "failed")
            for k in ("reason", "error", "note"):
                if res.get(k):
                    out[k] = res[k]
        except Exception as e:  # noqa: BLE001 -- one PMID's failure never blocks the rest
            out["result"] = "failed"
            out["error"] = str(e)
        if out["result"] in PDF_TO_PENDING and _in_library(library_root, pmid):
            queue_pending(library_root, slug, {pmid: out["result"]})
            out["pending"] = True
        results.append(out)
        if progress:
            progress(out)
    return results


def queue_full_text(library_root: Path, slug: str, pmids: list[str]) -> list[dict]:
    load(library_root, slug)
    records, _ = loaded_records(library_root, slug)
    library = {r["pmid"]: r for r in lib_inventory.rows(library_root)}
    results, items = [], {}
    for pmid in pmids:
        out = {"pmid": pmid}
        try:
            added = _prepare_for_fetch(library_root, slug, pmid, records)
            if added:
                out["add"] = added
            if (library.get(pmid) or {}).get("has_fulltext"):
                out["result"] = "already_full_text"
            else:
                items[pmid] = "requested"
                out["result"] = "queued"
        except (TriageError, SchemaError, ValueError, OSError) as e:
            out["result"] = "failed"
            out["error"] = str(e)
        results.append(out)
    if items:
        queue_pending(library_root, slug, items)
    return results


# ------------------------------------------------------------ views


def _library_state(row: dict | None) -> dict | None:
    if not row:
        return None
    return {
        "has_fulltext": bool(row.get("has_fulltext")), "has_pdf": bool(row.get("has_pdf")),
        "extraction_tier": row.get("extraction_tier"), "source_badge": row.get("source_badge"),
        "projects": [p.get("slug") for p in row.get("projects") or [] if p.get("slug")],
    }


def view(library_root: Path, slug: str, rows: list[dict] | None = None) -> dict:
    """Everything the Triage tab renders (§6.3). Read-only."""
    tri = load(library_root, slug)
    runs = _query_doc(library_root, slug).get("runs", [])
    order = display_order(runs)
    seen = first_seen(runs)
    latest_run = set(runs[-1].get("pmids", [])) if runs else set()
    records, missing = loaded_records(library_root, slug)
    decisions = latest_decisions(library_root, slug)
    pend = pending(library_root, slug)
    if rows is None:
        rows = lib_inventory.rows(library_root)
    library = {r["pmid"]: r for r in rows}

    counts = {
        "found": len(order), "loaded": 0, "missing": 0, "new": 0, "pending": len(pend),
        "decisions": {"included": 0, "pending": 0, "excluded": 0, "undecided": 0},
        "library": {"pdf": 0, "fulltext": 0, "abstract": 0, "none": 0},
        "pmc": 0,
    }
    papers = []
    for pmid in order:
        rec = records.get(pmid)
        lib = _library_state(library.get(pmid))
        dec = decisions.get(pmid)
        first = seen.get(pmid, 0)
        new_since = runs[first - 1]["retrieved_at"] if first > 0 else None
        papers.append({
            "pmid": pmid,
            "loaded": rec is not None,
            "missing": pmid in missing,
            "metadata": None if rec is None else {
                "title": rec.get("title"), "abstract": rec.get("abstract"),
                "authors": [a.get("last") for a in (rec.get("authors") or [])[:3]],
                "authors_count": len(rec.get("authors") or []),
                "journal": rec.get("journal"), "year": rec.get("year"),
                "doi": rec.get("doi"), "pmcid": rec.get("pmcid"),
                "publication_types": rec.get("publication_types") or [],
                "mesh_terms": (rec.get("mesh_terms") or [])[:12],
            },
            "decision": None if dec is None else {k: dec.get(k) for k in ("decision", "reason", "timestamp")},
            "new_since": new_since,
            "in_latest_run": pmid in latest_run,
            "pending": pend.get(pmid),
            "library": lib,
        })
        if rec is not None:
            counts["loaded"] += 1
            if rec.get("pmcid"):
                counts["pmc"] += 1
        if pmid in missing:
            counts["missing"] += 1
        if new_since:
            counts["new"] += 1
        if dec:
            counts["decisions"][dec["decision"]] = counts["decisions"].get(dec["decision"], 0) + 1
        elif rec is not None:
            counts["decisions"]["undecided"] += 1
        if lib is None:
            counts["library"]["none"] += 1
        elif lib["has_pdf"]:
            counts["library"]["pdf"] += 1
        elif lib["has_fulltext"]:
            counts["library"]["fulltext"] += 1
        else:
            counts["library"]["abstract"] += 1

    return {
        "triage": {k: tri.get(k) for k in ("slug", "project", "created_at", "project_linked_at", "batch_size")},
        "query": runs[-1]["query"] if runs else None,
        "runs": [{"run_id": r["run_id"], "retrieved_at": r["retrieved_at"], "count": len(r.get("pmids", []))} for r in runs],
        "unsynced_runs": [r["run_id"] for r in runs if r["run_id"] not in set(tri.get("synced_run_ids", []))],
        "counts": counts,
        "remaining": len([p for p in order if p not in records and p not in missing]),
        "reasons": project_module.screening_reasons(library_root, tri.get("project")),
        "papers": papers,
    }


def list_triages(library_root: Path, project: str | None = None) -> list[dict]:
    base = library_root / "triage"
    out = []
    if not base.is_dir():
        return out
    for d in sorted(base.iterdir()):
        tp = d / "triage.json"
        if not tp.is_file():
            continue
        tri = json.loads(tp.read_text())
        if project is not None and tri.get("project") != project:
            continue
        slug = tri["slug"]
        try:
            runs = _query_doc(library_root, slug).get("runs", [])
        except (TriageError, SlugError):
            runs = []
        records, _ = loaded_records(library_root, slug)
        out.append({
            "slug": slug, "project": tri.get("project"),
            "query": runs[-1]["query"] if runs else None,
            "found": len(display_order(runs)), "loaded": len(records),
            "decided": len(latest_decisions(library_root, slug)),
            "pending": len(pending(library_root, slug)),
            "last_run_at": runs[-1]["retrieved_at"] if runs else None,
        })
    return out


# ------------------------------------------------------------ CLI


def _summary(v: dict) -> dict:
    c = v["counts"]
    return {
        "slug": v["triage"]["slug"], "project": v["triage"]["project"], "query": v["query"],
        "runs": len(v["runs"]), "found": c["found"], "loaded": c["loaded"], "remaining": v["remaining"],
        "missing": c["missing"], "decisions": c["decisions"], "library": c["library"],
        "new_since_earlier_runs": c["new"], "pending_full_text": c["pending"],
        "unsynced_runs": v["unsynced_runs"],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=[
        "init", "sync", "load-batch", "decide", "link", "pending", "clear-pending", "show", "list",
    ])
    ap.add_argument("--repo", required=True)
    ap.add_argument("--slug")
    ap.add_argument("--project", help="init/link: project slug; list: filter by project")
    ap.add_argument("--no-project", action="store_true", help="link: unlink the project")
    ap.add_argument("--size", type=int, default=BATCH_SIZE)
    ap.add_argument("--pmids-file", help="JSON array of PMIDs")
    ap.add_argument("--decision", choices=DECISIONS)
    ap.add_argument("--reason")
    ap.add_argument("--full", action="store_true", help="show: the whole view model, not the summary")
    args = ap.parse_args()

    library_root = Path(args.repo).expanduser().resolve()
    if not library_root.is_dir():
        print(f"error: no library at {library_root}", file=sys.stderr)
        return 1
    if args.action != "list" and not args.slug:
        print("error: --slug is required", file=sys.stderr)
        return 1
    pmids = json.loads(Path(args.pmids_file).read_text()) if args.pmids_file else None

    try:
        if args.action == "init":
            result = init(library_root, args.slug, args.project)
        elif args.action == "sync":
            result = sync(library_root, args.slug)
        elif args.action == "load-batch":
            if not 1 <= args.size <= 500:
                raise TriageError("--size must be between 1 and 500")
            result = load_batch(library_root, args.slug, args.size, pmids)
        elif args.action == "decide":
            if not (args.decision and pmids):
                raise TriageError("--decision and --pmids-file are required")
            result = decide(library_root, args.slug, pmids, args.decision, args.reason)
        elif args.action == "link":
            if not (args.project or args.no_project):
                raise TriageError("pass --project <slug> or --no-project")
            result = link(library_root, args.slug, None if args.no_project else args.project)
        elif args.action == "pending":
            result = pending(library_root, args.slug)
        elif args.action == "clear-pending":
            if not pmids:
                raise TriageError("--pmids-file is required")
            result = clear_pending(library_root, args.slug, pmids)
        elif args.action == "show":
            v = view(library_root, args.slug)
            result = v if args.full else _summary(v)
        else:
            result = list_triages(library_root, args.project)
    except (TriageError, SlugError, SchemaError, lib_eutils.EutilsError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
