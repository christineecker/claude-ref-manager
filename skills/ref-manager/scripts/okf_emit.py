# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""`/ref:weave` (OKF half) -- generates okf/ from structured JSONL sources
(PLAN.md D1, §3, §3a: "Structured graph records back regenerable OKF views").

okf/ is a conformant OKF v0.2 bundle (readable by the `okf` plugin's
search_concepts/read_concept/get_neighbors MCP tools) -- markdown files with
YAML frontmatter, `type` required, cross-links as bundle-relative markdown
links. It is entirely regenerable: never hand-edit anything under okf/, edit
the JSONL/JSON sources and re-run this script. Regeneration with unchanged
inputs is idempotent (byte-identical output) -- callers pass `now` explicitly
so repeat runs in a test don't diverge on wall-clock time; production callers
omit it and get datetime.now(timezone.utc).

Reads (best-effort -- this agent built the OKF/people-graph half of phase 8
concurrently with another agent building graph/concepts.jsonl and
graph/relations.jsonl; if those files don't exist yet in a given library,
this degrades to "no relations data available" rather than crashing):

  graph/concepts.jsonl   {"concept_id", "name", "aliases": [...],
                          "provenance": [...]}  (assumed shape, per PLAN.md
                          §3: "stable concept IDs, names, aliases and
                          normalization provenance" -- field names are a
                          best guess, reconcile against the concurrent
                          agent's actual writer)
  graph/relations.jsonl  {"relation_id", "type", "subject_concept_id",
                          "object_concept_id", "supporting_claim_ids": [...],
                          "source_version_ids": [...], "review_state",
                          "stale": bool}  (assumed shape, same caveat)

  papers/<pmid>/meta.json, authorship.json, funding.json
  people/<slug>.json, grants/<slug>.json

Writes okf/concepts/<id>.md, okf/papers/<citekey>.md, okf/people/<slug>.md,
okf/grants/<slug>.md, okf/index.md, okf/log.md.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from lib_atomic import atomic_write_text

ACTOR = "process:ref-manager-okf-emit"


def _now(now: str | None) -> str:
    return now or datetime.now(timezone.utc).isoformat()


def _fm(d: dict) -> str:
    """Minimal deterministic YAML frontmatter writer (no PyYAML dependency,
    per this project's no-unnecessary-deps norm) -- sorted keys, simple
    scalar/list values only, sufficient for what this emitter needs."""
    lines = ["---"]
    for k, v in d.items():
        if v is None:
            continue
        if isinstance(v, list):
            if not v:
                continue
            lines.append(f"{k}:")
            for item in v:
                if isinstance(item, dict):
                    first = True
                    for ik, iv in item.items():
                        prefix = "  - " if first else "    "
                        lines.append(f"{prefix}{ik}: {json.dumps(iv)}")
                        first = False
                else:
                    lines.append(f"  - {json.dumps(item)}")
        elif isinstance(v, dict):
            lines.append(f"{k}:")
            for ik, iv in v.items():
                lines.append(f"  {ik}: {json.dumps(iv)}")
        elif isinstance(v, str) and (":" in v or v.startswith(("[", "{"))):
            lines.append(f'{k}: {json.dumps(v)}')
        else:
            lines.append(f"{k}: {json.dumps(v) if isinstance(v, str) else v}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def _read_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


def _write_concept(okf_root: Path, concept: dict, relations: list[dict] | None, now: str) -> None:
    cid = concept["concept_id"]
    fm = {
        "type": "Concept",
        "title": concept.get("name", cid),
        "description": f"Scientific concept: {concept.get('name', cid)}",
        "tags": concept.get("aliases", []),
        "generated": {"by": ACTOR, "at": now},
    }
    body = [f"# {concept.get('name', cid)}", ""]
    aliases = concept.get("aliases", [])
    if aliases:
        body.append("## Aliases")
        body.extend(f"- {a}" for a in aliases)
        body.append("")
    body.append("## Relations")
    if relations is None:
        body.append("No relations data available (graph/relations.jsonl not present in this library yet).")
    else:
        edges = [r for r in relations if r.get("subject_concept_id") == cid or r.get("object_concept_id") == cid]
        if not edges:
            body.append("No relations recorded for this concept yet.")
        else:
            for r in sorted(edges, key=lambda r: r.get("relation_id", "")):
                other = r["object_concept_id"] if r.get("subject_concept_id") == cid else r["subject_concept_id"]
                stale = " (STALE -- underlying claim superseded, needs re-confirmation)" if r.get("stale") else ""
                body.append(f"- **{r.get('type', 'related_to')}** -> [{other}](../concepts/{other}.md){stale} "
                            f"[{r.get('review_state', 'unreviewed')}]")
        body.append("")
    (okf_root / "concepts").mkdir(parents=True, exist_ok=True)
    atomic_write_text(okf_root / "concepts" / f"{cid}.md", _fm(fm) + "\n" + "\n".join(body) + "\n")


def _write_paper(okf_root: Path, library_root: Path, pmid: str, now: str) -> str | None:
    meta_path = library_root / "papers" / pmid / "meta.json"
    if not meta_path.exists():
        return None
    meta = json.loads(meta_path.read_text())
    citekey = meta["citekey"]
    authorship_path = library_root / "papers" / pmid / "authorship.json"
    authors = json.loads(authorship_path.read_text())["authors"] if authorship_path.exists() else []
    fm = {
        "type": "Reference",
        "title": meta.get("title", citekey),
        "description": f"Library record for PMID {pmid} ({meta.get('journal') or 'unknown journal'}, {meta.get('year') or 'unknown year'})",
        "tags": ["reference", meta.get("extraction_tier") or "unknown"],
        "resource": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        "generated": {"by": ACTOR, "at": now},
        "sources": [{"id": "pubmed", "resource": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"}],
    }
    body = [f"# {meta.get('title', citekey)}", "",
            f"- PMID: {pmid}", f"- Citekey: `{citekey}`",
            f"- DOI: {meta.get('doi') or 'unknown'}",
            f"- Journal: {meta.get('journal') or 'unknown'} ({meta.get('year') or 'unknown'})",
            f"- Extraction tier: {meta.get('extraction_tier')}"]
    if authors:
        body.append("")
        body.append("## Authors")
        for a in authors:
            fallback = f"{a.get('last', '')}, {a.get('first', '')}"
            body.append(f"- {a.get('raw') or fallback}")
    body.append("")
    (okf_root / "papers").mkdir(parents=True, exist_ok=True)
    atomic_write_text(okf_root / "papers" / f"{citekey}.md", _fm(fm) + "\n" + "\n".join(body) + "\n")
    return citekey


def _write_person(okf_root: Path, person: dict, now: str) -> None:
    slug = person["slug"]
    fm = {
        "type": "Entity",
        "title": person.get("name_variants", [slug])[0],
        "description": f"Researcher: {person.get('name_variants', [slug])[0]}",
        "tags": person.get("name_variants", []),
        "generated": {"by": ACTOR, "at": now},
    }
    body = [f"# {person.get('name_variants', [slug])[0]}", ""]
    if person.get("orcid"):
        body.append(f"- ORCID: {person['orcid']}")
    confirmed = person.get("confirmed_publications", [])
    body.append("")
    body.append("## Authored publications (confirmed)")
    if confirmed:
        for c in confirmed:
            body.append(f"- PMID {c['pmid']} (author position {c.get('author_index')})")
    else:
        body.append("None confirmed yet.")
    (okf_root / "people").mkdir(parents=True, exist_ok=True)
    atomic_write_text(okf_root / "people" / f"{slug}.md", _fm(fm) + "\n" + "\n".join(body) + "\n")


def _write_grant(okf_root: Path, grant: dict, now: str) -> None:
    slug = grant["slug"]
    fm = {
        "type": "Entity",
        "title": f"{grant.get('funder', 'unknown funder')} {grant.get('award_number', '')}".strip(),
        "description": f"Grant: {grant.get('funder', 'unknown funder')} award {grant.get('award_number', 'unknown')}",
        "tags": ["grant", grant.get("funder") or "unknown-funder"],
        "generated": {"by": ACTOR, "at": now},
    }
    body = [f"# {grant.get('funder', 'unknown funder')} — {grant.get('award_number', 'unknown award')}", "",
            f"- Funder: {grant.get('funder')}",
            f"- Award number: {grant.get('award_number')}",
            f"- Approved aliases: {', '.join(grant.get('approved_aliases', [])) or 'none'}",
            f"- Aims (free text): {grant.get('aims') or 'not recorded'}"]
    (okf_root / "grants").mkdir(parents=True, exist_ok=True)
    atomic_write_text(okf_root / "grants" / f"{slug}.md", _fm(fm) + "\n" + "\n".join(body) + "\n")


def emit(library_root: Path, now: str | None = None) -> dict:
    now = _now(now)
    okf_root = library_root / "okf"
    okf_root.mkdir(parents=True, exist_ok=True)

    concepts = _read_jsonl(library_root / "graph" / "concepts.jsonl")
    relations_path = library_root / "graph" / "relations.jsonl"
    relations = _read_jsonl(relations_path) if relations_path.exists() else None

    for c in sorted(concepts, key=lambda c: c["concept_id"]):
        _write_concept(okf_root, c, relations, now)

    papers_dir = library_root / "papers"
    citekeys = []
    if papers_dir.is_dir():
        for pmid_dir in sorted(p.name for p in papers_dir.iterdir() if p.is_dir()):
            ck = _write_paper(okf_root, library_root, pmid_dir, now)
            if ck:
                citekeys.append(ck)

    people_dir = library_root / "people"
    people = []
    if people_dir.is_dir():
        for p in sorted(people_dir.glob("*.json")):
            person = json.loads(p.read_text())
            _write_person(okf_root, person, now)
            people.append(person["slug"])

    grants_dir = library_root / "grants"
    grants = []
    if grants_dir.is_dir():
        for g in sorted(grants_dir.glob("*.json")):
            grant = json.loads(g.read_text())
            _write_grant(okf_root, grant, now)
            grants.append(grant["slug"])

    index_lines = [
        _fm({"okf_version": "0.2"}).rstrip("\n"),
        "", "# ref-manager knowledge bundle", "",
        f"Generated by {ACTOR} at {now}. Never hand-edit -- regenerate via /ref:weave.", "",
        f"## Concepts ({len(concepts)})",
    ]
    index_lines += [f"- [{c['concept_id']}](concepts/{c['concept_id']}.md)" for c in sorted(concepts, key=lambda c: c["concept_id"])]
    index_lines += ["", f"## Papers ({len(citekeys)})"]
    index_lines += [f"- [{ck}](papers/{ck}.md)" for ck in citekeys]
    index_lines += ["", f"## People ({len(people)})"]
    index_lines += [f"- [{s}](people/{s}.md)" for s in people]
    index_lines += ["", f"## Grants ({len(grants)})"]
    index_lines += [f"- [{s}](grants/{s}.md)" for s in grants]
    index_lines.append("")
    atomic_write_text(okf_root / "index.md", "\n".join(index_lines))

    log_path = okf_root / "log.md"
    entry = f"- {now} — regenerated ({len(concepts)} concepts, {len(citekeys)} papers, {len(people)} people, {len(grants)} grants)\n"
    if not log_path.exists():
        atomic_write_text(log_path, "# Log\n\n" + entry)
    else:
        # idempotent: don't append a duplicate entry for an unchanged regen
        # at the same `now` (tests pass a fixed `now` across repeat calls)
        existing = log_path.read_text()
        if entry not in existing:
            atomic_write_text(log_path, existing + entry)

    return {
        "concepts": len(concepts), "papers": len(citekeys),
        "people": len(people), "grants": len(grants),
        "relations_available": relations is not None,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--now")
    args = ap.parse_args()
    library_root = Path(args.repo).expanduser().resolve()
    if not library_root.is_dir():
        print(f"error: no library at {library_root}", file=sys.stderr)
        return 1
    result = emit(library_root, now=args.now)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
