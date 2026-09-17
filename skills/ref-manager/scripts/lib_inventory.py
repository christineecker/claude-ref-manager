#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Shared per-paper inventory (LIBRARY_VIEWER_IMPLEMENTATION_PLAN.md §4).

"One classifier, one inventory." Source state comes from
`lib_selector.source_badge()`; every per-paper row a viewer or report needs
comes from `rows()` / `detail()` here. `status.py`, `lint.py`, `/ref:list`,
and `/ref:dashboard` never re-derive either (§1.2).

`rows()` is the cheap, one-per-paper summary every list/summary view is
built from. `detail()` is the heavier per-paper payload (abstract, funding,
figures, claims, notes, files) a paper panel loads on demand. Both are
read-only -- nothing in this module writes to the library (§1.3: viewers are
read-only, with the one exception of `note.py append`, which lives
elsewhere).

`lint_flags()` factors the per-paper issue predicates that used to live only
in `lint.py`'s loop body into a shared helper (§4.2's note), so `rows()` and
`lint.lint()` agree on what "missing_current" etc. mean by construction
instead of by convention.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from lib_atomic import current_version
import catalog
from lib_selector import has_pdf, source_badge


def _current_version(pdir: Path) -> str | None:
    """Tolerant `lib_atomic.current_version`: a malformed current.json reads as no version."""
    try:
        return current_version(pdir)
    except ValueError:
        return None

STALE_DAYS_DEFAULT = 180

LINT_BUCKETS = (
    "missing_meta", "missing_title", "missing_year", "missing_journal",
    "missing_abstract", "metadata_only", "abstract_only", "oa_pending",
    "missing_doi", "missing_current", "missing_claim_registry",
    "stale_retraction_check", "malformed_meta",
)


def _load_json(path: Path) -> dict | list | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _paper_dirs(library_root: Path) -> list[Path]:
    papers_dir = library_root / "papers"
    if not papers_dir.is_dir():
        return []
    return sorted([p for p in papers_dir.iterdir() if p.is_dir()], key=lambda p: p.name)


def _read_meta(pdir: Path) -> tuple[str, dict | None]:
    """Returns (status, meta) where status is "ok" | "missing" | "malformed"."""
    meta_path = pdir / "meta.json"
    if not meta_path.exists():
        return "missing", None
    obj = _load_json(meta_path)
    if not isinstance(obj, dict):
        return "malformed", None
    return "ok", obj


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def lint_flags(
    pdir: Path,
    meta_status: str,
    meta: dict | None,
    *,
    now: datetime | None = None,
    stale_days: int = STALE_DAYS_DEFAULT,
) -> list[str]:
    """Per-paper issue-bucket predicates (LIBRARY_VIEWER_IMPLEMENTATION_PLAN.md
    §4.2's "factor them into a shared helper rather than duplicating").
    `meta_status`/`meta` come from `_read_meta()`. Shared verbatim by
    `rows()` and `lint.lint()` so a bucket means the same thing in both."""
    if meta_status == "missing":
        return ["missing_meta"]
    if meta_status == "malformed":
        return ["malformed_meta"]

    assert meta is not None
    flags: list[str] = []
    if not (meta.get("title") or "").strip():
        flags.append("missing_title")
    if not (meta.get("year") or "").strip():
        flags.append("missing_year")
    if not (meta.get("journal") or "").strip():
        flags.append("missing_journal")
    if not (meta.get("doi") or "").strip():
        flags.append("missing_doi")
    if not bool(meta.get("abstract_available")):
        flags.append("missing_abstract")

    badge = source_badge(pdir, meta)
    if badge in ("metadata-only", "abstract-only", "oa-pending"):
        flags.append(badge.replace("-", "_"))

    if not (pdir / "current.json").exists():
        flags.append("missing_current")
    if not (pdir / "claim_registry.json").exists():
        flags.append("missing_claim_registry")

    now = now or datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(days=stale_days)
    checked_at = _parse_iso(meta.get("checked_at"))
    if checked_at is not None and checked_at < stale_cutoff:
        flags.append("stale_retraction_check")

    return flags


def _pdf_paths(pdir: Path) -> list[str]:
    """Newest raw PDF first, so a replacement uploaded from the dashboard is
    the one its PDF tab opens; older variants stay listed after it."""
    raw: list[tuple[float, str]] = []
    raw_dir = pdir / "raw"
    if raw_dir.is_dir():
        for sub in sorted(raw_dir.iterdir()):
            pdf = sub / "source.pdf"
            if sub.is_dir() and pdf.exists():
                raw.append((pdf.stat().st_mtime, str(pdf.relative_to(pdir))))
    paths = [rel for _mtime, rel in sorted(raw, key=lambda t: -t[0])]
    reader_pdf = pdir / "reader" / "article.pdf"
    if reader_pdf.exists():
        paths.append(str(reader_pdf.relative_to(pdir)))
    return paths


