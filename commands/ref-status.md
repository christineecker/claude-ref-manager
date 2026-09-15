Show the configured library and catalog counts. Read-only.

No arguments.

Steps:
1. Print, then run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/status.py"
   ```
2. Print the script's own output verbatim. If it reports no library configured, tell the
   user to run `/ref:init <path>` first — don't guess a path.
