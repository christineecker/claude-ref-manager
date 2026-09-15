Persist a research answer and its evidence snapshot (PLAN.md §5a, D9: explicit
refresh only, no scheduled monitoring or automatic ingestion).

Parse `$ARGUMENTS` for:
- `<question>` — required on first save.
- `--key <label>` — required: a human-chosen name for this recurring brief (a
  project can hold many distinct saved questions). Not the same as the opaque
  snapshot ID minted on every save — see `brief.py`'s module docstring.
- `--project <slug>` — optional; omit for a library-wide brief.
- an optional §5c selector to constrain retrieval, same as `/ref:ask`.
- `--refresh` — re-run retrieval + synthesis and report the diff instead of
  reusing the frozen snapshot.
- `--show` — print the current frozen brief without re-running anything.
- `--edit <text>` — attach a user revision to the current snapshot (survives a
  refresh whose evidence didn't change for it; flagged stale otherwise).

Steps:
1. Resolve the library root.
2. `--show`: run
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/brief.py" show --repo <library_root> --key <key> [--project <slug>]
   ```
   print the result verbatim, stop.
3. `--edit <text>`: write `<text>` to a temp file, run
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/brief.py" edit --repo <library_root> --key <key> [--project <slug>] --revision-file <temp-file>
   ```
   print the result, stop.
4. Otherwise (save or `--refresh`): run this exact same retrieval + synthesis +
   validation sequence `/ref:ask` uses (steps 2-5 of `commands/ref-ask.md` —
   query expansion, `ask_retrieve.py`, the `ref-synthesizer` subagent,
   `validate_citations.py`). Write the returned candidates JSON and the
   selector resolution (if any) to temp files too.
5. Print, then run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/brief.py" save --repo <library_root> --key <key> [--project <slug>] --question "<question>" --answer-file <answer-temp-file> --evidence-file <candidates-temp-file> [--resolution-file <resolution-temp-file>] [--unresolved <q1> <q2> ...] [--refresh]
   ```
6. Print the script's own output verbatim. On a refresh, it reports
   `added_support_claim_ids`, `new_pmids`, and `withdrawn_evidence` (claims that
   backed the prior answer but are no longer active/were rejected via
   `/ref:verify` since the last brief) — present these to the user as the change
   summary; never silently overwrite the prior answer without them. A user's
   `--edit` revision survives a refresh whose underlying evidence is unchanged,
   and is reported `"stale": true` (not discarded) when the evidence changed.
