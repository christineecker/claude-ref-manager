Answer a research question grounded in the library's evidence (PLAN.md §5). Unlike
`/ref:extract`'s one-subagent-per-paper fan-out, this spawns exactly ONE
`ref-synthesizer` subagent over the whole retrieved evidence set — synthesis needs
the full candidate list in one place to write a coherent grounded answer.

Parse `$ARGUMENTS` for:
- `<question>` — required, free text.
- an optional §5c selector (`--project`, `--query`, `--study`, `--search`,
  `--from-file`, or a bare `<pmid...>` list) to constrain retrieval to a specific
  set of papers before ranking. Omit it to search the whole library.

Steps:
1. Resolve the library root (fail loudly, pointing at `/ref:init`, if unconfigured).
2. **Query expansion** (§5's compensating mechanism for no embeddings, D3): think of
   2-4 MeSH terms, synonyms, or drug/gene aliases relevant to the question yourself
   — `ask_retrieve.py` cannot do this, it only ORs literal terms into an FTS5 match
   expression. Pass them as `--expand <term> <term> ...`.
3. Print, then run (`--q`, not `--question` — the selector grammar's `--question
   <qid>` flag, for scoping to a project question ID, already claims that name;
   see `lib_selector.py`):
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/ask_retrieve.py" --repo <library_root> --q "<question>" --expand <term...> [selector flags]
   ```
   This rebuilds the FTS catalog from committed claims/passages and returns
   `{"candidates": [...], "report": {...}}`. Print the `report` — it states
   truncation and insufficient-coverage explicitly; if `report.insufficient_coverage`
   is true, say so to the user plainly rather than proceeding to a padded-out
   synthesis call.
4. If there are candidates, spawn ONE subagent using the prompt/contract in
   `agents/ref-synthesizer.md` (read it), giving it the question and the full
   `candidates` list. It returns `{"answer", "coverage_note", "unresolved_questions"}`.
5. Write the returned `answer` text to a temp file, then print and run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/validate_citations.py" --answer-file <temp-file> --candidates-file <candidates-temp-file>
   ```
   Print its result. If `all_resolved` is false, tell the user which citations didn't
   resolve to supplied evidence — do not silently drop or "fix" them.
6. Present the answer, the coverage note, unresolved questions, and the evidence
   tier/retraction-status of what backed it. This command does not persist
   anything — for a saved, refreshable answer use `/ref:brief`, which wraps this
   same retrieval + synthesis + validation flow.
