#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""index/catalog.sqlite — rebuildable projection over committed records (§1, §3a).

Phase 0 built a papers table plus an FTS5 stub for passages, populated
from papers/*/meta.json only. Phase 6 is the first phase with real
committed text to index (phase 4's claims.json/claim_registry.json, phase
3's versions/<id>/source.md), so `rebuild()` now actually populates:

  passages_fts  -- paragraph-split source.md of each paper's CURRENT
                   committed version (§1: "SQLite FTS5 over source-linked
                   abstract/body sections"). A markdown heading line
                   updates the running `section` label for the paragraphs
                   under it; the heading line itself isn't indexed as a
                   passage. This is a simple paragraph split, not a real
                   section/table/figure-aware chunker -- good enough for
                   phase 6's lexical-retrieval floor, not a claim of full
                   fidelity.
  claims        -- structured columns (status, excluded_from_synthesis,
                   locator, the §4a normalized fields) for every claim in
                   every paper's claim_registry.json, active AND
                   superseded/rejected alike -- this table is a
                   transparent projection, not a policy filter; retrieval
                   (ask_retrieve.py) is what decides to query
                   WHERE status='active' AND excluded_from_synthesis=0.
  claims_fts    -- FTS5 over each claim's evidence_span + its non-"unknown"
                   normalized field values, joined back to `claims` by
                   claim_id for structured filtering alongside ranking.

Because FTS5 virtual tables can't be ALTERed to add columns, and this
catalog is explicitly documented as a rebuildable projection (§3a: "Files
hold authoritative records; SQLite and OKF are rebuildable projections"),
`rebuild()` deletes and recreates the whole catalog.sqlite file rather than
trying to migrate an existing one in place. Incomplete staging directories
(versions/.staging-*) are never read -- only papers/*/current.json's
pointer and what it names are indexed, exactly like every other committed-
state reader in this codebase.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

CLAIM_NORMALIZED_FIELDS = (
    "population", "intervention", "comparator", "outcome", "timepoint",
    "direction", "effect_value", "effect_measure", "uncertainty_interval",
    "study_design", "cohort_identity", "adjustment_context",
)

