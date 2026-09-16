Print the stable inline `@citekey` for one paper, for use while writing (D14).

Parse `$ARGUMENTS` for:
- `<pmid>` — required.

Steps:
1. Resolve the library root.
2. Print, then run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/cite.py" --repo <library_root> --pmid <pmid>
   ```
3. Print the script's own output verbatim.
