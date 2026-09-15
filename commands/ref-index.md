Rebuild `index/catalog.sqlite` from committed records (§3a). Idempotent; incomplete
staging directories are ignored.

Parse `$ARGUMENTS` for:
- `--rebuild` — required for now (the only supported mode in phase 0).

Steps:
1. Resolve the library root from `~/.config/ref-manager/config.json` (fail loudly,
   pointing at `/ref:init`, if it's missing).
2. Print, then run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/catalog.py" rebuild --repo <library_root>
   ```
3. Print the script's own output verbatim.
