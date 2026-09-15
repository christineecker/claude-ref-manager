Full claim extraction for one or more already-added PMIDs (PLAN.md §4a). Unlike
`/ref:add`/`/ref:fetch`, this step needs real reading judgment (study-type
classification, PICO+ normalization) — it cannot be a deterministic script call, so
this command fans out one `ref-extractor` subagent per PMID instead of calling an
MCP tool.

Parse `$ARGUMENTS` for:
- `<pmid...>` — one or more PubMed IDs, required. Each must already have a
  `papers/<pmid>/meta.json` from `/ref:add`. Full text is not required — an
  abstract-tier paper extracts from its abstract (D4); this command never
  blocks on missing full text.

Steps:
1. Resolve the library root (fail loudly, pointing at `/ref:init`, if unconfigured).
2. For each PMID, read what's already committed:
   - `papers/<pmid>/meta.json` for `title`, and check `current.json` /
     `versions/<id>/source.md` for committed full text (from `/ref:fetch` or
     `/ref:attach`). If present, that's `full_text` for this PMID and
     `evidence_tier` is `"full"`.
   - Otherwise read `abstract_available`/the raw metadata response for the
     abstract, and `evidence_tier` is `"abstract"`.
3. **Spawn one subagent per PMID, in parallel** (use the Agent tool once per
   PMID in a single message so they run concurrently — per §4a: "fans out one
   `ref-extractor` agent invocation per PMID... each PMID commits its own
   version independently... one paper's extraction failure or missing full
   text does not block the others"). Use the prompt and output contract in
   `agents/ref-extractor.md` (read it — it's short and self-contained), giving
   each subagent that PMID's title/abstract/full_text. Each subagent returns
   the JSON object documented there: `{"pmid", "study_type",
   "study_type_confidence", "claims": [...]}`.
4. For each PMID's returned JSON, add two fields the subagent doesn't have
   access to and normalize into `extract.py`'s input envelope:
   ```json
   {
     "pmid": "<string>",
     "study_type": "<from the subagent>",
     "study_type_confidence": "<from the subagent>",
     "claims": [/* from the subagent, verbatim */],
     "evidence_tier": "abstract|full",
     "source_hash": "<sha256 of the source text you gave the subagent, for
                      provenance — hashlib.sha256(text.encode()).hexdigest()>",
     "retraction_status": {"status": "retracted|erratum|none|unknown",
                            "source": "pubmed", "checked_at": "<iso8601>"}
   }
   ```
   For `retraction_status`: call `mcp__claude_ai_PubMed__get_article_metadata`
   again for this PMID's `article_types` and check for a retraction/erratum/
   correction marker. If the call fails or the field is ambiguous, use
   `"status": "unknown"` — never report `"none"` unless the metadata
   genuinely says so (§4a: "failures yield unknown status", never a false
   negative).
5. Write the JSON array (one object per PMID) to a temp file, then print and run:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/ref-manager/scripts/extract.py" --repo <library_root> --input-file <temp-file> --extractor ref-extractor --model <the model you're running as> --prompt-version 1
   ```
6. Print the script's own output verbatim — one line per PMID
   (`extracted` / `failed`), each independent; one paper's malformed claims
   never block another's commit. A claim whose locator repeats a prior
   extraction's locator with materially different content supersedes the old
   claim (new `claim_id`, old one retained with `superseded_by` set, never
   deleted) — this is expected on a genuine re-extraction, not an error.
