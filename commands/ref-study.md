Manage study/dataset/method records (PLAN.md §3b, §3d, D22). A study is an
explicit, evidenced GROUPING of PMIDs believed to report the same underlying
investigation — never inferred from shared authors or a shared dataset alone.

Parse `$ARGUMENTS`:
- `create-study <study-id> --pmid <pmid...> --confidence confirmed|likely|uncertain --evidence "<why these are the same investigation>"`
- `create-dataset <dataset-id> --name "<display name>" [--pmid <pmid...>] [--notes "..."]`
- `create-method <method-id> --name "<display name>" [--pmid <pmid...>] [--context "..."] [--locator "..."]`
- `list-studies` / `list-datasets` / `list-methods`

Steps:
1. Resolve the library root (fail loudly, pointing at `/ref:init`, if unconfigured).
2. Run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/study.py" create-study --repo <library_root> --id <study-id> --pmid <pmid...> --confidence <c> --evidence "<text>"
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/study.py" create-dataset --repo <library_root> --id <dataset-id> --name "<name>" [--pmid <pmid...>] [--notes "..."]
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/study.py" create-method --repo <library_root> --id <method-id> --name "<name>" [--pmid <pmid...>] [--context "..."] [--locator "..."]
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/study.py" list-studies --repo <library_root>
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/study.py" list-datasets --repo <library_root>
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/study.py" list-methods --repo <library_root>
   ```
3. Print the script's output verbatim.

Notes:
- `create-study` **refuses without `--evidence`** — a study grouping must
  state why these PMIDs are believed to be the same investigation (a shared
  trial registration number, an explicit "we previously reported..."
  cross-reference), never asserted from coincidence.
- Dataset reuse is a separate relationship from study identity: two papers
  linked to the same `create-dataset` record are NOT thereby grouped as one
  study. Only `create-study` groups papers; use it deliberately.
- Study/dataset/method IDs are library-global user-minted slugs (§3d) — a
  colliding ID is refused, naming the conflicting record, never silently
  suffixed.
