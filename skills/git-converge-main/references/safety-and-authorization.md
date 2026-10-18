# Safety and Authorization Edges

Use this reference before this skill executes a remote or destructive-edge cleanup, or when it must
classify a blocked edge. Apply the ownership, authorization, and completion boundaries from
`SKILL.md`. Require mechanical evidence from the bundled audit helper or semantic proof from
`semantic-convergence.md`; age, names, `[gone]`, subjects, and `git cherry` are investigation leads,
not deletion authority.

## Contents

- [Dirty merged branch rescue](#dirty-merged-branch-rescue)
- [Remote cleanup boundaries](#remote-cleanup-boundaries)

## Dirty merged branch rescue

Enter this branch when the user names the exact dirty item for delivery or semantic cleanup, or
when the documentation retention exception in `SKILL.md` applies. Otherwise a bare convergence
pass preserves it as `LEAVE`. Documentation retention preserves the source until its KEEP/DROP
disposition is executed; it does not require a stash when the original can remain intact.

Preserve the only copy before changing refs. Use `stash push -u`, apply rather than pop, verify the
new branch contains the complete staged/unstaged/untracked set, and preserve the stash through commit
validation. Do not auto-generate a WIP commit unless committing was explicitly requested.

Avoid rebasing or merging a squash-merged source branch onto the default branch. Those operations
replay already-incorporated commits and obscure the new work. Move only the dirty delta to a fresh
branch based on the default remote.

## Remote cleanup boundaries

### Merged-head cleanup eligibility

Delete a repository-hosted merged PR head during an authorized convergence pass only when all
predicates below are freshly proven:

- authenticated provider login exactly equals the PR author;
- PR state is `MERGED`, and its merge commit is contained by the refreshed default branch;
- PR head repository is the configured repository remote;
- the live exact head ref still equals the PR's final full head OID;
- the ref is neither the default branch nor a protected branch.

Pin the login, PR number, head repository, exact ref, head OID, merge commit, and refreshed default
OID in the cleanup receipt. If any predicate is false or unavailable, classify the ref as `LEAVE` or
Waiting and record the failed predicate. Branch prefix, age, and naming conventions are not proof.

Delete only the exact ref. Completion proof must fetch/prune and require
`git ls-remote --heads <remote> <exact-ref>` to return no matching ref.

### Semantic or unmerged remote cleanup

Remote deletion outside the merged-head predicates requires explicit item-level intent. This
includes open or closed-unmerged PRs, post-merge branch movement, semantic supersession, and remote
refs without an exact merged PR. For semantic supersession or inferiority, run independent Standards
and Spec reviews and reconcile disagreement conservatively before cleanup.

An explicit request to clean named PRs, or to clean the exact PRs just classified in the active
conversation, supplies item-specific intent; it is not namespace-wide authority. Pin each PR's
state, head OID, and branch in the cleanup receipt. Never extend the request to adjacent branches or
another PR.

For an unmerged PR, require a concise closure receipt before deletion, followed by
fetch/prune, confirmation of the intended PR state, and the exact absence check above.
