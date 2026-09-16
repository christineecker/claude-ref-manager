#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Local, deterministic BibTeX (.bib) and CSL-JSON (.csl.json) entry parsing.

MAINTENANCE_FEATURE_IMPLEMENTATION_PLAN.md Phase 4: closes the intake gap
lib_intake.py used to flag as `"result": "unparsed"`. No network, no MCP —
these functions only turn file bytes into a flat list of entry dicts with
whatever identity clues (doi/pmid/title/year/journal) each entry carries.
Resolving a clue to a PMID stays in the calling command, same as it does for
url_identify.py/pdf_identify.py.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_PMID_IN_NOTE_RE = re.compile(r"PMID:?\s*(\d+)", re.IGNORECASE)
_WS_RE = re.compile(r"\s+")


def _clean(value: str) -> str:
    return _WS_RE.sub(" ", value).strip()


def _parse_bib_fields(body: str) -> dict[str, str]:
    """Parse `field = {value}` / `field = "value"` / `field = bare` pairs
    from the text after a BibTeX entry's citekey, respecting brace nesting
    (a title like `{Something {Special} Here}` must not split early)."""
    fields: dict[str, str] = {}
    i, n = 0, len(body)
    while i < n:
        while i < n and (body[i].isspace() or body[i] == ","):
            i += 1
        if i >= n:
            break
        j = i
        while j < n and body[j] not in "=,":
            j += 1
        if j >= n or body[j] != "=":
            break  # malformed tail, stop rather than misparse
        name = body[i:j].strip().lower()
        i = j + 1
        while i < n and body[i].isspace():
            i += 1
        if i >= n:
            break
        if body[i] == "{":
            depth = 1
            start = i + 1
            k = start
            while k < n and depth > 0:
                if body[k] == "{":
                    depth += 1
                elif body[k] == "}":
                    depth -= 1
                k += 1
            value = body[start:k - 1] if depth == 0 else body[start:k]
            i = k
        elif body[i] == '"':
            start = i + 1
            k = start
            while k < n and body[k] != '"':
                k += 1
            value = body[start:k]
            i = k + 1
        else:
            start = i
            k = i
            while k < n and body[k] != ",":
                k += 1
            value = body[start:k]
            i = k
        if name and name not in fields:
            fields[name] = _clean(value)
        while i < n and body[i] != ",":
            i += 1
    return fields


def _entry_from_fields(citekey: str, entry_type: str, fields: dict[str, str]) -> dict:
    return {
        "citekey": citekey or None,
        "entry_type": entry_type or None,
        "title": fields.get("title") or None,
        "doi": fields.get("doi") or None,
        "pmid": fields.get("pmid") or None,
        "year": fields.get("year") or fields.get("date") or None,
        "journal": fields.get("journal") or fields.get("journaltitle") or None,
        "url": fields.get("url") or None,
    }


def parse_bib_text(text: str) -> list[dict]:
    """Parse BibTeX source into entry dicts. Skips `@comment`/`@string`/
    `@preamble` blocks. Malformed entries (no closing brace) are dropped
    rather than raising — this is best-effort clue extraction, not a strict
    validator."""
    entries: list[dict] = []
    i, n = 0, len(text)
    while i < n:
        if text[i] != "@":
            i += 1
            continue
        j = i + 1
        while j < n and (text[j].isalpha()):
            j += 1
        entry_type = text[i + 1:j].lower()
        k = j
        while k < n and text[k].isspace():
            k += 1
        if k >= n or text[k] != "{":
            i = j if j > i else i + 1
            continue
        depth = 1
        body_start = k + 1
        m = body_start
        while m < n and depth > 0:
            if text[m] == "{":
                depth += 1
            elif text[m] == "}":
                depth -= 1
            m += 1
        if depth != 0:
            break  # unterminated entry at EOF; nothing more to parse
        body = text[body_start:m - 1]

        if entry_type not in ("comment", "string", "preamble") and entry_type:
            depth2 = 0
            comma_idx = None
            for pos, ch in enumerate(body):
                if ch == "{":
                    depth2 += 1
                elif ch == "}":
                    depth2 -= 1
                elif ch == "," and depth2 == 0:
                    comma_idx = pos
                    break
            if comma_idx is None:
                citekey, fields_str = body.strip(), ""
            else:
                citekey, fields_str = body[:comma_idx].strip(), body[comma_idx + 1:]
            fields = _parse_bib_fields(fields_str)
            entries.append(_entry_from_fields(citekey, entry_type, fields))
        i = m
    return entries


def parse_bib_file(path: Path) -> list[dict]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return parse_bib_text(text)


def _csl_year(item: dict) -> str | None:
    issued = item.get("issued")
    if isinstance(issued, dict):
        parts = issued.get("date-parts")
        if isinstance(parts, list) and parts and isinstance(parts[0], list) and parts[0]:
            return str(parts[0][0])
    return None


def _csl_pmid(item: dict) -> str | None:
    for key in ("PMID", "pmid"):
        value = item.get(key)
        if value:
            return str(value)
    note = item.get("note")
    if isinstance(note, str):
        m = _PMID_IN_NOTE_RE.search(note)
        if m:
            return m.group(1)
    return None


def parse_csl_json_text(text: str) -> list[dict]:
    try:
        data = json.loads(text)
    except ValueError:
        return []
    if isinstance(data, dict):
        data = data.get("items", [data]) if "items" in data else [data]
    if not isinstance(data, list):
        return []

    entries: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        entries.append({
            "citekey": item.get("id") or None,
            "entry_type": item.get("type") or None,
            "title": item.get("title") or None,
            "doi": item.get("DOI") or item.get("doi") or None,
            "pmid": _csl_pmid(item),
            "year": _csl_year(item),
            "journal": item.get("container-title") or None,
            "url": item.get("URL") or item.get("url") or None,
        })
    return entries


def parse_csl_json_file(path: Path) -> list[dict]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return parse_csl_json_text(text)
