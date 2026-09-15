#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""`/ref:status` — report the configured library and catalog counts."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from init_repo import CONFIG_PATH, load_config


def main() -> int:
    config = load_config()
    if config is None:
        print(
            f"error: no library configured ({CONFIG_PATH} not found). "
            "Run /ref:init <path> first.",
            file=sys.stderr,
        )
        return 1

    library_root = Path(config["library_root"])
    print(f"library: {library_root}")
    if not library_root.is_dir():
        print("error: configured library_root does not exist on disk", file=sys.stderr)
        return 1

    db_path = library_root / "index" / "catalog.sqlite"
    if db_path.exists():
        conn = sqlite3.connect(db_path)
        (n_papers,) = conn.execute("SELECT COUNT(*) FROM papers").fetchone()
        print(f"papers indexed: {n_papers}")
        conn.close()
    else:
        print("catalog: not built yet (run /ref:index --rebuild)")

    n_projects = sum(1 for p in (library_root / "projects").iterdir() if p.is_dir()) if (library_root / "projects").is_dir() else 0
    print(f"projects: {n_projects}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
