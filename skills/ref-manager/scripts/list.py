#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""`/ref:list` -- filterable browse/report over the paper library
(LIBRARY_VIEWER_IMPLEMENTATION_PLAN.md §5). Read-only, built entirely on
`lib_inventory.rows()`.

Unlike `lib_selector.resolve()` -- which requires an explicit selector and
raises `SelectorError` on an empty match -- this is a browse-first report:
no filters at all lists every paper in the library, and a filter
combination that matches nothing prints an explicit message rather than
silently printing nothing (or raising). The one exception is
`--format pmids`, whose whole point is to be piped straight into
`/ref:fetch` / `/ref:extract`: an empty match there prints nothing, since a
sentence would corrupt the space-separated contract.

`--project` / `--query` / `--from-file` / `--reading-status` are handled by
handing them straight to `lib_selector.resolve()` (reusing its selector
grammar and its project-scoped-state rule for `--reading-status`), then
intersecting the resolved PMIDs with the rows already filtered by the other
flags. A `SelectorError` whose message starts with "selector matched no
papers" is treated as an empty selection (folded into the same "no papers
matched" reporting as any other filter combination); any other
`SelectorError` (bad project, `--reading-status` without `--project`, etc.)
is a real usage error and is surfaced to the caller.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from pathlib import Path

import lib_selector
from lib_inventory import LINT_BUCKETS, STALE_DAYS_DEFAULT, rows as inventory_rows

SOURCE_BADGES = ("pdf-backed", "full-text", "oa-pending", "abstract-only", "metadata-only")
HAS_MISSING_KEYS = ("pdf", "fulltext", "claims", "figures", "notes")
SORT_KEYS = ("year", "added", "title", "checked", "claims")
FORMATS = ("table", "csv", "json", "pmids")
MATRIX_COLUMNS = ("meta", "abstract", "fulltext", "pdf", "figures", "claims", "indexed", "retraction")

DEFAULT_COLUMNS = ("pmid", "citekey", "title", "year", "source_badge", "extraction_tier", "claims_active")
ALL_COLUMNS = (
    "pmid", "citekey", "title", "year", "journal", "doi", "pmcid", "status",
    "extraction_tier", "checked_at", "source_badge", "has_pdf", "has_fulltext",
    "version_id", "figures_total", "figures_with_image", "claims_active",
    "retraction_status", "days_since_check", "stale_check", "notes_count",
    "authors_count", "first_author", "last_author", "authors_short", "in_catalog", "lint_flags", "projects",
)


def _csv_list(s: str | None) -> list[str]:
    if not s:
        return []
    return [part.strip() for part in s.split(",") if part.strip()]


def _has(row: dict, key: str) -> bool:
    if key == "pdf":
        return bool(row["has_pdf"])
    if key == "fulltext":
        return bool(row["has_fulltext"])
    if key == "claims":
        return row["claims_active"] > 0
    if key == "figures":
        return row["figures_total"] > 0
    if key == "notes":
        return row["notes_count"] > 0
    raise ValueError(f"unknown --has/--missing key {key!r}, expected one of {HAS_MISSING_KEYS}")


def _parse_year_range(spec: str) -> tuple[int, int]:
    if ".." in spec:
        lo_s, _, hi_s = spec.partition("..")
    else:
        lo_s = hi_s = spec
    try:
        lo, hi = int(lo_s), int(hi_s)
    except ValueError as e:
        raise ValueError(f"--year must be YYYY or YYYY..YYYY, got {spec!r}") from e
    if lo > hi:
        lo, hi = hi, lo
    return lo, hi


class ListError(ValueError):
    pass


