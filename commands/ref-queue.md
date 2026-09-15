Set or show a paper's reading state, priority, and why-saved note within a project (§3b —
reading state belongs to the project membership record, never set by acquisition or
model promotion).

Parse `$ARGUMENTS` for:
- `set --project <slug> --pmid <pmid> [--status to_screen|to_read|reading|read] [--priority N] [--why "<text>"]`
- `show --project <slug> [--pmid <pmid>]` — omit `--pmid` to list the whole project's queue.

Steps:
1. Resolve the library root (fail loudly, pointing at `/ref:init`, if unconfigured).
2. Print, then run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/queue.py" set --repo <library_root> --project <slug> --pmid <pmid> [--status <state>] [--priority N] [--why "<text>"]
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/queue.py" show --repo <library_root> --project <slug> [--pmid <pmid>]
   ```
3. Print the script's own output verbatim. `set` on a PMID that isn't yet a member of the
   project errors and points at `/ref:project add-paper` — add it to the project first.