SCHEMA = """
CREATE TABLE papers (
    pmid TEXT PRIMARY KEY,
    citekey TEXT UNIQUE,
    title TEXT,
    status TEXT,
    extraction_tier TEXT,
    checked_at TEXT,
    retraction_status TEXT
);

CREATE VIRTUAL TABLE passages_fts USING fts5(
    pmid UNINDEXED, version_id UNINDEXED, section, text, tokenize='porter'
);

CREATE TABLE claims (
    claim_id TEXT PRIMARY KEY,
    pmid TEXT,
    version_id TEXT,
    locator TEXT,
    evidence_tier TEXT,
    status TEXT,
    excluded_from_synthesis INTEGER,
    study_type TEXT,
    population TEXT, intervention TEXT, comparator TEXT, outcome TEXT,
    timepoint TEXT, direction TEXT, effect_value TEXT, effect_measure TEXT,
    uncertainty_interval TEXT, study_design TEXT, cohort_identity TEXT,
    adjustment_context TEXT, evidence_span TEXT
);

CREATE VIRTUAL TABLE claims_fts USING fts5(
    claim_id UNINDEXED, pmid UNINDEXED, text, tokenize='porter'
);

-- extension point (phase 8+): concepts / relations
CREATE TABLE concepts (
    concept_id TEXT PRIMARY KEY,
    name TEXT
);
CREATE TABLE relations (
    relation_id TEXT PRIMARY KEY,
    src_concept TEXT,
    dst_concept TEXT,
    kind TEXT
);

CREATE TABLE catalog_meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


def _connect(library_root: Path) -> sqlite3.Connection:
    db_path = library_root / "index" / "catalog.sqlite"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


_HEADING_RE = re.compile(r"^#{1,6}\s+(.*)")


def split_passages(text: str) -> list[tuple[str, str]]:
    """(section, paragraph) pairs. A markdown heading updates the running
    section label for subsequent paragraphs; the heading line itself is
    not a passage."""
    section = "body"
    out = []
    for block in re.split(r"\n\s*\n", text):
        block = block.strip()
        if not block:
            continue
        m = _HEADING_RE.match(block)
        if m:
            section = m.group(1).strip() or section
            continue
        out.append((section, block))
    return out


def _claim_fts_text(c: dict) -> str:
    parts = [c.get("evidence_span", "")]
    for f in CLAIM_NORMALIZED_FIELDS:
        v = c.get(f)
        if v and v != "unknown":
            parts.append(str(v))
    return " ".join(p for p in parts if p)


def rebuild(library_root: Path) -> dict:
    """Reconstruct the catalog from committed records. Incomplete staging
    directories are never read (§3a) -- only current.json's pointer."""
    db_path = library_root / "index" / "catalog.sqlite"
    if db_path.exists():
        db_path.unlink()
    conn = _connect(library_root)

    n_papers = n_passages = n_claims = 0
    papers_dir = library_root / "papers"
    if papers_dir.is_dir():
        for pdir in sorted(papers_dir.iterdir()):
            pmid = pdir.name
            meta_path = pdir / "meta.json"
            if not meta_path.exists():
                continue
            meta = json.loads(meta_path.read_text())
            retraction = meta.get("retraction_status") or {}
            conn.execute(
                "INSERT OR REPLACE INTO papers "
                "(pmid, citekey, title, status, extraction_tier, checked_at, retraction_status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    meta.get("pmid", pmid), meta.get("citekey"), meta.get("title"),
                    meta.get("status"), meta.get("extraction_tier"), meta.get("checked_at"),
                    retraction.get("status", "unknown"),
                ),
            )
            n_papers += 1

            current_path = pdir / "current.json"
            version_id = None
            if current_path.exists():
                version_id = json.loads(current_path.read_text()).get("version")
            if version_id:
                source_path = pdir / "versions" / version_id / "source.md"
                if source_path.exists():
                    for section, block in split_passages(source_path.read_text()):
                        conn.execute(
                            "INSERT INTO passages_fts (pmid, version_id, section, text) VALUES (?, ?, ?, ?)",
                            (pmid, version_id, section, block),
                        )
                        n_passages += 1

            registry_path = pdir / "claim_registry.json"
            if registry_path.exists():
                registry = json.loads(registry_path.read_text())
                for cid, c in registry.get("claims", {}).items():
                    conn.execute(
                        "INSERT OR REPLACE INTO claims (claim_id, pmid, version_id, locator, "
                        "evidence_tier, status, excluded_from_synthesis, study_type, "
                        "population, intervention, comparator, outcome, timepoint, direction, "
                        "effect_value, effect_measure, uncertainty_interval, study_design, "
                        "cohort_identity, adjustment_context, evidence_span) VALUES "
                        "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            cid, pmid, c.get("version_id"), c.get("locator"),
                            c.get("evidence_tier"), c.get("status"),
                            1 if c.get("excluded_from_synthesis") else 0,
                            c.get("study_type"),
                            c.get("population"), c.get("intervention"), c.get("comparator"),
                            c.get("outcome"), c.get("timepoint"), c.get("direction"),
                            c.get("effect_value"), c.get("effect_measure"),
                            c.get("uncertainty_interval"), c.get("study_design"),
                            c.get("cohort_identity"), c.get("adjustment_context"),
                            c.get("evidence_span"),
                        ),
                    )
                    conn.execute(
                        "INSERT INTO claims_fts (claim_id, pmid, text) VALUES (?, ?, ?)",
                        (cid, pmid, _claim_fts_text(c)),
                    )
                    n_claims += 1

    for k, v in (("papers_indexed", n_papers), ("passages_indexed", n_passages), ("claims_indexed", n_claims)):
        conn.execute("INSERT OR REPLACE INTO catalog_meta (key, value) VALUES (?, ?)", (k, str(v)))
    conn.commit()
    conn.close()
    return {"papers_indexed": n_papers, "passages_indexed": n_passages, "claims_indexed": n_claims}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["rebuild", "init"])
    ap.add_argument("--repo", required=True)
    args = ap.parse_args()

    library_root = Path(args.repo).expanduser().resolve()
    if not library_root.is_dir():
        print(f"error: no library at {library_root}", file=sys.stderr)
        return 1

    result = rebuild(library_root)
    print(
        f"catalog rebuilt: {result['papers_indexed']} paper(s), "
        f"{result['passages_indexed']} passage(s), {result['claims_indexed']} claim(s) indexed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
