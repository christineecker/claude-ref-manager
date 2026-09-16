Query confirmed authorship roles or derive a coauthor declaration (§3c).

Parse `$ARGUMENTS` for:
- `--person <id>` — required.
- `--role sole|first|last|middle|unresolved` — optional filter for the role-query form.
- `--coauthors --since <date> [--to <date>]` — collaborator-declaration form (NSF/NIH).

Steps:
1. Resolve the library root.
2. Print, then run the matching form:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/publications.py" --repo <library_root> --person <id> [--role <role>]
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/publications.py" --repo <library_root> --person <id> --coauthors --since <date> [--to <date>]
   ```
3. Print the script's own output verbatim. For `--coauthors`: group authors appear
   as the named group (never expanded), same-name unconfirmed candidates are listed
   separately from confirmed coauthors, and every incomplete-author-list paper in
   the window appears in the `gaps` list with its reason — none of this may be
   silently dropped when you summarize the result for the user.
