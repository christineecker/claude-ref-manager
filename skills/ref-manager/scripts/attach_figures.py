# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Figure image asset acquisition (ref_manager_feature_requests.md #1).

JATS conversion (`convert.py::_jats_figures`) always registers figures with
`asset_available: false` -- image bytes are never embedded in the XML we
receive. This script fills that gap:

- `download_auto()` -- run automatically by `fetch.py::fetch_one` right after
  a JATS conversion produces `figures.json` entries. Tries known, verified
  publisher image URL patterns by DOI prefix (currently: Springer Nature,
  `10.1038/...`). Per-figure resilient: one 404 never blocks the rest, and a
  publisher with no known pattern degrades to a diagnostic naming the gap,
  never a silent no-op.
- `attach_manual()` / `attach_dir()` -- post-hoc CLI paths for a version that
  was already fetched before this existed, or a publisher this script has no
  pattern for: hand it locally-downloaded bytes directly, per figure-id or by
  matching filenames in a directory to each figure's `source_locator`.

All three mutate an already-committed version's `figures.json`/`figures/` in
place (not through `lib_atomic.commit_version` -- there is no new version
here, just filling in bytes for locators that were already recorded).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from lib_atomic import atomic_write_bytes, atomic_write_json

DOWNLOAD_TIMEOUT = 20


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp")


def _locator_variants(source_locator: str) -> list[str]:
    """JATS's <graphic> href (what PMC hands us) is not reliably the same
    filename the publisher's web CDN actually serves -- verified live: PMC's
    JATS for 10.1038/s41467-025-61927-3 names `..._Fig1_HTML.jpg`, but
    nature.com's own rendered page links `..._Fig1_HTML.png` (200; the .jpg
    variant 404s). Try the locator as given first, then the same stem against
    every other common image extension."""
    variants = [source_locator]
    stem = source_locator.rsplit(".", 1)[0] if "." in source_locator else source_locator
    for ext in _IMAGE_EXTS:
        candidate = stem + ext
        if candidate not in variants:
            variants.append(candidate)
    return variants


def _candidate_urls(doi: str | None, source_locator: str) -> list[tuple[str, str]]:
    """Known, live-verified publisher image URL patterns, keyed by DOI
    prefix. Returns (label, url) pairs, one per (pattern, locator-variant).
    Coverage is intentionally partial -- unrecognized DOIs return [] and the
    caller records that as a diagnostic, not a failure (feature request #1:
    "degrade gracefully... never silently")."""
    if not doi:
        return []
    candidates = []
    if doi.startswith("10.1038/"):  # Springer Nature, incl. Nature-branded journals
        encoded_doi = urllib.parse.quote(doi, safe="")
        for locator in _locator_variants(source_locator):
            candidates.append((
                "springernature", locator,
                f"https://media.springernature.com/full/springer-static/image/"
                f"art%3A{encoded_doi}/MediaObjects/{locator}",
            ))
    return candidates


