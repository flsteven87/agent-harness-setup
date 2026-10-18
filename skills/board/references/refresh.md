# Reconcile before rendering

This contract serves both a `$board` invocation and its 更新筆記 upkeep assignment. It authorizes
synchronizing the default branch and editing the primary checkout's `MEMORY.md` to reflect evidence.
The output is accurate notes, not execution of their Next actions: keep code, tickets, deployments,
production data and messages unchanged. An explicit read-only request instead reports drift.

## Select and verify

1. Resolve the primary checkout with `git worktree list --porcelain`; for `--all`, resolve each
   repository through `orca repo list`. Read its instructions and existing `MEMORY.md`. Missing
   memory is `NO_MEMORY`, not permission to invent workstreams. Fetch the remote default branch
   and inspect Git/PR state using the board's existing collector (`board.py` without `--open`).
   Exit 3 only means briefs are pending: finish reconciliation before writing those briefs.
2. Run `$latest` when the default branch is behind/diverged or repository-wide notes need repair.
   It owns Git synchronization and Current State; it deliberately preserves keyed entries.
   Complete the separate entry reconciliation below even when main is already current.
3. Select entries with Stale markers, changed referenced PRs/runs/tickets, finished dispatches,
   elapsed waits, or an unverified next-action prerequisite. Read the referenced live fact that can
   change the next action, including external evidence that Git cannot reveal. Reuse evidence
   already read in this invocation. Leave unrelated history and deliberately deferred work alone,
   except when its named resume condition has changed. A completed PR is evidence of integration,
   not deployment, product acceptance or completion of its parent ticket.

Done when each selected key has current evidence for its State, Next and Blocker, or a precise
reason that verification is unavailable. No selected key disappears merely because access failed.

## Reconcile the source

Read [handoff](../../handoff/SKILL.md) for entry format, retention and concurrency. This board refresh
is an explicit notes-maintenance scope across the selected keys; it does not resume their work.

- Record the evidence checked and its time in the affected entry's State. Update State, Next and
  Blocker together; keep the owner's Objective, Priority, decisions and Ruled out constraints.
  Move an entry to its appropriate class when a verified prerequisite or external wait changes.
  Remove a completed entry only under handoff's retention rule, preserving unresolved custody.
- Respect live ownership. Inspect board dispatches and referenced worktrees before editing a key.
  A running receiver keeps its entry; retain a Stale reason naming that owner. Absence from the
  board's dispatch list alone does not prove a referenced worktree is idle.
- Immediately before each hunk, reread the file and compare the selected entry with the version
  whose evidence was checked. If another writer changed it, preserve their text and report the
  conflict for that key; continue independent keys. Preserve unrelated entries byte for byte.
- Remove only the selected key's Stale line after its source entry is reconciled. For missing
  access, contradictory evidence or active ownership, keep or update the line with that reason.
  Match the entry's full key as parsed by `board.parse_memory`, including any heading suffix.
  File modification time proves a write, not that every card was verified.

Done when every selected key is either reconciled with evidence or explicitly unresolved, and
unrelated entries are unchanged. Report those two sets separately; do not claim the whole board is
current when some evidence remains unavailable.

## Return to the caller

For a normal board invocation, regenerate briefs from the refreshed source and open the page using
SKILL.md's remaining steps. The renderer's source hash invalidates changed briefs automatically.
For 更新筆記 upkeep, return the reconciliation report to the existing launcher; stop before rendering
or dispatching another agent. Its existing endpoint owns delivery when MEMORY.md is Git-tracked.
