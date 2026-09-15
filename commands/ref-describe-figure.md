Request a model description of one figure, selectively and cached (PLAN.md
D17, §3a). Never runs automatically for every figure — an explicit,
on-demand step, typically during promotion review or while answering a
specific question about a figure.

Parse `$ARGUMENTS` for:
- `<pmid> <figure-id>` — `<figure-id>` matches an `id` in that paper's
  current version's `figures.json` (see `/ref:fetch`'s output, or read
  `papers/<pmid>/versions/<version>/figures.json` directly).
- If no `<pmid>` is given at all: run
  ```
  python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/lib_selector.py" recent --repo <library_root> --limit 15
  ```
  and present the results via `AskUserQuestion` (multiSelect, one option per
  paper labeled `<title> (<citekey>, <year>)`) instead of asking the user to
  recall a PMID from memory. Once a paper is picked, list that version's
  `figures.json` entries (id + caption) so the user can pick `<figure-id>`
  too, rather than requiring it to already be known.
- `--model <name>` — optional, defaults to the calling model's own name.
- `--prompt <text>` — optional, defaults to a plain "describe this figure"
  prompt. Caching is keyed on the exact `(figure hash, model, prompt)`
  triple — a different prompt is treated as a genuinely different request,
  not a cache hit.

Steps:
1. Resolve the library root (fail loudly, pointing at `/ref:init`, if unconfigured).
2. Print, then run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/vision.py" request --repo <library_root> --pmid <pmid> --figure-id <figure-id> --model <model> --prompt <prompt>
   ```
3. Branch on `status`:
   - `cache_hit` — print the cached `vision.description` verbatim, labeled as
     a prior model interpretation (not the paper's own caption). Stop here.
   - `asset_unavailable` — the figure's image bytes were never fetched
     during conversion (common — JATS/HTML conversion records figure
     locators, not bytes). Report this plainly; there is nothing to
     describe. Stop here.
   - `figure_not_found` — report the bad figure id. Stop here.
   - `needs_description` — look at the actual figure (its `source_locator`
     points at the asset; if it's not locally viewable, say so rather than
     guessing from the caption alone), write a genuine description of what
     the figure shows, then print and run:
     ```
     python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/vision.py" store --repo <library_root> --pmid <pmid> --figure-id <figure-id> --model <model> --prompt <prompt> --description "<your description>"
     ```
4. Present the description to the user labeled explicitly as a model
   interpretation of the figure, separate from and never substituting for
   the paper's own reported caption or findings (D17).
