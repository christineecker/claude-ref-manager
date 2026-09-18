# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Saved-query folder layout -- the single place that knows where a saved
PubMed search and its triage live.

  queries/<slug>/query.yaml          immutable run history (pubmed_query.py, D15)
  queries/<slug>/triage.json         triage state (triage.py) -- optional
  queries/<slug>/metadata/, decisions.jsonl, pending.json

A triage is 1:1 with its saved query (T2), so both share one folder. The
query file stays its own file and is never rewritten by triage, so saved
runs remain immutable.

Libraries created before this layout used `queries/<slug>.yaml` and
`triage/<slug>/`; every accessor here migrates them in place on first use.
"""
from __future__ import annotations

import os
from pathlib import Path

from lib_atomic import queries_layout_lock
from lib_ids import validate_slug

QUERY_FILE = "query.yaml"


def _needs_migration(library_root: Path) -> bool:
    if (library_root / "triage").is_dir():
        return True
    q = library_root / "queries"
    return q.is_dir() and any(q.glob("*.yaml"))


def migrate(library_root: Path) -> list[str]:
    """Move a legacy `queries/<slug>.yaml` + `triage/<slug>/` library into
    `queries/<slug>/`. Idempotent; never overwrites an existing target (a
    conflicting legacy file is left where it is). Returns moved paths."""
    if not _needs_migration(library_root):
        return []
    moved: list[str] = []
    with queries_layout_lock(library_root):
        qroot = library_root / "queries"
        if qroot.is_dir():
            for old in sorted(qroot.glob("*.yaml")):
                new = qroot / old.stem / QUERY_FILE
                if old.is_file() and not new.exists():
                    new.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(old, new)
                    moved.append(f"{old.relative_to(library_root)} -> {new.relative_to(library_root)}")
        troot = library_root / "triage"
        if troot.is_dir():
            for tdir in sorted(p for p in troot.iterdir() if p.is_dir()):
                dest = qroot / tdir.name
                dest.mkdir(parents=True, exist_ok=True)
                for entry in sorted(tdir.iterdir()):
                    target = dest / entry.name
                    if not target.exists():
                        os.replace(entry, target)
                        moved.append(f"{entry.relative_to(library_root)} -> {target.relative_to(library_root)}")
                _rmdir_quiet(tdir)
            _rmdir_quiet(troot)
    return moved


def _rmdir_quiet(d: Path) -> None:
    ds = d / ".DS_Store"
    if ds.is_file():
        ds.unlink()
    try:
        d.rmdir()
    except OSError:
        pass  # leftovers (conflicts) stay put for the user to inspect


def queries_root(library_root: Path) -> Path:
    migrate(library_root)
    return library_root / "queries"


def query_dir(library_root: Path, slug: str) -> Path:
    """The saved query's folder; also the triage folder."""
    validate_slug(slug)
    return queries_root(library_root) / slug


def query_file(library_root: Path, slug: str) -> Path:
    return query_dir(library_root, slug) / QUERY_FILE


def query_slugs(library_root: Path) -> list[str]:
    root = queries_root(library_root)
    return sorted(p.parent.name for p in root.glob(f"*/{QUERY_FILE}")) if root.is_dir() else []


def triage_files(library_root: Path) -> list[Path]:
    """Every queries/<slug>/triage.json."""
    root = queries_root(library_root)
    return sorted(root.glob("*/triage.json")) if root.is_dir() else []
