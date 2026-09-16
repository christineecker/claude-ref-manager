# /ref:project

Manage research projects — questions, membership, relevance, and reading state (§3b, D20).

Parse `$ARGUMENTS` for a subcommand:

- `create <slug> [--scope "<text>"] [--template <name>]` — `--template` stamps
  which proven command sequence this project follows (see below); it never
  invents scope text or research questions, those stay whatever you passed.
- `add-question <slug> --id <qid> --text "<text>"` — question IDs are unique only within
  their project (§3d); the same id string is fine in a different project.
- `add-paper <slug> <pmid> [--relevance "<text>"] [--priority N] [--reading-status to_screen|to_read|reading|read]`
  — a paper can belong to multiple projects; each project's membership record (relevance,
  priority, reading state) is independent of every other project's (§3b).
- `show <slug>`
- `list`
- `templates` — list the available `--template` names with a one-line description each.

Steps:

1. Resolve the library root (fail loudly, pointing at `/ref:init`, if unconfigured).
   `templates` is the one exception — it needs no library, print, then run:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/project.py" templates
   ```
2. Print, then run the matching form:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/project.py" create --repo <library_root> --slug <slug> [--scope "<text>"] [--template <name>]
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/project.py" add-question --repo <library_root> --slug <slug> --question-id <qid> --text "<text>"
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/project.py" add-paper --repo <library_root> --slug <slug> --pmid <pmid> [--relevance "<text>"] [--priority N] [--reading-status <state>]
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/project.py" show --repo <library_root> --slug <slug>
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/project.py" list --repo <library_root>
   ```

3. Print the script's own output verbatim. A duplicate slug is refused naming the
   conflicting project — don't retry with a suffix, tell the user to pick another name.
   When `--template` was passed, `create`'s output carries a `next_steps` list — the
   real command sequence for that workflow (from the matching tutorial), with `<slug>`
   already filled in. Print it after the project record so the user knows what to run
   next; the rest of `<pmid...>`/`<label>`/question text placeholders are still theirs
   to fill in.

`show` includes a summary with paper count, question count, reading-state
breakdown, and source/completeness counts, plus the project's linked triages
(saved PubMed searches screened with `/ref:triage`). `list` includes each project's paper
count, reading-state breakdown, and source/completeness counts so it can double
as a quick project dashboard.
