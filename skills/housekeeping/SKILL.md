---
name: housekeeping
description: Audit and tidy one repository's agent artifacts, including AGENTS.md, repo skills, handoffs, completed plans, and stale notes. Use for explicit repository housekeeping or accumulated agent-artifact cleanup.
---

# Housekeeping

Keep one repository's agent-facing context lean, current, and discoverable. Product source, tests,
migrations, lockfiles, active specs, secrets, and local env files stay outside the pass.

## Boundaries

- An audit or recommendation request is read-only. An explicit cleanup request authorizes reversible
  edits within its stated scope; name the affected paths before editing and preserve existing
  authorization. Confirm destructive actions under the user's authority rules.
- Treat an unspecified request to "housekeep" as an audit. Deleting untracked, ignored, or unique
  content requires explicit confirmation naming the paths; Git cannot recover that content.
  An explicit MEMORY cleanup already authorizes pruning redundant summaries under its retention
  rule; preserve unique decisions and custody facts instead of deleting them.
- User-level surfaces are read-only conflict context here; hand projectless findings to an explicit
  `$setup-hygiene` invocation.
- When cleanup reaches a branch, stash, worktree, remote ref, reflog recovery, or repository
  maintenance item, stop at the exact overlap and recommend an explicit `$git-converge-main`
  invocation. That skill owns Git classification, proof, and mutation.
- Preserve unique business decisions and unrelated edits. Redact secret-like values from output.
  Leave an ambiguous item unchanged and continue independent work; ask only when its disposition
  blocks the requested outcome.

## Scan

Run the bundled read-only scan from the repository root, or with `--project /path/to/project`:

```bash
bash ~/.agents/skills/housekeeping/scripts/scan.sh
```

Use its results to identify candidates. Without the script, inspect the same surfaces by hand:
global and repository `AGENTS.md`, `.agents/skills`, `.codex`, handoff or memory files, plans, and
stale docs.

## Judge each finding

Sort every finding into delete candidate, consolidate, needs user review, or out of scope. A candidate
label supplies no authorization; use the request's scope and the user's destructive-action rules.

A plan or design document is spent only once Git shows the work shipped. Search for the symbol, flag,
or route that document introduced:

```bash
git log -S '<symbol_the_document_introduced>'
```

Zero hits means the design was never built, whatever the document claims about itself, and deleting
it there loses unbuilt work. Keep that design and retire only its step-by-step plan.

Otherwise: remove a plan only when it is fully complete, with no `[ ]`, `TODO`, `PENDING`, or
`IN PROGRESS` marker left. For explicitly authorized MEMORY cleanup, apply the
[handoff retention rule](../handoff/SKILL.md#retention), including legacy completed inventories.
Keep only context that changes a future action; preserve unique facts and unresolved custody.
Keep `AGENTS.md` to durable rules, moving repeatable procedures into
`~/.agents/skills/<name>/` or `<repo>/.agents/skills/<name>/` and volatile external facts into
MCP-backed lookups or the task prompt. Skills keep one job each. Recommend an automation only after
its manual workflow is stable: skills define method, automations define schedule.

## Execute the authorized scope

Name the exact files and intended action, check completion evidence and existing authorization,
preserve unrelated content, and report every changed path with a concise summary of the changes.
Leave anything not clearly complete in place and say why it was skipped. Create no backup files; Git
history is the safety net.

## Completion

An audit is complete when evidence-backed candidates and unresolved items are reported without
changing files. A cleanup is complete when the authorized scope is handled, unrelated content and
unique decisions survive, each consolidation has one current owner, and the report lists every
changed path, deferred items, and any Git work referred to `$git-converge-main`.
