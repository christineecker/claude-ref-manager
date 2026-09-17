#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Derived, read-only dashboard models (DASHBOARD_IMPROVEMENTS_IMPLEMENTATION_PLAN.md
§3-§4, DASHBOARD_FEATURE_REQUESTS.md FR-04..FR-06, FR-09..FR-17).

Nothing here re-derives inventory semantics: every function takes the
`lib_inventory.rows()` list / `lint()` report the dashboard already has and
only aggregates it, so `/api/summary`, the static build and the next-action
panel can never disagree with the table they sit next to (§1.2 "one
inventory").

- `next_actions()` -- the ranked "what should I do next?" list. The score
  is deliberately explainable: `weight x papers x project boost`, and each
  action carries its `why` line so the UI can show the arithmetic.
- `summary()` -- the compact `/api/summary` model.
- `health()` -- the `/api/health` model: each data source loaded
  independently, a failure reported per source instead of failing the call.
- `knowledge()` -- claims, concepts, relations and per-paper topic terms for
  the Insights tab (evidence map, gaps, timeline, graph, clusters,
  synthesis). Those views are computed client-side from this payload so
  they follow the Papers filters without a round trip.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import threading
from pathlib import Path

import lib_inventory
import lib_schema
from lib_atomic import now_iso

# bucket -> (weight, label template, pmid command or None, why)
# A None command means the bucket has no command that takes a pmid list;
# the action falls back to the /ref:list query that names the papers.
ACTION_RULES: dict[str, tuple[int, str, str | None, str]] = {
    "malformed_meta": (10, "Repair malformed meta.json for {n}", None,
                       "unreadable records break listing, citing and fetching"),
    "missing_meta": (10, "Re-add {n} with no meta.json", None,
                     "a paper directory without metadata is invisible to every command"),
    "missing_current": (5, "Fetch full text for {n}", "/ref:fetch", "no committed version to read or extract from"),
    "metadata_only": (5, "Fetch abstract or full text for {n}", "/ref:fetch", "only bibliographic metadata on file"),
    "abstract_only": (4, "Fetch full text for {n}", "/ref:fetch", "claims can only come from the abstract"),
    "oa_pending": (4, "Download open-access PDFs for {n}", "/ref:fetch-pdf", "an open-access copy exists but isn't attached"),
    "missing_claim_registry": (3, "Extract claims from {n}", "/ref:extract", "not searchable by /ref:ask or the evidence map"),
    "stale_retraction_check": (2, "Re-check retraction status for {n}", "/ref:audit", "retraction status is out of date"),
    "missing_title": (2, "Fill missing titles for {n}", None, "untitled papers are hard to find and cite"),
    "missing_year": (1, "Fill missing years for {n}", None, "undated papers drop out of timelines"),
    "missing_journal": (1, "Fill missing journals for {n}", None, "citations will be incomplete"),
    "missing_abstract": (1, "Find abstracts for {n}", None, "screening and topic views have less to work with"),
    "missing_doi": (1, "Find DOIs for {n}", None, "PDF identity checks and links rely on the DOI"),
}
CATALOG_STALE_SCORE = 30
PROJECT_BOOST = 0.5  # share of the bucket inside projects raises its score by up to 50%
PROJECT_SCOPED_MIN_WEIGHT = 3
MAX_ACTIONS = 8
MAX_COMMAND_PMIDS = 50


def _plural(n: int) -> str:
    return f"{n} paper" + ("" if n == 1 else "s")


def _command(bucket: str, pmids: list[str], project: str | None) -> str:
    base = ACTION_RULES[bucket][2]
    if base and len(pmids) <= MAX_COMMAND_PMIDS:
        return f"{base} {' '.join(pmids)}"
    listing = f"/ref:list --issue {bucket} --format pmids"
    if project:
        listing += f" --project {project}"
    return f"{listing}  # then {base} <pmids>" if base else listing


def next_actions(rows: list[dict], lint_report: dict, *, include_pmids: bool = False,
                 limit: int | None = MAX_ACTIONS) -> list[dict]:
    """Ranked next actions. Each has `score = weight * count * boost` where
    `boost = 1 + PROJECT_BOOST * (share of the papers that sit in a
    project)`; project-scoped variants get the full boost. Global actions
    whose papers all belong to one project are replaced by that project's
    variant rather than listed twice. The dashboard asks for every action
    with pmids (`limit=None`) so "limit to the current filters" can re-rank
    beyond the global top list; the API default stays compact."""
    issues = lint_report.get("issues") or {}
    projects_of = {r["pmid"]: [p.get("slug") for p in r.get("projects") or [] if p.get("slug")] for r in rows}
    actions: list[dict] = []

    for bucket, (weight, label, _cmd, why) in ACTION_RULES.items():
        pmids = sorted(issues.get(bucket) or [])
        if not pmids:
            continue
        in_projects = sum(1 for p in pmids if projects_of.get(p))
        share = in_projects / len(pmids)
        boost = 1 + PROJECT_BOOST * share

        scoped: list[dict] = []
        if weight >= PROJECT_SCOPED_MIN_WEIGHT:
            by_project: dict[str, list[str]] = {}
            for p in pmids:
                for slug in projects_of.get(p) or []:
                    by_project.setdefault(slug, []).append(p)
            for slug, members in by_project.items():
                boost_p = 1 + PROJECT_BOOST
                scoped.append({
                    "id": f"{bucket}@{slug}", "type": bucket, "project": slug,
                    "label": label.format(n=_plural(len(members))) + f" in {slug}",
                    "template": label + f" in {slug}", "command_base": ACTION_RULES[bucket][2],
                    "count": len(members), "weight": weight, "boost": boost_p,
                    "score": round(weight * len(members) * boost_p, 2),
                    "why": f"{why} · weight {weight} × {len(members)} × project boost {boost_p:g}",
                    "suggested_command": _command(bucket, members, slug),
                    "pmids": members,
                })
        covers_all = any(a["count"] == len(pmids) for a in scoped)
        if not covers_all:
            actions.append({
                "id": bucket, "type": bucket, "project": None,
                "label": label.format(n=_plural(len(pmids))),
                "template": label, "command_base": ACTION_RULES[bucket][2],
                "count": len(pmids), "weight": weight, "boost": round(boost, 2),
                "score": round(weight * len(pmids) * boost, 2),
                "why": f"{why} · weight {weight} × {len(pmids)}"
                       + (f" × project boost {boost:.2g} ({round(share * 100)}% in projects)" if in_projects else ""),
                "suggested_command": _command(bucket, pmids, None),
                "pmids": pmids,
            })
        actions.extend(scoped)

    summary = lint_report.get("summary") or {}
    if summary.get("catalog_stale"):
        actions.append({
            "id": "catalog_stale", "type": "catalog_stale", "project": None,
            "label": "Rebuild the catalog index", "template": "Rebuild the catalog index", "command_base": None,
            "count": 0, "weight": CATALOG_STALE_SCORE, "boost": 1,
            "score": CATALOG_STALE_SCORE,
            "why": "search and /ref:ask read a catalog that no longer matches papers/ · fixed score "
                   f"{CATALOG_STALE_SCORE}",
            "suggested_command": "/ref:index --rebuild", "pmids": [],
        })

    actions.sort(key=lambda a: (-a["score"], a["id"]))
    # Two buckets can name the same papers and command (metadata_only and
    # missing_current usually do); list that work once, under the higher score.
    seen: dict[tuple, dict] = {}
    deduped = []
    for a in actions:
        key = (a["project"], a["command_base"], tuple(a["pmids"])) if a["command_base"] else (a["id"],)
        if key in seen:
            seen[key]["why"] += f" · also {a['type']}"
            continue
        seen[key] = a
        deduped.append(a)
    out = deduped if limit is None else deduped[:limit]
    for rank, a in enumerate(out, 1):
        a["rank"] = rank
        if not include_pmids:
            a.pop("pmids")
    return out


def _coverage(rows: list[dict]) -> dict:
    counts = {"pdf_backed": 0, "full_text": 0, "oa_pending": 0, "abstract_only": 0, "metadata_only": 0, "no_meta": 0}
    for r in rows:
        key = (r.get("source_badge") or "no-meta").replace("-", "_")
        counts[key] = counts.get(key, 0) + 1
    return counts


def summary(rows: list[dict], lint_report: dict, snapshots: list[dict], *,
            include_pmids: bool = False, data_sources: dict | None = None) -> dict:
    """`/api/summary`: the compact overview that drives the next-action panel."""
    generated_at = now_iso()
    issues = lint_report.get("issues") or {}
    lint_summary = lint_report.get("summary") or {}
    last = snapshots[-1] if snapshots else None
    return {
        "generated_at": generated_at,
        "paper_count": len(rows),
        "issues_total": lint_summary.get("issues_total", sum(len(v) for v in issues.values())),
        "catalog_present": lint_summary.get("catalog_present"),
        "catalog_stale": bool(lint_summary.get("catalog_stale")),
        "coverage": _coverage(rows),
        "pipeline": {
            "full_text_or_pdf": sum(1 for r in rows if r.get("has_fulltext") or r.get("has_pdf")),
            "with_claims": sum(1 for r in rows if r.get("claims_active")),
            "in_catalog": sum(1 for r in rows if r.get("in_catalog")),
        },
        "top_issue_buckets": sorted(
            ({"bucket": b, "count": len(p)} for b, p in issues.items() if p),
            key=lambda x: (-x["count"], x["bucket"]),
        ),
        "top_actions": next_actions(rows, lint_report, include_pmids=include_pmids,
                                    limit=None if include_pmids else MAX_ACTIONS),
        "snapshots": {"count": len(snapshots), "latest": last and {
            "stamp": last.get("stamp"), "issues_total": (last.get("summary") or {}).get("issues_total"),
        }},
        "data_sources": data_sources or {"rows": "ok", "lint": "ok", "snapshots": "ok"},
    }


def health(library_root: Path, loaders: dict) -> tuple[dict, int]:
    """`/api/health`: every loader runs on its own; one raising is recorded
    as that source's error, never propagated. `down` (HTTP 503) only when
    rows() itself fails -- nothing on the dashboard works without it."""
    sources: dict[str, str] = {}
    values: dict = {}
    for name, load in loaders.items():
        try:
            values[name] = load()
            sources[name] = "ok"
        except Exception as e:  # noqa: BLE001 -- reported, never raised
            sources[name] = f"error: {type(e).__name__}: {e}"

    warnings: list[str] = []
    lint_report = values.get("lint") or {}
    lint_summary = lint_report.get("summary") or {}
    if lint_summary.get("catalog_stale"):
        warnings.append("catalog is stale -- /ref:index --rebuild")
    elif lint_summary and not lint_summary.get("catalog_present"):
        warnings.append("no catalog yet -- /ref:index --rebuild")
    broken = len((lint_report.get("issues") or {}).get("malformed_meta") or [])
    if broken:
        warnings.append(f"{broken} paper(s) with malformed meta.json")
    snaps = values.get("snapshots")
    if sources.get("snapshots") == "ok" and not snaps:
        warnings.append("no lint snapshots yet -- /ref:lint --snapshot")
    if not shutil.which("pdftotext"):
        warnings.append("pdftotext not found -- uploaded PDFs can't be identity-checked")
    if not shutil.which("anydoc"):
        warnings.append("anydoc not found -- uploaded PDFs are stored but not converted to full text")

    failed = [k for k, v in sources.items() if v != "ok"]
    status = "down" if sources.get("rows", "ok") != "ok" else ("degraded" if failed or warnings else "ok")
    body = {
        "ok": not failed,
        "status": status,
        "library_root": str(library_root),
        "generated_at": now_iso(),
        "data_sources": sources,
        "counts": {
            "rows": len(values["rows"]) if isinstance(values.get("rows"), list) else None,
            "issues_total": lint_summary.get("issues_total"),
            "matrix_rows": len((values.get("matrix") or {}).get("rows") or []) if "matrix" in values else None,
            "snapshots": len(snaps) if isinstance(snaps, list) else None,
        },
        "warnings": warnings,
    }
    return body, (503 if status == "down" else 200)


# ------------------------------------------------------------- knowledge

MAX_NOTE_EXCERPT = 280
_clean = lib_schema.clean_claim_value


def direction_class(direction) -> str | None:
    """Collapse the extractor's free-text direction (agents/ref-extractor.md:
    increase / decrease / no significant difference / not reported) into
    up / down / null for colouring; anything else stays `other`."""
    d = _clean(direction)
    if d is None:
        return None
    low = d.casefold()
    if "no significant" in low or "no difference" in low or "no effect" in low or low in ("null", "none found"):
        return "null"
    if any(w in low for w in ("increase", "higher", "improve", "greater", "positive", "more")):
        return "up"
    if any(w in low for w in ("decrease", "lower", "reduc", "worse", "negative", "less", "fewer")):
        return "down"
    return "other"


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _paper_claims(pdir: Path) -> list[dict]:
    registry = lib_inventory._load_json(pdir / "claim_registry.json")
    claims = registry.get("claims") if isinstance(registry, dict) else None
    if not isinstance(claims, dict):
        return []
    out = []
    for cid, c in claims.items():
        if not isinstance(c, dict) or c.get("status") != "active" or c.get("excluded_from_synthesis"):
            continue
        out.append({
            "pmid": pdir.name,
            "claim_id": c.get("claim_id") or cid,
            "population": _clean(c.get("population")),
            "intervention": _clean(c.get("intervention")),
            "comparator": _clean(c.get("comparator")),
            "outcome": _clean(c.get("outcome")),
            "timepoint": _clean(c.get("timepoint")),
            "direction": _clean(c.get("direction")),
            "dir": direction_class(c.get("direction")),
            "tier": _clean(c.get("evidence_tier")),
            "study_type": _clean(c.get("study_type")),
            "effect": _clean(c.get("effect_measure")),
        })
    return out


def knowledge(library_root: Path, rows: list[dict]) -> dict:
    """The Insights tab payload. Per paper: MeSH terms (newest PubMed
    response), author surnames, the latest note excerpt. Library-wide:
    active, non-excluded claims; the concept registry; relations."""
    papers: dict[str, dict] = {}
    claims: list[dict] = []
    for row in rows:
        pmid = row["pmid"]
        pdir = library_root / "papers" / pmid
        response = lib_inventory._newest_response(pdir) or {}
        mesh = response.get("mesh_terms")
        authors = []
        for a in lib_inventory._authors(pdir):
            name = a.get("last") or a.get("raw")
            if isinstance(name, str) and name.strip():
                authors.append(name.strip())
        notes = lib_inventory._notes_detail(pdir)
        note = notes[-1]["text"][:MAX_NOTE_EXCERPT] if notes else None
        papers[pmid] = {
            "mesh": [m for m in mesh if isinstance(m, str)] if isinstance(mesh, list) else [],
            "authors": authors,
            "note": note,
            "notes_count": len(notes),
        }
        claims.extend(_paper_claims(pdir))

    concepts = [
        {"id": c.get("concept_id"), "name": c.get("name"), "aliases": [a for a in c.get("aliases") or [] if isinstance(a, str)]}
        for c in _read_jsonl(library_root / "graph" / "concepts.jsonl")
        if c.get("concept_id") and c.get("name")
    ]
    relations = [
        {
            "id": r.get("relation_id"), "type": r.get("type"),
            "subject": r.get("subject_concept_id"), "object": r.get("object_concept_id"),
            "pmids": sorted({sc.get("pmid") for sc in r.get("supporting_claims") or [] if isinstance(sc, dict) and sc.get("pmid")}),
            "claim_ids": [sc.get("claim_id") for sc in r.get("supporting_claims") or [] if isinstance(sc, dict) and sc.get("claim_id")],
            "supporting": [{"pmid": sc.get("pmid"), "claim_id": sc.get("claim_id")} for sc in r.get("supporting_claims") or []
                           if isinstance(sc, dict) and sc.get("pmid") and sc.get("claim_id")],
            "review_state": r.get("review_state"), "stale": bool(r.get("stale")),
            "rationale": r.get("rationale"), "reviewed_at": r.get("reviewed_at"),
        }
        for r in _read_jsonl(library_root / "graph" / "relations.jsonl")
        if r.get("relation_id")
    ]
    generated_at = now_iso()
    return {
        "reviews": _reviews(library_root),
        "generated_at": generated_at,
        "papers": papers,
        "claims": claims,
        "concepts": concepts,
        "relations": relations,
        "meta": {"cache_key": knowledge_signature(library_root, rows), "generated_at": generated_at},
    }


def _review_dirs(library_root: Path) -> list[Path]:
    """`/ref:review` advanced-mode batches: library-root `reviews/<batch>/`
    and `projects/<slug>/reviews/<batch>/` (appraise._batch_dir)."""
    found = list((library_root / "reviews").glob("*/manifest.json"))
    found += list((library_root / "projects").glob("*/reviews/*/manifest.json"))
    return sorted(p.parent for p in found)


def _reviews(library_root: Path) -> list[dict]:
    """Frozen GRADE/appraisal batches, compact. GRADE certainty is one rating
    for the whole batch (appraise.grade_certainty), not per outcome.
    Per-paper appraisals are re-merged with the paper's current appraisal
    corrections, so a review recorded after the batch froze still shows."""
    import appraise  # local: pulls in the selector/relation stack only when reviews exist

    out = []
    for bdir in _review_dirs(library_root):
        manifest = lib_inventory._load_json(bdir / "manifest.json")
        grade = lib_inventory._load_json(bdir / "grade.json")
        if not isinstance(manifest, dict) or not isinstance(grade, dict):
            continue
        appraisals = {}
        for pmid in manifest.get("pmids") or []:
            a = lib_inventory._load_json(bdir / "appraisals" / f"{pmid}.json")
            if not isinstance(a, dict):
                continue
            try:
                a = appraise.merge_appraisal_review(library_root, pmid, a)
            except (OSError, ValueError, KeyError):
                pass
            entries = list((a.get("domains") or {}).values()) + list((a.get("items") or {}).values())
            statuses: dict[str, int] = {}
            for e in entries:
                if isinstance(e, dict) and e.get("review_status"):
                    statuses[e["review_status"]] = statuses.get(e["review_status"], 0) + 1
            appraisals[pmid] = {
                "checklist": a.get("checklist"), "study_type": a.get("study_type"),
                "insufficient_information": bool(a.get("insufficient_information")),
                "overall_confidence": a.get("overall_confidence"),
                "review_status": statuses, **appraise.appraisal_signal(a),
            }
        out.append({
            "batch": manifest.get("batch") or bdir.name, "project": manifest.get("project"),
            "pmids": manifest.get("pmids") or [], "resolved_at": manifest.get("resolved_at"),
            "selector_expression": manifest.get("selector_expression"),
            "grade": {k: grade.get(k) for k in ("certainty", "baseline", "baseline_reason", "downgrades_applied", "factors")},
            "appraisals": appraisals,
        })
    return out


def _stamp(path: Path) -> str:
    try:
        st = path.stat()
    except OSError:
        return "-"
    return f"{st.st_mtime_ns}.{st.st_size}"


def knowledge_signature(library_root: Path, rows: list[dict]) -> str:
    """Cheap change detector for `knowledge()`: stats only, no reads. Covers
    every input the payload reads -- the concept and relation registries,
    and per paper its claim registry, notes, authorship, appraisal
    corrections and raw PubMed responses (a new response directory bumps
    `raw/`'s mtime), plus every review batch's manifest and grade."""
    h = hashlib.sha1()
    for name in ("concepts.jsonl", "relations.jsonl"):
        h.update(f"{name}={_stamp(library_root / 'graph' / name)};".encode())
    for bdir in _review_dirs(library_root):
        h.update(f"{bdir}={_stamp(bdir / 'manifest.json')},{_stamp(bdir / 'grade.json')},{_stamp(bdir / 'appraisals')};".encode())
    for pmid in sorted(r["pmid"] for r in rows):
        pdir = library_root / "papers" / pmid
        h.update(f"{pmid}={_stamp(pdir / 'claim_registry.json')},{_stamp(pdir / 'notes.md')},"
                 f"{_stamp(pdir / 'authorship.json')},{_stamp(pdir / 'corrections.json')},{_stamp(pdir / 'raw')};".encode())
    return h.hexdigest()[:16]


_MEMO: dict[str, tuple[str, dict]] = {}
_MEMO_LOCK = threading.Lock()


def knowledge_cached(library_root: Path, rows: list[dict], *, force: bool = False) -> dict:
    """`knowledge()` memoised per process and library, keyed by
    `knowledge_signature()`. `force` recomputes regardless (the dashboard's
    refresh button)."""
    root = str(library_root)
    if not force:
        key = knowledge_signature(library_root, rows)
        with _MEMO_LOCK:
            hit = _MEMO.get(root)
        if hit and hit[0] == key:
            return hit[1]
    payload = knowledge(library_root, rows)
    with _MEMO_LOCK:
        _MEMO[root] = (payload["meta"]["cache_key"], payload)
    return payload
