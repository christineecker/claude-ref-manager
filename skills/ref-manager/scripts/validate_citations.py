#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Citation validation (§5: "Validate that every citation resolves to
committed evidence supplied to the model"). Deterministic, no LLM needed --
parses `[^pmid]` markers out of a synthesized answer and cross-checks each
against the PMIDs actually present in the candidate set the synthesizer was
given (not just any PMID in the library -- citing an uncited-to-it paper is
exactly the failure this guards against).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

CITATION_RE = re.compile(r"\[\^([A-Za-z0-9][A-Za-z0-9_.\-]*)\]")


def extract_citations(text: str) -> list[str]:
    return CITATION_RE.findall(text or "")


def validate(answer_text: str, candidates: list[dict]) -> dict:
    cited = extract_citations(answer_text)
    candidate_pmids = {c["pmid"] for c in candidates}
    cited_unique = sorted(set(cited))
    resolved = sorted(p for p in cited_unique if p in candidate_pmids)
    unresolved = sorted(p for p in cited_unique if p not in candidate_pmids)
    return {
        "cited_pmids": cited_unique,
        "resolved": resolved,
        "unresolved": unresolved,
        "all_resolved": len(unresolved) == 0,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--answer-file", required=True)
    ap.add_argument("--candidates-file", required=True, help="ask_retrieve.py's candidates JSON")
    args = ap.parse_args()

    answer_text = Path(args.answer_file).read_text()
    candidates = json.loads(Path(args.candidates_file).read_text())
    result = validate(answer_text, candidates)
    print(json.dumps(result, indent=2))
    if not result["all_resolved"]:
        print(f"warning: {len(result['unresolved'])} citation(s) do not resolve to supplied evidence: "
              f"{result['unresolved']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