def filter_rows(all_rows: list[dict], library_root: Path, args) -> list[dict]:
    out = all_rows

    if args.source:
        wanted = set(_csv_list(args.source))
        unknown = wanted - set(SOURCE_BADGES)
        if unknown:
            raise ListError(f"--source: unknown badge(s) {sorted(unknown)}, expected one of {SOURCE_BADGES}")
        out = [r for r in out if r["source_badge"] in wanted]

    for key in _csv_list(args.has):
        out = [r for r in out if _has(r, key)]

    for key in _csv_list(args.missing):
        out = [r for r in out if not _has(r, key)]

    if args.tier:
        out = [r for r in out if r["extraction_tier"] == args.tier]

    if args.year:
        lo, hi = _parse_year_range(args.year)

        def _year_ok(r: dict) -> bool:
            try:
                return lo <= int(r["year"]) <= hi
            except (TypeError, ValueError):
                return False

        out = [r for r in out if _year_ok(r)]

    if args.journal:
        needle = args.journal.lower()
        out = [r for r in out if needle in (r["journal"] or "").lower()]

    if args.retracted:
        out = [r for r in out if r["retraction_status"] in ("retracted", "erratum")]

    if args.issue:
        if args.issue not in LINT_BUCKETS:
            raise ListError(f"--issue: unknown bucket {args.issue!r}, expected one of {LINT_BUCKETS}")
        out = [r for r in out if args.issue in r["lint_flags"]]

    # --stale-days is a filter here (unlike lint.py, where it only sets the
    # threshold): show only papers whose staleness at that threshold is true.
    if args.stale_days is not None:
        out = [r for r in out if r["stale_check"]]

    selector_active = any([args.project, args.query, args.from_file, args.reading_status])
    if selector_active:
        try:
            result = lib_selector.resolve(
                library_root,
                project=args.project,
                query=args.query,
                from_file=args.from_file,
                queue_state=args.reading_status,
            )
            selector_pmids = set(result["pmids"])
        except lib_selector.SelectorError as e:
            if str(e).startswith("selector matched no papers"):
                selector_pmids = set()
            else:
                raise ListError(str(e)) from e
        out = [r for r in out if r["pmid"] in selector_pmids]

    return out


def _sort_key(field: str):
    if field == "year":
        return lambda r: (r["year"] is None, r["year"] if r["year"] is not None else "")
    if field == "added":
        # meta.json has no added_at field; rows() already returns papers in
        # `papers/<pmid>` directory order, which is the best available
        # insertion-order proxy -- see LIBRARY_VIEWER_IMPLEMENTATION_PLAN.md
        # §5 deviation note in the /ref:list command doc.
        return lambda r: r["pmid"]
    if field == "title":
        return lambda r: (r["title"] or "").lower()
    if field == "checked":
        return lambda r: r["checked_at"] or ""
    if field == "claims":
        return lambda r: r["claims_active"]
    raise ListError(f"--sort: unknown key {field!r}, expected one of {SORT_KEYS}")


def sort_rows(rows: list[dict], sort: str | None) -> list[dict]:
    if not sort:
        return rows
    reverse = sort in ("year", "checked", "claims")
    return sorted(rows, key=_sort_key(sort), reverse=reverse)


def _display(col: str, value) -> str:
    if value is None:
        return ""
    if col == "first_author" and isinstance(value, dict):
        return value.get("last") or value.get("raw") or ""
    if col == "lint_flags" and isinstance(value, list):
        return ";".join(value)
    if col == "projects" and isinstance(value, list):
        return ";".join(p.get("slug", "") for p in value if isinstance(p, dict))
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def resolve_columns(spec: str | None) -> list[str]:
    if not spec:
        return list(DEFAULT_COLUMNS)
    columns = _csv_list(spec)
    unknown = [c for c in columns if c not in ALL_COLUMNS]
    if unknown:
        raise ListError(f"--columns: unknown column(s) {unknown}, expected one of {ALL_COLUMNS}")
    return columns


def _matrix_row(row: dict) -> dict:
    meta_present = "missing_meta" not in row["lint_flags"] and "malformed_meta" not in row["lint_flags"]
    return {
        "pmid": row["pmid"],
        "meta": meta_present,
        "abstract": meta_present and "missing_abstract" not in row["lint_flags"],
        "fulltext": bool(row["has_fulltext"]),
        "pdf": bool(row["has_pdf"]),
        "figures": row["figures_total"] > 0,
        "claims": row["claims_active"] > 0,
        "indexed": bool(row["in_catalog"]),
        "retraction": row["retraction_status"] not in (None, "unknown"),
    }


