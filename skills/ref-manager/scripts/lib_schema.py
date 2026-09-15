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


CITATION_CHECK_VERDICTS = ("supported", "overstated", "conflicting", "insufficient", "unavailable")


def validate_citation_check_finding(obj: dict) -> None:
    """One entry of a /ref:check-citations report's findings.json (§5a).

    `verdict` boundaries (not pinned by PLAN.md beyond naming the four
    categories "supporting, conflicting, insufficient, or unavailable" plus
    "overstatement" as a separate thing to flag -- reconciled here as five
    verdicts since overstatement is itself a verdict an assertion earns,
    not just an annotation on top of "supported"):
      - supported:    evidence directly backs the assertion as stated
      - overstated:   evidence exists and is relevant, but is weaker/more
                       hedged than the assertion claims (e.g. assertion says
                       "proves"/"causes", evidence says "associated with")
      - conflicting:  evidence contradicts the assertion
      - insufficient: relevant evidence exists but doesn't clearly resolve
                       the assertion either way
      - unavailable:  no relevant evidence among the retrieved candidates
    `evidence` is required (non-empty) for every verdict except
    "unavailable", where it must be empty -- there is nothing to point to.
    """
    _require(obj, "assertion_text", str)
    _require(obj, "verdict", str)
    if obj["verdict"] not in CITATION_CHECK_VERDICTS:
        raise SchemaError(f"verdict: unexpected value {obj['verdict']!r}")
    _require(obj, "evidence", list)
    if obj["verdict"] == "unavailable":
        if obj["evidence"]:
            raise SchemaError("verdict 'unavailable' must have empty evidence")
    elif not obj["evidence"]:
        raise SchemaError(f"verdict {obj['verdict']!r} requires at least one evidence reference")
    for ev in obj["evidence"]:
        _require(ev, "pmid", str)
    # existing_citation_pmid / citation_mismatch / note are optional


RELATION_TYPES = ("supports", "potential_conflict", "contradicts", "extends", "replicates")


def validate_concept(obj: dict) -> None:
    """graph/concepts.jsonl entry (§3, §3d). Primary key is a user-chosen
    slug (not a code) precisely because concepts accumulate aliases from
    normalization over time -- "MI" and "myocardial infarction" both
    resolve to one concept_id via the aliases list."""
    _require(obj, "concept_id", str)
    _require(obj, "name", str)
    _require(obj, "aliases", list)
    _require(obj, "alias_provenance", dict)
    _require(obj, "created_at", str)
    _require(obj, "updated_at", str)


def validate_relation(obj: dict) -> None:
    """graph/relations.jsonl entry (§3, §3a, §4a). A typed edge between two
    CONCEPTS (not two claims directly) -- §4a's claim-to-claim comparison
    is what PROPOSES an edge, but the edge itself lives at the concept
    level so "what contradicts concept X" (§5's structural retrieval
    layer) is a single lookup, not a claim-pair search. Every edge names
    its supporting claims (pmid + claim_id pairs, since claim_id alone
    isn't globally unique across papers) and source version ids, per §3a:
    "Each edge names supporting claims and source version IDs."

    `contradicts` requires review_state == "reviewed" and a non-empty
    rationale -- never auto-promoted from potential_conflict (§4a).
    `stale` flips true when a refresh finds a supporting claim no longer
    active (superseded or excluded_from_synthesis) -- §3a: "Re-extraction
    invalidates affected evidence links and triggers an incremental graph
    refresh." Going stale never clears review_state/rationale (§3a:
    "Reviewed edge decisions persist in relation records") -- it only
    flags the review's evidence changed and may need reconfirming, same
    pending-review-not-silently-dropped pattern §3b uses for claim
    corrections.
    """
    _require(obj, "relation_id", str)
    _require(obj, "type", str)
    if obj["type"] not in RELATION_TYPES:
        raise SchemaError(f"type: unexpected value {obj['type']!r}")
    _require(obj, "subject_concept_id", str)
    _require(obj, "object_concept_id", str)
    _require(obj, "supporting_claims", list)
    if not obj["supporting_claims"]:
        raise SchemaError("a relation must name at least one supporting claim (§3a)")
    for sc in obj["supporting_claims"]:
        _require(sc, "pmid", str)
        _require(sc, "claim_id", str)
    _require(obj, "source_version_ids", list)
    _require(obj, "review_state", str)
    if obj["review_state"] not in ("unreviewed", "reviewed"):
        raise SchemaError(f"review_state: unexpected value {obj['review_state']!r}")
    _require(obj, "rationale", (str, type(None)))
    if obj["type"] == "contradicts":
        if obj["review_state"] != "reviewed" or not (obj["rationale"] or "").strip():
            raise SchemaError(
                "type 'contradicts' requires review_state='reviewed' and a "
                "non-empty rationale -- never auto-promoted from potential_conflict (§4a)"
            )
    _require(obj, "stale", bool)
    _require(obj, "created_at", str)
    _require(obj, "updated_at", str)
