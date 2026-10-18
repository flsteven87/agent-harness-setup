---
name: latest
description: "Align local main exactly with the fetched remote default branch, preserve local-only commits on a retained branch, and refresh shared MEMORY.md. Use when the user asks to bring a repository up to date; catchup handles read-only context recovery."
---

# Latest

Fetch remote updates, make the local default branch (usually main) equal the fetched remote tip,
and record a verified checkpoint. Success requires equal commit OIDs and ahead0/behind0.
Local-only commits belong on a retained branch, so their contents survive without keeping main ahead.

An invocation authorizes local alignment after preservation and returning a detached primary checkout
to main. Remotes remain unchanged. Continue separately requested work after synchronization. A stale memory entry
alone does not invoke this workflow.

## Scope

Update remote references and tags, update the existing local default branch in its owning
worktree, replace `## Current State` in the primary checkout's existing `MEMORY.md`, and sort items
written outside any keyed entry. Existing
keyed entries belong to their own `$handoff` or an explicit MEMORY cleanup; this refresh flags them
and never edits them. Preserve other branches, worktrees, uncommitted files, stashes, and the changes in unique commits.
Keep the caller's task branch and other worktrees unchanged. The default branch moves only through
the shared sync script's `--exact` mode below. It preserves the original tip before aligning an
ahead or diverged main; it leaves `$ship`'s ordinary ancestry-based sync unchanged. Git cleanup belongs to
`$git-converge-main` and `$ship`; creating a missing `MEMORY.md` belongs to `$handoff`.

## 1. Fetch and inventory

From the active worktree, resolve the primary checkout (first record of
`git worktree list --porcelain`), read the applicable instructions and `MEMORY.md`, then run:

```bash
python3 "$HOME/.agents/skills/git-converge-main/scripts/git_converge.py" audit . --fetch --edge-checks --json
```

Hold its `state_token` as the anchor. A fetch failure leaves local branches untouched: report remote
facts as stale and rerun without `--fetch` for a local inventory. Read each branch through
`local_integration` and `remote_integration` (`reachable`, `patch-equivalent`, `not-proven`,
`unknown`) with `local_proof` and `remote_proof`, its upstream (`tracking`, `gone`, `none`, with
divergence), and its checkout (owning worktree or `unattached`). A gone upstream is metadata, not
integration proof; a patch-equivalent branch is a cleanup candidate, not deletion authority. Rerun
once with `--merge-proof` only when a remote `not-proven` result could change the ranked next action.
Any omitted recovery entry keeps that class Waiting.

## 2. Synchronize the default branch

Resolve the local default branch and the fetched remote OID from the inventory. Other worktrees'
dirty files or unmerged task commits are retained work, not blockers. Run the one sync
implementation, described in [`$ship`'s exact finalization](../ship/references/exact-finalization.md#default-branch-sync),
first as a preview, then with `--execute` once the preview still matches the inventory:

```bash
python3 "$HOME/.agents/skills/ship/scripts/sync_default_branch.py" \
  --repo "$primary" --default-branch "$default_branch" --target "$fetched_default_oid" --exact [--execute]
```

The script fast-forwards a behind branch. For ahead or diverged main, it first preserves the exact
old OID at the reported `preserved_ref`, then aligns main to the fetched OID. Existing preservation
refs are reused only when they point to that same old OID. Preview creates no refs. Dirty files carry
through Git's guarded branch switch; overlap, an ignored file that would be overwritten, a preservation
collision or an in-progress Git operation leaves main unchanged and supplies a `blocked` reason.
Keep any created preservation ref after a blocked attempt; it still owns the old commits.

Verify `git rev-parse "$default_branch"` equals the fetched OID and the post-action inventory reports
`default_synced: true`, ahead0/behind0. A blocked attempt still refreshes the checkpoint with the exact
remaining path, operation or ref collision and one next action.

### Checkout

Resolve checkout separately from main's ref. A task-branch caller keeps its branch and HEAD.
When invoked in the primary checkout with detached HEAD and main is unattached, switch it to the
default branch with `git switch --no-overwrite-ignore "$default_branch"` after successful alignment.
Verify the symbolic branch and HEAD; this makes the normal branch visible in Orca as well as Git.
An active native-lane custody requirement, Git operation, dirty overlap, or main owned by another
worktree keeps that checkout intact; report main alignment and checkout pending separately, naming
the blocker. Secondary detached checkouts also stay intact. Leave services and running apps alone.

## 3. Refresh the checkpoint

After synchronization or a blocked attempt, rerun the audit without fetch using the same
`--edge-checks` and `--merge-proof` settings. This post-action inventory anchors the checkpoint;
the expected fast-forward or rebase changes HEAD, branch relations, and reflogs. Report any unrelated drift.

Re-read `MEMORY.md` immediately before editing, and edit by hunk, never by rewriting the whole
file. Replace `## Current State` with repository-wide facts: the synchronization result and
default-branch relation with both OIDs, compact attention counts and shared blockers, current branch,
HEAD, worktree count, and the inventory token. Unresolved risks that are not yet owned work stay
there as facts.

- **Owned work outside any entry** (an item with an owner and a next action, such as a finding that
  waits on the owner's confirmation), wherever it sits outside a `###` entry: in Current State,
  before the first entry of a workstream section, or in any section the
  [handoff format](../handoff/SKILL.md#format) does not define. It becomes a new keyed entry in its
  class section. Never reuse or edit an existing key.
- **Every other item outside an entry** moves to the format section that owns it: rules every session
  honors to `## Standing Context` (keep each moved group's title as a `####` heading), pointers to
  `## Durable Pointers`, custody obligations to `## Retained Context`; a finished or obsolete item is
  dropped once Git or its evidence owner holds it. Remove a section this leaves empty.
- **Existing entries stay byte for byte.** For each entry that live evidence contradicts (a worktree,
  merge, ticket state, or environment fact), or whose outcome looks complete, add
  `- Stale: <key> — <what the evidence shows>` to Current State. The board marks that card, and the
  entry's owner corrects it: its receiver, its next `$handoff`, or an explicit cleanup.

Verify only evidence needed for those lines, not every historical delivery. Remaining acceptance or
custody facts must keep a minimal owner, pointer and next action/removal condition. When `MEMORY.md`
is absent, report `NO_MEMORY`; synchronization can still
succeed. Rerun the same audit without fetch after writing: its token may differ only because
`MEMORY.md` changed; report any other difference as concurrent drift with both readings.

## Done

Report exact alignment only when local main equals the fetched remote OID with ahead0/behind0;
otherwise report incomplete with the exact blocker and next executable action. State before/after
OIDs, whether main fast-forwarded, aligned after preservation, or was already equal; include each
preserved ref and its old OID, and the caller's actual branch/HEAD. A checkout blocker remains visible
even when main aligned. File-content equality alone does not prove commit equality.
Every worktree, local branch, dirty path, stash,
and Git operation must be accounted for, and every changed memory claim must trace to the final
inventory. Call the repository clean only when the inventory covered every worktree and found no
dirty, unique, active, or retained survivor. Repository cleanliness is separate from synchronization.
