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
from datetime import datetime, timezone
from pathlib import Path

from lib_atomic import atomic_write_json, atomic_write_text
import publications as pub_mod

DATE_BASIS = "publication_year"  # only year granularity exists before full-text metadata (phase 3+)
MISSING_DATE_HANDLING = "excluded"  # a paper with no year is excluded from the window, not guessed
IDENTITY_REVIEW_POLICY = "confirmed_publications_only"  # candidate/rejected matches never counted
DEDUP_POLICY = "unique_by_pmid"


def _report_dir(library_root: Path, label: str) -> Path:
    return library_root / "reports" / label


def generate(library_root: Path, person_slug: str, since: str, until: str, label: str) -> dict:
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
        rows.append({
            "pmid": pmid, "citekey": meta.get("citekey"), "doi": meta.get("doi") or "",
            "year": year, "journal": meta.get("journal") or "", "title": meta.get("title") or "",
            "author_role": role,
        })

    rows.sort(key=lambda r: (r["year"], r["pmid"]))  # deterministic order (DEDUP_POLICY: unique_by_pmid)

    csv_buf = io.StringIO()
    writer = csv.DictWriter(csv_buf, fieldnames=["pmid", "citekey", "doi", "year", "journal", "title", "author_role"])
    writer.writeheader()
    writer.writerows(rows)

    md_lines = [
        f"# Publication report — {person_slug}",
        "",
        f"Scope: confirmed publications in this library, {since}–{until} (`{DATE_BASIS}`). "
        "PubMed-only coverage; portfolio completeness not reviewed (§3c).",
        "",
        f"| PMID | Year | Role | Title |",
        f"|---|---|---|---|",
    ]
    for r in rows:
        md_lines.append(f"| {r['pmid']} | {r['year']} | {r['author_role']} | {r['title']} |")
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
    }
    atomic_write_json(rdir / "manifest.json", manifest)
    return manifest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--person", required=True)
    ap.add_argument("--from", dest="date_from", required=True)
    ap.add_argument("--to", dest="date_to", required=True)
    ap.add_argument("--label")
    args = ap.parse_args()

    library_root = Path(args.repo).expanduser().resolve()
    if not library_root.is_dir():
        print(f"error: no library at {library_root}", file=sys.stderr)
        return 1

    label = args.label or f"{args.person}-{args.date_from}-{args.date_to}"
    result = generate(library_root, args.person, args.date_from, args.date_to, label)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
