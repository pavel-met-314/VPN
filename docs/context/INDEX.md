# Context Index

For the required review-first process, see
[`PROPOSAL_WORKFLOW.md`](PROPOSAL_WORKFLOW.md).

For the Architect chat handoff policy, see
[`ARCHITECT_HANDOFF.md`](ARCHITECT_HANDOFF.md).

This directory stores source-backed context for coding agents and humans.

Use:

```bash
barry-cache resume --task "<task>"
barry-cache validate
```

## Routes

Feature context packs live in `docs/context/features/*`.

Optional workspace routing lives in `docs/context/workspaces.json` when a repo wants path/module-scoped context hints.

## Decisions

Architecture decision records live in `docs/context/adrs/*`.
