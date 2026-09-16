Open the live PDF+notes reading viewer for one or more already-fetched
papers.

Parse `$ARGUMENTS` for:
- `<pmid...>` — one or more PubMed IDs. Each must already exist and have a
  real PDF on file (`raw/<hash>/source.pdf` from `/ref:fetch-pdf` or
  `/ref:attach`).
- `--port <n>` — fixed port for the local server instead of an OS-assigned
  ephemeral one. Default is `0` (ephemeral).
- `--no-open` — print the reader URL(s) instead of opening a browser tab
  automatically.

Steps:
1. Resolve the library root (fail loudly, pointing at `/ref:init`, if
   unconfigured).
2. Print, then run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/read_article.py" --repo <library_root> [--port <n>] [--no-open] <pmid...>
   ```
3. Print the script's own output verbatim. Per PMID:
   - `ready` — has a PDF; a browser tab opens (unless `--no-open`) straight
     into that paper's drawer with the PDF tab active.
   - `no_pdf` — the paper exists but has no PDF on file; point at
     `/ref:fetch-pdf` or `/ref:attach`.
   - `failed` — no such paper; point at `/ref:add`.

Notes:
- This reuses the `/ref:dashboard serve` viewer (pdf.js canvas, page
  nav/zoom, notes composer that writes straight to `notes.md` via
  `note.py append()`, loopback-only with per-run token auth) rather than a
  separate reader — `?paper=<pmid>&tab=pdf` just deep-links into it. There
  is no separate reading reconstruction of converted text anymore; a paper
  with only `source.md` and no PDF is `no_pdf`, not a fallback render.
- The command blocks in the foreground serving the library over
  `127.0.0.1` (same as `/ref:dashboard serve`) until interrupted (Ctrl-C).
  Requesting multiple pmids opens one browser tab per paper against the
  same server.
- A note taken while reading page N of the PDF is tagged with that page
  number; clicking it later jumps the viewer back to that page.
