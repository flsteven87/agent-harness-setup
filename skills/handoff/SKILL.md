---
name: handoff
description: "Save one workstream to shared MEMORY.md at a change request's finish line, or when the user asks for a session checkpoint or notes for a later session. Transferring work to another running agent uses the runtime handoff route."
---

# Handoff

Leave one keyed checkpoint that a fresh session can resume without this conversation. The only
persistence target is `<primary-checkout>/MEMORY.md` (primary checkout: first record of
`git worktree list --porcelain`); never a memory island in a linked worktree, a dated session log,
or a temporary handoff file. `MEMORY.md` is an operational cache of what an agent cannot find by
looking: Git, pull requests, tickets, specs, ADRs, and source stay authoritative and hold the
history, so durable detail lives in its owner with a link here.

Write on a user request for a checkpoint, in prose or by name, and at a change request's finish
line, which the profile closes with a checkpoint. Noticing stale memory alone does not authorize
this write. Continue any separately requested work after saving.

## Identity

Key the workstream by the first stable identity available: an owning tracker or program ID
namespaced by repository (`github:owner/repo#171`), else an active non-default branch
(`branch:feature/x`), else a concise slug from the objective. The key survives moves between
sessions and worktrees; a worktree path, session ID, timestamp, or objective sentence is never the
key. Invocation arguments may name the intended key.

## Content

Ground the entry in current evidence: `git status --short --branch`, `git rev-parse HEAD`,
`git log --oneline -5`, `git worktree list --porcelain`, and only the referenced plans, pull
requests, or validation results that change the next action. A ticket lookup follows
`docs/agents/issue-tracker.md` and happens only when a ticket claim matters. The entry carries
Objective (one outcome), State (a snapshot of what is true now and not visible in Git: real-run
observations, uncommitted progress, what is verified and what is not; rewritten each handoff, citing
a commit only as evidence for a claim), Next (one concrete
action), Ruled out (approaches tried or rejected, each with its reason, so a later session starts
past them), Blocker (or `None`), Decision (only when the next step waits on the owner: the question,
each option with its consequence for users or the business, the recommended option, and whether each
can be undone), Priority (only when
the owner ranked the work: a number, 1 first, then who ranked it and when; carried unchanged until
the owner reranks it), Anchor (worktree, branch, short SHA, clean or dirty summary), and Pointers
(only what the next decision needs). Every claim is verified or marked unverified, and the file holds
no credentials or unnecessary personal data.

## Format

Each keyed workstream is one `### <key>` entry, and `###` marks nothing else. Its section is its
class: `## Active Workstreams` (moving now), `## Waiting on Decisions or External Evidence`, or
`## Deferred Workstreams` (parked on purpose, with Next stating the resume condition). Write fields
as `- **Label:** value` with the labels above. An item with its own owner and next action is its own
entry, never a bold sub-bullet inside another: each such item this session found beyond the selected
work gets a new entry in the same write. `## Current State` holds repository facts, `## Standing
Context` the rules every session honors, `## Retained Context` custody obligations, and `## Durable
Pointers` pointers; none of them holds owned work.

## Retention

This section owns shared MEMORY retention. Keep the smallest context that changes a future action.
A completed outcome removes its keyed checkpoint; Git, tickets and existing evidence owners retain
history. Do not accumulate a `Completed Workstreams` section or move it to another memory archive.

At every authorized handoff, apply this rule to the selected key. At an explicit MEMORY cleanup,
apply it across the file, including legacy completed sections and superseded Current State
snapshots. `$latest` lists other keys' candidates as Stale lines instead of removing them. A
read-only request reports candidates without changing them.

Retain completed context only when it supports a named active dependency, an unresolved custody or
rollback obligation, or a requested acceptance/release action. Keep one to three lines with the
specific reason, evidence pointer (or exact private custody location), responsible owner
(or explicitly unassigned), and removal
condition. Put dependency context in its active entry; use `## Retained Context` for independent
custody obligations. Genuine remaining work belongs in Active with one executable next action.
An optional future release or hypothetical recurrence alone does not justify retention.

Before dropping unique information from ignored memory, verify that an existing evidence owner
retains it, or keep the minimal necessary fact. Preserve unresolved decisions and private custody
locations; pruning memory never authorizes deleting backups, evidence, branches, or production data.
Dates trigger reassessment, not automatic deletion of unresolved obligations. Remove a retained note
when its dependency ends or its owner records disposition; if that cannot be established, keep it
briefly marked unverified. Replace duplicate history rather than appending audit summaries or counts.

## Concurrency

Re-read `MEMORY.md` immediately before writing, and edit by hunk (Edit, apply_patch), never by
rewriting the whole file. Update or remove only the selected keyed entry and
its retained-context note under the retention rule, and add the new entries this session found; repository-wide facts live under `## Current State`. Preserve unrelated entries byte for byte
unless the user explicitly requested a wider memory cleanup. When the same key now points at a
contradictory tracker, branch,
or objective that evidence cannot resolve, or the repository has no primary checkout, return the
checkpoint in chat and write nothing. Create a missing file with `## Current State`,
`## Active Workstreams`, and `## Durable Pointers`; a legacy single-objective `## Current State`
becomes its own keyed entry first.

## Done

The selected work has either a minimal resumable entry or has been removed after completion, with
only justified retained context, and every owned item this session found has its own entry. Unrelated entries remain unchanged. Reply in the
user's language with the file path, the key, and the next action in two or three sentences.
