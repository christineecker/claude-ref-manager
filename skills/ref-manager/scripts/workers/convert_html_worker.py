# /// script
# requires-python = ">=3.11"
# dependencies = ["trafilatura"]
# ///
"""HTML -> GFM extraction worker (PLAN.md D16). Run via `uv run` so the
trafilatura dependency is pulled per-invocation, not into the shared
dependency-free script environment. Reads HTML on stdin, writes a JSON
result {"markdown": "...", "title": "..." | null} on stdout."""
from __future__ import annotations

import json
import sys

import trafilatura


def main() -> int:
    html = sys.stdin.read()
    md = trafilatura.extract(
        html,
        output_format="markdown",
        with_metadata=True,
        include_images=True,
        include_tables=True,
        include_links=False,
    )
    meta = trafilatura.extract_metadata(html)
    title = meta.title if meta else None
    print(json.dumps({"markdown": md, "title": title}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
