#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""NCBI E-utilities `efetch` for PubMed metadata (PUBMED_TRIAGE_IMPLEMENTATION_PLAN.md
§6.1, decision T6).

Triage batches load metadata here rather than through the PubMed MCP tool,
because the dashboard server (a plain subprocess) can't call MCP. Like
fetch.py's Unpaywall lookup, this is one deterministic REST call needing no
LLM judgment, made with stdlib urllib.

`parse_pubmed_xml()` turns PubmedArticleSet XML into add.py's input envelope
(pmid, title, abstract, authors[{last, first, raw}], journal, year, doi,
pmcid, grants[{agency, grant_id, raw}]) plus two display-only fields
(publication_types, mesh_terms) that add_one() ignores.
"""
from __future__ import annotations

import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import init_repo

EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
TOOL = "ref-manager"
CHUNK = 100
TIMEOUT = 30

_throttle_lock = threading.Lock()
_last_request = [0.0]


class EutilsError(Exception):
    pass


def ncbi_credentials(config: dict | None = None) -> tuple[str, str | None]:
    """(email, api_key) from ~/.config/ref-manager/config.json. NCBI asks
    every client to identify itself, so a missing email is an error."""
    if config is None:
        config = init_repo.load_config() or {}
    email = config.get("ncbi_email") or config.get("unpaywall_email")
    if not email:
        raise EutilsError(
            "no contact email for NCBI E-utilities -- add \"ncbi_email\": \"you@example.org\" "
            f"to {init_repo.CONFIG_PATH}"
        )
    return email, config.get("ncbi_api_key")


def _throttle(api_key: str | None) -> None:
    # NCBI: 3 requests/s without an API key, 10/s with one.
    gap = 0.1 if api_key else 0.34
    with _throttle_lock:
        wait = _last_request[0] + gap - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_request[0] = time.monotonic()


def _post(params: dict, api_key: str | None) -> bytes:
    data = urllib.parse.urlencode(params).encode("ascii")
    last_error: Exception | None = None
    for attempt in range(2):
        _throttle(api_key)
        req = urllib.request.Request(EFETCH_URL, data=data, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            last_error = e
            if e.code not in (429, 500, 502, 503, 504) or attempt:
                break
            time.sleep(1.0)
        except (urllib.error.URLError, TimeoutError) as e:
            last_error = e
            if attempt:
                break
            time.sleep(1.0)
    raise EutilsError(f"efetch failed: {last_error}")


def efetch_pubmed(pmids: list[str], *, email: str, api_key: str | None = None) -> tuple[list[dict], list[str]]:
    """Fetch metadata for `pmids` in chunks of 100. Returns (records in the
    requested order, PMIDs NCBI returned nothing for)."""
    by_pmid: dict[str, dict] = {}
    for i in range(0, len(pmids), CHUNK):
        chunk = pmids[i:i + CHUNK]
        params = {"db": "pubmed", "retmode": "xml", "id": ",".join(chunk), "tool": TOOL, "email": email}
        if api_key:
            params["api_key"] = api_key
        for rec in parse_pubmed_xml(_post(params, api_key)):
            by_pmid[rec["pmid"]] = rec
    records = [by_pmid[p] for p in pmids if p in by_pmid]
    missing = [p for p in pmids if p not in by_pmid]
    return records, missing


def _text(node: ET.Element | None) -> str:
    """All text inside `node`, inline markup (<i>, <sup>, ...) flattened."""
    if node is None:
        return ""
    return re.sub(r"\s+", " ", "".join(node.itertext())).strip()


def _year(article: ET.Element) -> str | None:
    pub_date = article.find("./Journal/JournalIssue/PubDate")
    if pub_date is not None:
        y = pub_date.findtext("Year")
        if y:
            return y.strip()
        m = re.search(r"\b(\d{4})\b", pub_date.findtext("MedlineDate") or "")
        if m:
            return m.group(1)
    art_date = article.find("./ArticleDate/Year")
    return art_date.text.strip() if art_date is not None and art_date.text else None


def _authors(article: ET.Element) -> list[dict]:
    out = []
    for a in article.findall("./AuthorList/Author"):
        collective = _text(a.find("CollectiveName"))
        if collective:
            out.append({"last": collective, "first": None, "raw": collective})
            continue
        last = _text(a.find("LastName"))
        first = _text(a.find("ForeName")) or _text(a.find("Initials")) or None
        if not last:
            continue
        out.append({"last": last, "first": first, "raw": f"{last} {first}".strip() if first else last})
    return out


def _abstract(article: ET.Element) -> str | None:
    parts = []
    for node in article.findall("./Abstract/AbstractText"):
        body = _text(node)
        if not body:
            continue
        label = node.get("Label")
        parts.append(f"{label}: {body}" if label else body)
    return "\n\n".join(parts) or None


def parse_pubmed_xml(xml: bytes) -> list[dict]:
    # Stdlib only (no defusedxml): expat never fetches external entities,
    # and refusing any entity declaration / internal DTD subset up front
    # rules out entity-expansion bombs. NCBI's real output has neither.
    upper = xml.upper()
    doctype = upper.split(b"<!DOCTYPE", 1)[1].split(b">", 1)[0] if b"<!DOCTYPE" in upper else b""
    if b"<!ENTITY" in upper or b"[" in doctype:
        raise EutilsError("refusing PubMed XML with an internal DTD / entity declarations")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as e:
        raise EutilsError(f"malformed PubMed XML: {e}") from e

    out = []
    for pa in root.findall("./PubmedArticle"):
        citation = pa.find("MedlineCitation")
        if citation is None:
            continue
        pmid = (citation.findtext("PMID") or "").strip()
        article = citation.find("Article")
        if not pmid or article is None:
            continue

        ids = {i.get("IdType"): (i.text or "").strip() for i in pa.findall("./PubmedData/ArticleIdList/ArticleId")}
        journal = article.find("Journal")
        grants = []
        for g in article.findall("./GrantList/Grant"):
            agency = _text(g.find("Agency")) or None
            grant_id = _text(g.find("GrantID")) or None
            grants.append({"agency": agency, "grant_id": grant_id, "raw": " ".join(x for x in (grant_id, agency) if x)})

        out.append({
            "pmid": pmid,
            "title": _text(article.find("ArticleTitle")),
            "abstract": _abstract(article),
            "authors": _authors(article),
            "journal": (_text(journal.find("ISOAbbreviation")) or _text(journal.find("Title")) or None) if journal is not None else None,
            "year": _year(article),
            "doi": ids.get("doi") or None,
            "pmcid": ids.get("pmc") or None,
            "grants": grants,
            "publication_types": [_text(t) for t in article.findall("./PublicationTypeList/PublicationType") if _text(t)],
            "mesh_terms": [_text(d) for d in citation.findall("./MeshHeadingList/MeshHeading/DescriptorName") if _text(d)],
        })
    return out
