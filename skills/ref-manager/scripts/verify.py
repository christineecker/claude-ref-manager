# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""`/ref:verify` -- corrections.json overlays (§3b) and, reusing the same
overlay rules (§3c closing line), researcher-identity / grant-alias /
author-contribution review.

Six target types share one corrections.json record shape per paper
(target_type: claim | concept_mapping | person_identity | grant_link |
author_contribution | appraisal). person_identity review delegates to
person.py's confirm_publication/reject_publication (already built in phase
2) rather than reimplementing identity matching here -- verify.py's job for
that target_type is just to also log a correction record for audit symmetry
with the other types. appraisal (phase 10) reviews one RoB2/NOS/AMSTAR-2
domain drafted by appraise.py for one PMID; target_id = "<pmid>:<checklist>:
<domain_key>".
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from lib_atomic import atomic_write_json
from lib_ids import gen_opaque_id
from lib_schema import validate_correction, SchemaError
from lib_verify_link import (
    corrections_path, load_corrections, load_registry, revalidate_corrections,
    apply_reject_to_registry,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_correction(library_root: Path, pmid: str, correction: dict) -> dict:
    validate_correction(correction)
    corrections = load_corrections(library_root, pmid)
    corrections.append(correction)
    atomic_write_json(corrections_path(library_root, pmid), corrections)
    return correction


def review_claim(
    library_root: Path, pmid: str, claim_id: str, decision: str,
    reviewer: str, rationale: str, replacement_value: dict | None,
) -> dict:
    """Accept/edit/reject a claim (§3b). Refuses if the claim_id doesn't
    exist in this paper's registry at all (a real typo/stale reference),
    but does NOT refuse a superseded claim_id -- reviewing a superseded
    claim is still a legitimate audit action, it just won't affect the
    current evidence (that's what pending_review on any correction
    targeting it already communicates)."""
    registry = load_registry(library_root, pmid)
    if claim_id not in registry["claims"]:
        raise ValueError(f"claim {claim_id!r} not found for pmid {pmid}")

    correction = {
        "correction_id": gen_opaque_id("cor-"),
        "target_type": "claim",
        "target_id": claim_id,
        "decision": decision,
        "original_value": {k: registry["claims"][claim_id].get(k) for k in
                            ("population", "intervention", "comparator", "outcome")},
        "replacement_value": replacement_value,
        "rationale": rationale,
        "reviewer": reviewer,
        "timestamp": _now(),
        "evidence_locator": registry["claims"][claim_id].get("locator", ""),
        "status": "active",
    }
    _append_correction(library_root, pmid, correction)

    if decision == "reject":
        apply_reject_to_registry(library_root, pmid, claim_id)

    return correction


def review_grant_link(
    library_root: Path, pmid: str, grant_slug: str, decision: str,
    reviewer: str, rationale: str, evidence_locator: str, award_number: str | None,
) -> dict:
    """§3c: 'A publication can link to multiple grants... The link records
    the reported funder/award, exact funding statement or metadata
    evidence, source locator/hash, match method, timestamp, and review
    decision.' Normalization is funder-specific and MUST NOT collapse
    distinct awards without a reviewed rule (§3c) -- this function records
    the link but never calls grant.py's add_alias itself; a reviewer who
    wants award_number folded into the grant's approved_aliases must do
    that as an explicit separate step, so two distinct award numbers under
    the same funder stay distinct unless someone deliberately says
    otherwise."""
    grant_path = library_root / "grants" / f"{grant_slug}.json"
    if not grant_path.exists():
        raise ValueError(f"grant {grant_slug!r} does not exist")
    grant = json.loads(grant_path.read_text())

    link = {
        "pmid": pmid,
        "award_number": award_number,
        "match_method": "manual_review",
        "evidence_locator": evidence_locator,
        "decision": decision,
        "reviewer": reviewer,
        "rationale": rationale,
        "timestamp": _now(),
    }
    grant.setdefault("publication_links", [])
    grant["publication_links"] = [
        l for l in grant["publication_links"] if l.get("pmid") != pmid
    ] + [link]
    atomic_write_json(grant_path, grant)

    correction = {
        "correction_id": gen_opaque_id("cor-"),
        "target_type": "grant_link",
        "target_id": f"{grant_slug}:{pmid}",
        "decision": decision,
        "original_value": None,
        "replacement_value": link,
        "rationale": rationale,
        "reviewer": reviewer,
        "timestamp": _now(),
        "evidence_locator": evidence_locator,
        "status": "active",
    }
    _append_correction(library_root, pmid, correction)
    return link


def review_author_contribution(
    library_root: Path, pmid: str, author_index: int, flag: str,
    evidence_statement: str, reviewer: str,
) -> dict:
    """§3c: 'Shared-first, shared-senior, and corresponding authorship are
    independent flags requiring explicit contribution/correspondence
    evidence; do not infer seniority or correspondence from last position.'
    Refuses without a non-empty evidence_statement -- there is no default,
    no inference from position, ever."""
    if flag not in ("shared_first", "shared_senior", "corresponding"):
        raise ValueError(f"unknown contribution flag {flag!r}")
    if not evidence_statement or not evidence_statement.strip():
        raise ValueError(
            f"author_contribution flag {flag!r} refused: an explicit evidence "
            "statement is required, never inferred from author position (§3c)"
        )

    auth_path = library_root / "papers" / pmid / "authorship.json"
    if not auth_path.exists():
        raise ValueError(f"pmid {pmid} has no authorship.json -- run /ref:add first")
    auth = json.loads(auth_path.read_text())
    if author_index < 0 or author_index >= len(auth.get("authors", [])):
        raise ValueError(f"author_index {author_index} out of range for pmid {pmid}")

    entry = {
        "author_index": author_index, "flag": flag,
        "evidence_statement": evidence_statement, "reviewer": reviewer,
        "timestamp": _now(),
    }
    auth.setdefault("contribution_flags", [])
    auth["contribution_flags"] = [
        f for f in auth["contribution_flags"]
        if not (f["author_index"] == author_index and f["flag"] == flag)
    ] + [entry]
    atomic_write_json(auth_path, auth)

    correction = {
        "correction_id": gen_opaque_id("cor-"),
        "target_type": "author_contribution",
        "target_id": f"{pmid}:{author_index}:{flag}",
        "decision": "accept",
        "original_value": None,
        "replacement_value": entry,
        "rationale": evidence_statement,
        "reviewer": reviewer,
        "timestamp": _now(),
        "evidence_locator": f"authorship.json#author[{author_index}]",
        "status": "active",
    }
    _append_correction(library_root, pmid, correction)
    return entry


def review_person_identity(library_root: Path, pmid: str, person_slug: str, author_index: int,
                            decision: str, reviewer: str, rationale: str) -> dict:
    """Delegates the actual identity link to person.py (phase 2) --
    confirm_publication/reject_publication already implement 'never
    inferred from name similarity alone' (§3c). Logs a correction record
    here for audit symmetry with the other four target types."""
    import person as person_mod

    if decision == "accept":
        person_mod.confirm_publication(library_root, person_slug, pmid, author_index)
    elif decision == "reject":
        person_mod.reject_publication(library_root, person_slug, pmid)
    else:
        raise ValueError("person_identity review only supports accept/reject")

    correction = {
        "correction_id": gen_opaque_id("cor-"),
        "target_type": "person_identity",
        "target_id": f"{person_slug}:{pmid}:{author_index}",
        "decision": decision,
        "original_value": None,
        "replacement_value": {"person": person_slug, "pmid": pmid, "author_index": author_index},
        "rationale": rationale,
        "reviewer": reviewer,
        "timestamp": _now(),
        "evidence_locator": f"authorship.json#author[{author_index}]",
        "status": "active",
    }
    _append_correction(library_root, pmid, correction)
    return correction


def review_appraisal(
    library_root: Path, pmid: str, checklist: str, domain_key: str, decision: str,
    reviewer: str, rationale: str, replacement_value: dict | None,
) -> dict:
    """Phase 10: accept/edit/reject one RoB2/NOS/AMSTAR-2 domain or item
    drafted by appraise.py for this PMID. target_id = "<pmid>:<checklist>:
    <domain_key>", matching exactly what appraise.py's
    merge_appraisal_review() looks up so a reviewed domain shows
    human_confirmed/human_edited/human_rejected instead of model_draft the
    next time the appraisal is regenerated or displayed. The cross-paper
    GRADE certainty rating is NOT reviewable here -- it's a set-level
    judgment with no single PMID to scope a correction to; it lives
    directly on the persisted review artifact (grade.json), same pattern
    phase 8 used for relation review living on the relation record itself."""
    correction = {
        "correction_id": gen_opaque_id("cor-"),
        "target_type": "appraisal",
        "target_id": f"{pmid}:{checklist}:{domain_key}",
        "decision": decision,
        "original_value": None,
        "replacement_value": replacement_value,
        "rationale": rationale,
        "reviewer": reviewer,
        "timestamp": _now(),
        "evidence_locator": f"appraisal:{checklist}:{domain_key}",
        "status": "active",
    }
    _append_correction(library_root, pmid, correction)
    return correction


def show(library_root: Path, pmid: str) -> list[dict]:
    revalidate_corrections(library_root, pmid)
    return load_corrections(library_root, pmid)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=[
        "review-claim", "review-grant-link", "review-author-contribution",
        "review-person-identity", "review-appraisal", "show",
    ])
    ap.add_argument("--repo", required=True)
    ap.add_argument("--pmid", required=True)
    ap.add_argument("--claim-id")
    ap.add_argument("--decision")
    ap.add_argument("--reviewer", default="user")
    ap.add_argument("--rationale", default="")
    ap.add_argument("--replacement-file")
    ap.add_argument("--grant")
    ap.add_argument("--evidence-locator", default="")
    ap.add_argument("--award-number")
    ap.add_argument("--author-index", type=int)
    ap.add_argument("--flag")
    ap.add_argument("--evidence-statement")
    ap.add_argument("--person")
    ap.add_argument("--checklist")
    ap.add_argument("--domain-key")
    args = ap.parse_args()

    library_root = Path(args.repo).expanduser().resolve()
    if not library_root.is_dir():
        print(f"error: no library at {library_root}", file=sys.stderr)
        return 1

    try:
        if args.action == "review-claim":
            replacement = json.loads(Path(args.replacement_file).read_text()) if args.replacement_file else None
            result = review_claim(library_root, args.pmid, args.claim_id, args.decision,
                                   args.reviewer, args.rationale, replacement)
        elif args.action == "review-grant-link":
            result = review_grant_link(library_root, args.pmid, args.grant, args.decision,
                                        args.reviewer, args.rationale, args.evidence_locator,
                                        args.award_number)
        elif args.action == "review-author-contribution":
            result = review_author_contribution(library_root, args.pmid, args.author_index,
                                                  args.flag, args.evidence_statement, args.reviewer)
        elif args.action == "review-person-identity":
            result = review_person_identity(library_root, args.pmid, args.person, args.author_index,
                                              args.decision, args.reviewer, args.rationale)
        elif args.action == "review-appraisal":
            replacement = json.loads(Path(args.replacement_file).read_text()) if args.replacement_file else None
            result = review_appraisal(library_root, args.pmid, args.checklist, args.domain_key,
                                       args.decision, args.reviewer, args.rationale, replacement)
        else:
            result = show(library_root, args.pmid)
    except (SchemaError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
