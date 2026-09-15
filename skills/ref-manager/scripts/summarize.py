#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""`/ref:summarize <selector>` -- prose narrative over the §5c-selected set
(§5a's "Division of labour": "prose narrative across the selected set, or a
single paper when the set is one").

Reuses agents/ref-synthesizer.md unchanged (its contract is already generic:
"N retrieved evidence candidates -> one grounded answer") -- no new subagent
invented, same precedent /ref:check-citations set in phase 7 for judgment
tasks PLAN.md doesn't name a dedicated agent for, except here an existing
agent's contract genuinely fits rather than needing an inline alternative.
The "question" handed to ref-synthesizer is a fixed instruction ("produce a
narrative summary of what these papers establish"), and the candidate list
is NOT retrieved/ranked (unlike /ref:ask) -- it's every active claim for the
selector-resolved PMIDs, full stop, since the selector already fixed the set.

One-paper vs multi-paper is NOT a special-cased branch: build_candidates()
and run_summarize() operate uniformly over resolution["pmids"] regardless of
length (§8 gate: "a one-paper set degrades to a single-paper summary" through
the same code path).

Freeze/manifest contract matches compare.py's --batch idiom (selector-driven,
not question-driven like brief.py's --key): --batch <label>, reused unless
--refresh, project-scoped under projects/<slug>/summaries/<batch>/ or a
library-root summaries/<batch>/ fallback for a project-less selector -- same
precedent compare.py established for the project-less case.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from lib_atomic import atomic_write_json, atomic_write_text
from lib_status_check import diff_status
from lib_selector import resolve_from_args, add_selector_args, SelectorError
from lib_verify_link import load_registry


def _meta(library_root: Path, pmid: str) -> dict | None:
    p = library_root / "papers" / pmid / "meta.json"
    return json.loads(p.read_text()) if p.exists() else None


def build_candidates(library_root: Path, pmids: list[str]) -> list[dict]:
    """Every active claim for the resolved PMIDs, in the same candidate
    shape agents/ref-synthesizer.md and ask_retrieve.py already use
    (pmid/citekey/kind/text/locator/evidence_tier/retraction_status) --
    no retrieval/ranking, the selector already fixed the set."""
    candidates = []
    for pmid in pmids:
        meta = _meta(library_root, pmid) or {}
        registry = load_registry(library_root, pmid)
        for claim_id, c in registry.get("claims", {}).items():
            if c.get("status") != "active":
                continue
            candidates.append({
                "kind": "claim",
                "pmid": pmid,
                "claim_id": claim_id,
                "citekey": meta.get("citekey"),
                "locator": c.get("locator"),
                "text": c.get("evidence_span"),
                "evidence_tier": c.get("evidence_tier") or meta.get("extraction_tier"),
                "retraction_status": (meta.get("retraction_status") or {}).get("status", "unknown"),
            })
    return candidates


def _batch_dir(library_root: Path, batch: str, project: str | None) -> Path:
    if project:
        return library_root / "projects" / project / "summaries" / batch
    return library_root / "summaries" / batch


def _withdrawn_evidence(library_root: Path, prior_candidates: list[dict]) -> list[dict]:
    withdrawn = []
    for e in prior_candidates:
        if e.get("kind") != "claim":
            continue
        registry = load_registry(library_root, e["pmid"])
        entry = registry["claims"].get(e["claim_id"])
        if entry is None:
            withdrawn.append({"claim_id": e["claim_id"], "pmid": e["pmid"], "reason": "claim_id not found"})
        elif entry.get("status") != "active":
            withdrawn.append({"claim_id": e["claim_id"], "pmid": e["pmid"],
                               "reason": f"status={entry.get('status')} (superseded)"})
        elif entry.get("excluded_from_synthesis"):
            withdrawn.append({"claim_id": e["claim_id"], "pmid": e["pmid"],
                               "reason": "excluded_from_synthesis (rejected via /ref:verify)"})
    return withdrawn


def run_summarize(
    library_root: Path, batch: str, project: str | None,
    resolution: dict | None, answer: str, coverage_note: str | None,
    unresolved_questions: list[str] | None, refresh: bool,
) -> dict:
    bdir = _batch_dir(library_root, batch, project)
    manifest_path = bdir / "manifest.json"
    evidence_path = bdir / "evidence.json"
    summary_path = bdir / "summary.md"

    if manifest_path.exists() and not refresh:
        manifest = json.loads(manifest_path.read_text())
        return {"status": "reused_frozen_summary", "batch": batch, "manifest": manifest,
                "summary": summary_path.read_text()}

    if resolution is None:
        raise SelectorError("no selector resolution available for a new/refreshed summary")

    prior_pmids: list[str] = []
    prior_candidates: list[dict] = []
    if manifest_path.exists():
        prior_pmids = json.loads(manifest_path.read_text())["pmids"]
        prior_candidates = json.loads(evidence_path.read_text())

    pmids = resolution["pmids"]
    candidates = build_candidates(library_root, pmids)

    bdir.mkdir(parents=True, exist_ok=True)
    atomic_write_text(summary_path, answer)
    atomic_write_json(evidence_path, candidates)

    manifest = {
        "batch": batch,
        "project": project,
        "selector_expression": resolution["selector_expression"],
        "pmids": pmids,
        "resolved_at": datetime.now(timezone.utc).isoformat(),
        "report": resolution["report"],
        "coverage_note": coverage_note,
        "unresolved_questions": unresolved_questions or [],
    }
    atomic_write_json(manifest_path, manifest)

    status = "created" if not prior_pmids else "refreshed"
    result = {"status": status, "batch": batch, "manifest": manifest, "summary": answer}
    if prior_pmids:
        result["added_pmids"] = sorted(set(pmids) - set(prior_pmids))
        result["removed_pmids"] = sorted(set(prior_pmids) - set(pmids))
        result["withdrawn_evidence"] = _withdrawn_evidence(library_root, prior_candidates)
        # Phase 11: report a paper's retraction_status changing since this
        # summary was generated, same never-silent spirit as withdrawn claims.
        prior_status_by_pmid = {
            c["pmid"]: c.get("retraction_status", "unknown")
            for c in prior_candidates if c.get("retraction_status") is not None
        }
        result["retraction_status_changes"] = diff_status(library_root, prior_status_by_pmid)
    return result


def show_summary(library_root: Path, batch: str, project: str | None) -> dict:
    bdir = _batch_dir(library_root, batch, project)
    manifest_path = bdir / "manifest.json"
    if not manifest_path.exists():
        raise SelectorError(f"no summary {batch!r} -- run /ref:summarize first")
    manifest = json.loads(manifest_path.read_text())
    return {"batch": batch, "manifest": manifest, "summary": (bdir / "summary.md").read_text()}


def main() -> int:
    ap = argparse.ArgumentParser()
    add_selector_args(ap)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--batch")  # not required for --dump-candidates
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--answer-file")
    ap.add_argument("--coverage-note")
    ap.add_argument("--unresolved", nargs="*", default=None)
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--dump-candidates", action="store_true",
                     help="resolve the selector and print the candidate evidence list "
                          "for the ref-synthesizer subagent, without requiring an "
                          "--answer-file (there's no answer yet at this point -- the "
                          "calling agent needs candidates BEFORE it can produce one)")
    args = ap.parse_args()

    library_root = Path(args.repo).expanduser().resolve()
    if not library_root.is_dir():
        print(f"error: no library at {library_root}", file=sys.stderr)
        return 1

    try:
        if args.dump_candidates:
            resolution = resolve_from_args(library_root, args)
            result = {"resolution": resolution,
                      "candidates": build_candidates(library_root, resolution["pmids"])}
        elif not args.batch:
            print("error: --batch required (unless --dump-candidates)", file=sys.stderr)
            return 1
        elif args.show:
            result = show_summary(library_root, args.batch, args.project)
        else:
            manifest_exists = (_batch_dir(library_root, args.batch, args.project) / "manifest.json").exists()
            resolution = None
            if not manifest_exists or args.refresh:
                resolution = resolve_from_args(library_root, args)
            if not args.answer_file and (not manifest_exists or args.refresh):
                print("error: --answer-file required to create/refresh a summary", file=sys.stderr)
                return 1
            answer = Path(args.answer_file).read_text() if args.answer_file else ""
            result = run_summarize(library_root, args.batch, args.project, resolution,
                                    answer, args.coverage_note, args.unresolved, args.refresh)
    except SelectorError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