def _download(url: str) -> bytes | None:
    req = urllib.request.Request(url, headers={"User-Agent": "ref-manager/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT) as resp:
            if resp.status != 200:
                return None
            return resp.read()
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None


def _version_dir(paper_dir: Path, version_id: str | None) -> Path:
    if version_id is None:
        current_path = paper_dir / "current.json"
        if not current_path.exists():
            raise ValueError(f"{paper_dir.name}: no current.json -- run /ref:fetch first")
        version_id = json.loads(current_path.read_text())["version"]
    return paper_dir / "versions" / version_id


def _load_figures(vdir: Path) -> tuple[Path, list[dict]]:
    figures_path = vdir / "figures.json"
    if not figures_path.exists():
        raise ValueError(f"no figures.json in version {vdir.name} (JATS conversion found no figures)")
    return figures_path, json.loads(figures_path.read_text())


def _write_asset(vdir: Path, fig: dict, data: bytes, locator: str | None = None) -> None:
    if locator and locator != fig["source_locator"]:
        # the URL pattern that actually worked used a different extension
        # than the JATS-recorded locator (e.g. .jpg -> .png) -- keep
        # figures.json pointing at the file that really exists on disk.
        fig["source_locator"] = locator
    dest = vdir / "figures" / fig["source_locator"]
    atomic_write_bytes(dest, data)
    fig["sha256"] = _sha256(data)
    fig["asset_available"] = True


def download_auto(library_root: Path, pmid: str, doi: str | None, version_id: str | None = None) -> dict:
    paper_dir = library_root / "papers" / pmid
    vdir = _version_dir(paper_dir, version_id)
    figures_path, figures = _load_figures(vdir)

    diagnostics: list[str] = []
    images_available = sum(1 for f in figures if f.get("asset_available"))
    for fig in figures:
        if fig.get("asset_available"):
            continue
        candidates = _candidate_urls(doi, fig["source_locator"])
        if not candidates:
            diagnostics.append(f"figure {fig['id']}: no known image URL pattern for doi={doi!r}")
            continue
        acquired = False
        for label, locator, url in candidates:
            data = _download(url)
            if data:
                _write_asset(vdir, fig, data, locator)
                images_available += 1
                acquired = True
                break
            diagnostics.append(f"figure {fig['id']}: {label} fetch failed ({url})")
        if not acquired:
            continue

    atomic_write_json(figures_path, figures)
    return {"pmid": pmid, "figures": len(figures), "images_available": images_available, "diagnostics": diagnostics}


def attach_manual(library_root: Path, pmid: str, assets: list[tuple[str, str]], version_id: str | None = None) -> dict:
    paper_dir = library_root / "papers" / pmid
    vdir = _version_dir(paper_dir, version_id)
    figures_path, figures = _load_figures(vdir)
    by_id = {f["id"]: f for f in figures}

    diagnostics: list[str] = []
    attached = 0
    for figure_id, path_str in assets:
        fig = by_id.get(figure_id)
        if fig is None:
            diagnostics.append(f"figure {figure_id}: not found in figures.json")
            continue
        src = Path(path_str).expanduser()
        if not src.is_file():
            diagnostics.append(f"figure {figure_id}: local file not found: {src}")
            continue
        _write_asset(vdir, fig, src.read_bytes())
        attached += 1

    atomic_write_json(figures_path, figures)
    return {"pmid": pmid, "attached": attached, "of": len(assets), "diagnostics": diagnostics}


def attach_dir(library_root: Path, pmid: str, figures_dir: str, version_id: str | None = None) -> dict:
    paper_dir = library_root / "papers" / pmid
    vdir = _version_dir(paper_dir, version_id)
    figures_path, figures = _load_figures(vdir)
    dir_path = Path(figures_dir).expanduser()

    diagnostics: list[str] = []
    attached = 0
    for fig in figures:
        if fig.get("asset_available"):
            continue
        candidate = dir_path / Path(fig["source_locator"]).name
        if not candidate.is_file():
            diagnostics.append(f"figure {fig['id']}: no file named {candidate.name!r} in {dir_path}")
            continue
        _write_asset(vdir, fig, candidate.read_bytes())
        attached += 1

    atomic_write_json(figures_path, figures)
    return {"pmid": pmid, "attached": attached, "of": len(figures), "diagnostics": diagnostics}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--pmid", required=True)
    ap.add_argument("--version", help="version id; defaults to current.json's version")
    ap.add_argument("--doi", help="for auto-download by known publisher URL pattern")
    ap.add_argument("--asset", nargs=2, action="append", metavar=("FIGURE_ID", "PATH"),
                     help="post-hoc manual attach; repeatable")
    ap.add_argument("--figures-dir", help="post-hoc: match files in this dir by source_locator filename")
    args = ap.parse_args()

    library_root = Path(args.repo).expanduser().resolve()
    if not library_root.is_dir():
        print(f"error: no library at {library_root}", file=sys.stderr)
        return 1

    try:
        if args.asset:
            result = attach_manual(library_root, args.pmid, args.asset, args.version)
            print(f"{args.pmid}: attached {result['attached']}/{result['of']} figure(s) manually")
        elif args.figures_dir:
            result = attach_dir(library_root, args.pmid, args.figures_dir, args.version)
            print(f"{args.pmid}: attached {result['attached']}/{result['of']} figure(s) from {args.figures_dir}")
        else:
            result = download_auto(library_root, args.pmid, args.doi, args.version)
            print(f"{args.pmid}: figures={result['figures']} images={result['images_available']}/{result['figures']}")
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    for d in result["diagnostics"]:
        print(f"  diagnostic: {d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
