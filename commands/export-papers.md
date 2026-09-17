Export selected papers into a folder Papers.app imports from (PLAN.md §7a, D28).
One-way, file-based handoff — never writes the live Papers database.

`--triage <slug>` exports the papers included while screening that saved search
(`--triage <slug> --screened excluded|pending` for the other decisions; only
papers that are in the library). The Triage tab's **Copy export command** button
gives this command.

Parse `$ARGUMENTS` for the §5c selector (`<pmid...>`, `--project`, `--question`,
`--screened`, `--read`/`--queue`, `--query`/`--run`, `--triage`, `--search`, `--from-file`,
`--tier`, `--exclude`) plus:
- `--to <dir>` — destination; defaults to `papers_export_dir` in
  `~/.config/ref-manager/config.json`, else a self-contained
  `exports/papers/<batch>/` and says so.
- `--layout papers|flat` — `papers` mirrors `<LastAuthor>/<Journal>-<Year>.pdf`
  (default when writing into the configured folder); `flat` writes
  `<citekey>.pdf` (default otherwise).
- `--pdfs copy|link|none` (default `copy`).
- `--notes[=force]` / `--tags <a,b>` / `--tags-from <project-slug>` — push
  `notes.md` and tags into Papers' own `note`/`keywords` BibTeX fields (§7b).
  `--notes` alone refuses a paper whose note was already pushed by a prior
  export; `--notes=force` overwrites.
- `--skip-known` / `--force` — duplicate handling against a read-only snapshot
  of the live Papers library.
- `--collection <name>` — records an intended collection name in the manifest
  only; never creates a Papers collection.
- `--dry-run` — prints the plan, touches nothing.
- `--refresh` — re-resolve the selector even if a manifest already exists at
  the destination.
- `--batch <label>` — optional label for the fallback `exports/papers/<batch>/`
  destination.

Steps:
1. Resolve the library root from `~/.config/ref-manager/config.json` (fail
   loudly, pointing at `/ref:init`, if missing).
2. Find the real Papers.app database for duplicate detection: glob
   `~/Library/Application Support/Papers/*.db` and pass the first match as
   `--papers-db <path>`. If none exists, omit `--papers-db` — the export still
   proceeds, just without duplicate detection (this is expected, not an
   error).
3. Print, then run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/export_papers.py" \
     [selector args] --repo <library_root> [--to <dir>] [--layout papers|flat] \
     [--pdfs copy|link|none] [--notes] [--notes-force] [--tags <a,b>] \
     [--tags-from <slug>] [--skip-known] [--force] [--collection <name>] \
     [--dry-run] [--refresh] [--batch <label>] [--papers-db <path>]
   ```
4. Print the script's output verbatim: destination, manifest (selector
   resolution, per-paper PDF paths, missing PDFs, already-known duplicates,
   field omissions, foreign-path conflicts, note-push status), and the
   import instruction — "import `references.bib` through Papers' own UI; this
   command does not drive the app."

The command never opens Papers, never writes its database, and never
overwrites a file at the destination that isn't recorded in a prior
ref-manager manifest — such a path is reported as a foreign conflict instead.
