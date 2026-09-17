#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""`/ref:review --prisma --project <slug>` -- PRISMA 2020 flow record (§5a).

Every count is a query over already-committed state, never a re-derivation:
  - identified   <- queries/<slug>.yaml immutable run histories (explicit
                     --query <slug> args select which saved queries feed
                     this project. Without --query, the saved searches
                     whose triage is linked to the project
                     (triage/<slug>/triage.json "project") are used --
                     a triage's slug is its saved query's slug
                     (PUBMED_TRIAGE_IMPLEMENTATION_PLAN.md P3). With neither,
                     identified stays "unknown")
  - duplicates    <- identified count minus the deduplicated PMID set
                     (every paper is PMID-keyed at ingest, D11)
  - screened /
    excluded      <- projects/<slug>/screening.jsonl
  - sought /
    not_retrieved <- papers/<pmid>/meta.json's full_text flag, for
                     screened-included PMIDs
  - included
    studies       <- studies/studies.jsonl if present (assumed shape, per
                     lib_schema.py's existing validate_study stub from phase
                     0: {"study_id", "publications": [pmid...],
                     "grouping_confidence", "review_state"}); reported
                     SEPARATELY from included publications, never collapsed

Any number with no committed source backing it is "unknown" with a stated
reason -- never inferred to balance the arithmetic (§5a's explicit
requirement). Frozen snapshot: projects/<slug>/prisma/<id>/, same
reuse-unless-refresh idiom as export.py's frozen batches.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from lib_atomic import atomic_write_json, atomic_write_text
from lib_ids import gen_opaque_id
from project import linked_triages


def _project_dir(library_root: Path, slug: str) -> Path:
    return library_root / "projects" / slug


def _load_json(path: Path, default):
    return json.loads(path.read_text()) if path.exists() else default


def _load_query_run(library_root: Path, query_slug: str, run_id: str | None) -> dict | None:
    p = library_root / "queries" / f"{query_slug}.yaml"
    if not p.exists():
        return None
    doc = json.loads(p.read_text())
    runs = doc.get("runs", [])
    if not runs:
        return None
    if run_id:
        return next((r for r in runs if r["run_id"] == run_id), None)
    return runs[-1]  # latest run, since PRISMA reports the project's current search state


def _identified(library_root: Path, query_specs: list[tuple[str, str | None]]) -> dict:
    """query_specs: [(query_slug, run_id_or_None), ...] from --query args.
    Returns identified counts + the deduplicated PMID set + unresolved specs."""
    per_source: dict[str, dict] = {}
    all_pmids: list[str] = []
    unresolved = []
    for slug, run_id in query_specs:
        run = _load_query_run(library_root, slug, run_id)
        if run is None:
            unresolved.append({"query": slug, "run": run_id, "reason": "no such saved query or run"})
            continue
        src = run.get("source", "unknown")
        per_source.setdefault(src, {"count": 0, "runs": []})
        per_source[src]["count"] += len(run["pmids"])
        per_source[src]["runs"].append({
            "query_slug": slug, "run_id": run["run_id"], "query_text": run["query"],
            "retrieved_at": run["retrieved_at"], "pmid_count": len(run["pmids"]),
        })
        all_pmids.extend(run["pmids"])

    dedup_pmids = sorted(set(all_pmids))
    return {
        "per_source": per_source,
        "total_identified_raw": len(all_pmids),
        "duplicates_removed": len(all_pmids) - len(dedup_pmids),
        "identified_pmids": dedup_pmids,
        "unresolved_query_specs": unresolved,
    }


def _screening(library_root: Path, project_slug: str, identified_pmids: set[str]) -> dict:
    log_path = _project_dir(library_root, project_slug) / "screening.jsonl"
    records = []
    if log_path.exists():
        records = [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]

    # latest decision per PMID (screening.jsonl is an append-only history)
    latest: dict[str, dict] = {}
    for r in records:
        latest[r["pmid"]] = r  # later lines overwrite -- file is chronological

    screened_pmids = set(latest.keys())
    included = [pmid for pmid, r in latest.items() if r["decision"] == "included"]
    excluded = [pmid for pmid, r in latest.items() if r["decision"] == "excluded"]

    excluded_by_reason: dict[str, int] = {}
    for pmid in excluded:
        reason = latest[pmid]["reason"]
        excluded_by_reason[reason] = excluded_by_reason.get(reason, 0) + 1

    # screening decisions whose PMID never showed up in any resolved query
    # run for this project -- an unbalanceable/unevidenced case (§5a).
    unevidenced_screened = sorted(screened_pmids - identified_pmids)

    return {
        "screened_count": len(screened_pmids),
        "included_pmids": sorted(included),
        "excluded_pmids": sorted(excluded),
        "excluded_by_reason": excluded_by_reason,
        "unevidenced_screened_pmids": unevidenced_screened,
    }


