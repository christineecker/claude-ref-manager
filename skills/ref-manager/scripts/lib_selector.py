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
"""
from __future__ import annotations

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
    if study is not None:
        raise NotAvailableError("--study is not available until phase 5 (study grouping)")
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
    elif search:
        base = _search_pmids(library_root, search)
        sources_used += 1
    else:
        raise SelectorError(
            "no selector given: pass <pmid...>, --project, --query, --search, or --from-file"
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
    for pmid in resolved:
        meta = _meta(library_root, pmid)
        if meta is None:
            tier_counts["missing_record"] += 1
        else:
            tier_counts[meta.get("extraction_tier", "unavailable")] = (
                tier_counts.get(meta.get("extraction_tier", "unavailable"), 0) + 1
            )

    return {
        "pmids": resolved,
        "selector_expression": expr,
        "report": {
            "count": len(resolved),
            "by_extraction_tier": tier_counts,
            "by_human_verification_state": {"not_yet_tracked": len(resolved)},  # phase 4
            "by_retraction_errata_status": {"not_yet_tracked": len(resolved)},  # phase 11
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
