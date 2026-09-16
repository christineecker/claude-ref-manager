---
name: ref-manager
description: "Scientific reference management — acquire, extract, and retrieve PMID-keyed papers into a personal library with an OKF knowledge graph. Use when the user wants to add/search/cite papers, manage a research project's reading list, compare evidence, or mentions '/ref:', PMID ingestion, or a paper library."
---

# ref-manager

Acquisition + extraction + retrieval engine for a PMID-keyed paper library.
The library scaffold, identifier contract, core record schemas, and the
atomic-commit / locking / rebuild machinery underpin every acquisition,
extraction, and synthesis command described below.

## Layout

The library root is chosen at `/ref:init` and recorded in
`~/.config/ref-manager/config.json` (D2) — never hardcoded.

## Scripts (`scripts/`)

| File | Purpose |
|---|---|
| `init_repo.py` | `/ref:init` — creates the library layout, writes the config file |
| `status.py` | `/ref:status` — reports the configured library and catalog counts |
| `catalog.py` | `index/catalog.sqlite` bootstrap + `rebuild` (§3a) |
| `lib_ids.py` | identifier contract (§3d): slugs, citekeys, opaque IDs |
| `lib_atomic.py` | atomic JSON/file writes, library/per-PMID locks, version-commit helper (§3a) |
| `lib_schema.py` | record-shape validators for config/meta/project/screening/claim/correction/study/person/grant |

Later phases add scripts alongside these; commands stay thin wrappers that resolve
`--repo` from the config file and call a script (see `commands/init.md` for the
house style).

## Read next

`commands/*.md` are the authoritative behavior spec for each `/ref:` command.
Read a command's `.md` before changing its script.
