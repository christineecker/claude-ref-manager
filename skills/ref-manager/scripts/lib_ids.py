# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Identifier contract (PLAN.md §3d).

Two ID classes:
  - human-facing: user-minted slugs (project, question, study/dataset/method,
    concept, person/lab/grant, saved query). Collisions are refused, not
    suffixed, except the citekey (D14), which is minted automatically and
    takes a collision suffix under the library lock.
  - machine-facing: opaque IDs (version, claim_id, table/brief/report/PRISMA
    ids, content hashes). Generated at commit, never constructed by a caller.
"""
from __future__ import annotations

import json
import re
import secrets
from pathlib import Path

from lib_atomic import atomic_write_json, library_lock

SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

# kind -> path template relative to library root, {slug} placeholder.
# is_dir: slug names a directory (project, saved query root); otherwise a
# jsonl/registry entry keyed by slug (checked via aliases index instead of
# a filesystem path) or a single file (person/lab/grant).
_SLUG_LAYOUT = {
    "project": ("projects/{slug}", "dir"),
    "query": ("queries/{slug}.yaml", "file"),
    "person": ("people/{slug}.json", "file"),
    "lab": ("labs/{slug}.json", "file"),
    "grant": ("grants/{slug}.json", "file"),
    # registry kinds: existence is tracked in index/aliases/<kind>.json
    # (studies.jsonl / concepts.jsonl are the authoritative records; the
    # alias index here is only a fast slug->exists lookup).
    "study": ("studies/studies.jsonl", "registry"),
    "dataset": ("studies/datasets.jsonl", "registry"),
    "method": ("studies/methods.jsonl", "registry"),
    "concept": ("graph/concepts.jsonl", "registry"),
}


class SlugError(ValueError):
    pass


def normalize_title(title: str | None) -> str:
    """Lowercased alphanumeric words only -- the fuzzy-identity key add.py
    and attach.py use to spot the same paper under a different id."""
    return re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()


def validate_slug(slug: str) -> None:
    if not (1 <= len(slug) <= 64) or not SLUG_RE.match(slug):
        raise SlugError(
            f"invalid slug {slug!r}: must be lowercase a-z/0-9/hyphen, "
            "1-64 chars, no leading/trailing or doubled hyphen"
        )


def _alias_index_path(library_root: Path, kind: str) -> Path:
    return library_root / "index" / "aliases" / f"{kind}.json"


def _load_alias_index(library_root: Path, kind: str) -> dict:
    p = _alias_index_path(library_root, kind)
    if not p.exists():
        return {"live": {}, "aliases": {}}
    return json.loads(p.read_text())


def _conflict_record_info(library_root: Path, kind: str, slug: str) -> str:
    template, mode = _SLUG_LAYOUT[kind]
    if mode == "dir":
        return f"{kind} {slug!r} already exists at {template.format(slug=slug)}"
    if mode == "file":
        return f"{kind} {slug!r} already exists at {template.format(slug=slug)}"
    idx = _load_alias_index(library_root, kind)
    live = idx["live"].get(slug)
    return f"{kind} {slug!r} already registered (record: {live})" if live else f"{kind} {slug!r} already registered"


def slug_exists(library_root: Path, kind: str, slug: str) -> bool:
    if kind not in _SLUG_LAYOUT:
        raise SlugError(f"unknown slug kind {kind!r}")
    template, mode = _SLUG_LAYOUT[kind]
    if mode in ("dir", "file"):
        return (library_root / template.format(slug=slug)).exists()
    idx = _load_alias_index(library_root, kind)
    return slug in idx["live"] or slug in idx["aliases"]


def allocate_slug(library_root: Path, kind: str, slug: str) -> None:
    """Refuse a colliding slug, naming the conflicting record. Registers
    registry-kind slugs in the alias index; dir/file kinds are considered
    allocated once the caller creates the path (this only validates+checks)."""
    validate_slug(slug)
    if slug_exists(library_root, kind, slug):
        raise SlugError(_conflict_record_info(library_root, kind, slug))
    template, mode = _SLUG_LAYOUT[kind]
    if mode == "registry":
        with library_lock(library_root):
            idx = _load_alias_index(library_root, kind)
            if slug in idx["live"] or slug in idx["aliases"]:
                raise SlugError(_conflict_record_info(library_root, kind, slug))
            idx["live"][slug] = slug
            atomic_write_json(_alias_index_path(library_root, kind), idx)


def check_question_id(project_yaml: dict, question_id: str) -> None:
    """Question IDs are unique only within their own project (§3d)."""
    validate_slug(question_id)
    existing = {q["id"] for q in project_yaml.get("questions", [])}
    if question_id in existing:
        raise SlugError(f"question {question_id!r} already exists in this project")


# ---- citekey (D14): the deliberate collision-suffix exception ----

_CITEKEY_RE = re.compile(r"^[a-z][a-z]*[0-9]{4}[a-z]+$")


def _citekey_index_path(library_root: Path) -> Path:
    return library_root / "index" / "citekeys.json"


def make_citekey_base(author_lastname: str, year: str | int, first_title_word: str) -> str:
    def clean(s: str) -> str:
        return re.sub(r"[^a-z0-9]", "", s.lower())

    return f"{clean(author_lastname)}{year}{clean(first_title_word)}"


def allocate_citekey(library_root: Path, author_lastname: str, year: str | int, first_title_word: str) -> str:
    """Assign a stable citekey, suffixing -2, -3, ... on collision, under the
    library lock. Existing citekeys are never changed (§3a)."""
    base = make_citekey_base(author_lastname, year, first_title_word)
    with library_lock(library_root):
        idx_path = _citekey_index_path(library_root)
        idx = json.loads(idx_path.read_text()) if idx_path.exists() else {}
        if base not in idx:
            key = base
        else:
            n = 2
            while f"{base}-{n}" in idx:
                n += 1
            key = f"{base}-{n}"
        idx[key] = True
        atomic_write_json(idx_path, idx)
    return key


# ---- opaque machine IDs ----

def gen_opaque_id(prefix: str = "") -> str:
    """Short, unguessable, never typed by a user (§3d)."""
    token = secrets.token_hex(6)
    return f"{prefix}{token}" if prefix else token
