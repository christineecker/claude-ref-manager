# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""`/ref:fetch <pmid...>` -- full-text acquisition (PLAN.md §4, §6).

Priority order (§6): PMC OA JATS -> Unpaywall -> publisher HTML -> paywalled
(abstract-only stays first-class, never a failure). This script does not
call PubMed or scrape publisher pages itself -- the calling command markdown
resolves JATS (via the PubMed MCP tool) and publisher HTML (via WebFetch/
firecrawl) and hands normalized input to this script, exactly like add.py's
split. Unpaywall is the one exception: a single deterministic REST call
needing no LLM judgment, so this script makes it directly via stdlib
urllib.request (§6 point 2).

Input envelope (--input-file): a JSON array, one object per PMID:
{
  "pmid": "12345",
  "doi": "10.1234/x" | null,                 # needed for the Unpaywall step
  "jats_xml": "<article>...</article>" | null,  # genuine JATS markup only --
                                                 # NOT the live get_full_text_article
                                                 # tool's output, which is
                                                 # pre-extracted plain text
                                                 # (verified live); convert.py
                                                 # now refuses non-well-formed
                                                 # XML rather than mangling it
  "publisher_html": "<html>...</html>" | null,  # from WebFetch/firecrawl, if
                                                 # the calling agent already
                                                 # tried it (this script will
                                                 # NOT fetch a URL itself)
  "plain_text": "..." | null,                   # pre-extracted full text with
                                                 # no markup -- e.g. the live
                                                 # get_full_text_article tool's
                                                 # `articles[].full_text`.
                                                 # Written through as-is;
                                                 # section structure/figures
                                                 # are not recoverable from it.
}
Each PMID must already exist (papers/<pmid>/meta.json from /ref:add) -- fetch
augments a record, it doesn't create one (that's RESOLVE/DEDUP, §4 step 1-2).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

from lib_atomic import atomic_write_json, commit_version, pmid_lock
from lib_ids import gen_opaque_id
from convert import convert_jats, convert_html, convert_plain_text
from funding_extract import extract_funding_observations

UNPAYWALL_TIMEOUT = 15


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _preserve_raw(paper_dir: Path, data: bytes, filename: str) -> str:
    h = _sha256(data)
    raw_dir = paper_dir / "raw" / h
    raw_dir.mkdir(parents=True, exist_ok=True)
    dest = raw_dir / filename
    if not dest.exists():
        dest.write_bytes(data)
    return h


