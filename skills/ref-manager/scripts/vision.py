#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Selective figure-vision description (PLAN.md D17, §3a caching rule).

"Vision descriptions are selective, requested during promotion or for a
question, and cached per figure." -- this never runs automatically for
every figure; it's an explicit two-step request:

  1. `vision.py request` -- checks the cache (keyed by figure hash + model
     + prompt/options, §3a's exact caching key). Cache hit: returns the
     stored description immediately, no re-invocation. Cache miss: returns
     the figure's own metadata (caption, source_locator) so the calling
     agent -- which is multimodal and can actually look at the image --
     can produce a description; the script itself never calls a vision
     model.
  2. `vision.py store` -- persists the calling agent's description under
     that same (hash, model, prompt) key, in figures.json's own `vision`
     list on the figure entry (a sibling to `caption`, never merged into
     it -- D17: "Vision output is labeled model interpretation, separate
     from reported results, with provenance").

A figure whose bytes were never fetched (asset_available: False, sha256
null -- the common case as of phase 3, since JATS/HTML conversion records
figure locators but doesn't download image bytes) cannot be described:
there is nothing to look at, and no hash to cache against. `request`
reports this explicitly (`status: asset_unavailable`) rather than
pretending a description happened.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from lib_atomic import atomic_write_json, pmid_lock


def _figures_path(library_root: Path, pmid: str, version: str) -> Path:
    paper_dir = library_root / "papers" / pmid
    if version == "current":
        current_path = paper_dir / "current.json"
        if not current_path.exists():
            raise ValueError(f"pmid {pmid!r} has no committed version yet")
        version = json.loads(current_path.read_text())["version"]
    return paper_dir / "versions" / version / "figures.json"


def _load_figures(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text())


def _find_figure(figures: list[dict], figure_id: str) -> dict | None:
    for f in figures:
        if f.get("id") == figure_id:
            return f
    return None


def _find_cached(fig: dict, model: str, prompt: str) -> dict | None:
    for entry in fig.get("vision") or []:
        if entry.get("model") == model and entry.get("prompt") == prompt:
            return entry
    return None


def list_figures(library_root: Path, pmid: str, version: str = "current") -> dict:
    path = _figures_path(library_root, pmid, version)
    figures = _load_figures(path)
    return {
        "pmid": pmid,
        "version": version,
        "figures": [
            {
                "id": fig.get("id"),
                "label": fig.get("label"),
                "caption": fig.get("caption"),
                "source_locator": fig.get("source_locator"),
                "asset_available": bool(fig.get("asset_available")),
            }
            for fig in figures
        ],
    }


def request(library_root: Path, pmid: str, version: str, figure_id: str, model: str, prompt: str) -> dict:
    path = _figures_path(library_root, pmid, version)
    figures = _load_figures(path)
    fig = _find_figure(figures, figure_id)
    if fig is None:
        return {"status": "figure_not_found", "figure_id": figure_id}

    if not fig.get("asset_available") or not fig.get("sha256"):
        return {"status": "asset_unavailable", "figure_id": figure_id,
                "reason": "figure image bytes were not fetched during conversion; nothing to describe"}

    cached = _find_cached(fig, model, prompt)
    if cached is not None:
        return {"status": "cache_hit", "figure_id": figure_id, "vision": cached}

    return {
        "status": "needs_description", "figure_id": figure_id,
        "caption": fig.get("caption"), "source_locator": fig.get("source_locator"),
        "sha256": fig.get("sha256"),
        "note": "look at the actual figure image and call `vision.py store` with a description",
    }


def store(library_root: Path, pmid: str, version: str, figure_id: str, model: str, prompt: str, description: str) -> dict:
    with pmid_lock(library_root, pmid):
        path = _figures_path(library_root, pmid, version)
        figures = _load_figures(path)
        fig = _find_figure(figures, figure_id)
        if fig is None:
            return {"status": "figure_not_found", "figure_id": figure_id}
        if not fig.get("asset_available") or not fig.get("sha256"):
            return {"status": "asset_unavailable", "figure_id": figure_id}

        entry = {
            "model": model, "prompt": prompt, "description": description,
            "kind": "model_interpretation",  # D17: never masquerades as an author-reported finding
            "figure_sha256": fig["sha256"],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        fig.setdefault("vision", [])
        # replace any existing entry for this exact (model, prompt) key
        fig["vision"] = [e for e in fig["vision"] if not (e.get("model") == model and e.get("prompt") == prompt)]
        fig["vision"].append(entry)
        atomic_write_json(path, figures)
        return {"status": "stored", "figure_id": figure_id, "vision": entry}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["request", "store", "list"])
    ap.add_argument("--repo", required=True)
    ap.add_argument("--pmid", required=True)
    ap.add_argument("--version", default="current")
    ap.add_argument("--figure-id")
    ap.add_argument("--model")
    ap.add_argument("--prompt")
    ap.add_argument("--description")
    args = ap.parse_args()

    library_root = Path(args.repo).expanduser().resolve()
    if not library_root.is_dir():
        print(f"error: no library at {library_root}", file=sys.stderr)
        return 1

    try:
        if args.action == "list":
            result = list_figures(library_root, args.pmid, args.version)
        elif args.action == "request":
            if not (args.figure_id and args.model and args.prompt):
                print("error: --figure-id, --model, and --prompt are required for request", file=sys.stderr)
                return 1
            result = request(library_root, args.pmid, args.version, args.figure_id, args.model, args.prompt)
        else:
            if not (args.figure_id and args.model and args.prompt and args.description):
                print("error: --figure-id, --model, --prompt, and --description are required for store", file=sys.stderr)
                return 1
            result = store(library_root, args.pmid, args.version, args.figure_id, args.model, args.prompt, args.description)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
