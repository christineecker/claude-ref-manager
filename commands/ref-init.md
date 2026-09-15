Initialize a ref-manager library at a location you choose (D2 — the plugin never
hardcodes a location).

Parse `$ARGUMENTS` for:
- `<path>` — required, positional. Where the library is created.
- `--force` — reconfigure even if a library is already recorded.

If `<path>` is missing, ask for it rather than guessing.

Steps:
1. Print, then run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/init_repo.py" <path> [--force]
   ```
2. Report the library root created and that `--repo` is no longer needed — every other
   `/ref:*` command resolves the active library from `~/.config/ref-manager/config.json`.

This library is the prerequisite for every other `/ref:*` command; they fail loudly if
no library is configured yet.