def _unpaywall_lookup(doi: str, email: str) -> dict | None:
    url = f"https://api.unpaywall.org/v2/{doi}?email={email}"
    try:
        with urllib.request.urlopen(url, timeout=UNPAYWALL_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None


def _best_oa_pdf_url(unpaywall_doc: dict) -> str | None:
    loc = unpaywall_doc.get("best_oa_location") or {}
    return loc.get("url_for_pdf") or loc.get("url")


def _merge_funding(paper_dir: Path, pmid: str, new_observations: list[dict], new_state: str) -> None:
    """Append (never overwrite) funding observations found during conversion,
    independent of claim extraction (§3c: "funding locators resolve even
    without full claim promotion")."""
    funding_path = paper_dir / "funding.json"
    doc = json.loads(funding_path.read_text()) if funding_path.exists() else {
        "pmid": pmid, "observations": [], "state": "not_checked",
    }
    doc["observations"].extend(new_observations)
    rank = {"not_checked": 0, "unknown": 1, "possible_match": 2,
            "indexed_funding_association": 2, "explicit_acknowledgement_verified": 3}
    if rank.get(new_state, 0) > rank.get(doc.get("state", "not_checked"), 0):
        doc["state"] = new_state
    atomic_write_json(funding_path, doc)


def fetch_one(library_root: Path, record: dict, unpaywall_email: str | None) -> dict:
    pmid = str(record["pmid"])
    paper_dir = library_root / "papers" / pmid
    meta_path = paper_dir / "meta.json"

    with pmid_lock(library_root, pmid):
        if not meta_path.exists():
            raise ValueError(f"pmid {pmid} has no meta.json -- run /ref:add first")
        meta = json.loads(meta_path.read_text())

        source = None  # "pmc_jats" | "unpaywall" | "publisher_html" | None
        conv_input = None
        conv_kind = None

        jats_xml = record.get("jats_xml")
        if jats_xml:
            source, conv_kind, conv_input = "pmc_jats", "jats", jats_xml
        elif record.get("doi") and unpaywall_email:
            doc = _unpaywall_lookup(record["doi"], unpaywall_email)
            pdf_url = _best_oa_pdf_url(doc) if doc else None
            if pdf_url:
                # We only record the discovered OA location here -- actually
                # downloading and PDF-converting it goes through the same PDF
                # path as /ref:attach (convert_pdf, anydoc), triggered by the
                # calling command if it chooses to download it. Recording the
                # location is itself useful even when anydoc is unavailable.
                result = {
                    "pmid": pmid, "result": "oa_location_found", "source": "unpaywall",
                    "pdf_url": pdf_url, "note": "Unpaywall found an OA location; "
                    "download + PDF conversion not performed by fetch.py directly "
                    "(use /ref:attach once downloaded, or a future auto-download step)",
                }
                meta["full_text"] = False
                meta["oa_location"] = {"source": "unpaywall", "url": pdf_url}
                atomic_write_json(meta_path, meta)
                return result
        html = record.get("publisher_html")
        if source is None and html:
            source, conv_kind, conv_input = "publisher_html", "html", html

        plain_text = record.get("plain_text")
        if source is None and plain_text:
            source, conv_kind, conv_input = "plain_text", "plain_text", plain_text

        if source is None:
            meta["full_text"] = False
            meta["checked_at"] = meta.get("checked_at")
            atomic_write_json(meta_path, meta)
            return {"pmid": pmid, "result": "abstract_only",
                    "note": "no full text available from any source (§6) -- abstract-only stays first-class"}

        raw_bytes = conv_input.encode("utf-8")
        raw_hash = _preserve_raw(paper_dir, raw_bytes, f"source.{conv_kind}")

        version_id = gen_opaque_id("v-")

        def write_fn(staging: Path) -> None:
            if conv_kind == "jats":
                conv = convert_jats(conv_input, staging)
            elif conv_kind == "html":
                conv = convert_html(conv_input, staging)
            else:
                conv = convert_plain_text(conv_input, staging)
            if conv["status"] != "ok":
                raise ValueError(f"conversion failed ({conv['status']}): {conv['diagnostics']}")
            manifest = {
                "version_id": version_id, "pmid": pmid, "source": source,
                "converter": conv["converter"], "converter_version": conv["version"],
                "raw_hash": raw_hash, "diagnostics": conv["diagnostics"],
            }
            atomic_write_json(staging / "manifest.json", manifest)
            write_fn.conv = conv  # stash for caller

        write_fn.conv = None
        commit_version(paper_dir, version_id, write_fn)
        conv = write_fn.conv

        if conv_kind == "jats":
            observations, funding_state = extract_funding_observations(conv_input)
            if observations:
                _merge_funding(paper_dir, pmid, observations, funding_state)

        meta["full_text"] = True
        meta["extraction_tier"] = meta.get("extraction_tier") or "abstract"
        atomic_write_json(meta_path, meta)

        return {
            "pmid": pmid, "result": "acquired", "source": source, "version": version_id,
            "converter": conv["converter"], "diagnostics": conv["diagnostics"],
        }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--input-file", required=True)
    args = ap.parse_args()

    library_root = Path(args.repo).expanduser().resolve()
    if not library_root.is_dir():
        print(f"error: no library at {library_root}", file=sys.stderr)
        return 1

    config_path = Path.home() / ".config" / "ref-manager" / "config.json"
    unpaywall_email = None
    if config_path.exists():
        unpaywall_email = json.loads(config_path.read_text()).get("unpaywall_email")

    records = json.loads(Path(args.input_file).read_text())
    if not isinstance(records, list):
        records = [records]

    results = []
    exit_code = 0
    for record in records:
        try:
            results.append(fetch_one(library_root, record, unpaywall_email))
        except (ValueError, KeyError) as e:
            results.append({"pmid": record.get("pmid", "?"), "result": "failed", "error": str(e)})
            exit_code = 1

    for r in results:
        line = f"{r['pmid']}: {r['result']}"
        if r.get("source"):
            line += f" (source={r['source']})"
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
