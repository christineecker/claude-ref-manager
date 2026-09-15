Show the configured library, catalog counts, extraction-tier breakdown, source
completeness, project summaries, and a few recent papers. Read-only.

No arguments.

Steps:
1. Print, then run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/status.py"
   ```
2. Print the script's own output verbatim. If it reports no library configured, tell the
   user to run `/ref:init <path>` first — don't guess a path.
3. If the dashboard shows recent papers, source/completeness counts, or project
   summaries, keep the output compact and readable; the goal is to help the
   user orient quickly, not to replace full search. Recent papers should carry
   a concise source badge such as `full-text`, `pdf-backed`, `oa-pending`,
   `abstract-only`, or `metadata-only`.
