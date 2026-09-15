Manage `graph/concepts.jsonl` — stable concept nodes with accumulating aliases
(PLAN.md §3, §3d). A concept's primary key is a user-chosen slug specifically because
aliases accumulate onto it over time ("MI" and "myocardial infarction" both end up
pointing at one concept, not two).

Parse `$ARGUMENTS` for:
- `find "<name or alias>"` — look up an existing concept before minting a new one.
  **Always do this first** when a claim's normalized field (population/intervention/
  outcome/etc.) needs a concept mapping — never mint a new concept without checking.
- `create <slug> "<canonical name>"` — refused if `find` would already match this name.
- `add-alias <slug> "<alias>" [--source "claim:<pmid>:<claim_id>" | manual]` — refused
  if the alias already resolves to a *different* concept (that's a merge decision, not
  an automatic addition).
- `show <slug>` / `list`

Steps:
1. Resolve the library root (fail loudly, pointing at `/ref:init`, if unconfigured).
2. Run the matching subcommand:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/concept.py" find --repo <library_root> --name "<name>"
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/concept.py" create --repo <library_root> --id <slug> --name "<name>"
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/concept.py" add-alias --repo <library_root> --id <slug> --alias "<alias>" [--source "..."]
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/concept.py" show --repo <library_root> --id <slug>
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/concept.py" list --repo <library_root>
   ```
3. Print the script's own output verbatim.
