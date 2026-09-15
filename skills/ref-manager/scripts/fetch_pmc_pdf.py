# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""`/ref:fetch-pdf <pmid...>` -- download free PMC OA PDFs and attach them.

This is deliberately narrower than `/ref:fetch`: it only uses the documented
PMC Open Access Web Service to find downloadable PDF resources for articles
already in the library with a PMCID. It does not scrape the PMC PDF viewer and
does not bypass access controls. Downloaded bytes are committed through
attach.py's normal identity-check, raw-hash, conversion, and version path.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from attach import attach_pdf_bytes

OA_SERVICE = "https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi"
PMC_EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
TIMEOUT = 30


def _pmcid(pmcid: str | None) -> str | None:
    if not pmcid:
        return None
    value = str(pmcid).strip()
    if value.upper().startswith("PMC"):
        value = value[3:]
    return f"PMC{value}" if value.isdigit() else None


def _urlopen_bytes(url: str, limit: int | None = None) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "ref-manager/1.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read(limit) if limit is not None else resp.read()


def _normalize_href(href: str) -> str:
    href = href.strip()
    # Some mirrors/documentation accidentally prefix FTP links with a leading
    # slash. The real service returns ftp://...; tolerate both.
    if href.startswith("/ftp://"):
        href = href[1:]
    return href


def _oa_pdf_link(pmcid: str) -> tuple[str | None, list[str]]:
    url = OA_SERVICE + "?" + urllib.parse.urlencode({"id": pmcid})
    diagnostics: list[str] = []
    try:
        xml = _urlopen_bytes(url)
    except (urllib.error.URLError, TimeoutError) as e:
        return None, [f"PMC OA lookup failed ({url}): {e}"]

    try:
        root = ET.fromstring(xml)
    except ET.ParseError as e:
        return None, [f"PMC OA lookup did not return XML ({url}): {e}"]
    if root.tag.lower() != "oa":
        return None, [f"PMC OA lookup did not return an OA response ({url}); got <{root.tag}>"]

    err = root.find(".//error")
    if err is not None:
        code = err.get("code") or "unknown"
        msg = (err.text or "").strip()
        return None, [f"PMC OA lookup returned {code}: {msg}"]

    for link in root.findall(".//link"):
        if link.get("format") == "pdf" and link.get("href"):
            return _normalize_href(link.get("href", "")), diagnostics

    diagnostics.append(f"PMC OA record for {pmcid} has no downloadable PDF link")
    return None, diagnostics


def _pmc_jats_available(pmcid: str) -> tuple[bool, str | None]:
    url = PMC_EFETCH + "?" + urllib.parse.urlencode({
        "db": "pmc", "id": pmcid, "rettype": "full", "retmode": "xml",
    })
    try:
        sample = _urlopen_bytes(url, limit=8192)
    except (urllib.error.URLError, TimeoutError) as e:
        return False, f"PMC JATS check failed ({url}): {e}"

    if b"<article" in sample or b"<pmc-articleset" in sample:
        return True, None
    return False, f"PMC JATS check did not find article XML ({url})"


def fetch_pmc_pdf_one(library_root: Path, pmid: str, force: bool = False) -> dict:
    paper_dir = library_root / "papers" / str(pmid)
    meta_path = paper_dir / "meta.json"
    if not meta_path.exists():
        raise ValueError(f"pmid {pmid} has no meta.json -- run /ref:add first")

    meta = json.loads(meta_path.read_text())
    pmcid = _pmcid(meta.get("pmcid"))
    if not pmcid:
        return {"pmid": str(pmid), "result": "no_pmcid", "reason": "paper has no PMCID"}

    pdf_url, diagnostics = _oa_pdf_link(pmcid)
    if not pdf_url:
        jats_available, jats_diagnostic = _pmc_jats_available(pmcid)
        if jats_diagnostic:
            diagnostics.append(jats_diagnostic)
        note = None
        if jats_available:
            note = "PMC JATS full text is available; use /ref:fetch for structured full text and figures"
        return {
            "pmid": str(pmid), "result": "no_pdf", "pmcid": pmcid,
            "reason": diagnostics[0] if diagnostics else "PMC OA PDF unavailable",
            "diagnostics": diagnostics[1:],
            "full_text_available": jats_available,
            "full_text_source": "pmc_jats" if jats_available else None,
            "note": note,
        }

    try:
        data = _urlopen_bytes(pdf_url)
    except (urllib.error.URLError, TimeoutError) as e:
        return {
            "pmid": str(pmid), "result": "failed", "pmcid": pmcid,
            "error": f"PDF download failed ({pdf_url}): {e}",
        }

    if not data.startswith(b"%PDF"):
        jats_available, jats_diagnostic = _pmc_jats_available(pmcid)
        diagnostics.append(f"downloaded OA response did not look like a PDF ({pdf_url})")
        if jats_diagnostic:
            diagnostics.append(jats_diagnostic)
        if jats_available:
            return {
                "pmid": str(pmid), "result": "no_pdf", "pmcid": pmcid,
                "reason": diagnostics[0],
                "diagnostics": diagnostics[1:],
                "full_text_available": True,
                "full_text_source": "pmc_jats",
                "note": "PMC JATS full text is available; use /ref:fetch for structured full text and figures",
            }
        return {
            "pmid": str(pmid), "result": "failed", "pmcid": pmcid,
            "error": f"download did not look like a PDF: {pdf_url}",
        }

    result = attach_pdf_bytes(library_root, str(pmid), data, f"pmc_oa:{pdf_url}", force)
    result["source"] = "pmc_oa_pdf"
    result["pmcid"] = pmcid
    result["pdf_url"] = pdf_url
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--force", action="store_true", help="attach despite a failed PDF identity check")
    ap.add_argument("pmids", nargs="+")
    args = ap.parse_args()

    library_root = Path(args.repo).expanduser().resolve()
    if not library_root.is_dir():
        print(f"error: no library at {library_root}", file=sys.stderr)
        return 1

    exit_code = 0
    results = []
    for pmid in args.pmids:
        try:
            result = fetch_pmc_pdf_one(library_root, pmid, force=args.force)
        except (ValueError, OSError) as e:
            result = {"pmid": pmid, "result": "failed", "error": str(e)}
        if result["result"] in {"failed", "refused"}:
            exit_code = 1
        results.append(result)

    for r in results:
        line = f"{r['pmid']}: {r['result']}"
        if r.get("source"):
            line += f" (source={r['source']})"
        if r.get("reason"):
            line += f" -- {r['reason']}"
        if r.get("note"):
            line += f" -- {r['note']}"
        if r.get("error"):
            line += f" -- {r['error']}"
        print(line)
        for d in r.get("diagnostics", []):
            print(f"  diagnostic: {d}")

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
