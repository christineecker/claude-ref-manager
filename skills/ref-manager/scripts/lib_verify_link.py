# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Shared linkage between extract.py and verify.py (§3b overlay rules).

Split into its own module (not folded into either extract.py or verify.py)
because both need it: extract.py calls revalidate_corrections() right after
committing a new extraction pass (to catch corrections whose target claim
just got superseded), and verify.py calls it too when applying a new
correction (so a stale claim_id can't be corrected as if it were current).
"""
from __future__ import annotations

import json
from pathlib import Path

from lib_atomic import atomic_write_json


def corrections_path(library_root: Path, pmid: str) -> Path:
    return library_root / "papers" / pmid / "corrections.json"


def registry_path(library_root: Path, pmid: str) -> Path:
    return library_root / "papers" / pmid / "claim_registry.json"


def load_corrections(library_root: Path, pmid: str) -> list[dict]:
    p = corrections_path(library_root, pmid)
    return json.loads(p.read_text()) if p.exists() else []


def load_registry(library_root: Path, pmid: str) -> dict:
    p = registry_path(library_root, pmid)
    if p.exists():
        return json.loads(p.read_text())
    return {"claims": {}, "by_locator": {}}


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
