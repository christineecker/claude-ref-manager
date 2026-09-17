# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Atomic writes and locking (PLAN.md §3a).

"Write each version into a staging directory, validate it, then atomically
replace current.json. Write authoritative JSON updates with temporary files
and atomic replacement." / "Serialize mutations per PMID; use a library lock
for citekey allocation and graph commits."
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def now_iso() -> str:
    """UTC timestamp every record's created_at/checked_at/timestamp uses."""
    return datetime.now(timezone.utc).isoformat()


def now_stamp() -> str:
    """Filesystem-safe UTC stamp for snapshot/staging names."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def read_json(path: Path, default=None):
    """Parse a JSON file, or return `default` when it does not exist.
    Malformed JSON still raises -- callers that must tolerate it (viewers,
    lint) catch ValueError themselves."""
    return json.loads(path.read_text()) if path.exists() else default


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    text = "\n".join(json.dumps(r, sort_keys=True) for r in rows)
    atomic_write_text(path, text + "\n" if rows else text)


def current_version(paper_dir: Path) -> str | None:
    """The version id papers/<pmid>/current.json points at, or None."""
    obj = read_json(paper_dir / "current.json")
    return obj.get("version") if isinstance(obj, dict) else None


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)  # atomic on same filesystem
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def atomic_write_json(path: Path, obj) -> None:
    atomic_write_text(path, json.dumps(obj, indent=2, sort_keys=True) + "\n")


@contextlib.contextmanager
def _flock(lock_path: Path):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def library_lock(library_root: Path):
    """Library-wide lock: citekey allocation, slug registries, graph commits."""
    return _flock(library_root / "index" / ".library.lock")


def catalog_lock(library_root: Path):
    """Serializes catalog rebuilds. Separate from library_lock so a caller
    already holding the library lock can still trigger a rebuild."""
    return _flock(library_root / "index" / ".catalog.lock")


def pmid_lock(library_root: Path, pmid: str):
    """Per-PMID lock: one paper's stage commits are serialized against
    themselves, but independent of every other paper's (§4, batch commands
    report per-PMID results, one failure never blocks the rest)."""
    return _flock(library_root / "index" / ".locks" / f"{pmid}.lock")


def project_lock(library_root: Path, slug: str):
    """Per-project lock: serializes read-modify-write of a project's
    papers.yaml (screen.decide) now that the threaded dashboard server can
    record decisions concurrently."""
    return _flock(library_root / "index" / ".locks" / f"project-{slug}.lock")


def triage_lock(library_root: Path, slug: str):
    """Per-triage lock: every write under triage/<slug>/. Lock order is
    always pmid -> project -> triage."""
    return _flock(library_root / "index" / ".locks" / f"triage-{slug}.lock")


def commit_version(paper_dir: Path, version_id: str, write_fn) -> Path:
    """Write a new version into a staging dir, call write_fn(staging_dir) to
    populate it, then atomically point current.json at it. write_fn must
    raise to abort — nothing is promoted until it returns cleanly."""
    versions_dir = paper_dir / "versions"
    staging = versions_dir / f".staging-{version_id}"
    final = versions_dir / version_id
    staging.mkdir(parents=True, exist_ok=False)
    try:
        write_fn(staging)
        os.replace(staging, final)  # atomic rename, same filesystem
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            import shutil

            shutil.rmtree(staging, ignore_errors=True)
        raise
    atomic_write_json(paper_dir / "current.json", {"version": version_id})
    return final
