#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""`/ref:check-citations` (§5a): accepts a paragraph and an optional
project/selector, reports supporting/overstated/conflicting/insufficient/
unavailable evidence per assertion, and flags mismatched existing citations.

No third subagent is invented for this. PLAN.md §3 names exactly two:
`agents/ref-extractor.md` (1 paper -> extraction, phase 4) and
`agents/ref-synthesizer.md` (N candidates -> 1 answer, phase 6). Splitting a
paragraph into assertions and judging each against supplied evidence is
closer to ref-synthesizer's "grounded judgment over supplied evidence" than
to ref-extractor's per-paper extraction, but it verifies EXISTING text
rather than writing new text -- a distinct enough task that reusing either
agent file verbatim would blur its contract. Rather than invent a third
agent file, `commands/check-citations.md` instructs the calling Claude
session to do the assertion-splitting and evidence-judgment itself, inline
-- the same pattern `/ref:add`'s metadata normalization already uses (no
dedicated agent, just command-markdown instructions the calling session
follows directly). This script only validates the calling agent's findings
JSON against a schema, persists it as a frozen artifact, and optionally
triggers a bibliography export -- no judgment happens here.

This is a verification task, so the ground rule that matters most: the
input paragraph is NEVER rewritten. It's stored once, verbatim, in
input.md. Findings are a separate report keyed to assertion text (a
substring of the original), never an edited version of the paragraph
presented as if it were the same text (§8 phase-7 gate: "findings link to
evidence and do not rewrite user text automatically").

Report location: checks/<id>/ at the library root, or
projects/<slug>/checks/<id>/ when --project is given (PLAN.md's §3 repo
layout doesn't name a location for this artifact -- picked to match
compare.py's project-scoped-vs-project-less-fallback precedent). <id> is
an opaque ID (§3d: report/table/brief IDs are minted at commit, never
typed) -- there's no recurring "key" the way /ref:brief has one, since a
citation check is inherently a one-off snapshot of one paragraph, not a
standing question you refresh over time.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from lib_atomic import atomic_write_json, atomic_write_text
from lib_ids import gen_opaque_id
from lib_cite import build_exports
from lib_schema import validate_citation_check_finding, SchemaError
from validate_citations import extract_citations

COVERAGE_CAVEAT = (
    "Available library coverage does not establish a comprehensive literature "
    "check (§5a) -- an 'unavailable' or 'insufficient' verdict means this "
    "library doesn't have evidence either way, not that none exists."
)


def _check_dir(library_root: Path, project: str | None, check_id: str) -> Path:
    base = (library_root / "projects" / project / "checks") if project else (library_root / "checks")
    return base / check_id


def merge_cited_pmid_candidates(paragraph: str, candidates: list[dict], claims_lookup) -> list[dict]:
    """A citation check must verify what's ALREADY cited, not only what BM25
    would surface from the paragraph's own words -- a paragraph can cite a
    PMID using vocabulary that doesn't lexically match its own assertion
    text (e.g. citing a trial by number, discussing its finding in different
    words). Any [^pmid] already in the paragraph gets its active claims
    pulled in via `claims_lookup(pmid) -> list[dict]` even if retrieval
    missed it, tagged `cited_in_input: true` so the report can distinguish
    "found by search" from "found because you already cited it"."""
    have = {c["pmid"] for c in candidates}
    for pmid in extract_citations(paragraph):
        if pmid in have:
            continue
        for c in claims_lookup(pmid):
            c = dict(c)
            c["cited_in_input"] = True
            candidates.append(c)
        have.add(pmid)
    return candidates


def persist_check(
    library_root: Path,
    project: str | None,
    paragraph: str,
    findings: list[dict],
    candidates: list[dict],
    resolution: dict | None,
    export_bib: bool,
) -> dict:
    for f in findings:
        validate_citation_check_finding(f)
        if f["assertion_text"] not in paragraph:
            raise SchemaError(
                f"assertion_text {f['assertion_text']!r} is not a substring of the input "
                "paragraph -- findings must reference the original text, never invented or "
                "paraphrased spans"
            )

    candidate_by_pmid_claim = {(c.get("pmid"), c.get("claim_id")) for c in candidates if c.get("kind") == "claim"}
    candidate_pmids = {c["pmid"] for c in candidates}
    for f in findings:
        for ev in f["evidence"]:
            if ev["pmid"] not in candidate_pmids:
                raise SchemaError(
                    f"finding cites pmid {ev['pmid']!r} which is not in the supplied candidate "
                    "set -- evidence refs must resolve to retrieved evidence, same rule as "
                    "validate_citations.py"
                )
            if ev.get("claim_id") and (ev["pmid"], ev["claim_id"]) not in candidate_by_pmid_claim:
                raise SchemaError(
                    f"finding cites claim_id {ev['claim_id']!r} on pmid {ev['pmid']!r} which is "
                    "not among the supplied claim candidates"
                )

    check_id = gen_opaque_id("check-")
    cdir = _check_dir(library_root, project, check_id)
    cdir.mkdir(parents=True, exist_ok=True)

    atomic_write_text(cdir / "input.md", paragraph)
    atomic_write_json(cdir / "findings.json", findings)

    referenced_pmids = sorted({ev["pmid"] for f in findings for ev in f["evidence"]})

    manifest = {
        "check_id": check_id,
        "project": project,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "selector_expression": resolution["selector_expression"] if resolution else "<none>",
        "pmids_at_resolution": resolution["pmids"] if resolution else None,
        "referenced_pmids": referenced_pmids,
        "verdict_counts": {
            v: sum(1 for f in findings if f["verdict"] == v)
            for v in ("supported", "overstated", "conflicting", "insufficient", "unavailable")
        },
        "caveat": COVERAGE_CAVEAT,
    }

    if export_bib and referenced_pmids:
        csl_entries, bib_text = build_exports(library_root, referenced_pmids)
        atomic_write_json(cdir / "references.csl.json", csl_entries)
        atomic_write_text(cdir / "references.bib", bib_text)
        manifest["bibliography_exported"] = True
    else:
        manifest["bibliography_exported"] = False

    atomic_write_json(cdir / "manifest.json", manifest)

    return {"check_id": check_id, "manifest": manifest, "findings": findings, "caveat": COVERAGE_CAVEAT}


def show_check(library_root: Path, project: str | None, check_id: str) -> dict:
    cdir = _check_dir(library_root, project, check_id)
    manifest_path = cdir / "manifest.json"
    if not manifest_path.exists():
        raise ValueError(f"no check {check_id!r}")
    manifest = json.loads(manifest_path.read_text())
    findings = json.loads((cdir / "findings.json").read_text())
    paragraph = (cdir / "input.md").read_text()
    return {"check_id": check_id, "manifest": manifest, "findings": findings, "input": paragraph}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["check", "show"])
    ap.add_argument("--repo", required=True)
    ap.add_argument("--project")
    ap.add_argument("--paragraph-file")
    ap.add_argument("--findings-file")
    ap.add_argument("--candidates-file", help="ask_retrieve.py's candidates JSON, "
                     "after merge_cited_pmid_candidates if the calling command did that")
    ap.add_argument("--resolution-file")
    ap.add_argument("--export-bib", action="store_true")
    ap.add_argument("--id", help="check_id, for 'show'")
    args = ap.parse_args()

    library_root = Path(args.repo).expanduser().resolve()
    if not library_root.is_dir():
        print(f"error: no library at {library_root}", file=sys.stderr)
        return 1

    try:
        if args.action == "check":
            paragraph = Path(args.paragraph_file).read_text()
            findings = json.loads(Path(args.findings_file).read_text())
            candidates = json.loads(Path(args.candidates_file).read_text())
            resolution = json.loads(Path(args.resolution_file).read_text()) if args.resolution_file else None
            result = persist_check(library_root, args.project, paragraph, findings,
                                    candidates, resolution, args.export_bib)
        else:
            result = show_check(library_root, args.project, args.id)
    except (SchemaError, ValueError, FileNotFoundError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
