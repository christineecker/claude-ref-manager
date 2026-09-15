# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Shared retraction/errata-status change detection for saved artifacts
(§4a: "Later /ref:audit refreshes status and invalidates affected answer
caches and graph projections"; Phase 11 gate: "Changed status propagates to
subsequent answers/views; saved artifacts expose stale evidence without
overwriting their history").

brief.py and summarize.py's evidence candidates already embed the
retraction_status *string* that was current when the artifact was
generated (see ask_retrieve.py/summarize.py's candidate-building code).
compare.py's rows/cells don't carry it, so compare.py additionally stores a
`retraction_status_snapshot` in its manifest at generation time. Either way,
detecting a change on --refresh is the same shape: compare a recorded prior
status string per PMID against the CURRENT live value in meta.json.
"""
from __future__ import annotations

import json
from pathlib import Path


def current_status(library_root: Path, pmid: str) -> str:
    meta_path = library_root / "papers" / pmid / "meta.json"
    if not meta_path.exists():
        return "unknown"
    meta = json.loads(meta_path.read_text())
    return (meta.get("retraction_status") or {}).get("status", "unknown")


def diff_status(library_root: Path, prior_status_by_pmid: dict[str, str]) -> list[dict]:
    """prior_status_by_pmid: {pmid: status string recorded at generation
    time}. Returns a change record per PMID whose live status now differs --
    never silent, always reported on refresh, never mutates the prior
    frozen artifact itself."""
    changes = []
    for pmid, prior in prior_status_by_pmid.items():
        current = current_status(library_root, pmid)
        if current != prior:
            changes.append({"pmid": pmid, "prior_status": prior, "current_status": current})
    return changes
