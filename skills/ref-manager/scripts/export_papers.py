#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""`/ref:export --papers` — the Papers handoff (PLAN.md §7a, §7b, D28).

One-way, file-based export into a folder Papers imports from. Never writes
the live database. Reuses lib_cite.py's CSL-JSON (D10) for field data but
renders Papers' OWN BibTeX dialect (literal UTF-8, double-braced
title/abstract, local-url attachment) — a separate renderer from
/ref:export --bib's plain dialect, by design (§7a's own wording: "The
export format is not invented ... its shape is the specification this
command reproduces").

ASSUMPTION (flagged for reconciliation with the concurrent fetch/attach
agent): an acquired PDF for a PMID is discovered via
papers/<pmid>/acquisitions.json — a list of
{"media_type": "pdf", "availability": "available", "hash": "<sha256>"}
records (§3 layout: "acquisitions.json — origin, URL/item ID, fetched_at,
media type, hash, availability") — pointing at
papers/<pmid>/raw/<hash>/source.pdf (the same raw/<sha256>/ convention
§6/§7a's own /ref:attach paragraph specifies: "Store verified bytes under
raw/<sha256>/source.pdf"). If acquisitions.json is absent or has no
available PDF entry, we also glob raw/*/source.pdf directly as a fallback
before concluding "no PDF acquired" (metadata-only entry, §7a: "--pdfs
none omits local-url").
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import unicodedata
from pathlib import Path

from lib_atomic import atomic_write_json, atomic_write_text, now_iso
from init_repo import load_config
from lib_cite import to_csl
from lib_selector import resolve_from_args, add_selector_args, SelectorError
from papers_snapshot import try_read_items, find_duplicate


# ---------------------------------------------------------------- metadata

def _load_raw_record(library_root: Path, pmid: str) -> dict:
    """Best-effort: the normalized envelope add.py stored under raw/<hash>/
    response.json carries abstract/volume/issue/pages/issn if the caller's
    PubMed normalization included them (§7a: "entry-field omissions" are
    expected and reported, not an error)."""
    raw_dir = library_root / "papers" / pmid / "raw"
    if not raw_dir.is_dir():
        return {}
    candidates = sorted(raw_dir.glob("*/response.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for c in candidates:
        try:
            return json.loads(c.read_text())
        except (OSError, ValueError):
            continue
    return {}


def _papers_csl(library_root: Path, pmid: str) -> tuple[dict, list[str]]:
    """CSL entry plus a list of field names that were requested but
    unavailable (feeds manifest's entry-field omissions)."""
    csl = to_csl(library_root, pmid)
    raw = _load_raw_record(library_root, pmid)
    omissions = []
    for field, key in (("abstract", "abstract"), ("volume", "volume"), ("issue", "issue"),
                        ("pages", "pages"), ("issn", "issn")):
        val = raw.get(key)
        if val:
            csl[field] = val
        else:
            omissions.append(field)
    return csl, omissions


# ------------------------------------------------------------------ bibtex

_ESCAPE_RE = re.compile(r"([&%$#_{}])")


def _escape_bibtex(text: str) -> str:
    if not text:
        return ""
    return _ESCAPE_RE.sub(r"\\\1", text)


def _pages_field(pages: str | None) -> str | None:
    if not pages:
        return None
    return re.sub(r"\s*-\s*", "--", pages)


def papers_bibtex_entry(csl: dict, local_url: str | None) -> str:
    """Papers' own dialect (§7a): @article with typed fallback, double-
    braced title/abstract, author list preserving ingest order, literal
    UTF-8 (not TeX-escaped for accents — only BibTeX-special chars are
    escaped), local-url when a PDF is attached."""
    entry_type = "article" if csl.get("container-title") else "misc"
    authors = csl.get("author", [])
    author_str = " and ".join(
        a.get("literal") or f"{a.get('family', '')}, {a.get('given', '')}".strip(", ")
        for a in authors
    )
    lines = [f"@{entry_type}{{{csl['id']},"]
    fields = []
    if csl.get("title"):
        fields.append(("title", f"{{{{{_escape_bibtex(csl['title'])}}}}}"))
    if csl.get("abstract"):
        fields.append(("abstract", f"{{{{{_escape_bibtex(csl['abstract'])}}}}}"))
    if author_str:
        fields.append(("author", f"{{{_escape_bibtex(author_str)}}}"))
    if csl.get("container-title"):
        fields.append(("journal", f"{{{_escape_bibtex(csl['container-title'])}}}"))
    if csl.get("volume"):
        fields.append(("volume", f"{{{csl['volume']}}}"))
    if csl.get("issue"):
        fields.append(("number", f"{{{csl['issue']}}}"))
    pages = _pages_field(csl.get("pages"))
    if pages:
        fields.append(("pages", f"{{{pages}}}"))
    if csl.get("issn"):
        fields.append(("issn", f"{{{csl['issn']}}}"))
    if csl.get("issued"):
        fields.append(("year", str(csl["issued"]["date-parts"][0][0])))
    if csl.get("DOI"):
        fields.append(("doi", f"{{{csl['DOI']}}}"))
    if csl.get("PMID"):
        fields.append(("pmid", f"{{{csl['PMID']}}}"))
    if csl.get("PMCID"):
        fields.append(("pmcid", f"{{{csl['PMCID']}}}"))
    if local_url:
        fields.append(("local-url", f"{{{local_url}}}"))
    if csl.get("note_text"):
        fields.append(("note", f"{{{_escape_bibtex(csl['note_text'])}}}"))
    if csl.get("tags"):
        fields.append(("keywords", f"{{{','.join(csl['tags'])}}}"))
    lines.extend(f"  {k} = {v}," for k, v in fields)
    if lines[-1].endswith(","):
        lines[-1] = lines[-1][:-1]
    lines.append("}")
    return "\n".join(lines)


def _percent_encode_file_url(path: Path) -> str:
    from urllib.parse import quote
    return f"file://localhost{quote(str(path))}"


# ----------------------------------------------------------------- pdf lookup

def resolve_pdf(library_root: Path, pmid: str) -> tuple[Path, str] | None:
    """(path, sha256) of an acquired PDF, or None. See module docstring for
    the acquisitions.json shape assumption and the raw/*/source.pdf
    fallback."""
    paper_dir = library_root / "papers" / pmid
    acq_path = paper_dir / "acquisitions.json"
    if acq_path.exists():
        try:
            acquisitions = json.loads(acq_path.read_text())
        except ValueError:
            acquisitions = []
        for a in acquisitions if isinstance(acquisitions, list) else acquisitions.get("acquisitions", []):
            if a.get("media_type") == "pdf" and a.get("availability") == "available" and a.get("hash"):
                p = paper_dir / "raw" / a["hash"] / "source.pdf"
                if p.exists():
                    return p, a["hash"]
    for p in sorted((paper_dir / "raw").glob("*/source.pdf")) if (paper_dir / "raw").is_dir() else []:
        return p, p.parent.name
    return None


# ------------------------------------------------------------- path layout

_UNSAFE_RE = re.compile(r"[\/:]+")


def sanitize_path_component(s: str) -> str:
    s = unicodedata.normalize("NFC", s or "unknown")
    s = _UNSAFE_RE.sub("-", s).strip()
    return s or "unknown"


def layout_relative_path(layout: str, citekey: str, last_author: str, journal: str, year) -> Path:
    if layout == "flat":
        return Path(f"{citekey}.pdf")
    author_dir = sanitize_path_component(last_author or "unknown")
    journal_year = sanitize_path_component(f"{journal or 'unknown'}-{year or 'n.d.'}")
    return Path(author_dir) / f"{journal_year}.pdf"


def _last_author_lastname(csl: dict) -> str:
    authors = csl.get("author", [])
    if not authors:
        return "unknown"
    a = authors[-1]
    return a.get("family") or a.get("literal") or "unknown"


# --------------------------------------------------------- written-path index

def _written_index_path(dest: Path) -> Path:
    return dest / ".ref-manager-written.json"


def _load_written_index(dest: Path) -> dict:
    p = _written_index_path(dest)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except ValueError:
        return {}


def _save_written_index(dest: Path, idx: dict) -> None:
    atomic_write_json(_written_index_path(dest), idx)


def _allocate_path(dest: Path, layout: str, csl: dict, written: dict) -> tuple[Path, bool]:
    """Return (relative_path, is_foreign_conflict). Suffixes -2/-3 on
    collision with something NOT ours; reuses our own prior path for the
    same citekey untouched."""
    citekey = csl["id"]
    for rel, owner in written.items():
        if owner.get("citekey") == citekey:
            return Path(rel), False

    base_rel = layout_relative_path(layout, citekey, _last_author_lastname(csl), csl.get("container-title"), _year_of(csl))
    if layout == "flat":
        return base_rel, _is_foreign(dest, base_rel, written)

    stem = base_rel.stem
    parent = base_rel.parent
    candidate = base_rel
    n = 1
    while _occupied_by_other(dest, candidate, written, citekey) and n <= 50:
        n += 1
        candidate = parent / f"{stem}-{n}.pdf"
    return candidate, _is_foreign(dest, candidate, written)


def _occupied_by_other(dest: Path, rel: Path, written: dict, citekey: str) -> bool:
    """True if `rel` is claimed by a different citekey (ours, from this or a
    prior run) or exists on disk without being in our index at all
    (unrecorded/foreign)."""
    owner = written.get(str(rel))
    if owner is not None:
        return owner.get("citekey") != citekey
    return (dest / rel).exists()


def _is_foreign(dest: Path, rel: Path, written: dict) -> bool:
    full = dest / rel
    if not full.exists():
        return False
    return str(rel) not in written


def _year_of(csl: dict):
    issued = csl.get("issued")
    if issued:
        return issued["date-parts"][0][0]
    return None


# --------------------------------------------------------------- note push

def _note_push_index_path(library_root: Path) -> Path:
    return library_root / "exports" / "papers" / "note_pushes.json"


def _load_note_pushes(library_root: Path) -> dict:
    p = _note_push_index_path(library_root)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except ValueError:
        return {}


def _record_note_push(library_root: Path, pmid: str, text_hash: str, batch: str) -> None:
    idx = _load_note_pushes(library_root)
    idx[pmid] = {
        "hash": text_hash,
        "batch": batch,
        "pushed_at": now_iso(),
    }
    atomic_write_json(_note_push_index_path(library_root), idx)


def _notes_text(library_root: Path, pmid: str) -> str | None:
    p = library_root / "papers" / pmid / "notes.md"
    if not p.exists():
        return None
    text = p.read_text().strip()
    return text or None


def _tags_for(library_root: Path, pmid: str, explicit_tags: list[str] | None, tags_from_project: str | None) -> list[str]:
    if explicit_tags:
        return explicit_tags
    if tags_from_project:
        proj_papers = library_root / "projects" / tags_from_project / "papers.yaml"
        if proj_papers.exists():
            try:
                doc = json.loads(proj_papers.read_text())
            except ValueError:
                return []
            for m in doc.get("papers", []):
                if m.get("pmid") == pmid:
                    return [tags_from_project]
        return []
    return []


# --------------------------------------------------------------------- run

def run_export_papers(library_root: Path, args, resolution: dict) -> dict:
    pmids = resolution["pmids"]
    if not pmids:
        raise SelectorError("selector matched no papers")

    # --to > configured papers_export_dir > exports/papers/<batch>/, and the
    # layout default follows which of those three applies (§7a).
    if args.to:
        dest = Path(args.to).expanduser()
        dest_reason = "--to"
        default_layout = "flat"
    else:
        cfg = load_config() or {}
        if cfg.get("papers_export_dir"):
            dest = Path(cfg["papers_export_dir"]).expanduser()
            dest_reason = "config.json papers_export_dir"
            default_layout = "papers"
        else:
            batch_label = args.batch or args.collection or "batch"
            dest = library_root / "exports" / "papers" / batch_label
            dest_reason = "no destination configured; using exports/papers/<batch>/"
            default_layout = "flat"

    layout = args.layout or default_layout

    items, snapshot_error = (None, "no --papers-db given") if not args.papers_db else try_read_items(Path(args.papers_db))
    dup_detection_available = items is not None

    written = _load_written_index(dest) if dest.exists() else {}
    note_pushes = _load_note_pushes(library_root)

    per_paper = []
    already_known = []
    missing_pdfs = []
    field_omissions = {}
    foreign_conflicts = []
    skipped = []

    for pmid in pmids:
        csl, omissions = _papers_csl(library_root, pmid)
        if omissions:
            field_omissions[pmid] = omissions

        dup = None
        if dup_detection_available:
            dup = find_duplicate(items, pmid, csl.get("DOI"))
            if dup:
                already_known.append(pmid)
                if args.skip_known and not args.force:
                    skipped.append(pmid)
                    continue

        rel_path, is_foreign = _allocate_path(dest, layout, csl, written) if args.pdfs != "none" else (None, False)
        pdf_info = resolve_pdf(library_root, pmid) if args.pdfs != "none" else None

        local_url = None
        pdf_written_path = None
        if args.pdfs != "none" and pdf_info is not None:
            if is_foreign:
                foreign_conflicts.append({"pmid": pmid, "path": str(rel_path)})
            else:
                full_path = dest / rel_path
                if not args.dry_run:
                    full_path.parent.mkdir(parents=True, exist_ok=True)
                    src_path, src_hash = pdf_info
                    existing_owner = written.get(str(rel_path))
                    needs_write = not full_path.exists() or (existing_owner is None) or existing_owner.get("hash") != src_hash
                    if needs_write:
                        if args.pdfs == "link":
                            if full_path.exists() or full_path.is_symlink():
                                full_path.unlink()
                            full_path.symlink_to(src_path)
                        else:
                            shutil.copy2(src_path, full_path)
                    written[str(rel_path)] = {"citekey": csl["id"], "hash": src_hash}
                local_url = _percent_encode_file_url(full_path.resolve() if not args.dry_run else (dest / rel_path))
                pdf_written_path = str(rel_path)
        elif args.pdfs != "none" and pdf_info is None:
            missing_pdfs.append(pmid)

        pushed_note_hash = None
        note_status = None
        if args.notes:
            text = _notes_text(library_root, pmid)
            if text:
                text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
                prior = note_pushes.get(pmid)
                if prior and prior["hash"] and not args.notes_force:
                    note_status = f"refused: note already pushed for {pmid} (hash {prior['hash'][:12]}...); use --notes=force to overwrite"
                else:
                    pushed_note_hash = text_hash
                    csl["note_text"] = text
                    note_status = "pushed"
                    if not args.dry_run:
                        _record_note_push(library_root, pmid, text_hash, args.batch or "unnamed")
            else:
                note_status = "no notes.md content"

        tags = _tags_for(library_root, pmid, args.tags, args.tags_from)
        if tags:
            csl["tags"] = tags

        entry = papers_bibtex_entry(csl, local_url)
        per_paper.append({
            "pmid": pmid,
            "citekey": csl["id"],
            "bib_entry": entry,
            "pdf_path": pdf_written_path,
            "already_known": bool(dup),
            "note_status": note_status,
            "pushed_note_hash": pushed_note_hash,
        })

    if not args.dry_run:
        dest.mkdir(parents=True, exist_ok=True)
        _save_written_index(dest, written)
        bib_text = "\n\n".join(p["bib_entry"] for p in per_paper) + ("\n" if per_paper else "")
        atomic_write_text(dest / "references.bib", bib_text)

    manifest = {
        "selector_expression": resolution["selector_expression"],
        "pmids": [p["pmid"] for p in per_paper],
        "citekeys": [p["citekey"] for p in per_paper],
        "destination": str(dest),
        "destination_reason": dest_reason,
        "layout": layout,
        "pdfs_mode": args.pdfs,
        "timestamp": now_iso(),
        "per_paper": {
            p["pmid"]: {
                "citekey": p["citekey"],
                "pdf_path": p["pdf_path"],
                "already_known": p["already_known"],
                "pushed_note_hash": p["pushed_note_hash"],
            }
            for p in per_paper
        },
        "missing_pdfs": missing_pdfs,
        "already_known": already_known,
        "skipped_known": skipped,
        "field_omissions": field_omissions,
        "foreign_conflicts": foreign_conflicts,
        "duplicate_detection_available": dup_detection_available,
        "duplicate_detection_note": snapshot_error if not dup_detection_available else None,
        "collection": args.collection,
    }

    if not args.dry_run:
        atomic_write_json(dest / "manifest.json", manifest)

    return {
        "dry_run": args.dry_run,
        "destination": str(dest),
        "manifest": manifest,
        "note_statuses": {p["pmid"]: p["note_status"] for p in per_paper if p["note_status"]},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    add_selector_args(ap)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--batch")
    ap.add_argument("--to")
    ap.add_argument("--layout", choices=["papers", "flat"])
    ap.add_argument("--pdfs", choices=["copy", "link", "none"], default="copy")
    ap.add_argument("--notes", action="store_true")
    ap.add_argument("--notes-force", action="store_true")
    ap.add_argument("--tags")
    ap.add_argument("--tags-from")
    ap.add_argument("--skip-known", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--collection")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--papers-db", help="path to a Papers.app sqlite db (tests must point this at a synthetic scratch db, never the real library)")
    args = ap.parse_args()
    if args.tags:
        args.tags = [t.strip() for t in args.tags.split(",") if t.strip()]

    library_root = Path(args.repo).expanduser().resolve()
    if not library_root.is_dir():
        print(f"error: no library at {library_root}", file=sys.stderr)
        return 1

    try:
        resolution = resolve_from_args(library_root, args)
        result = run_export_papers(library_root, args, resolution)
    except SelectorError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
