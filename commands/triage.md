# /ref:triage

Screen a saved PubMed search: open its Queries section, link it to a project, load
more metadata, or hand pending full-text work to Claude. One triage per saved search; re-runs
from `/ref:update-queries` merge into it.

In the Queries section, **Include** adds the paper to the library immediately.
**Exclude** never removes anything from the library. With a linked project,
every decision is also recorded in that project's screening log
(`/ref:screen`, feeding `/ref:review --prisma`, which uses linked triages as
its saved queries when `--query` is omitted).

With papers selected, reason chips in the action bar decide them with a
reason (keys 1-9 = the first nine exclusion reasons). Chips come from the
linked project (`/ref:project set-reasons`), or the defaults. **Copy export
command** gives `/ref:export-papers --triage <slug>` for the included papers.

Parse `$ARGUMENTS` for one form:

- `<slug>` — open the triage (creating it for an existing saved query if needed).
- `<slug> --project <project>` — link the triage to a project; every current
  decision is copied into the project's screening log. `--no-project` unlinks
  (the project's screening history is kept).
- `<slug> --more` — load metadata for the next 100 PMIDs, after asking.
- `apply <slug>` — fetch full text for the papers waiting for Claude.
- `list` — every triage with its project and progress.

Steps:

1. Resolve the library root (fail loudly, pointing at `/ref:init`, if unconfigured).

2. `<slug>` (open):
   a. If `triage/<slug>/triage.json` doesn't exist, print, then run:
      ```bash
      python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/triage.py" init --repo <library_root> --slug <slug>
      ```
      then load the first batch as in step 4b (no need to ask for the first 100).
   b. Otherwise print, then run `triage.py sync` (records runs added since last
      time) and `triage.py show`:
      ```bash
      python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/triage.py" sync --repo <library_root> --slug <slug>
      python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/triage.py" show --repo <library_root> --slug <slug>
      ```
   c. Start the dashboard in the background and print its launch URL line verbatim:
      ```bash
      python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/dashboard.py" serve --repo <library_root> --open --triage <slug>
      ```

3. `<slug> --project <project>` / `<slug> --no-project`: print, then run:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/triage.py" link --repo <library_root> --slug <slug> --project <project>
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/triage.py" link --repo <library_root> --slug <slug> --no-project
   ```
   Print the output verbatim (`replayed` = decisions copied into the project).

4. `<slug> --more`:
   a. Run `triage.py show` and tell the user how many are loaded / remaining.
      If nothing remains, say so and stop. Otherwise ask:
      "Load metadata for the next <min(100, remaining)> PMIDs from NCBI?"
      Stop unless the user says yes.
   b. Print, then run:
      ```bash
      python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/triage.py" load-batch --repo <library_root> --slug <slug>
      ```
      Print the output verbatim. An open Queries section picks the batch up on refresh.

5. `apply <slug>`:
   a. Print, then run:
      ```bash
      python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/triage.py" pending --repo <library_root> --slug <slug>
      ```
      If empty, say there's nothing waiting and stop.
   b. For the pending PMIDs, run the `/ref:fetch` workflow (same priority ladder:
      PMC E-utilities JATS, PubMed MCP plain text, Unpaywall, publisher HTML,
      otherwise abstract-only). Every pending PMID is already in the library.
   c. Write the PMIDs whose fetch result is final — anything except `failed`
      (so `abstract_only` counts: it means no source has full text) — to a temp
      JSON file, then print and run:
      ```bash
      python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/triage.py" clear-pending --repo <library_root> --slug <slug> --pmids-file <temp-file>
      ```
   d. Print the fetch output and the clear-pending output verbatim. `failed`
      PMIDs stay pending so a later `apply` retries them. An open Queries section
      updates by itself within a few seconds.

6. `list`: print, then run
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/triage.py" list --repo <library_root> [--project <project>]
   ```

Notes:
- Metadata comes from NCBI E-utilities `efetch` (stdlib HTTP, ≤3 requests/s, or
  10/s with `ncbi_api_key`). It needs `ncbi_email` (or `unpaywall_email`) in
  `~/.config/ref-manager/config.json`.
- Files: `triage/<slug>/triage.json`, `metadata/batch-NNNN.json`,
  `decisions.jsonl` (append-only, newest per PMID wins), `pending.json`.
  `queries/<slug>.yaml` is never modified.
- The dashboard's **Get PDFs** downloads PMC Open Access PDFs itself; papers
  without one are queued for `apply`.