def _figures_counts(pdir: Path, version_id: str | None) -> tuple[int, int]:
    if not version_id:
        return 0, 0
    figures_path = pdir / "versions" / version_id / "figures.json"
    figures = _load_json(figures_path)
    if not isinstance(figures, list):
        return 0, 0
    total = len(figures)
    with_image = sum(1 for f in figures if isinstance(f, dict) and f.get("asset_available"))
    return total, with_image


def _claims_active(pdir: Path) -> int:
    registry = _load_json(pdir / "claim_registry.json")
    if not isinstance(registry, dict):
        return 0
    claims = registry.get("claims")
    if not isinstance(claims, dict):
        return 0
    return sum(1 for c in claims.values() if isinstance(c, dict) and c.get("status") == "active")


def _notes_count(pdir: Path) -> int:
    notes_path = pdir / "notes.md"
    if not notes_path.exists():
        return 0
    text = notes_path.read_text(encoding="utf-8")
    return sum(1 for part in text.split("\n---\n") if part.strip())


def _authors(pdir: Path) -> list[dict]:
    authorship = _load_json(pdir / "authorship.json")
    if not isinstance(authorship, dict):
        return []
    authors = authorship.get("authors")
    if not isinstance(authors, list):
        return []
    return [a for a in authors if isinstance(a, dict)]


def _author_surname(a: dict) -> str:
    return (a.get("last") or a.get("raw") or "").strip()


def _author_display(a: dict | None) -> str | None:
    """`Last, First` for the dashboard's Last-author column; None if unknown."""
    if not a:
        return None
    last, first = (a.get("last") or "").strip(), (a.get("first") or "").strip()
    if last and first:
        return f"{last}, {first}"
    return last or first or (a.get("raw") or "").strip() or None


def _authors_short(authors: list[dict], limit: int = 3) -> str | None:
    """`Smith, Jones, Patel, …` -- the first `limit` surnames, with an
    ellipsis when the list is longer (the dashboard's Authors column)."""
    names = [n for n in (_author_surname(a) for a in authors) if n]
    if not names:
        return None
    head = ", ".join(names[:limit])
    return head + ", …" if len(names) > limit else head


def _project_index(library_root: Path) -> dict[str, list[dict]]:
    """pmid -> [{slug, reading_status, added_at}], scanned once (§4.2)."""
    index: dict[str, list[dict]] = {}
    projects_dir = library_root / "projects"
    if not projects_dir.is_dir():
        return index
    for pdir in sorted(projects_dir.iterdir()):
        if not pdir.is_dir():
            continue
        slug = pdir.name
        papers_doc = _load_json(pdir / "papers.yaml")
        if not isinstance(papers_doc, dict):
            continue
        for m in papers_doc.get("papers", []):
            if not isinstance(m, dict) or not m.get("pmid"):
                continue
            index.setdefault(m["pmid"], []).append({
                "slug": slug,
                "reading_status": m.get("reading_status"),
                "added_at": m.get("added_at"),
            })
    return index


def _catalog_pmids(library_root: Path) -> set[str] | None:
    """None when there is no catalog at all; a (possibly empty) set otherwise."""
    if catalog.catalog_info(library_root) is None:
        return None
    db_path = library_root / "index" / "catalog.sqlite"
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            return {row[0] for row in conn.execute("SELECT pmid FROM papers")}
        finally:
            conn.close()
    except sqlite3.Error:
        return set()


