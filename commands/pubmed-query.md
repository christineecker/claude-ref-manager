Translate a natural-language research prompt or PICO into a PubMed query, but
do not run the search.

Parse `$ARGUMENTS` for:
- `<question or PICO>` — required. Can be prose or explicit P/I/C/O lines.
- `--broad` — favor sensitivity: more synonyms, fewer restrictive filters.
- `--specific` — favor precision: tighter terms and optional study-design
  filters when the prompt implies them.

Steps:
1. Read the user's prompt and identify concepts: population/problem,
   intervention/exposure, comparator, outcome, study design, date, language,
   species, age group, and named author constraints when present.
2. Produce a PubMed Boolean query using:
   - MeSH terms when stable and obvious, combined with free-text `[tiab]`
     synonyms.
   - Date ranges with `[dp]`, for example
     `("2021/01/01"[dp] : "3000"[dp])`.
   - Publication types such as `randomized controlled trial[pt]` only when the
     prompt requests that design or `--specific` makes it appropriate.
   - Author filters such as `Lastname Initial[au]`; use `Lastname Initial[1au]`
     only for explicit first-author requests. Do not pretend standard PubMed
     has a reliable last-author-only field.
3. Print:
   - `query:` with the final PubMed expression.
   - `strategy:` one concise paragraph explaining broad/specific choices.
   - `notes:` limitations or likely follow-up filters, especially when an
     author-position, age, outcome, or date constraint is approximate.
4. Do not call PubMed MCP, do not write files, and do not add papers. Point the
   user to `/ref:search-pubmed "<query>" --slug <slug> --create` to run and
   save it.

Output example:
```text
query:
(("Autism Spectrum Disorder"[Mesh] OR autism[tiab] OR autistic[tiab])
 AND ("transcranial direct current stimulation"[tiab] OR tDCS[tiab])
 AND (sham[tiab] OR placebo[tiab])
 AND ("social cognition"[tiab] OR "theory of mind"[tiab]))

strategy:
Sensitive PICO translation with MeSH/free-text population terms and outcome
synonyms kept in title/abstract fields.

notes:
Run with /ref:search-pubmed when ready.
```
