Append your own free-text thoughts on a paper, or show what's there. `notes.md` is
authoritative user content (§3a) — no generated view ever overwrites it, and this is the
only command that writes to it.

Parse `$ARGUMENTS` for:
- `<pmid> <text>` — append `<text>` as a new dated entry.
- `<pmid> --show` — print the full notes file instead of appending.

Steps:
1. Resolve the library root (fail loudly, pointing at `/ref:init`, if unconfigured).
2. Print, then run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/note.py" append --repo <library_root> --pmid <pmid> --text "<text>"
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/note.py" show --repo <library_root> --pmid <pmid>
   ```
3. Print the script's own output verbatim.