def _sought_and_retrieved(library_root: Path, included_pmids: list[str]) -> dict:
    sought = []
    retrieved = []
    not_retrieved = []
    unknown = []
    for pmid in included_pmids:
        meta_path = library_root / "papers" / pmid / "meta.json"
        if not meta_path.exists():
            unknown.append(pmid)
            continue
        sought.append(pmid)
        meta = json.loads(meta_path.read_text())
        if meta.get("full_text") is True:
            retrieved.append(pmid)
        else:
            not_retrieved.append(pmid)
    return {
        "sought_pmids": sorted(sought),
        "retrieved_pmids": sorted(retrieved),
        "not_retrieved_pmids": sorted(not_retrieved),
        "unevidenced_sought_pmids": sorted(unknown),  # included but never /ref:add'ed -- shouldn't
                                                        # normally happen, but reported, not hidden
    }


def _included_studies(library_root: Path, included_pmids: list[str]) -> dict | None:
    studies_path = library_root / "studies" / "studies.jsonl"
    if not studies_path.exists():
        return None
    included_set = set(included_pmids)
    groups = []
    covered = set()
    for line in studies_path.read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        # study.py (phase 5's actual writer) uses "pmids"/"confidence", not
        # the phase-0 lib_schema.py stub's "publications"/"grouping_confidence"
        # -- this reader was originally written against the stale stub before
        # the concurrently-developed study.py landed; reconciled post-merge.
        pubs = [p for p in rec.get("pmids", []) if p in included_set]
        if pubs:
            groups.append({
                "study_id": rec["study_id"], "publications": sorted(pubs),
                "grouping_confidence": rec.get("confidence", "unknown"),
            })
            covered.update(pubs)
    ungrouped = sorted(included_set - covered)  # each ungrouped PMID is its own independent study
    return {
        "grouped_studies": groups,
        "ungrouped_publications": ungrouped,
        "included_studies_count": len(groups) + len(ungrouped),
        "included_publications_count": len(included_pmids),
    }


def build_flow(library_root: Path, project_slug: str, query_specs: list[tuple[str, str | None]]) -> dict:
    pdir = _project_dir(library_root, project_slug)
    if not pdir.is_dir():
        raise ValueError(f"project {project_slug!r} does not exist")

    if not query_specs:
        identified = {
            "per_source": {}, "total_identified_raw": 0, "duplicates_removed": 0,
            "identified_pmids": [], "unresolved_query_specs": [],
        }
        identified_note = "no --query given: identified counts are unknown, not zero"
    else:
        identified = _identified(library_root, query_specs)
        identified_note = None

    screening = _screening(library_root, project_slug, set(identified["identified_pmids"]))
    sought = _sought_and_retrieved(library_root, screening["included_pmids"])
    studies = _included_studies(library_root, screening["included_pmids"])

    flow = {
        "project": project_slug,
        "data_cutoff": datetime.now(timezone.utc).isoformat(),
        "identified": {
            "per_source": {k: {"count": v["count"], "runs": v["runs"]} for k, v in identified["per_source"].items()},
            "total_raw": identified["total_identified_raw"] if query_specs else "unknown",
            "note": identified_note,
        },
        "duplicates_removed": identified["duplicates_removed"] if query_specs else "unknown",
        "unresolved_query_specs": identified["unresolved_query_specs"],
        "screened": screening["screened_count"],
        "excluded": {
            "count": len(screening["excluded_pmids"]),
            "by_reason": screening["excluded_by_reason"],
        },
        "unevidenced_screened_pmids": screening["unevidenced_screened_pmids"],
        "reports": {
            "sought": len(sought["sought_pmids"]),
            "not_retrieved": len(sought["not_retrieved_pmids"]),
            "not_retrieved_pmids": sought["not_retrieved_pmids"],
            "unevidenced_sought_pmids": sought["unevidenced_sought_pmids"],
        },
        "included": {
            "publications_count": len(screening["included_pmids"]),
            "publications": screening["included_pmids"],
            "studies_count": studies["included_studies_count"] if studies else "unknown",
            "studies_note": None if studies else "studies/studies.jsonl not available -- "
                                                    "included-studies count is unknown, not "
                                                    "assumed equal to included-publications count",
            "grouped_studies": studies["grouped_studies"] if studies else [],
            "ungrouped_publications": studies["ungrouped_publications"] if studies else [],
        },
    }
    return flow


