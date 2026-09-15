Manage grant/funding records — funder, award number, approved aliases, title, dates,
optional PI links, aims (§3c). Grant IDs are user-minted, library-global slugs (§3d).

Parse `$ARGUMENTS` for a subcommand:
- `create <slug> --funder "<name>" --award "<award number>" [--title "<text>"] [--pi <person-slug>] [--aims "<text>"]`
- `add-alias <slug> --alias "<award string>"` — funders often report the same award under
  several normalized/legacy strings (§3c); preserve each as an approved alias rather than
  overwriting.
- `show <slug>`
- `list`

Steps:
1. Resolve the library root (fail loudly, pointing at `/ref:init`, if unconfigured).
2. Print, then run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/grant.py" create --repo <library_root> --slug <slug> --funder "<name>" --award "<award>" [--title "<text>"] [--pi <slug>] [--aims "<text>"]
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/grant.py" add-alias --repo <library_root> --slug <slug> --alias "<award string>"
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/grant.py" show --repo <library_root> --slug <slug>
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/grant.py" list --repo <library_root>
   ```
3. Print the script's own output verbatim. A duplicate slug is refused naming the
   conflicting record.
