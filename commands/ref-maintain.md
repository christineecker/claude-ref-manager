# /ref:maintain

Run a compact maintenance cycle in one command: status, lint, optional index
rebuild, and optional retraction audit. This is an orchestration wrapper; it
does not replace `/ref:status`, `/ref:lint`, `/ref:index`, or `/ref:audit`.

Parse `$ARGUMENTS` for:

- `--stale-days <N>` — optional, default `180`. Passed to `/ref:lint`.
- `--no-index` — skip the index rebuild stage.
- `--no-audit` — skip the retraction audit stage.
- `--verbosity quick|normal|verbose` — optional, default `quick`. Passed to
  `/ref:status`.

Steps:

1. Resolve the library root from `~/.config/ref-manager/config.json` (fail
   loudly, pointing at `/ref:init`, if unconfigured).
2. Print stage header `status:`, then run:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/status.py" --verbosity <level>
   ```

3. Print stage header `lint:`, then run:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/lint.py" run --repo <library_root> --stale-days <N> --snapshot
   ```

   `--snapshot` records this run's report under `<library_root>/maintenance/` so
   later `/ref:maintain` runs can be diffed against past state.

4. Unless `--no-index` is passed, print stage header `index:` and run:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/catalog.py" rebuild --repo <library_root>
   ```

   If `graph/relations.jsonl` exists, also run:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/relation.py" refresh --repo <library_root>
   ```

5. Unless `--no-audit` is passed, print stage header `audit:` and run the same
   retraction-status sweep as `/ref:audit` default mode for the whole library
   (or user-provided selector, if this wrapper is later extended with selector
   passthrough). Reuse `/ref:audit` logic exactly: call PubMed metadata for each
   PMID, normalize to retraction status results JSON, run `audit.py retraction`,
   then `audit.py propagate` when statuses changed.
6. Print a final `next:` section with 1-3 concrete follow-up commands based on
   lint/audit output, e.g. `/ref:fetch <pmid...>`, `/ref:extract <pmid...>`,
   `/ref:review --refresh ...`.

Suggested output shape:

```text
status:
...

lint:
...

index:
...

audit:
...

next:
- /ref:fetch ...
- /ref:extract ...
```

Notes:

- Keep each stage independent: one stage failing should still allow later
  read-only stages to run when safe.
- This wrapper is maintenance-oriented, so the default scope is whole-library.
- Do not fabricate citation counts. For citation observations, users still run
  `/ref:audit --citations` when a real count source is available.
