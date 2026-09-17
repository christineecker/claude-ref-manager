#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Dashboard intake: one dropped thing -> one library paper, end to end.

The dashboard's "Add papers" panel (serve mode only) hands this module either
a text item (PMID, DOI, PubMed / PMC / DOI URL) or the bytes of a dropped PDF.
Each item runs the same deterministic pipeline, no LLM, no MCP:

    identify -> resolve to a PMID -> check the library -> add if new
             -> attach the PDF if one was dropped -> get full text if missing

"Check the library" is the point: an item that resolves to a paper already in
`papers/` is never re-added. Instead the pipeline looks at what that paper
still lacks (a PDF, full text) and fills only that in, so dropping a PDF for a
paper you added last week just attaches it.

Every result carries a `steps` trail the panel renders inline, and a
`status`: `done`, `exists` (nothing new to do), `needs_pmid` (a PDF with no
DOI/PMID clue -- the page asks for one), `needs_replace` (the paper already
has a different PDF), `needs_force` (attach.py's identity check failed) or
`failed`.

Network hops (`efetch`, `esearch`, PMC OA download) are injectable so
`tests/test_dashboard_serve.py` runs the whole path offline.
"""
from __future__ import annotations

import contextlib
import hashlib
import os
import tempfile
import urllib.error
import urllib.parse
from pathlib import Path

import add as add_module
import attach as attach_module
import fetch as fetch_module
import fetch_pmc_pdf
import lib_eutils
import lib_intake
import lib_inventory
import pdf_identify
from lib_selector import has_pdf


def _default_fetcher(pmids: list[str]) -> tuple[list[dict], list[str]]:
    email, api_key = lib_eutils.ncbi_credentials()
    return lib_eutils.efetch_pubmed(pmids, email=email, api_key=api_key)


def _default_resolver(doi: str | None, pmcid: str | None) -> str | None:
    email, api_key = lib_eutils.ncbi_credentials()
    return lib_eutils.resolve_to_pmid(doi=doi, pmcid=pmcid, email=email, api_key=api_key)


def _default_pdf_fetcher(library_root: Path, pmid: str) -> dict:
    return fetch_pmc_pdf.fetch_pmc_pdf_one(library_root, pmid)


def _default_jats_fetcher(library_root: Path, pmid: str) -> dict:
    """PMC JATS full text -> fetch.fetch_one (pandoc conversion, figures,
    funding), the same commit path `/ref:fetch` uses when it has the XML."""
    _p, meta = lib_inventory._read_meta(_paper_dir(library_root, pmid))
    pmcid = fetch_pmc_pdf._pmcid((meta or {}).get("pmcid"))
    if not pmcid:
        return {"pmid": pmid, "result": "no_pmcid"}
    url = fetch_pmc_pdf.PMC_EFETCH + "?" + urllib.parse.urlencode({
        "db": "pmc", "id": pmcid, "rettype": "full", "retmode": "xml", "tool": lib_eutils.TOOL,
    })
    try:
        xml = fetch_pmc_pdf._urlopen_bytes(url).decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError) as e:
        return {"pmid": pmid, "result": "failed", "error": f"PMC JATS download failed: {e}"}
    if "<article" not in xml:
        return {"pmid": pmid, "result": "no_jats"}
    return fetch_module.fetch_one(library_root, {"pmid": pmid, "jats_xml": xml, "doi": (meta or {}).get("doi"), "pmcid": pmcid}, None)


def has_fulltext(paper_dir: Path) -> bool:
    version = lib_inventory._current_version(paper_dir)
    return bool(version and (paper_dir / "versions" / version / "source.md").exists())


def _paper_dir(library_root: Path, pmid: str) -> Path:
    return library_root / "papers" / pmid


def _title(library_root: Path, pmid: str) -> str | None:
    _pmid, meta = lib_inventory._read_meta(_paper_dir(library_root, pmid))
    return (meta or {}).get("title")


def _citekey(library_root: Path, pmid: str) -> str | None:
    _pmid, meta = lib_inventory._read_meta(_paper_dir(library_root, pmid))
    return (meta or {}).get("citekey")


def _resolve(clues: dict, resolver, steps: list[str]) -> str | None:
    """pmid / doi / pmcid clues -> PMID, recording the hop taken."""
    if clues.get("pmid"):
        return str(clues["pmid"])
    doi, pmcid = clues.get("doi"), clues.get("pmcid")
    if not doi and not pmcid:
        return None
    try:
        pmid = resolver(doi, pmcid)
    except lib_eutils.EutilsError as e:
        steps.append(f"lookup failed: {e}")
        return None
    if pmid:
        steps.append(f"{'DOI' if doi else 'PMCID'} matched PMID {pmid}")
    else:
        steps.append("no PubMed record for " + (f"DOI {doi}" if doi else f"{pmcid}"))
    return pmid


def _ensure_paper(library_root: Path, pmid: str, fetcher, steps: list[str]) -> tuple[bool, str | None]:
    """(existed_already, error). Adds the paper through add.py when missing."""
    if (_paper_dir(library_root, pmid) / "meta.json").exists():
        steps.append("already in library")
        return True, None
    try:
        records, missing = fetcher([pmid])
    except lib_eutils.EutilsError as e:
        return False, f"PubMed fetch failed: {e}"
    if not records or pmid in missing:
        return False, f"PubMed has no record for PMID {pmid}"
    steps.append("metadata fetched")
    try:
        res = add_module.add_one(library_root, records[0])
    except (KeyError, ValueError) as e:
        return False, f"add failed: {e}"
    if res.get("result") == "already_present":
        steps.append("already in library")
        return True, None
    steps.append("added")
    return False, None


def _fill_fulltext(library_root: Path, pmid: str, pdf_fetcher, jats_fetcher, steps: list[str]) -> None:
    """Top up what the paper lacks: a PMC OA PDF when it has none (attach.py
    converts it), then PMC JATS full text when the text is still missing."""
    pdir = _paper_dir(library_root, pmid)
    if has_fulltext(pdir):
        steps.append("full text already present")
        return
    in_pmc = True
    if not has_pdf(pdir):
        try:
            res = pdf_fetcher(library_root, pmid)
        except (ValueError, OSError) as e:
            res = {"result": "failed", "error": str(e)}
        result = res.get("result")
        if result == "attached":
            if res.get("conversion_status", "ok") == "ok":
                steps.append("PMC PDF attached, full text extracted")
            else:
                steps.append("PMC PDF attached (text conversion " + str(res.get("conversion_status")) + ")")
        elif result == "duplicate_noop":
            steps.append("PMC PDF already attached")
        elif result == "no_pmcid":
            in_pmc = False
            steps.append("no full text: not in PMC")
        elif result == "no_pdf":
            steps.append("no PMC PDF")
        else:
            steps.append("PMC PDF: " + str(res.get("error") or res.get("reason") or result))
    if has_fulltext(pdir) or not in_pmc:
        return
    try:
        res = jats_fetcher(library_root, pmid)
    except (ValueError, OSError) as e:
        steps.append(f"PMC full text failed: {e}")
        return
    result = res.get("result")
    if result in ("acquired", "duplicate_noop"):
        steps.append("full text extracted (PMC JATS)")
    elif result == "no_pmcid":
        steps.append("no full text: not in PMC")
    elif result == "no_jats":
        steps.append("no PMC full text XML")
    else:
        steps.append("PMC full text: " + str(res.get("error") or res.get("reason") or result))


def _finish(library_root: Path, pmid: str | None, base: dict, status: str, **extra) -> dict:
    out = dict(base)
    out["status"] = status
    out["pmid"] = pmid
    if pmid:
        out["title"] = _title(library_root, pmid)
        out["citekey"] = _citekey(library_root, pmid)
    out.update(extra)
    return out


def intake_text(library_root: Path, raw: str, *, fulltext: bool, fetcher=None, resolver=None, pdf_fetcher=None,
                jats_fetcher=None) -> dict:
    """One PMID / DOI / URL string -> result dict (see module docstring)."""
    fetcher = fetcher or _default_fetcher
    resolver = resolver or _default_resolver
    pdf_fetcher = pdf_fetcher or _default_pdf_fetcher
    jats_fetcher = jats_fetcher or _default_jats_fetcher
    steps: list[str] = []
    base = {"input": raw, "steps": steps}

    item = lib_intake.classify_item(raw)
    kind = item.get("kind")
    if kind not in ("pmid", "doi", "url"):
        return _finish(library_root, None, base, "failed", kind="unknown",
                       error="not a PMID, DOI or PubMed/PMC/DOI link")
    base["kind"] = kind
    steps.append({"pmid": "PMID", "doi": "DOI", "url": "link"}[kind] + " recognised")

    pmid = _resolve(item, resolver, steps)
    if not pmid:
        return _finish(library_root, None, base, "failed", error="could not resolve to a PMID")

    existed, error = _ensure_paper(library_root, pmid, fetcher, steps)
    if error:
        return _finish(library_root, None, base, "failed", error=error)

    pdir = _paper_dir(library_root, pmid)
    changed = not existed
    if fulltext:
        before = has_fulltext(pdir)
        _fill_fulltext(library_root, pmid, pdf_fetcher, jats_fetcher, steps)
        changed = changed or (has_fulltext(pdir) and not before)

    return _finish(library_root, pmid, base, "done" if changed else "exists",
                   has_pdf=has_pdf(pdir), has_fulltext=has_fulltext(pdir))


def intake_pdf(library_root: Path, data: bytes, name: str, *, pmid_override: str | None = None,
               replace: bool = False, force: bool = False, fetcher=None, resolver=None) -> dict:
    """One dropped PDF -> identify -> add if new -> attach (which converts to
    full text). Returns `needs_pmid` when the PDF carries no DOI/PMID clue."""
    fetcher = fetcher or _default_fetcher
    resolver = resolver or _default_resolver
    steps: list[str] = []
    base = {"input": name, "kind": "pdf", "steps": steps}

    fd, temp_name = tempfile.mkstemp(prefix="ref-manager-intake-", suffix=".pdf")
    temp_pdf = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        clues = pdf_identify.identify_pdf(temp_pdf)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temp_pdf.unlink()

    if pmid_override:
        clues = {"pmid": pmid_override}
        steps.append("PMID given")
    elif clues.get("result") == "failed":
        steps.append("could not read PDF text: " + str(clues.get("error")))
    elif clues.get("pmid"):
        steps.append(f"PMID {clues['pmid']} found in PDF")
    elif clues.get("doi"):
        steps.append(f"DOI {clues['doi']} found in PDF")
    elif clues.get("pmcid"):
        steps.append(f"{clues['pmcid']} found in PDF")
    else:
        steps.append("no DOI or PMID in the PDF")

    pmid = _resolve(clues, resolver, steps)
    if not pmid:
        return _finish(library_root, None, base, "needs_pmid", title_guess=clues.get("title_guess"))

    existed, error = _ensure_paper(library_root, pmid, fetcher, steps)
    if error:
        return _finish(library_root, None, base, "failed", error=error)

    pdir = _paper_dir(library_root, pmid)
    if _same_pdf_present(pdir, data):
        steps.append("this PDF is already attached")
        return _finish(library_root, pmid, base, "exists", has_pdf=True, has_fulltext=has_fulltext(pdir))
    if has_pdf(pdir) and not replace:
        steps.append("paper already has a different PDF")
        return _finish(library_root, pmid, base, "needs_replace", has_pdf=True, has_fulltext=has_fulltext(pdir))

    try:
        res = attach_module.attach_pdf_bytes(library_root, pmid, data, f"dashboard_intake:{name}", force,
                                             commit_failed_conversion=False)
    except ValueError as e:
        return _finish(library_root, pmid, base, "failed", error=str(e))
    if res.get("result") == "refused":
        steps.append("identity check failed: " + str(res.get("reason")))
        return _finish(library_root, pmid, base, "needs_force", error=res.get("reason"))
    if res.get("result") == "duplicate_noop":
        steps.append("this PDF is already attached")
        return _finish(library_root, pmid, base, "exists", has_pdf=True, has_fulltext=has_fulltext(pdir))
    steps.append("PDF attached")
    if res.get("conversion_status") == "ok":
        steps.append("full text extracted")
    else:
        steps.append("text conversion " + str(res.get("conversion_status")) + " (PDF kept)")
    return _finish(library_root, pmid, base, "done", has_pdf=True, has_fulltext=has_fulltext(pdir))


def _same_pdf_present(pdir: Path, data: bytes) -> bool:
    return (pdir / "raw" / hashlib.sha256(data).hexdigest() / "source.pdf").exists()
