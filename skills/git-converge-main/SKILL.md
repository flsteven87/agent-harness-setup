---
name: git-converge-main
description: Audit and clean owned Git branches, worktrees, and recovery artifacts; complete authorized delivery through ship before retiring source artifacts. Use for repository cleanup, full convergence, or a read-only Git artifact audit.
---

# Git Main Convergence

Finish the requested scope: account for every owned artifact, complete authorized delivery, and
remove every redundant cleanup target. Preserve each remaining source with a concrete release
condition. Routing to another skill is an execution step, not a handoff back to the human.

## Intent and authority

Resolve intent from the current request and existing conversation authorization:

- **Audit** explains the repository state. It is read-only except for refreshing remote-tracking refs.
- **Clean** removes exact owned artifacts proven redundant and applies the documentation retention
  exception below. A bare invocation selects this intent.
- **Converge** completes delivery and cleanup when the human has requested or accepted that combined
  outcome. Acceptance includes a follow-up request to finish the same named targets after the
  conversation explained their remaining delivery and cleanup work; the human need not repeat
  "ship" or type a skill command. Carry the accepted targets, remaining work, and endpoint into
  `$ship`, then return here for the remaining cleanup.

Resolve references such as "those two branches" against the preceding explanation. A stated
release condition can supply that context when it identifies the remaining value and delivery
needed before retirement. Record which explanation and follow-up establish acceptance; adjacent
unrelated pending work stays outside that acceptance. A vague "needs work" note, a bare inventory,
or newly discovered content supplies no delivery plan to accept.

"Clean everything" alone supplies cleanup scope, not external delivery authority. Converge reuses
existing authorization; discovery of valuable work does not create it. Honor narrower endpoints and
repository-specific restrictions on contributors, PRs, or deployments. Keep other-owned, parked, and
unrelated work outside the delivery set.

`$ship` owns remote delivery and its default-branch synchronization. This skill moves the default
branch only under the documentation retention exception. Cleanup alone does not authorize push,
PR creation or closure, deployment, remote-ref deletion, production mutation, history rewriting,
reflog expiry, or aggressive garbage collection. Retain applicable action-time confirmations.

## Evidence contract

Anchor a frozen inventory with the bundled read-only helper, refreshing remote truth when the
decision depends on it:

```bash
python3 $HOME/.agents/skills/git-converge-main/scripts/git_converge.py audit . --fetch --json
```

Use edge checks only when the request includes stashes, reflogs, recovery objects, or repository-wide
recovery cleanliness. Use merge proof only when remote landing cannot be established by reachability.

Treat local and remote containment as separate facts:

- `local_integration` answers whether the local default branch contains the exact source tip.
- `remote_integration` answers whether the refreshed remote default contains it or an exact merged
  PR proves an equivalent cumulative patch.

Ownership comes from Git identity plus task, provider, reflog, or worktree-manager provenance. Names,
prefixes, age, subjects, and `git cherry` are discovery signals, not ownership or integration proof.
For manager-owned worktrees, include its current agent and terminal state. Missing evidence preserves
the artifact.

## Decisions

Give every owned artifact one direction and one execution state.

- **DELIVER** — its unique delta is current, cohesive, in scope, and belongs in the local default
  branch; `$ship` owns the integration and delivery action.
- **CLEAN** — no valuable unique content remains outside the local default branch, or stronger
  remote or semantic evidence proves it redundant.
- **LEAVE** — it is other-owned, ownership-ambiguous, intentionally parked, newly observed after the
  anchor, outside scope, or not a coherent delivery candidate.

Execution state is **Ready**, **Waiting** with a checkable release condition, or **No action** for
LEAVE. Activity, dirtiness, conflict, stale default, failed validation, and incomplete review block
execution; they do not decide direction. Read
[semantic convergence](references/semantic-convergence.md) only when reachability and current task
evidence cannot settle an owned candidate.

## Delivery boundary

### Documentation retention exception (Clean and Converge)

Inspect the complete unique delta, including staged, unstaged, and untracked files. This exception
applies only to owned documentation work: prose, static reports, and their presentation assets or
manifests. Executable tooling, application behavior, migrations, and operational configuration use
the normal delivery route, even when accompanied by documentation or stored under `docs/`.

Compare each document with its current canonical destination and repository lifecycle policy.
Decide autonomously from that evidence; a unique commit or an old in-progress card alone is not a
reason to park finished documentation. Different documents in one worktree may have different decisions.

- **KEEP:** Reconcile useful current knowledge into the existing canonical document, or retain its
  policy-compliant path if it is the sole document owner. In this clean pass, preserve the source,
  validate the resulting documentation, and record the retained content in a task-scoped local
  commit on the primary default branch. This is local retention, not publication; no separate ship
  request is needed. Require a current default branch, clean destination paths, and no competing
  writer. If those conditions fail, name the exact blocker and retain the source until resolved.
- **DROP:** Record why the document is duplicated, superseded, expired under its lifecycle, or has
  no remaining purpose. Map any retained knowledge to its destination. Before discarding unmerged
  work, satisfy applicable action-time confirmation requirements with the exact paths, source OID,
  and loss described; the KEEP/DROP judgment alone does not waive those requirements.

