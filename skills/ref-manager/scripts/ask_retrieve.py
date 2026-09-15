#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""`/ref:ask` retrieval half (§5, D3, D19) -- "cheapest layer first": lexical
FTS5 over claims + passages, no vector store (D3's design constraint: nothing
here may assume one exists). This script does the plumbing only; two things
it deliberately does NOT do, because they need judgment a plain script can't
supply:

  - Query expansion (MeSH terms, synonyms, gene/drug aliases, §5's
    compensating mechanism for no embeddings). The CALLING command markdown
    asks its own Claude session to think of 2-4 expansion terms for the
    question BEFORE invoking this script, and passes them via --expand. This
    script only ORs literal terms into an FTS5 MATCH expression -- it cannot
    itself decide "myocardial infarction" and "MI" are the same concept.
  - Synthesis (writing the grounded answer). That's agents/ref-synthesizer.md,
    invoked by the command markdown AFTER this script returns candidates.

catalog.rebuild() runs unconditionally before every retrieval (§D19: cache
by input hash where it matters for expensive work; rebuilding a local SQLite
projection from already-committed files is cheap at the 500-5k paper scale
D6 targets, so correctness-over-staleness wins here rather than tracking a
separate dirty flag).
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

import catalog
from lib_selector import add_selector_args, resolve_from_args, SelectorError

DEFAULT_CANDIDATE_BUDGET = 30
DEFAULT_TOKEN_BUDGET = 6000
_TOKEN_CHARS_PER_TOKEN = 4  # rough estimate, no real tokenizer dependency (§5)
_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-]{2,}")


def _terms(question: str, expansion_terms: list[str] | None) -> list[str]:
    words = _WORD_RE.findall(question or "")
    return list(dict.fromkeys(words + list(expansion_terms or [])))


def _match_expr(terms: list[str]) -> str | None:
    quoted = [f'"{t.replace(chr(34), " ")}"' for t in terms if t.strip()]
    return " OR ".join(quoted) if quoted else None


def _dedupe(candidates: list[dict]) -> list[dict]:
    """Claims win over an overlapping passage from the same paper (§5:
    "exclude duplicated rendered claims ... from the scientific-evidence
    index" -- applied here as: don't hand the synthesizer the same finding
    twice under two different candidate shapes). A passage is a duplicate of
    an already-kept candidate from the same pmid if one text contains the
    other; this is a cheap substring heuristic, not semantic dedup."""
    ordered = sorted(candidates, key=lambda c: (0 if c["kind"] == "claim" else 1, c["rank"]))
    kept: list[dict] = []
    seen_by_pmid: dict[str, list[str]] = {}
    for c in ordered:
        text = (c.get("text") or "").strip()
        prior = seen_by_pmid.setdefault(c["pmid"], [])
        if text and any(text in t or t in text for t in prior):
            continue
        if text:
            prior.append(text)
        kept.append(c)
    return kept


def _diversify(candidates: list[dict], budget: int) -> list[dict]:
    """Round-robin across distinct PMIDs (best-ranked-first within each) so
    one heavily-indexed paper can't fill the whole candidate budget (§5:
    "diversifies across PMIDs"). `candidates` must already be rank-sorted."""
    by_pmid: dict[str, list[dict]] = {}
    order: list[str] = []
    for c in candidates:
        by_pmid.setdefault(c["pmid"], []).append(c)
        if c["pmid"] not in order:
            order.append(c["pmid"])
    out: list[dict] = []
    i = 0
    while len(out) < budget and any(by_pmid.values()) and i < 100_000:
        pmid = order[i % len(order)]
        queue = by_pmid[pmid]
        if queue:
            out.append(queue.pop(0))
        i += 1
    return out


