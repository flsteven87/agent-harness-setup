---
name: milestone-dispatch
description: Reconcile one program and hand off ready milestones to autonomous worktree agents. Use for milestone planning or parallel dispatch; receivers own implementation through PR merge, ticket updates, cleanup, and local main synchronization.
---

# Milestone Dispatch

Choose the current implementation frontier within one selected program and transfer each authorized
milestone to a worktree agent that owns its complete delivery. The dispatcher finishes after verified
prompt delivery; the receiving agent continues to the agreed outcome. Route to `$topics` when the
choice still spans programs.

## Plan and Dispatch

**Plan** answers priorities, dependencies, parallel grouping, or what an assignment should say.
Inspect and recommend while leaving code, worktrees, agents, and trackers unchanged.

**Dispatch** applies to an explicit request to launch, assign, or hand work to worktree agents.
Read [the assignment contract](references/handoff-contract.md) before preparing prompts or launching.
Default to Codex with the launcher's default model (`scripts/dispatch.py`), `medium` reasoning effort, and `fast` service tier.
Honor explicit user overrides for the dimensions they name.
By default, assign the receiver implementation, checks, local commits, PR creation and merge to the
repository's default branch, exact owning-ticket updates, fast-forward of local main through `$ship`
finalization, the final checkpoint, and task cleanup. The assignment explicitly authorizes its
required `$handoff` checkpoint. Where the repository explicitly enables asynchronous staging,
carry its binding into the assignment and apply `$ship` custody verification before cleanup; other
repositories and explicit deploy/live endpoints retain observed delivery.
An explicit Dispatch request authorizes this default endpoint under the user's working profile;
carry its originating request, resolved targets, and any narrower endpoint into the prompt using
the assignment contract's authority block. The receiver invokes `$ship` under that inherited user
authorization. PR creation is a required delivery step, not a new permission question. Runtime and
repository protections still apply; the launcher's autonomy setting does not override them.

Automatic skill selection supplies no missing execution scope or external authority. A request to
edit this skill is not a request to dispatch repository work. Existing authorization persists across
phases; the receiver needs no new request merely to progress from implementation to delivery.

Ownership transfers with verified prompt delivery. Report each worktree and agent handle, assigned
outcome, terminal endpoint, and any launch or authority gap, then stop. Supervision applies only if
the user separately requests it; load `$orchestration` for that Orca route. A receiver needing a human
raises its own concrete blocker instead of relying on a supervising dispatcher. Before launch, resolve
which actions the user authorized, which still require action-time confirmation, and the primary
checkout path where the receiver fast-forwards local main before removing its own worktree. Carry
those facts into the assignment.

## Establish the frontier

Read target `AGENTS.md` and its context pointers. Reconcile current remote default-branch, source,
owning tickets, active worktrees/agents, and delivery evidence. Earlier reports locate evidence;
revalidate their claims before assigning work. Missing evidence remains an explicit coverage gap.
Tracker status, merge, deployment, and customer-visible acceptance are separate claims.

Bound each milestone by the originating customer or operating outcome, exact owning tickets, module
seam, prerequisite capabilities, acceptance gate, exclusions, and delivery endpoint. Follow the user's
order; otherwise prioritize integrity and current user harm, then shared prerequisites. Group only
work with one coherent interface and acceptance surface. Use `$codebase-design` when seam selection
needs investigation. Adjacent findings stay with their named owner rather than expanding the task.

Dispatch every independent ready milestone in the same pass, each with one writer, branch, worktree,
and non-overlapping ticket ownership; hold back only for a stated dependency. Give shared schema/API
changes one owner; serialize work that needs them, or place a coherent dependency chain under one
receiver. A prerequisite must exist on the selected base before dependent work starts. Keep
unavailable prerequisites undispatched with their exact readiness condition, and record that condition
as the owning workstream's next action in the primary checkout's MEMORY.md through `$handoff`, so the
board surfaces the milestone once it is ready; do not create a worker that needs an absent coordinator.

Use `$orca-cli` for Orca-managed worktrees and agent launches. Apply the assignment contract's launch
and timeout-recovery checks for each target. Dispatch the remaining independent assignments while a
single launch is blocked. Runtime lineage does not choose the Git base; prerequisite evidence does.

## Dispatcher completion

A Plan is complete when each candidate has a grounded outcome, owning set, base/prerequisites,
acceptance gate, and reason to start or defer.

A Dispatch is complete when each authorized ready assignment has one verified worktree/agent handle,
proved launch configuration, and one accepted prompt delivery containing the receiver's full terminal
contract. Give the user those identifiers and any deferred assignment's exact next action. A launch
receipt proves launch, not implementation or merge. Preserve uncertain handles and recover readiness
through [the timeout route](references/handoff-contract.md#startup-timeout-recovery); reconcile an
ambiguous prompt send before retrying. End without monitoring receiver implementation.

The receiver's completion criteria belong to [delivery ownership](references/handoff-contract.md#receiver-delivery-ownership).
Include that pointer and the terminal contract in every assignment so work continues after dispatch.