def rows(library_root: Path, *, stale_days: int = STALE_DAYS_DEFAULT) -> list[dict]:
    """One cheap summary row per paper under `papers/<pmid>/` (§4.2)."""
    now = datetime.now(timezone.utc)
    project_index = _project_index(library_root)
    catalog_pmids = _catalog_pmids(library_root)

    out = []
    for pdir in _paper_dirs(library_root):
        pmid = pdir.name
        meta_status, meta = _read_meta(pdir)
        flags = lint_flags(pdir, meta_status, meta, now=now, stale_days=stale_days)

        if meta_status != "ok":
            out.append({
                "pmid": pmid, "citekey": None, "title": None, "year": None,
                "journal": None, "doi": None, "pmcid": None, "status": None,
                "extraction_tier": None, "checked_at": None,
                "source_badge": None,
                "has_pdf": has_pdf(pdir), "pdf_paths": _pdf_paths(pdir),
                "has_fulltext": False, "version_id": None,
                "figures_total": 0, "figures_with_image": 0,
                "claims_active": _claims_active(pdir),
                "retraction_status": "unknown",
                "days_since_check": None, "stale_check": False,
                "projects": project_index.get(pmid, []),
                "notes_count": _notes_count(pdir),
                "authors_count": len(_authors(pdir)), "first_author": None,
                "last_author": None, "authors_short": None,
                "in_catalog": bool(catalog_pmids and pmid in catalog_pmids),
                "lint_flags": flags,
            })
            continue

        version_id = _current_version(pdir)
        has_fulltext = bool(version_id and (pdir / "versions" / version_id / "source.md").exists())
        figures_total, figures_with_image = _figures_counts(pdir, version_id)
        checked_at_dt = _parse_iso(meta.get("checked_at"))
        days_since_check = (now - checked_at_dt).days if checked_at_dt is not None else None
        authors = _authors(pdir)

        out.append({
            "pmid": pmid,
            "citekey": meta.get("citekey"),
            "title": meta.get("title"),
            "year": meta.get("year"),
            "journal": meta.get("journal"),
            "doi": meta.get("doi"),
            "pmcid": meta.get("pmcid"),
            "status": meta.get("status"),
            "extraction_tier": meta.get("extraction_tier"),
            "checked_at": meta.get("checked_at"),
            "source_badge": source_badge(pdir, meta),
            "has_pdf": has_pdf(pdir),
            "pdf_paths": _pdf_paths(pdir),
            "has_fulltext": has_fulltext,
            "version_id": version_id,
            "figures_total": figures_total,
            "figures_with_image": figures_with_image,
            "claims_active": _claims_active(pdir),
            "retraction_status": (meta.get("retraction_status") or {}).get("status", "unknown"),
            "days_since_check": days_since_check,
            "stale_check": "stale_retraction_check" in flags,
            "projects": project_index.get(pmid, []),
            "notes_count": _notes_count(pdir),
            "authors_count": len(authors),
            "first_author": authors[0] if authors else None,
            "last_author": _author_display(authors[-1]) if len(authors) > 1 else None,
            "authors_short": _authors_short(authors),
            "in_catalog": bool(catalog_pmids and pmid in catalog_pmids),
            "lint_flags": flags,
        })

    return out


# --------------------------------------------------------------- detail()


def _iter_headings(text: str) -> list[tuple[int, str, int, int]]:
    """[(level, heading_text, start_line_idx, end_line_idx)] spans of a
    markdown source.md, where end_line_idx is the line index (exclusive)
    where the next heading of the same or higher level begins (or EOF).
    `<div>` / `:::` fence lines are dropped from the returned body when
    callers slice with `section_body()` below."""
    lines = text.splitlines()
    headings: list[tuple[int, str, int]] = []  # (level, text, line_idx)
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#"):
            j = 0
            while j < len(stripped) and stripped[j] == "#":
                j += 1
            if j <= 6 and (j == len(stripped) or stripped[j] == " "):
                headings.append((j, stripped[j:].strip(), i))

    spans = []
    for idx, (level, htext, start) in enumerate(headings):
        end = len(lines)
        for level2, _htext2, start2 in headings[idx + 1:]:
            if level2 <= level:
                end = start2
                break
        spans.append((level, htext, start + 1, end))
    return spans


def _clean_body(lines: list[str]) -> list[str]:
    """Drops `<div ...>`/`</div>`/`:::` fence lines from a section body."""
    out = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("<div") or stripped == "</div>" or stripped.startswith(":::"):
            continue
        out.append(line)
    return out


def _sections_matching(text: str, *needles: str) -> list[str]:
    """Bodies of every heading whose text contains any of `needles`
    (case-insensitive), fence/div lines dropped, blank lines collapsed."""
    lines = text.splitlines()
    matches = []
    for _level, htext, start, end in _iter_headings(text):
        low = htext.lower()
        if any(n in low for n in needles):
            body_lines = _clean_body(lines[start:end])
            body = "\n".join(body_lines).strip()
            if body:
                matches.append(body)
    return matches


def _newest_response(pdir: Path) -> dict | None:
    raw_dir = pdir / "raw"
    if not raw_dir.is_dir():
        return None
    candidates = []
    for sub in raw_dir.iterdir():
        resp = sub / "response.json"
        if resp.exists():
            try:
                mtime = resp.stat().st_mtime
            except OSError:
                continue
            candidates.append((mtime, resp))
    for _mtime, resp in sorted(candidates, key=lambda t: t[0], reverse=True):
        obj = _load_json(resp)
        if isinstance(obj, dict):
            return obj
    return None


