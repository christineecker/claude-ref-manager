#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# ///
"""Regenerate the README change log from git history.

Replaces everything between the changelog markers in README.md with the
latest non-merge commits. Exits 0 whether or not the file changed.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"
START, END = "<!-- changelog:start -->", "<!-- changelog:end -->"
LIMIT = int(os.environ.get("README_LOG_LIMIT", "15"))


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True,
                          capture_output=True, text=True).stdout.strip()


def repo_url() -> str | None:
    if slug := os.environ.get("GITHUB_REPOSITORY"):
        return f"https://github.com/{slug}"
    try:
        remote = git("remote", "get-url", "origin")
    except subprocess.CalledProcessError:
        return None
    m = re.search(r"github\.com[:/](.+?)(?:\.git)?$", remote)
    return f"https://github.com/{m.group(1)}" if m else None


def render() -> str:
    log = git("log", "--no-merges", f"-n{LIMIT}", "--date=short",
              "--invert-grep", "--grep=update README change log",
              "--pretty=format:%ad%x09%h%x09%s")
    url = repo_url()
    lines = []
    for row in log.splitlines():
        date, sha, subject = row.split("\t", 2)
        ref = f"[`{sha}`]({url}/commit/{sha})" if url else f"`{sha}`"
        lines.append(f"- {date} · {ref} {subject}")
    return "\n".join(lines)


def main() -> int:
    text = README.read_text(encoding="utf-8")
    if START not in text or END not in text:
        print(f"error: {README.name} lacks {START} / {END} markers", file=sys.stderr)
        return 1
    head, rest = text.split(START, 1)
    _, tail = rest.split(END, 1)
    new = f"{head}{START}\n{render()}\n{END}{tail}"
    if new != text:
        README.write_text(new, encoding="utf-8")
        print("README change log updated")
    else:
        print("README change log already current")
    return 0


if __name__ == "__main__":
    sys.exit(main())
