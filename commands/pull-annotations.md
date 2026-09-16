Bring your highlights and margin notes for one paper from Papers.app into its
record (PLAN.md §7's "Annotation pull" bullet, §7b). Read-only, one-way:
Papers is the annotation source, never overwritten; `notes.md` (your own
free-text thoughts, `/ref:note`) is never touched by this command.

Parse `$ARGUMENTS` for:
- `<pmid>` — required. Must already exist (`/ref:add` first).

Steps:
1. Resolve the library root (fail loudly, pointing at `/ref:init`, if unconfigured).
2. Glob `~/Library/Application Support/Papers/*.db` and pass the first match as
   `--papers-db <path>`. If none exists, omit `--papers-db` — the command
   reports `no_papers_db_configured` rather than failing.
3. Print, then run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/pull_annotations.py" --repo <library_root> --pmid <pmid> [--papers-db <path>]
   ```
4. Print the script's own output verbatim. Statuses: `ok` (with `added`/
   `updated`/`tombstoned`/`unchanged` id lists — a repeat pull with no
   upstream changes reports everything as `unchanged`, never re-adds
   duplicates), `no_matching_papers_item` (this paper isn't in your Papers
   library — not an error), `snapshot_unavailable` (the live database
   couldn't be read — degrades cleanly, doesn't fail the command),
   `no_papers_db_configured`.

An annotation removed from Papers since the last pull is never silently
deleted locally — it is tombstoned (`deleted_upstream: true`) and kept for
audit, and its id appears in the `tombstoned` list so the loss is visible,
not silent.
