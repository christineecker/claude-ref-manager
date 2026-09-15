# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""`/ref:audit [selector]` -- library-hygiene sweep: re-check retraction/
errata status, and (`--citations`) record dated PMC cited-by observations
(PLAN.md §1, D25, §3c, §4a's closing paragraph).

This script never calls PubMed itself -- same command-markdown-calls-MCP-
then-hands-JSON-to-script split as add.py/fetch.py/extract.py. The
retraction check reuses the EXACT logic extract.py's own command doc
(commands/ref-extract.md) already specifies at ingestion time: call
get_article_metadata again, check article_types for a retraction/erratum/
correction marker, "unknown" on any failure or ambiguity, never a false
"none".

Unlike every other §5c-selector command, no selector at all means "the
whole library" here -- /ref:audit is a hygiene sweep, not a set-scoped
artifact. A selector may still be passed to scope a re-check.

Two independent behaviors, both load-bearing for the phase-11 gate:
  - retraction status: a FAILED check must never downgrade/reset the
    existing value in meta.json -- it's left untouched, with a diagnostic
    recorded separately. Only a genuinely different SUCCESSFUL result
    updates meta.json, and the set of PMIDs that actually changed status is
    returned so callers (this script also exposes a `propagate` action) can
    invalidate saved brief/compare/summarize artifacts that used them.
  - citation observations (--citations): papers/<pmid>/citations.json is a
    list that only ever APPENDS (D25). A failed lookup for a PMID with
    prior data adds nothing (or an explicit check_failed marker), never a
    zero that could be mistaken for a real observation. A PMID with no
    PMCID gets an explicit no_pmcid marker, not silence.

Citation-count source availability: checked every PubMed MCP tool in this
environment (search_articles, get_article_metadata, get_full_text_article,
find_related_articles, convert_article_ids, lookup_article_by_citation,
get_copyright_status) -- NONE provide a real cited-by/citing-article COUNT.
find_related_articles has no citation-graph link type at all (confirmed
live in phase 9's /ref:related work: only pubmed_pubmed word-similarity).
So --citations' machinery is built and tested fully, ready the moment a
real PMC ELink cited-by count source is wired in, but commands/ref-audit.md
says so plainly rather than pretending pubmed_pubmed counts are citations.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

from lib_atomic import atomic_write_json, pmid_lock
from lib_schema import validate_retraction_status, validate_citation_observation, SchemaError
from lib_selector import resolve_from_args, add_selector_args, SelectorError, _all_pmids
from lib_status_check import diff_status


def _meta_path(library_root: Path, pmid: str) -> Path:
    return library_root / "papers" / pmid / "meta.json"


def _citations_path(library_root: Path, pmid: str) -> Path:
    return library_root / "papers" / pmid / "citations.json"


def resolve_pmids(library_root: Path, args) -> list[str]:
    """No selector at all -> whole library (audit's own default, distinct
    from every other §5c command's "empty selector is an error" rule)."""
    has_selector = bool(
        args.pmids or args.project or args.screened or args.read or args.queue
        or args.query or args.search or args.from_file or args.study or args.concept
    )
    if not has_selector:
        return _all_pmids(library_root)
    return resolve_from_args(library_root, args)["pmids"]


def audit_retraction_status(library_root: Path, pmid: str, result: dict | None, error: str | None) -> dict:
    """`result`: {"status": "...", "source": "...", "checked_at": "..."} from
    a successful check, or None if the check failed/errored (`error` then
    names why). Never downgrades on failure -- prior value is read back and
    returned untouched."""
    meta_path = _meta_path(library_root, pmid)
    with pmid_lock(library_root, pmid):
        if not meta_path.exists():
            raise ValueError(f"pmid {pmid} has no meta.json -- run /ref:add first")
        meta = json.loads(meta_path.read_text())
        prior = meta.get("retraction_status") or {"status": "unknown", "source": None, "checked_at": None}

        if result is None:
            return {
                "pmid": pmid, "audit_result": "check_failed",
                "diagnostic": error or "unknown error", "prior_status_retained": prior,
            }

        validate_retraction_status(result)
        changed = result["status"] != prior.get("status")
        meta["retraction_status"] = result
        atomic_write_json(meta_path, meta)
        return {
            "pmid": pmid, "audit_result": "checked",
            "prior_status": prior.get("status"), "current_status": result["status"],
            "changed": changed,
        }


def audit_citation_observation(library_root: Path, pmid: str, observation: dict | None,
                                no_pmcid: bool, error: str | None) -> dict:
    """`observation`: {"source", "query", "count", "coverage"} from a
    successful lookup (retrieved_at is stamped here), or None. `no_pmcid`
    marks a PMID that structurally can't have a PMC cited-by observation.
    `error` explains a failed lookup when observation is None and
    no_pmcid is False. Always APPENDS -- see module docstring."""
    path = _citations_path(library_root, pmid)
    with pmid_lock(library_root, pmid):
        existing = json.loads(path.read_text()) if path.exists() else []
        now = datetime.now(timezone.utc).isoformat()

        if no_pmcid:
            entry = {"retrieved_at": now, "status": "no_pmcid", "reason": "paper has no PMCID"}
        elif observation is None:
            entry = {"retrieved_at": now, "status": "check_failed",
                      "reason": error or "citation lookup failed"}
        else:
            entry = dict(observation)
            entry["retrieved_at"] = now

        validate_citation_observation(entry)
        existing.append(entry)
        atomic_write_json(path, existing)
        return {"pmid": pmid, "entry": entry, "total_observations": len(existing)}


def latest_real_observation(library_root: Path, pmid: str) -> dict | None:
    """Most recent entry that's an actual count, skipping check_failed/
    no_pmcid markers -- "a failed check retains the prior observation with
    its date rather than writing a zero" (D25)."""
    path = _citations_path(library_root, pmid)
    if not path.exists():
        return None
    entries = json.loads(path.read_text())
    for entry in reversed(entries):
        if "count" in entry:
            return entry
    return None


def propagate_status_changes(library_root: Path, changed_pmids: list[str]) -> dict:
    """After an audit finds real status changes, report which saved
    brief/compare/summarize artifacts reference an affected PMID and are
    therefore stale as of their last generation -- callers should --refresh
    them (this function doesn't refresh anything itself, it only surfaces
    what's affected, since refreshing needs the same synthesis-agent
    involvement every --refresh already requires elsewhere)."""
    if not changed_pmids:
        return {"changed_pmids": [], "potentially_stale_artifacts": []}
    changed = set(changed_pmids)
    stale: list[dict] = []

    def _scan_batches(root: Path, kind: str, project: str | None):
        if not root.is_dir():
            return
        for bdir in root.iterdir():
            manifest_path = bdir / "manifest.json"
            if kind == "brief":
                latest_path = bdir / "latest.json"
                if not latest_path.exists():
                    continue
                snap = json.loads(latest_path.read_text()).get("snapshot_id")
                manifest_path = bdir / snap / "manifest.json" if snap else None
            if not manifest_path or not manifest_path.exists():
                continue
            manifest = json.loads(manifest_path.read_text())
            pmids = set(manifest.get("pmids") or manifest.get("pmids_at_resolution") or [])
            hit = pmids & changed
            if hit:
                stale.append({"kind": kind, "batch_or_key": bdir.name, "project": project,
                               "affected_pmids": sorted(hit)})

    _scan_batches(library_root / "tables", "compare", None)
    _scan_batches(library_root / "summaries", "summarize", None)
    _scan_batches(library_root / "briefs", "brief", None)
    projects_dir = library_root / "projects"
    if projects_dir.is_dir():
        for pdir in projects_dir.iterdir():
            slug = pdir.name
            _scan_batches(pdir / "tables", "compare", slug)
            _scan_batches(pdir / "summaries", "summarize", slug)
            _scan_batches(pdir / "briefs", "brief", slug)

    return {"changed_pmids": sorted(changed), "potentially_stale_artifacts": stale}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["retraction", "citations", "propagate", "show-citations"])
    add_selector_args(ap)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--results-file", help="JSON array of per-PMID check results from the calling agent")
    ap.add_argument("--stale-days", type=int, default=180)
    args = ap.parse_args()

    library_root = Path(args.repo).expanduser().resolve()
    if not library_root.is_dir():
        print(f"error: no library at {library_root}", file=sys.stderr)
        return 1

    try:
        if args.action == "show-citations":
            pmids = resolve_pmids(library_root, args)
            out = []
            for pmid in pmids:
                latest = latest_real_observation(library_root, pmid)
                stale = None
                if latest:
                    age = datetime.now(timezone.utc) - datetime.fromisoformat(latest["retrieved_at"])
                    stale = age > timedelta(days=args.stale_days)
                out.append({"pmid": pmid, "latest_observation": latest, "stale": stale})
            print(json.dumps(out, indent=2))
            return 0

        if not args.results_file:
            print("error: --results-file required (calling agent supplies MCP check results)",
                  file=sys.stderr)
            return 1
        results = json.loads(Path(args.results_file).read_text())

        if args.action == "retraction":
            out = []
            changed = []
            for r in results:
                pmid = str(r["pmid"])
                rec = audit_retraction_status(
                    library_root, pmid, r.get("result"), r.get("error"),
                )
                out.append(rec)
                if rec.get("changed"):
                    changed.append(pmid)
            for rec in out:
                if rec["audit_result"] == "checked":
                    print(f"{rec['pmid']}: checked ({rec['prior_status']} -> {rec['current_status']})"
                          + (" [CHANGED]" if rec["changed"] else ""))
                else:
                    print(f"{rec['pmid']}: check_failed -- prior status retained "
                          f"({rec['prior_status_retained'].get('status')}); {rec['diagnostic']}")
            print(json.dumps({"results": out, "changed_pmids": changed}, indent=2))

        elif args.action == "citations":
            out = []
            for r in results:
                pmid = str(r["pmid"])
                rec = audit_citation_observation(
                    library_root, pmid, r.get("observation"),
                    r.get("no_pmcid", False), r.get("error"),
                )
                out.append(rec)
            print(json.dumps(out, indent=2))

        else:  # propagate
            pmids = [str(r) for r in results] if isinstance(results, list) else [str(results)]
            print(json.dumps(propagate_status_changes(library_root, pmids), indent=2))

    except (SelectorError, SchemaError, KeyError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