def retrieve(
    library_root: Path,
    question: str,
    expansion_terms: list[str] | None = None,
    resolution: dict | None = None,
    candidate_budget: int = DEFAULT_CANDIDATE_BUDGET,
    token_budget: int = DEFAULT_TOKEN_BUDGET,
) -> dict:
    catalog.rebuild(library_root)
    db_path = library_root / "index" / "catalog.sqlite"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    allowed = set(resolution["pmids"]) if resolution else None
    terms = _terms(question, expansion_terms)
    match_expr = _match_expr(terms)

    candidates: list[dict] = []
    if match_expr:
        for r in conn.execute(
            "SELECT c.claim_id, c.pmid, c.locator, c.evidence_tier, c.evidence_span, "
            "bm25(claims_fts) AS rank FROM claims_fts "
            "JOIN claims c ON c.claim_id = claims_fts.claim_id "
            "WHERE claims_fts MATCH ? AND c.status = 'active' AND c.excluded_from_synthesis = 0 "
            "ORDER BY rank LIMIT ?",
            (match_expr, candidate_budget * 3),
        ):
            candidates.append({
                "kind": "claim", "pmid": r["pmid"], "claim_id": r["claim_id"],
                "locator": r["locator"], "text": r["evidence_span"],
                "evidence_tier": r["evidence_tier"], "rank": r["rank"],
            })
        for r in conn.execute(
            "SELECT rowid, pmid, version_id, section, text, bm25(passages_fts) AS rank "
            "FROM passages_fts WHERE passages_fts MATCH ? ORDER BY rank LIMIT ?",
            (match_expr, candidate_budget * 3),
        ):
            candidates.append({
                "kind": "passage", "pmid": r["pmid"], "passage_id": r["rowid"],
                "version_id": r["version_id"], "locator": r["section"], "text": r["text"],
                "evidence_tier": None, "rank": r["rank"],
            })

    if allowed is not None:
        candidates = [c for c in candidates if c["pmid"] in allowed]

    candidates = _dedupe(candidates)
    candidates.sort(key=lambda c: c["rank"])
    total_matches = len(candidates)

    diversified = _diversify(candidates, candidate_budget)
    truncated_by_candidate_budget = total_matches > len(diversified)

    meta_cache: dict[str, dict] = {}
    enriched: list[dict] = []
    running_chars = 0
    dropped_for_tokens = 0
    for c in diversified:
        pmid = c["pmid"]
        if pmid not in meta_cache:
            row = conn.execute(
                "SELECT citekey, extraction_tier, retraction_status FROM papers WHERE pmid = ?", (pmid,)
            ).fetchone()
            meta_cache[pmid] = dict(row) if row else {}
        m = meta_cache[pmid]
        c["citekey"] = m.get("citekey")
        c["evidence_tier"] = c.get("evidence_tier") or m.get("extraction_tier")
        c["retraction_status"] = m.get("retraction_status", "unknown")
        text_len = len(c.get("text") or "")
        est_tokens = text_len // _TOKEN_CHARS_PER_TOKEN
        if (running_chars // _TOKEN_CHARS_PER_TOKEN) + est_tokens > token_budget:
            dropped_for_tokens += 1
            continue
        running_chars += text_len
        enriched.append(c)

    conn.close()

    report = {
        "candidate_budget": candidate_budget,
        "token_budget": token_budget,
        "match_terms": terms,
        "total_matches_before_limits": total_matches,
        "returned": len(enriched),
        "truncated_by_candidate_budget": truncated_by_candidate_budget,
        "dropped_for_token_budget": dropped_for_tokens,
        "insufficient_coverage": len(enriched) == 0,
        "selector_constrained": resolution is not None,
    }
    return {"candidates": enriched, "report": report}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--q", required=True, help="the research question")
    ap.add_argument("--expand", nargs="*", default=None,
                     help="query-expansion terms the calling agent supplied (§5)")
    ap.add_argument("--candidate-budget", type=int, default=DEFAULT_CANDIDATE_BUDGET)
    ap.add_argument("--token-budget", type=int, default=DEFAULT_TOKEN_BUDGET)
    add_selector_args(ap)
    args = ap.parse_args()

    library_root = Path(args.repo).expanduser().resolve()
    if not library_root.is_dir():
        print(f"error: no library at {library_root}", file=sys.stderr)
        return 1

    selector_given = any([args.pmids, args.project, args.query, args.study, args.search, args.from_file])
    resolution = None
    try:
        if selector_given:
            resolution = resolve_from_args(library_root, args)
        result = retrieve(library_root, args.q, args.expand, resolution,
                           args.candidate_budget, args.token_budget)
    except SelectorError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
