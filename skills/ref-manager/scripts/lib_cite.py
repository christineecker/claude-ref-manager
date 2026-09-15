#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""CSL-JSON generation + BibTeX rendering from it (D10, D14).

`meta.json` is the bibliographic authority; CSL-JSON is its generated
interchange representation, and BibTeX is rendered FROM the CSL-JSON — one
generation path, not two independent renderers, so every export target
stays consistent by construction.
"""
from __future__ import annotations

import json
import re
from pathlib import Path


def _paper_authors(library_root: Path, pmid: str) -> list[dict]:
    p = library_root / "papers" / pmid / "authorship.json"
    if not p.exists():
        return []
    return json.loads(p.read_text()).get("authors", [])


def to_csl(library_root: Path, pmid: str) -> dict:
    meta = json.loads((library_root / "papers" / pmid / "meta.json").read_text())
    authors = _paper_authors(library_root, pmid)
    csl_authors = []
    for a in authors:
        if a.get("is_group"):
            csl_authors.append({"literal": a.get("raw") or a.get("last", "")})
        else:
            csl_authors.append({"family": a.get("last", ""), "given": a.get("first", "")})

    csl = {
        "id": meta["citekey"],
        "type": "article-journal",
        "title": meta.get("title"),
        "author": csl_authors,
        "container-title": meta.get("journal"),
        "PMID": meta.get("pmid"),
    }
    if meta.get("year"):
        try:
            year_int = int(str(meta["year"])[:4])
            csl["issued"] = {"date-parts": [[year_int]]}
        except ValueError:
            pass
    if meta.get("doi"):
        csl["DOI"] = meta["doi"]
    if meta.get("pmcid"):
        csl["PMCID"] = meta["pmcid"]
    return csl


_BIBTEX_ESCAPES = {
    "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
    "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def _escape(text: str) -> str:
    return "".join(_BIBTEX_ESCAPES.get(c, c) for c in text or "")


def csl_to_bibtex_entry(csl: dict) -> str:
    authors = csl.get("author", [])
    author_str = " and ".join(
        a.get("literal") or f"{a.get('family', '')}, {a.get('given', '')}".strip(", ")
        for a in authors
    )
    lines = [f"@article{{{csl['id']},"]
    fields = [
        ("title", f"{{{_escape(csl.get('title') or '')}}}"),
        ("author", f"{{{_escape(author_str)}}}"),
        ("journal", f"{{{_escape(csl.get('container-title') or '')}}}"),
    ]
    if csl.get("issued"):
        fields.append(("year", str(csl["issued"]["date-parts"][0][0])))
    if csl.get("DOI"):
        fields.append(("doi", f"{{{csl['DOI']}}}"))
    if csl.get("PMID"):
        fields.append(("pmid", f"{{{csl['PMID']}}}"))
    if csl.get("PMCID"):
        fields.append(("pmcid", f"{{{csl['PMCID']}}}"))
    lines.extend(f"  {k} = {v}," for k, v in fields)
    lines[-1] = lines[-1].rstrip(",")
    lines.append("}")
    return "\n".join(lines)


def build_exports(library_root: Path, pmids: list[str]) -> tuple[list[dict], str]:
    csl_entries = [to_csl(library_root, pmid) for pmid in pmids]
    bib = "\n\n".join(csl_to_bibtex_entry(c) for c in csl_entries) + "\n"
    return csl_entries, bib
