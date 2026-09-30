# Context Maintenance

## Active policy

This repository uses the mandatory review-first process in
[`PROPOSAL_WORKFLOW.md`](PROPOSAL_WORKFLOW.md). Canonical context in
`docs/context/` is proposal-only until the user explicitly approves the shown
change.

- Keep project truth in Git and make every durable fact source-backed.
- Prepare, do not silently apply, context updates after substantial work.
- Before approval do not write canonical context or semantic operational memory;
  do not run commands that write memory (`finalize`, `failure record`,
  `feature new`, `adr new`, or `--write`). A temporary patch preview in
  `.context-state/proposals/` and disposable cache from `resume` are allowed.
- Never include or inspect `.env` files, keys, tokens, passwords, UUIDs,
  VLESS links, subscription URLs, or private access addresses in context work.
- Do not enable `kb`, `cq`, or a shared knowledge base without a separate,
  explicit user decision.

## After approval

1. Apply only the approved proposal to `docs/context/`.
2. Show `git diff -- docs/context`.
3. Run `barry-cache validate`.
4. Keep risks and open work factual; do not turn speculation into canonical
   facts.

## Canonical content rules

- Use feature `FACTS.jsonl` files for source-backed facts.
- Use an ADR only for durable architecture, policy, storage-layout, or
  cross-module decisions.
- Use ISO 8601 timestamps in fact `updated_at` values.
- Use collision-resistant fact IDs such as `REV-20260526T160512Z-a8f3`.
- Review the diff before committing canonical context.
