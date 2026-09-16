Show a one-line health state, what needs attention and what to run next, then catalog
counts, extraction-tier breakdown, source completeness, project summaries, and a few
recent papers. Read-only.

Parse `$ARGUMENTS` for:
- `--verbosity quick|normal|verbose` — optional, default `normal`. `quick` prints only
  the health header (state, needs attention, suggested next actions) — no breakdowns,
  no recent papers. `normal` is the full dashboard described below. `verbose` is the
  same dashboard with every project listed (not just the first 5) and up to 15 recent
  papers instead of 3.

Steps:
1. Print, then run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/status.py" [--verbosity <level>]
   ```
2. Print the script's own output verbatim. If it reports no library configured, tell the
   user to run `/ref:init <path>` first — don't guess a path.
3. The script leads with `status: <state>` (`healthy` / `empty` / `not indexed` /
   `needs metadata` / `needs full text` / `no active project`), a `needs attention` list,
   and up to three `suggested next actions` — all derived from the same counts it prints
   below, not a separate check. Keep the rest compact; the goal is to help the user orient
   quickly, not to replace full search. Recent papers should carry a concise source badge
   such as `full-text`, `pdf-backed`, `oa-pending`, `abstract-only`, or `metadata-only`.