For a documentation-only source, after every document has a retention commit or an authorized DROP
disposition, take a fresh audit anchor and classify the source CLEAN. A mixed source also requires
the component mapping below. Its proof is the source-to-destination mapping and DROP
receipt, rather than source-tip ancestry alone. Verify that the work is finished, then apply the
manager activity check under the cleanup boundary and remove the worktree and exact local ref.
Preserve private backups and unexplained ignored material until their disposition is established.

This path is complete only when Git and manager registrations are absent, or a concrete authority,
content-preservation, validation, or activity blocker is reported. Audit mode reports the proposed
KEEP/DROP disposition without committing or deleting anything.

### Implementation and mixed branches

Inspect the complete unique delta, including committed, staged, unstaged, and untracked content.
Map each component to landed evidence, a current delivery candidate, documentation KEEP/DROP, or
retained work. Shared predecessor branches can reuse the same verified component mapping. A mixed
branch becomes CLEAN only when every component is proven redundant or has an executed KEEP/DROP
disposition; retained unique work keeps its source. Delivering useful code alone does not prove its
reports or other commits redundant.

For each DELIVER component, resolve its source OID, current value, acceptance boundary, destination,
and required checks. Prepare a concrete, reviewable result under existing implementation authority;
preserve the original while extracting or adapting the accepted delta in an isolated task worktree.
Do not replay already-landed components or import unrelated changes from the old branch.

- **Delivery authorized:** finish implementation and relevant checks, commit the accepted delta,
  then execute `$ship` through the authorized endpoint. Carry the exact source-to-delivery mapping,
  validation, and user authorization into any receiver assignment. Continue without another request
  to invoke `$ship`.
- **Delivery not authorized:** complete permitted inspection and validation, and any separately
  authorized implementation. Resolve the exact candidate, destination, scope, and remaining action
  before asking for the missing authorization. Continue independent Ready cleanup meanwhile.
- **Blocked:** preserve the source and report the failed predicate plus an executable recovery step.
  A required external approval or changed outcome can block delivery; a phase transition cannot.

After delivery, take a fresh inventory and verify containment or the complete semantic mapping.
Resume cleanup of every original target still in scope, including predecessor refs beyond `$ship`'s
exact task cleanup. A PR-only endpoint leaves unmerged sources Waiting until integration is proven.

## Cleanup boundary

Any delivery invalidates the original inventory token. Take a fresh cleanup anchor, and map its
source and destination tips back to the original inventory. Remove only a CLEAN/Ready artifact whose
path, full ref, expected OID, ownership, containment proof, and current cleanup token still match. A
removable worktree is clean, operation-free, unlocked, unused by another worktree, and released by
the manager activity check below. Record its ignored status-entry count; inspect and classify each
ignored group as preserved elsewhere, task-owned disposable output, or unresolved unique material.
Ignored material is outside Git recovery; its count alone supplies neither deletion proof nor a
permanent blocker.

### Manager activity check

For an owned CLEAN worktree, use fresh manager state and terminal/process evidence:

- **Running:** An agent turn, tool call, background task, build, or service is executing in or using
  the worktree. Preserve it as Waiting until execution ends or the owner explicitly authorizes
  interruption.
- **Idle:** The agent is done, stopped, or waiting for input and has no executing tool/background
  task; any remaining shell is at its prompt. Cleanup authorization includes closing these agent
  sessions and shells through their manager. Close them, verify all associated processes stopped,
  then continue removal in the same pass.
- **Unknown:** Execution state or process shutdown cannot be verified. Preserve it as Waiting with
  the exact missing observation and one executable recovery step.

Use execution evidence to select Running, Idle, or Unknown. A connected PTY, live agent process,
or old in-progress card alone does not establish Running. Refresh activity immediately before
closing; if execution has resumed, apply Running.
Completion requires zero executing tasks and verified terminal shutdown. Other cleanup predicates,
including source preservation and ignored-material disposition, still apply.

Use the worktree's manager for removal and require both manager and Git registrations to disappear.
Delete a surviving local ref only by exact old-OID comparison. Read
[safety and authorization edges](references/safety-and-authorization.md) for dirty rescue, remote
refs, open or unmerged PRs, or any destructive edge beyond an ordinary task-local worktree.

## Completion

A fresh inventory must account for every frozen owned item and every item discovered during the
pass. Report local and remote delivery separately, along with retained release conditions, cleanup
receipts, unavailable evidence, and the final inventory token.

- **Audit complete**: every in-scope item has a supported direction.
- **Cleanup complete**: every Ready CLEAN item authorized by the pass is removed and verified absent.
- **Convergence complete**: authorized delivery reached its endpoint and every original cleanup
  target eligible within that endpoint is removed and verified absent. Any remaining requested
  action makes convergence incomplete; name its blocker and retained source even when cleanup of
  the Ready subset succeeded.
- **Repository clean**: no dirty, unique, active, blocked, or intentionally retained survivor remains
  in the audited scope.
