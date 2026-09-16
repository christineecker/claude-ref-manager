Rebuild `index/catalog.sqlite` from committed records (§3a), and recompute graph edge
staleness (phase 8, §3a: "Re-extraction invalidates affected evidence links and triggers
an incremental graph refresh"). Idempotent; incomplete staging directories are ignored.

The rebuild writes to a temp file under `index/.catalog.lock` and atomically replaces
`catalog.sqlite`, so a failed or concurrent rebuild never leaves a partial catalog. It
records a fingerprint (path, size, mtime of every `meta.json`, `current.json`,
`claim_registry.json`, and current `source.md`) in `catalog_meta`; `/ref:status` and
`/ref:lint` compare it against the files on disk and report the catalog as stale when
anything changed since the last rebuild.

Parse `$ARGUMENTS` for:
- `--rebuild` — required for now (the only supported mode).

Steps:
1. Resolve the library root from `~/.config/ref-manager/config.json` (fail loudly,
   pointing at `/ref:init`, if it's missing).
2. Print, then run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/catalog.py" rebuild --repo <library_root>
   ```
3. If `graph/relations.jsonl` exists, also print and run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/relation.py" refresh --repo <library_root>
   ```
   This flips `stale: true` on any relation whose supporting evidence was superseded
   or excluded since the last refresh — it never clears a review decision, only flags
   it for re-confirmation. Report which relation IDs went stale, if any.
4. Print both scripts' output verbatim.
