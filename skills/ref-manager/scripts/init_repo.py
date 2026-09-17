#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""`/ref:init [path]` — D2: library path chosen at init, recorded in
~/.config/ref-manager/config.json. Every other command fails loudly when
no library is configured (see status.py / any command doc)."""
from __future__ import annotations

import argparse
from pathlib import Path

from lib_atomic import atomic_write_json
from lib_schema import validate_config

CONFIG_PATH = Path.home() / ".config" / "ref-manager" / "config.json"

# Core dirs only -- everything else (projects, people, labs, grants, reports,
# studies, graph, okf, queries) is created lazily by the command that first
# writes into it (every writer goes through atomic_write_json/_text, which
# mkdir(parents=True)'s its own parent, or mkdir's explicitly -- see
# project.py:create, report.py, okf_emit.py, graph_people.py).
LIBRARY_DIRS = [
    "papers", "index", "index/.locks", "index/aliases",
    "exports", "exports/papers",
]


def load_config() -> dict | None:
    if not CONFIG_PATH.exists():
        return None
    import json

    return json.loads(CONFIG_PATH.read_text())


def init_library(path: Path, force: bool = False) -> dict:
    if CONFIG_PATH.exists() and not force:
        existing = load_config()
        raise SystemExit(
            f"error: a library is already configured at {existing.get('library_root')} "
            f"({CONFIG_PATH}). Pass --force to reconfigure."
        )

    library_root = path.expanduser().resolve()
    if library_root.exists() and not library_root.is_dir():
        raise SystemExit(
            f"error: {library_root} already exists and is not a directory. "
            "Choose a different path."
        )
    try:
        for rel in LIBRARY_DIRS:
            (library_root / rel).mkdir(parents=True, exist_ok=True)
    except (PermissionError, OSError) as e:
        raise SystemExit(
            f"error: could not create library at {library_root}: {e}. "
            "Check the path is writable, then retry."
        )
    log = library_root / "log.md"
    if not log.exists():
        log.write_text("# ref-manager log\n")

    config = {"library_root": str(library_root)}
    validate_config(config)
    atomic_write_json(CONFIG_PATH, config)
    return config


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    config = init_library(Path(args.path), force=args.force)
    print(f"library initialized at {config['library_root']}")
    print(f"config written to {CONFIG_PATH}")
    print()
    print("Next steps:")
    print("  /ref:add <pmid>   add your first paper")
    print("  /ref:status       check library health")
    print("  /ref:project      create a project to organize papers")
    print()
    print("Example: /ref:add 12345678")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
