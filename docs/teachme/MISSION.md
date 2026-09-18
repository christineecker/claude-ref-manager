# Mission: Maintaining the claude-ref-manager paper repo

## Why
Two goals: (1) contribute code/docs to claude-ref-manager as an open-source project, which needs real understanding of its architecture and conventions to submit good PRs; (2) learn general practices for maintaining a personal paper library + OKF knowledge-graph system (PMID acquisition, extraction tiers, claims graph) that transfer beyond this one codebase.

## Success looks like
- Can explain the acquire -> extract -> retrieve pipeline (papers/<pmid>/meta.json, extraction tiers, ref-extractor subagent fan-out) and point to the code/docs backing each stage
- Can read and reason about the claim contract and data model (lib_schema.py, Claim v2, corrections overlay, atomic writes, locks) well enough to spot where a change would need to touch them
- Can navigate the command layer (commands/*.md, e.g. /ref:add, /ref:extract, /ref:ask) and trace a command to the scripts/subagents it invokes
- Could submit a small, correct PR (bug fix or doc fix) to this repo without hand-holding

## Constraints
- Sessions are ad hoc, not scheduled — pace lessons to fit short bursts
- Prefer grounding in this repo's actual code/docs over generic ref-manager theory
- User is in caveman-mode session context; lessons themselves should stay normal prose (lessons are artifacts, not chat)

## Out of scope
- Building new commands/features from scratch (that's feature-dev territory, not this course)
- Deep OKF/knowledge-graph theory beyond what's needed to read this repo's implementation
