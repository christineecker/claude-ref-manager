# ref-manager

Claude Code plugin for scientific reference management: acquire, extract, and
retrieve PMID-keyed papers into a personal library, with an OKF knowledge graph
over claims and concepts. Full design in [`PLAN.md`](PLAN.md).

Status: Phase 0 (scaffold, identifier contract, core schemas, atomic commit/lock/
rebuild machinery) — see `PLAN.md` §8 for the phase list.

## Quick start

```
/ref:init <path-to-library-root>
/ref:status
```

`/ref:init` records the library root in `~/.config/ref-manager/config.json` (D2);
every other command resolves it from there rather than taking `--repo`.
