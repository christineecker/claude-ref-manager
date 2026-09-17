# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""`/ref:attach <pmid> <path> [<pmid> <path> ...]` -- PDF attachment
(PLAN.md §6 opening paragraph).

Identity check: no PDF-parsing python library is available on this machine
and D-general says avoid unnecessary dependencies, so identity is verified
by shelling out to `pdftotext` (poppler, already installed) to pull the
first two pages of text and checking whether the paper's DOI (if known) or
a normalized run of the title appears in it. This is a real content check,
not just a filename heuristic -- but it is also not a full bibliographic
parse, so a PDF that fails the check is *refused*, never silently attached,
and the failure names what didn't match so the user can resolve it (attach
under a different pmid, or accept it with an explicit override arg).

Duplicate content (identical sha256 already stored) is a no-op. Each
pmid/path pair is processed independently under its own per-PMID lock; one
conflict or failure never blocks the rest of the batch (§6, same per-PMID-
batch contract as add.py/fetch.py). `attach_pdf_bytes` is the same commit path
for trusted downloaders such as PMC OA PDF fetches; it keeps provenance in
attachment.json rather than pretending a downloaded file was local input.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from lib_atomic import atomic_write_bytes, atomic_write_json, commit_version, pmid_lock
from lib_ids import gen_opaque_id, normalize_title
from convert import convert_pdf

PDFTOTEXT_PAGES = 2


def _pdf_head_text(pdf_path: Path) -> str | None:
    pdftotext = shutil.which("pdftotext")
    if not pdftotext:
        return None
    proc = subprocess.run(
        [pdftotext, "-f", "1", "-l", str(PDFTOTEXT_PAGES), str(pdf_path), "-"],
        capture_output=True,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout.decode("utf-8", "replace")


def _check_identity(meta: dict, pdf_text: str | None) -> tuple[bool, str]:
    """Returns (verified, method_description)."""
    if pdf_text is None:
        return False, "pdftotext unavailable or failed -- identity NOT verified against content"

    norm_text = normalize_title(pdf_text)
    doi = meta.get("doi")
    if doi and normalize_title(doi) in norm_text:
        return True, f"DOI {doi!r} found in first {PDFTOTEXT_PAGES} page(s) of text"

    title = meta.get("title") or ""
    title_words = normalize_title(title).split()
    # require a run of >=6 consecutive title words to appear verbatim, since
    # short substrings match too many unrelated PDFs
    if len(title_words) >= 6:
        run = " ".join(title_words[:8])
        if run in norm_text:
            return True, "title (first 8 words) found verbatim in first page(s) of text"

    return False, (
        "neither DOI nor a run of the title text was found in the PDF's first "
        f"{PDFTOTEXT_PAGES} page(s) -- refusing silent attachment (§6)"
    )


class _ConversionNotCommitted(Exception):
    """Raised inside commit_version's write_fn to discard the staging dir."""


def attach_pdf_bytes(library_root: Path, pmid: str, data: bytes, attached_from: str, force: bool,
                     commit_failed_conversion: bool = True) -> dict:
    """`commit_failed_conversion=False` (the dashboard upload) keeps the raw
    PDF but leaves current.json alone when conversion isn't ok, so a paper
    that already has committed full text never loses it to a PDF that
    couldn't be converted."""
    paper_dir = library_root / "papers" / pmid
    meta_path = paper_dir / "meta.json"
    if not meta_path.exists():
        raise ValueError(f"pmid {pmid} has no meta.json -- run /ref:add first")

    with pmid_lock(library_root, pmid):
        meta = json.loads(meta_path.read_text())
        file_hash = hashlib.sha256(data).hexdigest()

        existing_raw = paper_dir / "raw" / file_hash / "source.pdf"
        if existing_raw.exists():
            return {"pmid": pmid, "result": "duplicate_noop", "sha256": file_hash}

        fd, temp_name = tempfile.mkstemp(prefix=f"ref-manager-{pmid}-", suffix=".pdf")
        temp_pdf = Path(temp_name)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            pdf_text = _pdf_head_text(temp_pdf)
        finally:
            with contextlib.suppress(FileNotFoundError):
                temp_pdf.unlink()
        verified, method = _check_identity(meta, pdf_text)
        if not verified and not force:
            return {"pmid": pmid, "result": "refused", "reason": method, "sha256": file_hash}

        raw_dir = paper_dir / "raw" / file_hash
        raw_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(raw_dir / "source.pdf", data)
        atomic_write_json(raw_dir / "attachment.json", {
            "attached_from": attached_from, "sha256": file_hash,
            "identity_check": method, "identity_verified": verified, "forced": force and not verified,
        })

        version_id = gen_opaque_id("v-")

        def write_fn(staging: Path) -> None:
            conv = convert_pdf(raw_dir / "source.pdf", staging)
            manifest = {
                "version_id": version_id, "pmid": pmid, "source": "local_attach",
                "converter": conv["converter"], "converter_version": conv["version"],
                "raw_hash": file_hash, "diagnostics": conv["diagnostics"],
                "conversion_status": conv["status"],
            }
            write_fn.conv = conv
            if conv["status"] != "ok" and not commit_failed_conversion:
                raise _ConversionNotCommitted
            atomic_write_json(staging / "manifest.json", manifest)

        write_fn.conv = None
        try:
            commit_version(paper_dir, version_id, write_fn)
        except _ConversionNotCommitted:
            version_id = None
        conv = write_fn.conv

        if conv["status"] == "ok":
            meta["full_text"] = True
        atomic_write_json(meta_path, meta)

        return {
            "pmid": pmid, "result": "attached", "sha256": file_hash, "version": version_id,
            "identity_check": method, "identity_verified": verified, "forced": force and not verified,
            "conversion_status": conv["status"], "diagnostics": conv["diagnostics"],
        }


def attach_one(library_root: Path, pmid: str, pdf_path: Path, force: bool) -> dict:
    if not pdf_path.is_file():
        raise ValueError(f"no such file: {pdf_path}")
    return attach_pdf_bytes(library_root, pmid, pdf_path.read_bytes(), str(pdf_path), force)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--force", action="store_true", help="attach despite a failed identity check")
    ap.add_argument("pairs", nargs="+", help="<pmid> <path> [<pmid> <path> ...]")
    args = ap.parse_args()

    if len(args.pairs) % 2 != 0:
        print("error: pairs must be <pmid> <path> ... in matched pairs", file=sys.stderr)
        return 2

    library_root = Path(args.repo).expanduser().resolve()
    if not library_root.is_dir():
        print(f"error: no library at {library_root}", file=sys.stderr)
        return 1

    results = []
    exit_code = 0
    it = iter(args.pairs)
    for pmid, path_str in zip(it, it):
        try:
            results.append(attach_one(library_root, pmid, Path(path_str).expanduser(), args.force))
        except (ValueError, OSError) as e:
            results.append({"pmid": pmid, "result": "failed", "error": str(e)})
            exit_code = 1

    for r in results:
        line = f"{r['pmid']}: {r['result']}"
        if r.get("result") == "attached":
            if r.get("identity_verified"):
                line += f" -- {r.get('identity_check')}"
            elif r.get("forced"):
                line += " -- attached with --force after failed identity check"
        if r.get("reason"):
            line += f" -- {r['reason']}"
        if r.get("error"):
            line += f" -- {r['error']}"
        print(line)
        for d in r.get("diagnostics", []):
            print(f"  diagnostic: {d}")
    if any(r["result"] == "refused" for r in results):
        exit_code = 1

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
