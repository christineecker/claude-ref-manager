Attach one or more local PDFs you've already acquired to existing PMID records
(PLAN.md §6 opening paragraph).

Parse `$ARGUMENTS` for:
- `<pmid> <path> [<pmid> <path> ...]` — one or more pairs, required. Each PMID
  must already have a `papers/<pmid>/meta.json` (from `/ref:add`).
- `--force` — attach even if the identity check below fails; refused otherwise.

Steps:
1. Resolve the library root (fail loudly, pointing at `/ref:init`, if unconfigured).
2. Print, then run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/attach.py" --repo <library_root> [--force] <pmid1> <path1> [<pmid2> <path2> ...]
   ```
3. Print the script's own output verbatim. Per pair: `attached` / `duplicate_noop`
   (identical bytes already stored) / `refused` (identity check failed — the DOI
   and a run of the title text were both absent from the PDF's first two pages;
   named so you can resolve it, e.g. re-run with `--force` if you're sure it's
   right) / `failed` (bad path or missing record). One pair's conflict or failure
   never blocks the rest. Print any `diagnostic:` lines — these flag PDF
   conversion status (anydoc availability).
