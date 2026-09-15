# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Record shapes for Phase 0 (PLAN.md §1, §3, §3a-§3d, §4a).

Stdlib-only, dependency-free validators (no jsonschema dep per D-scripts:
uv single-file, minimize dependencies). Each validate_* raises SchemaError
naming the missing/bad field; later phases extend these, they don't replace
them.
"""
from __future__ import annotations


class SchemaError(ValueError):
    pass


def _require(obj: dict, field: str, types=None):
    if field not in obj:
        raise SchemaError(f"missing required field {field!r}")
    if types is not None and not isinstance(obj[field], types):
        raise SchemaError(f"field {field!r} must be {types}, got {type(obj[field])}")


def validate_config(obj: dict) -> None:
    _require(obj, "library_root", str)
    # optional: papers_export_dir, unpaywall_email


def validate_meta(obj: dict) -> None:
    """papers/<pmid>/meta.json — bibliographic authority (D11, D14, §3a)."""
    _require(obj, "pmid", str)
    _require(obj, "citekey", str)
    _require(obj, "title", str)
    _require(obj, "status", str)
    _require(obj, "checked_at", str)
    _require(obj, "extraction_tier", str)
    if obj["extraction_tier"] not in ("abstract", "full", "unavailable"):
        raise SchemaError(f"extraction_tier: unexpected value {obj['extraction_tier']!r}")


def validate_project(obj: dict) -> None:
    """projects/<slug>/project.yaml (§3b, D20)."""
    _require(obj, "slug", str)
    _require(obj, "questions", list)
    ids = set()
    for q in obj["questions"]:
        _require(q, "id", str)
        if q["id"] in ids:
            raise SchemaError(f"duplicate question id {q['id']!r} within project {obj['slug']!r}")
        ids.add(q["id"])


def validate_screening_record(obj: dict) -> None:
    """one line of projects/<slug>/screening.jsonl (§3b)."""
    _require(obj, "pmid", str)
    _require(obj, "decision", str)
    if obj["decision"] not in ("included", "excluded", "pending"):
        raise SchemaError(f"decision: unexpected value {obj['decision']!r}")
    _require(obj, "reason", str)
    _require(obj, "timestamp", str)
    # search_run is optional (screening outside a saved query is legal, §5a)


CLAIM_NORMALIZED_FIELDS = (
    "population", "intervention", "comparator", "outcome", "timepoint",
    "direction", "effect_value", "effect_measure", "uncertainty_interval",
    "study_design", "cohort_identity", "adjustment_context",
)

STUDY_TYPES = (
    "rct", "cohort", "case_control", "meta_analysis", "molecular",
    "imaging", "review", "mixed", "unknown",
)


def validate_claim(obj: dict) -> None:
    """versions/<id>/claims.json entry (§4a)."""
    for f in ("claim_id", "pmid", "version_id", "evidence_tier", "source_hash", "locator"):
        _require(obj, f, str)
    _require(obj, "evidence_span", str)
    _require(obj, "study_type", str)
    if obj["study_type"] not in STUDY_TYPES:
        raise SchemaError(f"study_type: unexpected value {obj['study_type']!r}")
    # normalized fields stay explicitly unknown (§4a), not absent:
    for f in CLAIM_NORMALIZED_FIELDS:
        if f not in obj:
            raise SchemaError(f"missing required (possibly 'unknown') field {f!r}")


def validate_correction(obj: dict) -> None:
    """corrections.json overlay entry (§3b). target_type distinguishes what
    kind of thing is under review -- claim / concept mapping / person
    identity / grant link / author contribution statement -- all sharing
    this one overlay shape per §3c's closing line ('the same persistent-
    overlay rules as claim correction')."""
    _require(obj, "correction_id", str)
    _require(obj, "target_type", str)
    if obj["target_type"] not in (
        "claim", "concept_mapping", "person_identity", "grant_link", "author_contribution",
    ):
        raise SchemaError(f"target_type: unexpected value {obj['target_type']!r}")
    _require(obj, "target_id", str)  # claim_id / concept mapping id / etc.
    _require(obj, "decision", str)
    if obj["decision"] not in ("accept", "edit", "reject"):
        raise SchemaError(f"decision: unexpected value {obj['decision']!r}")
    _require(obj, "reviewer", str)
    _require(obj, "timestamp", str)
    _require(obj, "evidence_locator", str)
    _require(obj, "status", str)
    if obj["status"] not in ("active", "pending_review"):
        raise SchemaError(f"status: unexpected value {obj['status']!r}")


def validate_study(obj: dict) -> None:
    """studies/studies.jsonl entry (§3d). Field names match study.py's
    actual phase-5 writer, not this validator's original phase-0 stub
    (renamed publications->pmids, grouping_confidence->confidence; added
    the required "evidence" field §3b calls for: "Store grouping evidence,
    confidence, and review state")."""
    _require(obj, "study_id", str)
    _require(obj, "pmids", list)
    _require(obj, "confidence", str)
    _require(obj, "evidence", str)
    _require(obj, "review_state", str)


def validate_person(obj: dict) -> None:
    """people/<slug>.json (§3c)."""
    _require(obj, "slug", str)
    _require(obj, "name_variants", list)
    # orcid optional ("when supplied")


def validate_grant(obj: dict) -> None:
    """grants/<slug>.json (§3c)."""
    _require(obj, "slug", str)
    _require(obj, "funder", str)
    _require(obj, "award_number", str)
    _require(obj, "approved_aliases", list)
