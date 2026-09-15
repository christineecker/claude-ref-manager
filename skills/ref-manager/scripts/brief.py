#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""`/ref:brief` -- persisted research answer (§5a, §3b, D9: explicit refresh
only, no scheduled monitoring).

ID shape follows prisma.py's precedent (phase 5), not compare.py's: a
human-chosen `--key <label>` names WHICH recurring brief this is (a project
can have many distinct saved questions), separate from the opaque
`snapshot_id` (§3d: "table/brief/PRISMA/report IDs ... are generated at
commit, short, and never typed") minted per save/refresh. A `latest.json`
pointer under the key's directory tracks the current snapshot, exactly like
prisma.py's `_latest_snapshot_id`/`latest.json`. (compare.py instead uses
its `--batch` label directly as the artifact directory name, conflating the
two ID classes §3d keeps separate -- flagged, not fixed here, out of scope.)

Layout: projects/<slug>/briefs/<key>/{latest.json, <snapshot_id>/{manifest.json,
answer.md, evidence.json}, edits.json}. Project-less fallback (no --project):
briefs/<key>/... at the library root, matching compare.py's project-less
table-batch fallback.

Refresh diff (§5a: "reports new support, conflicts, withdrawn evidence, and
unresolved questions"): "withdrawn evidence" is checkable deterministically
-- a claim that backed the prior answer is withdrawn if it's no longer
`active` or is now `excluded_from_synthesis` in its paper's
claim_registry.json (e.g. rejected via /ref:verify since the last brief).
"conflicts" needs semantic judgment this script doesn't have; the closest
deterministic proxy reported is `new_pmids` (papers appearing in evidence
that weren't cited last time) -- the calling agent's synthesis step is what
actually reasons about whether new evidence conflicts with the prior answer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from lib_atomic import atomic_write_json, atomic_write_text
from lib_ids import gen_opaque_id
from lib_status_check import diff_status


def _key_dir(library_root: Path, project: str | None, key: str) -> Path:
    if project:
        return library_root / "projects" / project / "briefs" / key
    return library_root / "briefs" / key


def _snapshot_dir(library_root: Path, project: str | None, key: str, snapshot_id: str) -> Path:
    return _key_dir(library_root, project, key) / snapshot_id


def _edits_path(library_root: Path, project: str | None, key: str) -> Path:
    return _key_dir(library_root, project, key) / "edits.json"


def _latest_snapshot_id(library_root: Path, project: str | None, key: str) -> str | None:
    p = _key_dir(library_root, project, key) / "latest.json"
    return json.loads(p.read_text()).get("snapshot_id") if p.exists() else None


def _load_edits(library_root: Path, project: str | None, key: str) -> dict | None:
    p = _edits_path(library_root, project, key)
    return json.loads(p.read_text()) if p.exists() else None


def _evidence_hash(candidates: list[dict]) -> str:
    ids = sorted((c.get("claim_id") or f"passage:{c.get('passage_id')}") for c in candidates)
    return hashlib.sha256(json.dumps(ids, sort_keys=True).encode()).hexdigest()


def _withdrawn_evidence(library_root: Path, prior_evidence: list[dict]) -> list[dict]:
    from lib_verify_link import load_registry  # local import, same precedent as extract.py/compare.py

    withdrawn = []
    for e in prior_evidence:
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


def save_brief(
    library_root: Path, project: str | None, key: str, question: str,
    resolution: dict | None, candidates: list[dict], answer: str,
    unresolved_questions: list[str] | None, refresh: bool,
) -> dict:
    latest_id = _latest_snapshot_id(library_root, project, key)

    if latest_id and not refresh:
        sdir = _snapshot_dir(library_root, project, key, latest_id)
        manifest = json.loads((sdir / "manifest.json").read_text())
        result = {"status": "reused_frozen_brief", "snapshot_id": latest_id,
                   "manifest": manifest, "answer": (sdir / "answer.md").read_text()}
        edits = _load_edits(library_root, project, key)
        if edits:
            result["user_edit"] = edits
        return result

    prior_evidence: list[dict] = []
    if latest_id:
        pdir = _snapshot_dir(library_root, project, key, latest_id)
        prior_evidence = json.loads((pdir / "evidence.json").read_text())

    withdrawn = _withdrawn_evidence(library_root, prior_evidence) if latest_id else []
    new_claim_ids = {c["claim_id"] for c in candidates if c.get("kind") == "claim"}
    prior_claim_ids = {e["claim_id"] for e in prior_evidence if e.get("kind") == "claim"}
    added_support = sorted(new_claim_ids - prior_claim_ids)
    new_pmids = sorted({c["pmid"] for c in candidates} - {e["pmid"] for e in prior_evidence})
    # Phase 11: a paper's retraction_status can change (via /ref:audit) after
    # this brief was generated -- report that on refresh, same
    # never-silent-never-overwrite-history spirit as withdrawn claim evidence.
    prior_status_by_pmid = {
        e["pmid"]: e.get("retraction_status", "unknown")
        for e in prior_evidence if e.get("retraction_status") is not None
    }
    status_changes = diff_status(library_root, prior_status_by_pmid) if latest_id else []

    snapshot_id = gen_opaque_id("brief-")
    sdir = _snapshot_dir(library_root, project, key, snapshot_id)
    sdir.mkdir(parents=True, exist_ok=True)
    atomic_write_text(sdir / "answer.md", answer)
    atomic_write_json(sdir / "evidence.json", candidates)

    evidence_hash = _evidence_hash(candidates)
    manifest = {
        "snapshot_id": snapshot_id, "key": key, "project": project, "question": question,
        "selector_expression": resolution["selector_expression"] if resolution else "<all>",
        "pmids_at_resolution": resolution["pmids"] if resolution else None,
        "resolved_at": datetime.now(timezone.utc).isoformat(),
        "unresolved_questions": unresolved_questions or [],
        "evidence_hash": evidence_hash,
    }
    atomic_write_json(sdir / "manifest.json", manifest)
    atomic_write_json(_key_dir(library_root, project, key) / "latest.json", {"snapshot_id": snapshot_id})

    edits = _load_edits(library_root, project, key)
    if edits:
        edits["stale"] = edits.get("based_on_evidence_hash") != evidence_hash
        atomic_write_json(_edits_path(library_root, project, key), edits)

    status = "created" if not latest_id else "refreshed"
    result = {"status": status, "snapshot_id": snapshot_id, "manifest": manifest, "answer": answer}
    if latest_id:
        result["added_support_claim_ids"] = added_support
        result["new_pmids"] = new_pmids
        result["withdrawn_evidence"] = withdrawn
        result["retraction_status_changes"] = status_changes
    if edits:
        result["user_edit"] = edits
    return result


def edit_brief(library_root: Path, project: str | None, key: str, revision_text: str) -> dict:
    latest_id = _latest_snapshot_id(library_root, project, key)
    if not latest_id:
        raise ValueError(f"no brief {key!r} to edit -- run /ref:brief first")
    manifest = json.loads((_snapshot_dir(library_root, project, key, latest_id) / "manifest.json").read_text())
    edits = {
        "revision": revision_text,
        "based_on_evidence_hash": manifest["evidence_hash"],
        "edited_at": datetime.now(timezone.utc).isoformat(),
        "stale": False,
    }
    atomic_write_json(_edits_path(library_root, project, key), edits)
    return edits


def show_brief(library_root: Path, project: str | None, key: str) -> dict:
    latest_id = _latest_snapshot_id(library_root, project, key)
    if not latest_id:
        raise ValueError(f"no brief {key!r}")
    sdir = _snapshot_dir(library_root, project, key, latest_id)
    manifest = json.loads((sdir / "manifest.json").read_text())
    result = {"snapshot_id": latest_id, "manifest": manifest, "answer": (sdir / "answer.md").read_text()}
    edits = _load_edits(library_root, project, key)
    if edits:
        result["user_edit"] = edits
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["save", "edit", "show"])
    ap.add_argument("--repo", required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--project")
    ap.add_argument("--question")
    ap.add_argument("--answer-file")
    ap.add_argument("--evidence-file", help="ask_retrieve.py's candidates JSON")
    ap.add_argument("--resolution-file")
    ap.add_argument("--unresolved", nargs="*", default=None)
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--revision-file")
    args = ap.parse_args()

    library_root = Path(args.repo).expanduser().resolve()
    if not library_root.is_dir():
        print(f"error: no library at {library_root}", file=sys.stderr)
        return 1

    try:
        if args.action == "save":
            candidates = json.loads(Path(args.evidence_file).read_text())
            resolution = json.loads(Path(args.resolution_file).read_text()) if args.resolution_file else None
            answer = Path(args.answer_file).read_text()
            result = save_brief(library_root, args.project, args.key, args.question,
                                 resolution, candidates, answer, args.unresolved, args.refresh)
        elif args.action == "edit":
            revision = Path(args.revision_file).read_text()
            result = edit_brief(library_root, args.project, args.key, revision)
        else:
            result = show_brief(library_root, args.project, args.key)
    except (ValueError, FileNotFoundError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
