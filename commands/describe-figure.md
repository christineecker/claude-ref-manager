# /ref:describe-figure

Request a model description of one figure, selectively and cached (PLAN.md
D17, §3a). This never runs automatically for every figure. It is an explicit,
on-demand step, typically during promotion review or while answering a
specific question about a figure.

Parse `$ARGUMENTS` for:

- `<pmid> <figure-id>` - `<figure-id>` matches an `id` in that paper's
  current version's `figures.json` (see `/ref:fetch` output, or read
  `papers/<pmid>/versions/<version>/figures.json` directly).
- If no `<pmid>` is given at all: run

  ```bash
  python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/lib_selector.py" recent --repo <library_root> --limit 15
  ```

  and present the results via `AskUserQuestion` (multiSelect, one option per
  paper labeled `<title> (<citekey>, <year>)`) instead of asking the user to
  recall a PMID from memory. Once a paper is picked, print and run:

  ```bash
  python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/vision.py" list --repo <library_root> --pmid <pmid>
  ```

  so the user can choose from the current version's figure inventory (id +
  caption) rather than requiring the `<figure-id>` to already be known.
- `--model <name>` - optional, defaults to the calling model's own name.
- `--prompt <text>` - optional, defaults to a plain `describe this figure`
  prompt. Caching is keyed on the exact `(figure hash, model, prompt)`
  triple, so a different prompt is treated as a genuinely different request,
  not a cache hit.

Steps:

1. Resolve the library root (fail loudly, pointing at `/ref:init`, if unconfigured).
2. If the figure id is not yet known, run `vision.py list` first as above.
3. Print, then run:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/vision.py" request --repo <library_root> --pmid <pmid> --figure-id <figure-id> --model <model> --prompt <prompt>
   ```

4. Branch on `status`:

   - `cache_hit` - print the cached `vision.description` verbatim, labeled as
     a prior model interpretation, not the paper's own caption. Stop here.
   - `asset_unavailable` - the figure's image bytes were never fetched during
     conversion. Report this plainly; there is nothing to describe. Stop
     here.
   - `figure_not_found` - report the bad figure id. Stop here.
   - `needs_description` - look at the actual figure (its `source_locator`
     points at the asset; if it's not locally viewable, say so rather than
     guessing from the caption alone), write a genuine description of what the
     figure shows, then print and run:

     ```bash
     python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/vision.py" store --repo <library_root> --pmid <pmid> --figure-id <figure-id> --model <model> --prompt <prompt> --description "<your description>"
     ```

5. Present the description to the user labeled explicitly as a model
   interpretation of the figure, separate from and never substituting for the
   paper's own reported caption or findings (D17).