def render_markdown(flow: dict) -> str:
    lines = [f"# PRISMA 2020 flow — project `{flow['project']}`", "", f"Data cutoff: {flow['data_cutoff']}", ""]
    lines.append("## Identification")
    if flow["identified"]["note"]:
        lines.append(f"- **unknown**: {flow['identified']['note']}")
    else:
        for src, info in flow["identified"]["per_source"].items():
            lines.append(f"- {src}: {info['count']} identified across {len(info['runs'])} run(s)")
        lines.append(f"- total raw: {flow['identified']['total_raw']}")
        lines.append(f"- duplicates removed: {flow['duplicates_removed']}")
    if flow["unresolved_query_specs"]:
        lines.append(f"- **unresolved query references (unknown, not counted)**: {flow['unresolved_query_specs']}")
    lines.append("")
    lines.append("## Screening")
    lines.append(f"- screened: {flow['screened']}")
    lines.append(f"- excluded: {flow['excluded']['count']} ({flow['excluded']['by_reason']})")
    if flow["unevidenced_screened_pmids"]:
        lines.append(f"- **screened but not in any identified run (unknown provenance)**: {flow['unevidenced_screened_pmids']}")
    lines.append("")
    lines.append("## Reports sought / retrieved")
    lines.append(f"- sought: {flow['reports']['sought']}")
    lines.append(f"- not retrieved: {flow['reports']['not_retrieved']}")
    lines.append("")
    lines.append("## Included")
    lines.append(f"- publications: {flow['included']['publications_count']}")
    lines.append(f"- studies: {flow['included']['studies_count']}"
                  + (f" ({flow['included']['studies_note']})" if flow["included"]["studies_note"] else ""))
    return "\n".join(lines) + "\n"


def render_csv(flow: dict) -> str:
    rows = [
        ("stage", "count"),
        ("identified_total_raw", flow["identified"]["total_raw"]),
        ("duplicates_removed", flow["duplicates_removed"]),
        ("screened", flow["screened"]),
        ("excluded", flow["excluded"]["count"]),
        ("sought", flow["reports"]["sought"]),
        ("not_retrieved", flow["reports"]["not_retrieved"]),
        ("included_publications", flow["included"]["publications_count"]),
        ("included_studies", flow["included"]["studies_count"]),
    ]
    return "\n".join(f"{k},{v}" for k, v in rows) + "\n"


def _snapshot_dir(library_root: Path, project_slug: str, snapshot_id: str) -> Path:
    return library_root / "projects" / project_slug / "prisma" / snapshot_id


def _latest_snapshot_id(library_root: Path, project_slug: str) -> str | None:
    root = library_root / "projects" / project_slug / "prisma"
    if not root.is_dir():
        return None
    index_path = root / "latest.json"
    if index_path.exists():
        return json.loads(index_path.read_text()).get("snapshot_id")
    return None


def run_prisma(library_root: Path, project_slug: str, query_specs: list[tuple[str, str | None]], refresh: bool) -> dict:
    root = library_root / "projects" / project_slug / "prisma"
    latest_id = _latest_snapshot_id(library_root, project_slug)

    if latest_id and not refresh:
        sdir = _snapshot_dir(library_root, project_slug, latest_id)
        manifest = json.loads((sdir / "manifest.json").read_text())
        return {"status": "reused_frozen_snapshot", "snapshot_id": latest_id, "manifest": manifest}

    query_source = "explicit"
    if not query_specs:
        query_specs = [(slug, None) for slug in linked_triages(library_root, project_slug)]
        query_source = "linked_triages" if query_specs else "none"

    flow = build_flow(library_root, project_slug, query_specs)
    snapshot_id = gen_opaque_id("prisma-")
    sdir = _snapshot_dir(library_root, project_slug, snapshot_id)
    sdir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "snapshot_id": snapshot_id,
        "project": project_slug,
        "query_specs": [{"query": s, "run": r} for s, r in query_specs],
        "query_source": query_source,
        "data_cutoff": flow["data_cutoff"],
        "flow": flow,
    }
    atomic_write_json(sdir / "manifest.json", manifest)
    atomic_write_text(sdir / "flow.md", render_markdown(flow))
    atomic_write_text(sdir / "flow.csv", render_csv(flow))
    atomic_write_json(root / "latest.json", {"snapshot_id": snapshot_id})

    status = "created" if not latest_id else "refreshed"
    result = {"status": status, "snapshot_id": snapshot_id, "manifest": manifest}
    if latest_id:
        prior = json.loads((_snapshot_dir(library_root, project_slug, latest_id) / "manifest.json").read_text())
        prior_included = set(prior["flow"]["included"]["publications"])
        new_included = set(flow["included"]["publications"])
        result["included_added"] = sorted(new_included - prior_included)
        result["included_removed"] = sorted(prior_included - new_included)
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--project", required=True)
    ap.add_argument("--query", action="append", default=[],
                     help="query slug, optionally slug:run_id; repeatable")
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    library_root = Path(args.repo).expanduser().resolve()
    if not library_root.is_dir():
        print(f"error: no library at {library_root}", file=sys.stderr)
        return 1

    query_specs = []
    for q in args.query:
        if ":" in q:
            slug, run_id = q.split(":", 1)
        else:
            slug, run_id = q, None
        query_specs.append((slug, run_id))

    try:
        result = run_prisma(library_root, args.project, query_specs, args.refresh)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
