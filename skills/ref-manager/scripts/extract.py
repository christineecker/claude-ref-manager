# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""`/ref:extract <pmid...>` -- full claim extraction, one commit per paper (§4a).

Extraction judgment (study-type classification, PICO+ normalization) needs
an LLM, so it cannot be a deterministic script like add.py/fetch.py. The
split: commands/extract.md spawns one `agents/ref-extractor.md` subagent
per PMID (in parallel, per §4a: "fans out one ref-extractor agent invocation
per PMID"), each returning the JSON shape documented in that agent file.
This script only validates that JSON, assigns stable claim IDs, and commits
it -- it never calls PubMed, never runs a subagent, never sees full text.

Stable claim IDs (§4a: "Retain IDs for unchanged claims across reruns;
materially changed claims receive new IDs with supersession links"):
a persistent per-paper registry (papers/<pmid>/claim_registry.json, NOT
named in PLAN.md's repo layout table but needed as bookkeeping the layout
doesn't preclude) keys claim identity by locator. On each extraction run,
a claim's *content hash* (sha256 of its normalized fields + study_type,
sorted) is compared against what's on file for that locator:
  - same locator, same content hash  -> same claim_id (evidence unchanged)
  - same locator, different hash     -> new claim_id, "supersedes" the old
                                         one; the old entry is marked
                                         superseded_by and RETAINED (never
                                         deleted) for audit
  - new locator                      -> new claim_id
This is also what lets verify.py detect "changed or superseded evidence"
(§3b): a correction's target claim_id shows up superseded_by-set in the
registry.

versions/<id>/claims.json holds exactly what this extraction run emitted
(validated, with assigned claim_ids) -- the per-version snapshot the repo
layout names. claim_registry.json is the cross-version accumulated history
corrections.json / audits need to resolve a claim_id regardless of which
version originally emitted it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from lib_atomic import atomic_write_json, commit_version, pmid_lock, now_iso
from lib_ids import gen_opaque_id
from lib_schema import validate_claim, SchemaError, CLAIM_NORMALIZED_FIELDS, STUDY_TYPES
from lib_verify_link import load_registry, registry_path, revalidate_corrections

SCHEMA_VERSION = "phase4-v1"


def _content_hash(claim: dict) -> str:
    payload = {f: claim.get(f, "unknown") for f in CLAIM_NORMALIZED_FIELDS}
    payload["study_type"] = claim.get("study_type", "unknown")
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def assign_claim_ids(registry: dict, incoming_claims: list[dict], study_type: str) -> list[dict]:
    """Mutates registry in place; returns the list of fully-formed claim
    objects (with claim_id assigned) for this extraction run.

    A locator can hold MULTIPLE distinct, simultaneously-active claims (a
    coarse locator like "abstract" commonly does) -- they are co-existing
    claims, not sequential versions of one claim slot. Supersession only
    matches an incoming claim against what was already active at that
    locator BEFORE this run started (`snapshot`), and only when the match is
    unambiguous:
      - exact content-hash match against a prior active claim at that
        locator -> same claim_id, evidence unchanged
      - no exact match, and exactly ONE prior active claim at that locator
        remains unconsumed by an earlier claim in this same run -> that one
        claim's content changed -> supersede it
      - no exact match, and zero or MORE THAN ONE unconsumed prior claims at
        that locator -> ambiguous or genuinely new -> mint a fresh claim_id,
        no supersession asserted (a wrong non-supersession is recoverable
        via /ref:verify; a wrong supersession silently drops a real claim
        from the active set, which is the more harmful failure mode)
    """
    snapshot: dict[str, list[str]] = {}
    for cid, c in registry["claims"].items():
        if c.get("status") == "active":
            snapshot.setdefault(c["locator"], []).append(cid)
    consumed: set[str] = set()

    out = []
    for raw in incoming_claims:
        claim_for_hash = dict(raw)
        claim_for_hash["study_type"] = study_type
        chash = _content_hash(claim_for_hash)
        locator = raw["locator"]

        candidates = [cid for cid in snapshot.get(locator, []) if cid not in consumed]
        exact = next((cid for cid in candidates if registry["claims"][cid]["content_hash"] == chash), None)

        supersedes = None
        if exact is not None:
            claim_id = exact
            consumed.add(exact)
        elif len(candidates) == 1:
            prior_id = candidates[0]
            claim_id = gen_opaque_id("c-")
            registry["claims"][prior_id]["superseded_by"] = claim_id
            registry["claims"][prior_id]["status"] = "superseded"
            supersedes = prior_id
            consumed.add(prior_id)
        else:
            claim_id = gen_opaque_id("c-")

        claim = dict(raw)
        claim["claim_id"] = claim_id
        claim["study_type"] = study_type
        claim["content_hash"] = chash
        claim["status"] = "active"
        claim["excluded_from_synthesis"] = False
        if supersedes:
            claim["supersedes"] = supersedes

        registry["claims"][claim_id] = claim
        out.append(claim)
    return out


def extract_one(library_root: Path, record: dict, schema_stamps: dict) -> dict:
    pmid = str(record["pmid"])
    paper_dir = library_root / "papers" / pmid
    meta_path = paper_dir / "meta.json"

    with pmid_lock(library_root, pmid):
        if not meta_path.exists():
            raise ValueError(f"pmid {pmid} has no meta.json -- run /ref:add first")
        meta = json.loads(meta_path.read_text())

        study_type = record.get("study_type") or "unknown"
        if study_type not in STUDY_TYPES:
            study_type = "unknown"

        raw_claims = record.get("claims") or []
        source_hash = record.get("source_hash") or ""
        evidence_tier = record.get("evidence_tier") or ("full" if meta.get("full_text") else "abstract")

        now = now_iso()
        version_id = gen_opaque_id("v-")

        # normalize + validate each incoming claim BEFORE touching the
        # registry, so a malformed claim in this batch fails this PMID only
        # (never partially mutates the registry).
        normalized = []
        for c in raw_claims:
            claim = dict(c)
            claim.setdefault("pmid", pmid)
            claim.setdefault("version_id", version_id)
            claim.setdefault("evidence_tier", evidence_tier)
            claim.setdefault("source_hash", source_hash)
            claim["study_type"] = study_type
            for f in CLAIM_NORMALIZED_FIELDS:
                claim.setdefault(f, "unknown")
            # validate a provisional claim_id so validate_claim's shape
            # check passes before real IDs are assigned below.
            provisional = dict(claim)
            provisional.setdefault("claim_id", "provisional")
            validate_claim(provisional)
            normalized.append(claim)

        registry = load_registry(library_root, pmid)
        committed_claims = assign_claim_ids(registry, normalized, study_type)
        for c in committed_claims:
            c["version_id"] = version_id
            c["pmid"] = pmid
            validate_claim(c)

        def write_fn(staging: Path) -> None:
            atomic_write_json(staging / "claims.json", committed_claims)
            manifest = {
                "version_id": version_id, "pmid": pmid, "kind": "extraction",
                "schema_version": SCHEMA_VERSION,
                "extractor": schema_stamps.get("extractor", "ref-extractor"),
                "model": schema_stamps.get("model", "unknown"),
                "prompt_version": schema_stamps.get("prompt_version", "1"),
                "study_type": study_type,
                "study_type_confidence": record.get("study_type_confidence", "uncertain"),
                "claim_count": len(committed_claims),
                "committed_at": now,
            }
            atomic_write_json(staging / "manifest.json", manifest)

        commit_version(paper_dir, version_id, write_fn)
        atomic_write_json(registry_path(library_root, pmid), registry)

        # extraction_tier promotion is monotonic: abstract -> full, never
        # downgraded by a thinner rerun (D4).
        tier_rank = {"unavailable": 0, "abstract": 1, "full": 2}
        current_rank = tier_rank.get(meta.get("extraction_tier"), 0)
        new_rank = tier_rank.get(evidence_tier, 0)
        if new_rank > current_rank:
            meta["extraction_tier"] = evidence_tier
        meta["checked_at"] = now

        retraction = record.get("retraction_status")
        if retraction:
            meta["retraction_status"] = retraction
        else:
            meta.setdefault("retraction_status", {"status": "unknown", "source": None, "checked_at": None})

        atomic_write_json(meta_path, meta)

    revalidate_corrections(library_root, pmid)

    return {
        "pmid": pmid, "result": "extracted", "version": version_id,
        "study_type": study_type, "claim_count": len(committed_claims),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--input-file", required=True)
    ap.add_argument("--extractor", default="ref-extractor")
    ap.add_argument("--model", default="unknown")
    ap.add_argument("--prompt-version", default="1")
    args = ap.parse_args()

    library_root = Path(args.repo).expanduser().resolve()
    if not library_root.is_dir():
        print(f"error: no library at {library_root}", file=sys.stderr)
        return 1

    records = json.loads(Path(args.input_file).read_text())
    if not isinstance(records, list):
        records = [records]

    stamps = {"extractor": args.extractor, "model": args.model, "prompt_version": args.prompt_version}

    exit_code = 0
    for record in records:
        try:
            r = extract_one(library_root, record, stamps)
            line = f"{r['pmid']}: {r['result']} (study_type={r['study_type']}, claims={r['claim_count']})"
        except (SchemaError, KeyError, ValueError) as e:
            r = {"pmid": record.get("pmid", "?"), "result": "failed"}
            line = f"{r['pmid']}: failed — {e}"
            exit_code = 1
        print(line)

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
