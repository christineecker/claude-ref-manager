# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Claim registry + corrections overlay access (§3b overlay rules).

One home for reading papers/<pmid>/claim_registry.json and corrections.json
and for the derived views every consumer needs: `active_claims()` (appraise,
compare, methods, gaps, summarize) and `withdrawn_evidence()` (brief,
summarize refresh). extract.py calls revalidate_corrections() right after
committing a new extraction pass (to catch corrections whose target claim
just got superseded), and verify.py calls it too when applying a new
correction (so a stale claim_id can't be corrected as if it were current).
"""
from __future__ import annotations

from pathlib import Path

from lib_atomic import atomic_write_json, read_json


def corrections_path(library_root: Path, pmid: str) -> Path:
    return library_root / "papers" / pmid / "corrections.json"


def registry_path(library_root: Path, pmid: str) -> Path:
    return library_root / "papers" / pmid / "claim_registry.json"


def load_corrections(library_root: Path, pmid: str) -> list[dict]:
    return read_json(corrections_path(library_root, pmid), [])


def load_registry(library_root: Path, pmid: str) -> dict:
    return read_json(registry_path(library_root, pmid), {"claims": {}, "by_locator": {}})


def active_claims(library_root: Path, pmid: str, *, for_synthesis: bool = False) -> list[dict]:
    """A paper's currently active claims. `for_synthesis=True` also drops
    claims a /ref:verify reject excluded from synthesis (gap analysis and
    retrieval want that; appraisal/comparison views show them)."""
    claims = [c for c in load_registry(library_root, pmid).get("claims", {}).values() if c.get("status") == "active"]
    if for_synthesis:
        claims = [c for c in claims if not c.get("excluded_from_synthesis")]
    return claims


def withdrawn_evidence(library_root: Path, prior_evidence: list[dict]) -> list[dict]:
    """Claim candidates of a frozen artifact (brief/summary) that are no
    longer usable: missing, superseded, or rejected since it was written."""
    withdrawn = []
    for e in prior_evidence:
        if e.get("kind") != "claim":
            continue
        entry = load_registry(library_root, e["pmid"])["claims"].get(e["claim_id"])
        if entry is None:
            reason = "claim_id not found"
        elif entry.get("status") != "active":
            reason = f"status={entry.get('status')} (superseded)"
        elif entry.get("excluded_from_synthesis"):
            reason = "excluded_from_synthesis (rejected via /ref:verify)"
        else:
            continue
        withdrawn.append({"claim_id": e["claim_id"], "pmid": e["pmid"], "reason": reason})
    return withdrawn


def revalidate_corrections(library_root: Path, pmid: str) -> list[dict]:
    """Walk this paper's corrections; any whose target claim is now
    superseded (a rerun of /ref:extract produced materially different
    content at that locator) flips to pending_review. Unchanged-evidence
    corrections are untouched -- this is a no-op for them by design
    (§3b: 'Preserve decisions on unchanged evidence')."""
    corrections = load_corrections(library_root, pmid)
    if not corrections:
        return corrections
    registry = load_registry(library_root, pmid)
    changed = False
    for c in corrections:
        if c.get("target_type") != "claim":
            continue
        entry = registry["claims"].get(c["target_id"])
        if entry and entry.get("superseded_by") and c.get("status") != "pending_review":
            c["status"] = "pending_review"
            changed = True
    if changed:
        atomic_write_json(corrections_path(library_root, pmid), corrections)
    return corrections


def apply_reject_to_registry(library_root: Path, pmid: str, claim_id: str) -> None:
    """A claim-target 'reject' decision denormalizes excluded_from_synthesis
    onto the registry entry itself, so any reader of claim_registry.json
    (a future retrieval/synthesis layer, phase 6+) doesn't have to cross-
    reference corrections.json for every claim it considers. The claim
    stays in the registry -- rejected claims are retained for audit,
    never deleted (§3b)."""
    registry = load_registry(library_root, pmid)
    entry = registry["claims"].get(claim_id)
    if entry is not None:
        entry["excluded_from_synthesis"] = True
        atomic_write_json(registry_path(library_root, pmid), registry)
