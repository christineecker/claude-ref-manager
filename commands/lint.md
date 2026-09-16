# /ref:lint

Lint the paper library for maintenance gaps: incomplete metadata, abstract-only
papers, OA pending fetches, missing claim registries, stale status checks, and
missing or stale index DB. Read-only.

Parse `$ARGUMENTS` for:

- `--stale-days <N>` — optional, default `180`. Flags papers whose
  `meta.json.checked_at` is older than this threshold.
- `--json` — optional. Print full machine-readable JSON report.
- `--snapshot` — optional. Also write the report to
  `<library_root>/maintenance/<UTC-timestamp>.json` for later comparison.
- `--diff [snapshot]` — optional. Also report per-bucket added/removed PMIDs
  vs a prior snapshot under `<library_root>/maintenance/` (filename or
  stem). With no value, diffs against the most recent existing snapshot
  (sorted by filename, which is timestamp order). Errors loudly if no
  snapshot exists yet or the named one isn't found.

Steps:

1. Resolve the library root from `~/.config/ref-manager/config.json` (fail
   loudly, pointing at `/ref:init`, if unconfigured).
2. Print, then run:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/lint.py" run --repo <library_root> [--stale-days <N>] [--json] [--snapshot] [--diff [snapshot]]
   ```

3. Print the script output verbatim.

Output highlights:

- `missing_meta`, `malformed_meta`
- `missing_title`, `missing_year`, `missing_journal`, `missing_doi`
- `metadata_only`, `abstract_only`, `oa_pending`
- `missing_current`, `missing_claim_registry`
- `stale_retraction_check`
- `catalog_present`, `catalog_stale` (catalog fingerprint no longer matches the files)
- `recommendations` with direct next commands
- with `--diff`: `+pmid`/`-pmid` per bucket that changed since the compared snapshot

Suggested follow-up loop:

- `/ref:index --rebuild`
- `/ref:audit`
- `/ref:fetch <pmid...>` or `/ref:add-fetch <pmid...>`
- `/ref:extract <pmid...>`
