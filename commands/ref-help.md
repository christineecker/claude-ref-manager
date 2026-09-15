Quick-start tour: list every `/ref:*` command grouped by what it's for, or show
one command's full spec without leaving the terminal. Read-only, no library
required.

Parse `$ARGUMENTS` for:
- Nothing — print the grouped overview below.
- `<command>` — the bare command name with or without its `ref-`/`/ref:` prefix
  (`status`, `ref-status`, `/ref:status` all mean the same thing) — print that
  command's own spec.

Steps:

1. If `$ARGUMENTS` is empty:
   - Check whether a library is configured (`~/.config/ref-manager/config.json`).
     If not, lead with: run `/ref:init <path>` first, then come back here.
   - Print the grouped overview verbatim (below), substituting nothing — every
     line is a real command and a real one-line description, not a summary
     Claude writes fresh each time.
   - If a library *is* configured, close with: run `/ref:status` next for a
     health check and concrete next actions.
2. If `$ARGUMENTS` names one command:
   - Resolve it to `commands/ref-<name>.md` (strip a leading `/ref:` or `ref-`
     if given). If no such file exists, say so and suggest the closest matches
     by name, or point at the grouped overview instead of guessing.
   - Read and print that file's content — it's already the authoritative,
     terse spec for that command (arguments, steps, safety notes). Don't
     paraphrase or shorten it; the whole point is showing the real spec.

## Grouped overview

**Bring papers in**
- `/ref:init <path>` — create a library where you choose and record it in the config file
- `/ref:add <pmid...>` — core ingest path: resolve metadata via PubMed, dedupe by PMID, allocate a stable citekey
- `/ref:add-pdf <path...>` — identify PDFs by DOI/PMID clues, add PubMed records, then attach the files
- `/ref:add-fetch <pmid...>` — convenience wrapper: add missing records, then fetch full text for records that exist
- `/ref:add-url <url...>` — identify articles by URL (DOI/PMID/PMCID clues or page metadata), add records, then fetch
- `/ref:import <item...>` — source-aware front door: routes a mix of PMIDs, URLs, PDFs/folders, DOIs, or BibTeX/CSL-JSON into add/fetch/attach
- `/ref:fetch <pmid...>` — acquire full text in priority order and convert it to `source.md`, per-PMID results
- `/ref:fetch-pdf <pmid...>` — download free PMC OA PDFs and attach them through the PDF pipeline
- `/ref:attach <pmid> <path>...` — attach PDFs you already have, after an identity check
- `/ref:read <pmid...>` — render a local HTML reading copy from the current full-text version and figures
- `/ref:extract <pmid...>` — full claim extraction, one ref-extractor subagent per paper
- `/ref:describe-figure <pmid> <figure-id>` — on-demand, cached model description of one figure

**Find**
- `/ref:search` — search the library's evidence, or your personal notes, with distinct labels
- `/ref:ask <question>` — retrieve evidence and write one grounded answer with `[^pmid]` citations
- `/ref:pubmed-query <question>` — translate a prompt or PICO into a PubMed query without running it
- `/ref:search-pubmed` — turn a question into a PubMed query and save the run immutably
- `/ref:search-add-fetch` — search PubMed, save the run, add selected PMIDs, then fetch full text
- `/ref:update-queries <slug>` — manually re-run a saved query and append a new run
- `/ref:related <pmid>` — snowball backward through references and forward via PubMed

**Organize & review**
- `/ref:project` — projects, questions, membership, and relevance; `--template` starts one from a proven workflow
- `/ref:queue` — reading state, priority, and why-saved notes within a project
- `/ref:screen` — record a project-specific include/exclude/pending decision with a reason
- `/ref:note <pmid>` — append your own dated notes to `notes.md`
- `/ref:verify` — accept, edit, or reject claims, identity matches, and grant links as overlays
- `/ref:study` — group publications into studies; record datasets and methods

**Write & compare**
- `/ref:compare <selector>` — evidence matrix with source-linked cells
- `/ref:methods <selector>` — protocols, instruments, datasets, and software with locators
- `/ref:summarize <selector>` — prose narrative across a set, or a single paper
- `/ref:review` — appraised synthesis, or `--prisma` flow record for a project's search
- `/ref:check-citations` — check a paragraph's assertions against library evidence
- `/ref:brief` — save an answer and its evidence snapshot; refresh explicitly
- `/ref:cite <pmid>` — print the stable `@citekey`
- `/ref:export <selector>` — BibTeX and CSL-JSON for a frozen set
- `/ref:export-papers <selector>` — Papers-dialect BibTeX plus PDF copies for import into Papers.app

**Explore the graph**
- `/ref:weave` — build and review concepts and relations, regenerate OKF views
- `/ref:concept` — find, create, and alias concept nodes
- `/ref:gaps <selector>` — fragile single-study claims, open conflicts, coverage gaps
- `/ref:hypothesize --concept <slug>` — Swanson ABC candidates, each checked against PubMed

**People, grants & reports**
- `/ref:person` — researcher identity: name variants, ORCID, matches
- `/ref:publications --person <id>` — authorship roles, or a coauthor declaration for a window
- `/ref:grant` — funders, awards, aliases, and publication links
- `/ref:discover --person <id>` — explicit PubMed search for portfolio candidates
- `/ref:report --person <id>` — reproducible publication report for a date window

**Maintain**
- `/ref:audit` — re-check retraction/errata status; `--citations` records dated PMC cited-by counts
- `/ref:index --rebuild` — rebuild `catalog.sqlite` from committed records
- `/ref:status` — one-line health state, what needs attention, and what to run next
- `/ref:open <pmid>` — open the acquired PDF in Papers.app
- `/ref:pull-annotations <pmid>` — import your Papers highlights and margin notes, read-only

Commands that work on a set of papers share one selector grammar (`<pmid...>`,
`--project`, `--query`, `--study`, `--search`, `--from-file`, refined by
`--tier`/`--exclude`) — see `docs/commands/find.html#selectors` for the full
grammar, or `/ref:help <any-selector-command>` for one command's own arg list.

New here? Run `/ref:init <path>`, then `/ref:add <pmid>`, then `/ref:status`.
