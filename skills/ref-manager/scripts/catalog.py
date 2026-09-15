#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""index/catalog.sqlite — rebuildable projection over committed records (§1, §3a).

Phase 0: papers table + an FTS5 stub for passages, populated from
papers/*/meta.json only (no extraction yet, so passages/claims/concepts stay
empty). Later phases extend `rebuild()` to walk versions/*/claims.json and
graph/*.jsonl — that's the extension point marked below.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
    pmid TEXT PRIMARY KEY,
    citekey TEXT UNIQUE,
    title TEXT,
    status TEXT,
    extraction_tier TEXT,
    checked_at TEXT
);

-- extension point (phase 2+): passages, populated from versions/*/source.md
CREATE VIRTUAL TABLE IF NOT EXISTS passages_fts USING fts5(
    pmid UNINDEXED, section, text, tokenize='porter'
);

-- extension point (phase 4+): claims
CREATE TABLE IF NOT EXISTS claims (
    claim_id TEXT PRIMARY KEY,
    pmid TEXT,
    version_id TEXT,
    evidence_tier TEXT
);

-- extension point (phase 8+): concepts / relations
CREATE TABLE IF NOT EXISTS concepts (
    concept_id TEXT PRIMARY KEY,
    name TEXT
);
CREATE TABLE IF NOT EXISTS relations (
    relation_id TEXT PRIMARY KEY,
    src_concept TEXT,
    dst_concept TEXT,
    kind TEXT
);

CREATE TABLE IF NOT EXISTS catalog_meta (
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


def rebuild(library_root: Path) -> dict:
    """Reconstruct the catalog from committed records. Incomplete staging
    directories (versions/.staging-*) are ignored (§3a)."""
    conn = _connect(library_root)
    conn.execute("DELETE FROM papers")
    papers_dir = library_root / "papers"
    n = 0
    if papers_dir.is_dir():
        for pdir in sorted(papers_dir.iterdir()):
            meta_path = pdir / "meta.json"
            if not meta_path.exists():
                continue
            meta = json.loads(meta_path.read_text())
            conn.execute(
                "INSERT OR REPLACE INTO papers "
                "(pmid, citekey, title, status, extraction_tier, checked_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    meta.get("pmid", pdir.name),
                    meta.get("citekey"),
                    meta.get("title"),
                    meta.get("status"),
                    meta.get("extraction_tier"),
                    meta.get("checked_at"),
                ),
            )
            n += 1
    conn.execute(
        "INSERT OR REPLACE INTO catalog_meta (key, value) VALUES ('papers_indexed', ?)",
        (str(n),),
    )
    conn.commit()
    conn.close()
    return {"papers_indexed": n}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["rebuild", "init"])
    ap.add_argument("--repo", required=True)
    args = ap.parse_args()

    library_root = Path(args.repo).expanduser().resolve()
    if not library_root.is_dir():
        print(f"error: no library at {library_root}", file=sys.stderr)
        return 1

    if args.action in ("rebuild", "init"):
        result = rebuild(library_root)
        print(f"catalog rebuilt: {result['papers_indexed']} paper(s) indexed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
