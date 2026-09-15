#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Selector grammar (PLAN.md §5c) — shared by every set-valued command.

Not a standalone command; other scripts import `resolve()`. Implements the
subset of §5c available before full-text/graph phases:
  <pmid...>, --project [--question], --screened, --read/--queue,
  --query [--run], --search, --from-file, refined by --tier / --exclude.
`--study`/`--concept` are phase 5/8 selectors — they raise a named
NotAvailableError here rather than silently matching nothing, so callers get
an explicit "not yet available" instead of a false empty result.

"Resolve, report, then work" / "Freeze the resolved set" (§5c): resolve()
always returns counts by extraction tier before any caller does real work.
Human-verification state (phase 4 corrections) and retraction/errata status
(phase 11 audit) don't exist as concepts yet — reported as "not_yet_tracked"
rather than fabricated. An empty resolution is a SelectorError naming the
selector expression, never a silent empty list.

One exception to "not a standalone command": `recent()` backs the shared
no-selector fallback (ref_manager_feature_requests.md #2) that every
`/ref:*` command taking a §5c selector falls back to when invoked with no
PMID/selector at all -- list recently-added papers instead of failing or
asking the user to recall a PMID from memory. `kind="unresolved"` adds a
follow-up view for records that still need source work (metadata-only or
OA-location-pending). Centralized here (rather than reimplemented per
command) since every caller needs the same listing. `main()` below is the
minimal CLI those command specs shell out to.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


class SelectorError(ValueError):
    pass


class NotAvailableError(SelectorError):
    pass


def _load_json(path: Path, default):
    return json.loads(path.read_text()) if path.exists() else default


def _all_pmids(library_root: Path) -> list[str]:
    papers_dir = library_root / "papers"
    if not papers_dir.is_dir():
        return []
    return sorted(p.name for p in papers_dir.iterdir() if (p / "meta.json").exists())


def _project_membership(library_root: Path, slug: str) -> list[dict]:
    papers_path = library_root / "projects" / slug / "papers.yaml"
    if not papers_path.exists():
        raise SelectorError(f"--project {slug!r}: no such project")
    return _load_json(papers_path, {"papers": []})["papers"]


def _query_run_pmids(library_root: Path, slug: str, run_id: str | None) -> tuple[list[str], str]:
    qpath = library_root / "queries" / f"{slug}.yaml"
    if not qpath.exists():
        raise SelectorError(f"--query {slug!r}: no such saved query")
    doc = _load_json(qpath, {"runs": []})
    runs = doc.get("runs", [])
    if not runs:
        raise SelectorError(f"--query {slug!r}: no runs recorded yet")
    if run_id:
        matches = [r for r in runs if r["run_id"] == run_id]
        if not matches:
            raise SelectorError(f"--query {slug!r} --run {run_id!r}: no such run")
        run = matches[0]
    else:
        run = runs[-1]  # most recent run, immutable history preserved (§5c)
    return list(run.get("pmids", [])), run["run_id"]


def _study_pmids(library_root: Path, study_id: str) -> list[str]:
    # local import: study.py is phase 5, avoid a hard dependency for callers
    # that never use --study (matches the --search/search.py precedent above)
    import study as study_mod

    for r in study_mod.list_studies(library_root):
        if r["study_id"] == study_id:
            return list(r["pmids"])
    raise SelectorError(f"--study {study_id!r}: no such study")


def _search_pmids(library_root: Path, expr: str) -> list[str]:
    # local import to avoid a hard dependency for callers that never use --search
    import search as search_mod

    hits = search_mod.run(library_root, scope="evidence", query=expr)
    return sorted({h["pmid"] for h in hits})


def _meta(library_root: Path, pmid: str) -> dict | None:
    p = library_root / "papers" / pmid / "meta.json"
    return json.loads(p.read_text()) if p.exists() else None


def selector_expression(**kwargs) -> str:
    parts = []
    for k, v in kwargs.items():
        if v in (None, [], ""):
            continue
        parts.append(f"--{k.replace('_', '-')} {v}")
    return " ".join(parts) if parts else "<all>"


def resolve(
    library_root: Path,
    *,
    pmids: list[str] | None = None,
    project: str | None = None,
    question: str | None = None,
    screened: str | None = None,
    read: bool = False,
    queue_state: str | None = None,
    query: str | None = None,
    run: str | None = None,
    search: str | None = None,
    from_file: str | None = None,
    study: str | None = None,
    concept: str | None = None,
    tier: str = "any",
    exclude: list[str] | None = None,
) -> dict:
    if concept is not None:
        raise NotAvailableError("--concept is not available until phase 8 (concept graph)")
    if tier not in ("abstract", "full", "any"):
        raise SelectorError(f"--tier must be abstract|full|any, got {tier!r}")
    if (screened or read or queue_state) and not project:
        raise SelectorError("--screened/--read/--queue require --project (state is project-scoped, §3b)")

    sources_used = 0
    base: list[str]

    if pmids:
        base = list(dict.fromkeys(pmids))  # de-dup, preserve order
        sources_used += 1
    elif from_file:
        text = Path(from_file).expanduser().read_text()
        base = [line.strip() for line in text.splitlines() if line.strip()]
        sources_used += 1
    elif project:
        members = _project_membership(library_root, project)
        base = [m["pmid"] for m in members]
        sources_used += 1
    elif query:
        base, _run_id = _query_run_pmids(library_root, query, run)
        sources_used += 1
    elif study:
        base = _study_pmids(library_root, study)
        sources_used += 1
    elif search:
        base = _search_pmids(library_root, search)
        sources_used += 1
    else:
        raise SelectorError(
            "no selector given: pass <pmid...>, --project, --query, --study, --search, or --from-file"
        )

    # AND-narrow by project-scoped state (only meaningful in combination with --project)
    if project and (question or screened or read or queue_state):
        members_by_pmid = {m["pmid"]: m for m in _project_membership(library_root, project)}
        narrowed = []
        for pmid in base:
            m = members_by_pmid.get(pmid)
            if m is None:
                continue
            if screened is not None and (m.get("screening") or {}).get("decision") != screened:
                continue
            if read and m.get("reading_status") != "read":
                continue
            if queue_state is not None and m.get("reading_status") != queue_state:
                continue
            narrowed.append(pmid)
        base = narrowed

    if exclude:
        exclude_set = set(exclude)
        base = [p for p in base if p not in exclude_set]

    if tier != "any":
        base = [p for p in base if (_meta(library_root, p) or {}).get("extraction_tier") == tier]

    resolved = sorted(dict.fromkeys(base))

    expr = selector_expression(
        pmid=" ".join(pmids) if pmids else None,
        project=project, question=question, screened=screened,
        read=read or None, queue=queue_state, query=query, run=run,
        search=search, from_file=from_file, tier=tier if tier != "any" else None,
        exclude=" ".join(exclude) if exclude else None,
    )

    if not resolved:
        raise SelectorError(f"selector matched no papers: {expr}")

    tier_counts = {"abstract": 0, "full": 0, "unavailable": 0, "missing_record": 0}
    retraction_counts: dict[str, int] = {}
    for pmid in resolved:
        meta = _meta(library_root, pmid)
        if meta is None:
            tier_counts["missing_record"] += 1
            retraction_counts["unknown"] = retraction_counts.get("unknown", 0) + 1
        else:
            tier_counts[meta.get("extraction_tier", "unavailable")] = (
                tier_counts.get(meta.get("extraction_tier", "unavailable"), 0) + 1
            )
            # meta.json's retraction_status exists since phase 4's extract.py
            # and is kept current by phase 11's /ref:audit -- report the real
            # counts, not a placeholder (this used to hardcode
            # "not_yet_tracked" for every PMID even though the field has been
            # populated since phase 4).
            rstatus = (meta.get("retraction_status") or {}).get("status", "unknown")
            retraction_counts[rstatus] = retraction_counts.get(rstatus, 0) + 1

    return {
        "pmids": resolved,
        "selector_expression": expr,
        "report": {
            "count": len(resolved),
            "by_extraction_tier": tier_counts,
            "by_human_verification_state": {"not_yet_tracked": len(resolved)},  # phase 4
            "by_retraction_errata_status": retraction_counts,
        },
    }


def add_selector_args(ap) -> None:
    """Shared argparse wiring for commands that take the §5c selector."""
    ap.add_argument("pmids", nargs="*", help="explicit PMIDs (base case)")
    ap.add_argument("--project")
    ap.add_argument("--question")
    ap.add_argument("--screened", choices=["included", "excluded", "pending"])
    ap.add_argument("--read", action="store_true")
    ap.add_argument("--queue")
    ap.add_argument("--query")
    ap.add_argument("--run")
    ap.add_argument("--search")
    ap.add_argument("--from-file")
    ap.add_argument("--study")
    ap.add_argument("--concept")
    ap.add_argument("--tier", default="any", choices=["abstract", "full", "any"])
    ap.add_argument("--exclude", nargs="*", default=None)


def resolve_from_args(library_root: Path, args) -> dict:
    return resolve(
        library_root,
        pmids=args.pmids or None,
        project=args.project,
        question=args.question,
        screened=args.screened,
        read=args.read,
        queue_state=args.queue,
        query=args.query,
        run=args.run,
        search=args.search,
        from_file=args.from_file,
        study=args.study,
        concept=args.concept,
        tier=args.tier,
        exclude=args.exclude,
    )


def _recent_row(library_root: Path, pmid: str) -> dict:
    meta = _meta(library_root, pmid) or {}
    raw_dir = library_root / "papers" / pmid / "raw"
    has_pdf = raw_dir.is_dir() and any((p / "source.pdf").exists() for p in raw_dir.iterdir() if p.is_dir())
    if has_pdf:
        source_badge = "pdf-backed"
    elif meta.get("full_text"):
        source_badge = "full-text"
    elif meta.get("oa_location"):
        source_badge = "oa-pending"
    elif meta.get("abstract_available"):
        source_badge = "abstract-only"
    else:
        source_badge = "metadata-only"
    return {
        "pmid": pmid,
        "citekey": meta.get("citekey"),
        "title": meta.get("title"),
        "year": meta.get("year"),
        "checked_at": meta.get("checked_at", ""),
        "source_badge": source_badge,
    }


def recent(library_root: Path, limit: int = 15, kind: str = "recent") -> list[dict]:
    """Browse-first paper lists used by the shared no-selector picker.

    `kind="recent"` / `kind="imports"` returns the newest papers by
    `meta.json.checked_at`. `kind="unresolved"` returns papers that still
    need source follow-up, newest first.
    Each row carries what a checkbox UI needs to label an option: pmid,
    citekey, title, year, source badge, and checked_at.
    """
    rows = []
    for pmid in _all_pmids(library_root):
        row = _recent_row(library_root, pmid)
        if kind == "unresolved":
            if row["source_badge"] not in ("metadata-only", "oa-pending"):
                continue
        rows.append(row)
    rows.sort(key=lambda r: r["checked_at"], reverse=True)
    return rows[:limit]


def main() -> int:
    """`python3 lib_selector.py recent --repo <root> [--limit N]` -- prints
    `recent()` as JSON. The one standalone entry point this module exposes
    (see module docstring); everything else is imported, not shelled out to."""
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    recent_ap = sub.add_parser("recent", help="list browse-first papers for the no-selector fallback picker")
    recent_ap.add_argument("--repo", required=True)
    recent_ap.add_argument("--limit", type=int, default=15)
    recent_ap.add_argument("--kind", choices=["recent", "imports", "unresolved"], default="recent")
    args = ap.parse_args()

    library_root = Path(args.repo).expanduser().resolve()
    print(json.dumps(recent(library_root, args.limit, args.kind), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
