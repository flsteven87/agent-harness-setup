# Exact Finalization

Read this reference only after a pull-request delivery is integrated and its recorded source branch
or linked worktree may be removed. This phase owns the recorded PR head, `delivery_branch`,
`delivery_worktree`, and bringing the local default branch up to the integration commit.
Run it from the delivering session while it is alive: the helper advances local main before it
touches the branch or worktree, so a session that ends during worktree removal has already
synchronized main.

Verified asynchronous staging custody under the ship contract permits this cleanup while deployment
is pending. Keep its receipt and recovery owner outside the removable worktree. Missing custody or a
synchronous failure requiring local edits preserves the worktree until recovery or transfer is proved.
Cleanup proves source integration; it does not establish deployment or acceptance.

## Refresh The Proof

Refresh the default branch, PR, and exact remote head immediately before cleanup. The remote source
ref is eligible only when all conditions hold:

- the PR is `MERGED`;
- its merge commit is contained by the refreshed default branch;
- its author exactly matches the recorded authenticated provider login;
- its head repository and branch match the recorded push remote and `delivery_branch`;
- the live remote head still equals the full recorded `delivery_head`;
- the head is neither the default branch nor a protected branch.

Delete only that eligible remote ref. If the provider already deleted it, treat the remote action as
complete. Fetch with prune and require an exact `git ls-remote --heads` lookup to return no matching
ref. A moved or unverifiable ref remains intact and produces a deferred-cleanup receipt.

## Finalize Local State

Resolve this skill's directory and run the bundled helper from a surviving worktree or a directory
outside a linked `delivery_worktree`. For an Orca-managed linked worktree, add
`--preserve-worktree`.

Preview first:

```bash
python3 "$skill_dir/scripts/finalize_local_delivery.py" \
  --repo "$control_worktree" \
  --worktree "$delivery_worktree" \
  --branch "$delivery_branch" \
  --expected-head "$delivery_head" \
  --default-branch "$default_branch" \
  --integrated-ref "$fresh_integration_ref" \
  ${squash_commit:+--squash-commit "$squash_commit"} \
  ${orca_worktree_id:+--preserve-worktree}
```

Execute only when the preview reports `"safe": true`, the recorded inputs still match, and every
action is task-scoped. Re-run the same command with `--execute`; the helper revalidates the target.

### Default-branch sync

`scripts/sync_default_branch.py` is the one implementation that brings local main up to a commit;
this helper and `$latest` both run it. `$ship` uses the default ancestry-based mode; `$latest` uses
`--exact` to preserve local-only commits on the reported retained ref and make main equal its fetched
target. The `align` preview becomes `aligned` after execution, with the old OID in `preserved_ref`;
this does not change `$ship`'s completion criterion. Dirty files in the primary checkout (staged, unstaged,
untracked) ride along like any branch switch, so they never block a sync unless the incoming
commits change the same file or would overwrite an ignored one. The report's `default_branch_sync` layer records what happened:

| `status` | Meaning | Next action |
|---|---|---|
| `fast_forwarded` | Local default was behind and now equals the integration commit; `before`/`after` carry both OIDs. | None. |
| `rebased` | Local default held local-only commits; they were replayed onto the integration commit. | None. |
| `already_current` | Local default already contained the integration commit. | None. |
| `blocked` | Git refused; `detail` names the dirty file the incoming commits change, the conflicting file, or the Git operation in progress, and the branch is unchanged. | Report the exact file and OIDs as the one remaining sync action for the owner of that file. |

A `blocked` sync never stops branch and worktree cleanup; report it as its own layer.

For an Orca-managed worktree, load `$orca-cli` after the helper succeeds and use the resolved Orca
executable:

```text
ORCA worktree rm --worktree <full_orca_worktree_id> --run-hooks --json
```

From a session outside that worktree, re-query the exact Orca worktree and Git worktree registration
and require both to be absent. A session running inside the worktree, such as a dispatched receiver,
issues the removal as its last command after its checkpoint and receipt, since removal can end it;
the board observes the absence and a leftover belongs to `$git-converge-main`. When Orca refuses
removal, preserve the clean detached worktree and report deferred cleanup; raw Git worktree removal
would strand Orca registry state.

## Refusal Is A Result

Preserve state and defer cleanup when the helper or Orca refuses. Recommend a new `$ship` exact
finalization attempt for a helper refusal, or an exact Orca retry for an Orca refusal.

The helper must refuse when the worktree is dirty, locked, prunable, or detached; the branch moved;
the branch is protected or checked out elsewhere; integration evidence is missing or stale; or the
merge cannot be proven. It uses `git branch -d` only when the delivered head is an ancestor of the
integration ref. For a squash merge, it uses `git branch -D` only when the supplied squash commit
is contained by the integration ref and its cumulative patch matches the delivered branch. Rebase
or ambiguous integration remains preserved; a later human-invoked `$git-converge-main` pass may
reclassify and remove that exact survivor when its own proof reaches `CLEAN` and Ready.

For a linked task worktree, the helper first syncs the local default branch as above. It then detaches the task worktree at the recorded
delivery head and deletes only that branch; a non-Orca worktree is removed by Git, and an
Orca-managed one is left for Orca to remove with its registry entry. For a task branch in the
primary worktree, it switches the clean worktree to the local default branch, syncs it as above, and
then deletes the task branch.

Completion criterion: the local default branch contains the integration commit or its sync layer
has a `blocked` receipt with one next action, and the exact remote source ref, local
task branch, linked worktree, and Orca registry entry are absent, or each preserved layer has a
refusal receipt and one retry action.