def _print_table(headers: list[str], str_rows: list[list[str]]) -> str:
    widths = [len(h) for h in headers]
    for r in str_rows:
        for i, cell in enumerate(r):
            widths[i] = max(widths[i], len(cell))
    lines = ["  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)).rstrip()]
    lines.append("  ".join("-" * widths[i] for i in range(len(headers))))
    for r in str_rows:
        lines.append("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(r)).rstrip())
    return "\n".join(lines)


def _print_csv(headers: list[str], str_rows: list[list[str]]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    writer.writerows(str_rows)
    return buf.getvalue().rstrip("\r\n")


def render(rows: list[dict], args) -> str | None:
    """Returns the text to print, or None when the caller should print the
    "no papers matched"/pmids-empty handling instead."""
    if args.format == "pmids":
        return " ".join(r["pmid"] for r in rows)

    if not rows:
        return None

    if args.matrix:
        matrix_rows = [_matrix_row(r) for r in rows]
        if args.format == "json":
            return json.dumps(matrix_rows, indent=2)
        headers = ["pmid", *MATRIX_COLUMNS]
        str_rows = [
            [mr["pmid"], *("✓" if mr[c] else "·" for c in MATRIX_COLUMNS)]
            for mr in matrix_rows
        ]
        if args.format == "csv":
            return _print_csv(headers, str_rows)
        return _print_table(headers, str_rows)

    columns = resolve_columns(args.columns)
    if args.format == "json":
        return json.dumps([{c: r[c] for c in columns} for r in rows], indent=2)
    str_rows = [[_display(c, r[c]) for c in columns] for r in rows]
    if args.format == "csv":
        return _print_csv(columns, str_rows)
    return _print_table(columns, str_rows)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--source", help=f"comma-separated subset of {SOURCE_BADGES}")
    ap.add_argument("--has", help=f"comma-separated subset of {HAS_MISSING_KEYS}, ANDed")
    ap.add_argument("--missing", help=f"comma-separated subset of {HAS_MISSING_KEYS}, ANDed")
    ap.add_argument("--tier", choices=["abstract", "full", "unavailable"])
    ap.add_argument("--year", help="YYYY or YYYY..YYYY")
    ap.add_argument("--journal", help="case-insensitive substring match")
    ap.add_argument("--retracted", action="store_true", help="retraction_status in retracted|erratum")
    ap.add_argument("--stale-days", type=int, default=None,
                     help="filter to papers whose checked_at is older than N days "
                          f"(default threshold {STALE_DAYS_DEFAULT} when given without a value effect on rows())")
    ap.add_argument("--issue", help=f"one of the lint buckets: {LINT_BUCKETS}")
    ap.add_argument("--project")
    ap.add_argument("--reading-status", help="requires --project (project-scoped state)")
    ap.add_argument("--query")
    ap.add_argument("--from-file")
    ap.add_argument("--sort", choices=SORT_KEYS)
    ap.add_argument("--columns", help=f"comma-separated subset of {ALL_COLUMNS}")
    ap.add_argument("--format", choices=FORMATS, default="table")
    ap.add_argument("--matrix", action="store_true",
                     help=f"paper x {{{', '.join(MATRIX_COLUMNS)}}} coverage grid instead of --columns")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    library_root = Path(args.repo).expanduser().resolve()
    if not library_root.is_dir():
        print(f"error: no library at {library_root}", file=sys.stderr)
        return 1

    stale_days = args.stale_days if args.stale_days is not None else STALE_DAYS_DEFAULT
    all_rows = inventory_rows(library_root, stale_days=stale_days)

    try:
        filtered = filter_rows(all_rows, library_root, args)
    except ListError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    filtered = sort_rows(filtered, args.sort)

    if not filtered:
        if args.format == "pmids":
            return 0  # deliberately silent: piped straight into /ref:fetch etc.
        if not all_rows:
            print("no papers in the library yet.")
        else:
            print("no papers matched the given filters.")
        return 0

    try:
        text = render(filtered, args)
    except ListError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
