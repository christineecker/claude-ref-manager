Record a human review decision — accept/edit/reject a claim, link/unlink a grant,
flag an author contribution, or confirm/reject a researcher identity match — as an
authoritative correction overlay (PLAN.md §3b, §3c closing line). All five target
types share one `corrections.json` record shape and the same persistence rules:
decisions survive an unchanged re-extraction, but flip to `pending_review` (never
silently reapplied or dropped) when the evidence they reference materially changes.

Parse `$ARGUMENTS` for the review kind and its fields:
- `claim <pmid> <claim_id> accept|edit|reject [--replacement <json-file>] [--rationale "..."] [--reviewer "..."]`
- `grant-link <pmid> <grant-slug> accept|reject --evidence-locator "..." [--award-number "..."] [--rationale "..."] [--reviewer "..."]`
- `author-contribution <pmid> <author_index> shared_first|shared_senior|corresponding --evidence "<explicit statement>" [--reviewer "..."]`
- `person-identity <pmid> <person-slug> <author_index> accept|reject [--rationale "..."] [--reviewer "..."]`
- `show <pmid>` — print all corrections on file for this paper (this also
  revalidates them against the current claim registry first, so a claim that
  was superseded since the last check shows up as `pending_review`).

Steps:
1. Resolve the library root (fail loudly, pointing at `/ref:init`, if unconfigured).
2. Run the matching subcommand:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/verify.py" review-claim --repo <library_root> --pmid <pmid> --claim-id <id> --decision <accept|edit|reject> [--replacement-file <path>] [--rationale "..."] [--reviewer "..."]
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/verify.py" review-grant-link --repo <library_root> --pmid <pmid> --grant <slug> --decision <accept|reject> --evidence-locator "..." [--award-number "..."] [--rationale "..."] [--reviewer "..."]
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/verify.py" review-author-contribution --repo <library_root> --pmid <pmid> --author-index <N> --flag <shared_first|shared_senior|corresponding> --evidence-statement "..." [--reviewer "..."]
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/verify.py" review-person-identity --repo <library_root> --pmid <pmid> --person <slug> --author-index <N> --decision <accept|reject> [--rationale "..."] [--reviewer "..."]
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/verify.py" show --repo <library_root> --pmid <pmid>
   ```
3. Print the script's output verbatim.

Notes:
- `author-contribution` **refuses without `--evidence-statement`**, by
  design (§3c): shared-first/shared-senior/corresponding authorship is
  never inferred from author position, only from an explicit statement you
  provide (e.g. a quoted "these authors contributed equally" note from the
  paper).
- `grant-link` records the link but never folds a new award number into
  the grant's approved aliases automatically — normalization that could
  collapse two genuinely distinct awards under one funder requires a
  separate, deliberate `/ref:grant add-alias` call, never this command
  (§3c: "must not collapse distinct awards or award periods without a
  reviewed rule").
- `person-identity` delegates to the same `/ref:person confirm-publication`/
  `reject-publication` machinery `/ref:discover` already uses — this
  command just also logs the decision as a correction record for audit
  symmetry with the other review kinds.
