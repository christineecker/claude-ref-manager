Manage researcher identity records — name variants, ORCID, affiliation history,
confirmed/candidate publication matches (§3c). Person IDs are user-minted, library-global
slugs (§3d); name similarity alone never establishes identity.

Parse `$ARGUMENTS` for a subcommand:
- `create <slug> --name "<Last, First>" [--orcid <id>]`
- `show <slug>`
- `list`

Steps:
1. Resolve the library root (fail loudly, pointing at `/ref:init`, if unconfigured).
2. Print, then run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/person.py" create --repo <library_root> --slug <slug> --name "<name>" [--orcid <id>]
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/person.py" show --repo <library_root> --slug <slug>
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/person.py" list --repo <library_root>
   ```
3. Print the script's own output verbatim. A duplicate slug is refused naming the
   conflicting record — pick another slug, don't overwrite.
