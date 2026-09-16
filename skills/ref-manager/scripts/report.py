#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""`/ref:report --person <id> --from <date> --to <date>` — basic reproducible
report (§3c "Reproducible reports").

Phase-2 scoping (no grant/lab grouping yet — that's a later, fuller
`/ref:report`; this is explicitly the "basic" slice named in the phase 2
gate): one person, one date window, publication list with author role,
CSV + Markdown (§3c: "CSV plus Markdown is the first export scope").

The manifest persists date basis, missing-date handling, identity-review
policy, and dedup policy so a rerun with unchanged inputs reproduces
identical publications.csv/report.md content — only the manifest's
generated_at timestamp differs between runs.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

from lib_atomic import atomic_write_json, atomic_write_text
import publications as pub_mod
from audit import latest_real_observation

CITATION_STALE_DAYS_DEFAULT = 180

DATE_BASIS = "publication_year"  # only year granularity exists before full-text metadata (phase 3+)
MISSING_DATE_HANDLING = "excluded"  # a paper with no year is excluded from the window, not guessed
IDENTITY_REVIEW_POLICY = "confirmed_publications_only"  # candidate/rejected matches never counted
DEDUP_POLICY = "unique_by_pmid"


def _report_dir(library_root: Path, label: str) -> Path:
    return library_root / "reports" / label


def generate(library_root: Path, person_slug: str, since: str, until: str, label: str,
             include_citations: bool = False, stale_days: int = CITATION_STALE_DAYS_DEFAULT) -> dict:
    person = json.loads((library_root / "people" / f"{person_slug}.json").read_text())
    since_y, until_y = since[:4], until[:4]

    rows = []
    for cp in person.get("confirmed_publications", []):
        pmid = cp["pmid"]
        meta_path = library_root / "papers" / pmid / "meta.json"
        if not meta_path.exists():
            continue
        meta = json.loads(meta_path.read_text())
        year = str(meta.get("year") or "")[:4]
        if not year or year < since_y or year > until_y:
            continue  # missing/out-of-window year: excluded (MISSING_DATE_HANDLING)
        auth = json.loads((library_root / "papers" / pmid / "authorship.json").read_text()) \
            if (library_root / "papers" / pmid / "authorship.json").exists() else {"authors": [], "complete": True}
        role = pub_mod.classify_role(cp["author_index"], len(auth.get("authors", [])), auth.get("complete", True))
        row = {
            "pmid": pmid, "citekey": meta.get("citekey"), "doi": meta.get("doi") or "",
            "year": year, "journal": meta.get("journal") or "", "title": meta.get("title") or "",
            "author_role": role,
            "extraction_tier": meta.get("extraction_tier") or "unknown",
            "abstract_available": bool(meta.get("abstract_available")),
            "full_text": bool(meta.get("full_text")),
            "checked_at": meta.get("checked_at") or "",
        }
        if include_citations:
            # D25: "Citation counts are dated observations from a named
            # source, never 'the' citation count" -- never a bare int, and
            # a publication with no observation is unknown, never zero.
            obs = latest_real_observation(library_root, pmid)
            if obs is None:
                row["citation_count"] = None
                row["citation_source"] = None
                row["citation_retrieved_at"] = None
                row["citation_coverage"] = "no observation available"
                row["citation_stale"] = None
            else:
                age = datetime.now(timezone.utc) - datetime.fromisoformat(obs["retrieved_at"])
                row["citation_count"] = obs["count"]
                row["citation_source"] = obs["source"]
                row["citation_retrieved_at"] = obs["retrieved_at"]
                row["citation_coverage"] = obs["coverage"]
                row["citation_stale"] = age > timedelta(days=stale_days)
        rows.append(row)

    rows.sort(key=lambda r: (r["year"], r["pmid"]))  # deterministic order (DEDUP_POLICY: unique_by_pmid)

    fieldnames = [
        "pmid", "citekey", "doi", "year", "journal", "title", "author_role",
        "extraction_tier", "abstract_available", "full_text", "checked_at",
    ]
    if include_citations:
        fieldnames += ["citation_count", "citation_source", "citation_retrieved_at",
                        "citation_coverage", "citation_stale"]
    csv_buf = io.StringIO()
    writer = csv.DictWriter(csv_buf, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)

    md_lines = [
        f"# Publication report — {person_slug}",
        "",
        f"Scope: confirmed publications in this library, {since}–{until} (`{DATE_BASIS}`). "
        "PubMed-only coverage; portfolio completeness not reviewed (§3c).",
        "",
    ]
    if include_citations:
        md_lines.append(
            "Citation counts below are **PMC-indexed citing-article counts (D25)** — "
            "not total citations, and not comparable to Scopus/Web of Science. Each "
            "count names its source and retrieval date; `unknown` means no observation "
            "has been recorded, never zero."
        )
        md_lines.append("")
        md_lines += [
            "| PMID | Year | Role | Title | Tier | Citing articles (PMC) | Source | Retrieved | Stale |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for r in rows:
            count = r["citation_count"] if r["citation_count"] is not None else "unknown"
            src = r["citation_source"] or "—"
            retrieved = (r["citation_retrieved_at"] or "—")[:10]
            stale = "yes" if r["citation_stale"] else ("no" if r["citation_stale"] is False else "—")
            md_lines.append(
                f"| {r['pmid']} | {r['year']} | {r['author_role']} | {r['title']} | {r['extraction_tier']} |"
                f" {count} | {src} | {retrieved} | {stale} |"
            )
    else:
        md_lines += [
            f"| PMID | Year | Role | Title | Tier |",
            f"|---|---|---|---|---|",
        ]
        for r in rows:
            md_lines.append(f"| {r['pmid']} | {r['year']} | {r['author_role']} | {r['title']} | {r['extraction_tier']} |")
    md_lines.append("")
    md_lines.append(f"Total unique publications: {len(rows)}")
    md_text = "\n".join(md_lines) + "\n"

    rdir = _report_dir(library_root, label)
    rdir.mkdir(parents=True, exist_ok=True)
    atomic_write_text(rdir / "publications.csv", csv_buf.getvalue())
    atomic_write_text(rdir / "report.md", md_text)

    manifest = {
        "person": person_slug,
        "from": since,
        "to": until,
        "date_basis": DATE_BASIS,
        "missing_date_handling": MISSING_DATE_HANDLING,
        "identity_review_policy": IDENTITY_REVIEW_POLICY,
        "dedup_policy": DEDUP_POLICY,
        "publication_count": len(rows),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "includes_citations": include_citations,
    }
    if include_citations:
        manifest["citation_stale_days"] = stale_days
        manifest["citation_coverage_note"] = (
            "citing articles indexed in PMC; not a total citation count (D25)"
        )
    atomic_write_json(rdir / "manifest.json", manifest)
    return manifest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--person", required=True)
    ap.add_argument("--from", dest="date_from", required=True)
    ap.add_argument("--to", dest="date_to", required=True)
    ap.add_argument("--label")
    ap.add_argument("--citations", action="store_true",
                     help="include PMC-indexed citing-article counts (D25), never total citations")
    ap.add_argument("--stale-days", type=int, default=CITATION_STALE_DAYS_DEFAULT)
    args = ap.parse_args()

    library_root = Path(args.repo).expanduser().resolve()
    if not library_root.is_dir():
        print(f"error: no library at {library_root}", file=sys.stderr)
        return 1

    label = args.label or f"{args.person}-{args.date_from}-{args.date_to}"
    result = generate(library_root, args.person, args.date_from, args.date_to, label,
                       include_citations=args.citations, stale_days=args.stale_days)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