def _figures_detail(pdir: Path, version_id: str | None) -> list[dict]:
    if not version_id:
        return []
    figures = _load_json(pdir / "versions" / version_id / "figures.json")
    if not isinstance(figures, list):
        return []
    return [
        {
            "label": f.get("label"),
            "caption": f.get("caption"),
            "asset_available": bool(f.get("asset_available")),
        }
        for f in figures
        if isinstance(f, dict)
    ]


def _claims_detail(pdir: Path) -> list[dict]:
    registry = _load_json(pdir / "claim_registry.json")
    if not isinstance(registry, dict):
        return []
    claims = registry.get("claims")
    if not isinstance(claims, dict):
        return []
    out = []
    for c in claims.values():
        if not isinstance(c, dict) or c.get("status") != "active":
            continue
        out.append({
            "locator": c.get("locator"),
            "evidence_tier": c.get("evidence_tier"),
            "direction": c.get("direction"),
            "outcome": c.get("outcome"),
            "population": c.get("population"),
            "evidence_span": c.get("evidence_span"),
        })
    return out


def _notes_detail(pdir: Path) -> list[dict]:
    notes_path = pdir / "notes.md"
    if not notes_path.exists():
        return []
    text = notes_path.read_text(encoding="utf-8")
    out = []
    for part in text.split("\n---\n"):
        part = part.strip()
        if not part:
            continue
        at, _, rest = part.partition("\n")
        out.append({"at": at.strip(), "text": rest.strip()})
    return out


def _files_checklist(pdir: Path, version_id: str | None) -> list[dict]:
    checklist = [
        ("meta.json", "meta.json", "record metadata"),
        ("authorship.json", "authorship.json", "author list"),
        ("funding.json", "funding.json", "funding observations"),
        ("current.json", "current.json", "pointer to the current version"),
        ("claim_registry.json", "claim_registry.json", "extracted claims"),
        ("notes.md", "notes.md", "user notes"),
    ]
    out = [
        {"path": rel, "exists": (pdir / rel).exists(), "note": note}
        for rel, _label, note in checklist
    ]
    if version_id:
        out.append({
            "path": f"versions/{version_id}/source.md",
            "exists": (pdir / "versions" / version_id / "source.md").exists(),
            "note": "committed full-text markdown",
        })
        out.append({
            "path": f"versions/{version_id}/figures.json",
            "exists": (pdir / "versions" / version_id / "figures.json").exists(),
            "note": "figure manifest",
        })
    return out


def detail(library_root: Path, pmid: str) -> dict:
    """Heavy per-paper payload for one paper's panel (§4.3)."""
    pdir = library_root / "papers" / pmid
    if not pdir.is_dir():
        raise FileNotFoundError(f"pmid {pmid!r} not found under {library_root / 'papers'}")

    version_id = _current_version(pdir)
    response = _newest_response(pdir)
    funding = _load_json(pdir / "funding.json")
    if not isinstance(funding, dict):
        funding = {}
    observations = [
        {
            "funder": o.get("funder"),
            "fundref_id": o.get("fundref_id"),
            "award_number": o.get("award_number"),
            "kind": o.get("kind"),
        }
        for o in funding.get("observations", [])
        if isinstance(o, dict)
    ]

    source_md = ""
    if version_id:
        source_path = pdir / "versions" / version_id / "source.md"
        if source_path.exists():
            source_md = source_path.read_text(encoding="utf-8")

    return {
        "pmid": pmid,
        "authors": _authors(pdir),
        "abstract": (response or {}).get("abstract"),
        "grants": (response or {}).get("grants", []),
        "funding": {
            "state": funding.get("state", "unknown"),
            "observations": observations,
        },
        "acknowledgements": _sections_matching(source_md, "acknowledg"),
        "conflicts": _sections_matching(source_md, "conflict", "competing"),
        "data_availability": _sections_matching(source_md, "data availability"),
        "figures": _figures_detail(pdir, version_id),
        "claims": _claims_detail(pdir),
        "notes": _notes_detail(pdir),
        "files": _files_checklist(pdir, version_id),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    rows_ap = sub.add_parser("rows", help="print rows() as JSON")
    rows_ap.add_argument("--repo", required=True)
    rows_ap.add_argument("--stale-days", type=int, default=STALE_DAYS_DEFAULT)

    detail_ap = sub.add_parser("detail", help="print detail() for one pmid as JSON")
    detail_ap.add_argument("--repo", required=True)
    detail_ap.add_argument("--pmid", required=True)

    args = ap.parse_args()
    library_root = Path(args.repo).expanduser().resolve()
    if not library_root.is_dir():
        print(f"error: no library at {library_root}", file=sys.stderr)
        return 1

    if args.cmd == "rows":
        print(json.dumps(rows(library_root, stale_days=args.stale_days), indent=2))
        return 0

    try:
        print(json.dumps(detail(library_root, args.pmid), indent=2))
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
