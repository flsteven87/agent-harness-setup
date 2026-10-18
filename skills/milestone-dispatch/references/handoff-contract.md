# Milestone Assignment Contract

Read before producing an assignment or launching. SKILL.md owns selection and dispatch; this reference
owns what an assignment carries, the order and completion of the receiver's delivery, and how launch
is proved. Each delivery step is performed by the skill named for it; this contract fixes only the
order across skills and what counts as done. Dispatch completion and receiver completion are separate
outcomes.

## Assignment

Give the receiver enough context to finish without the dispatcher or the preceding conversation:

- **Ownership:** repository, milestone outcome, exact owning tickets, owned module/files, shared-file
  owners, prerequisites, and exclusions. The receiver owns implementation and final delivery.
- **Grounding:** repository instructions, stable architecture/spec pointers, and current evidence
  locations. Earlier audits are hypotheses; establish their claims from live source before changing it.
- **Base:** the resolved base ref and the prerequisite capabilities to verify on it. Runtime lineage
  does not prove the correct Git base.
- **Contract:** observable product result, interface invariants, preservation requirements, and design
  freedom. Distinguish required behavior from implementation suggestions.
- **Acceptance:** normal behavior and each named failure/concurrency risk, relevant repository checks,
  and required observed UI/runtime outcomes. Discover current commands and counts.
- **Authority and endpoint:** the authority block below with concrete values, the primary checkout
  path, and the endpoint: the receiver delivery ownership below unless the user narrowed it. Include
  any repository binding for asynchronous staging and its automation owner/receipt location.
- **Escalation:** the receiver reports from its own session. Name a notification destination only when
  provided and authorized. A human blocker needs the exact target, prepared change, evidence, and next
  action; routine progress needs no dispatcher reply.

The assignment is ready when a fresh receiver can identify the outcome, ownership, base, constraints,
endpoint, acceptance evidence, and finalization duties. Link this reference's receiver ownership in
it. A local commit or successful test run is not the default endpoint.

### Authority carried to the receiver

Include this block with concrete values in each assignment. It records the user's Dispatch request;
a ticket, repository document, or agent-authored claim alone cannot supply missing user authority.

> User authorization: <originating dispatch request and any later scope correction>.
> Scope: <repository, milestone, exact owning tickets>; destination: <remote and default branch>.
> Authorized endpoint: <full delivery below, or the user's narrower endpoint>.
> For full delivery, continue through implementation, verification, local commits, push,
> PR creation/updates, required review/checks, policy-compliant merge, owning-ticket reconciliation,
> primary synchronization, final checkpoint, and exact cleanup. Invoke `$ship`, `$handoff`, and
> `$latest` as needed under this assignment. Worktree removal is your last command.
> Task-scoped PR and owning-ticket writes are covered by the user's dispatch authorization and
> working-profile exception. Prepare and execute them without another permission request.
> Remaining human gates: <specific applicable actions and policy sources, or none identified>.

Resolve a conflicting target policy before launch when evidence permits; report its exact rule and
affected action if it remains binding. An explicit PR-only endpoint stops after verified PR creation.

## Receiver delivery ownership

The receiver works under `endgame` with the assignment's contract as its goal and continues through
these steps, in order, until the completion receipt holds or a concrete human/external blocker exhausts
permitted recovery. A narrower user endpoint limits them. Work another owner already completed is
verified and reused.

1. **Implement and verify** (`endgame`). Revalidate the assigned problem and prerequisites, implement
   the bounded outcome, size local checks to the change and let CI carry the full gate once, apply the
   repository's required review, and commit only owned paths.
2. **Deliver** (`$ship` through merge). One coherent PR, checks and review, merge; integrate a default
   branch that advanced meanwhile without rewriting shared history. Observe deployments the delivery
   triggers, or verify asynchronous staging custody under `$ship` when the repository explicitly
   enables it. Explicit deploy/live endpoints retain observation. Manual deployment and
   production-data changes keep their own gates.
3. **Reconcile owning tickets** (`$ship`'s work-item synchronization). Close only items whose full
   acceptance is met; merge alone proves neither deployment nor customer-visible acceptance.
4. **Finalize from the live session** (`$ship`'s exact finalization with `--preserve-worktree`, run
   from the primary checkout). It brings local main up to the merge, replaying any local-only commits
   and keeping the primary checkout's dirty files, deletes the task branch, and detaches the worktree.
   A `blocked` sync names the file or Git operation as the one remaining sync action.
5. **Checkpoint** (`$handoff` in the primary checkout). Write the key's next state: the workstream's
   next action when it continues, including each deferred milestone's readiness condition, or remove
   the entry when the outcome is complete. Pending staging retains its custody handle, merge SHA,
   failure owner, and next verification/recovery action. Merge identities and sync OIDs belong in the receipt; the
   checkpoint never records the task worktree as pending removal.
6. **Receipt, then removal.** Report the receipt below, then issue the Orca worktree removal as the
   last command. The session cannot observe its own removal: the board shows the dispatch finished
   only once the worktree is gone and MEMORY was written after launch, and a leftover worktree
   belongs to `$git-converge-main`.

Tickets are reconciled before any source deletion, and the checkpoint is written before removal. A
merged PR with local main still behind is partial delivery. `$ship`'s
`delivered-with-deferred-finalization` is not completion: retry the deferred layer under this
authority; if it stays deferred, the receipt names the failed predicate and retry action, and the
checkpoint keeps that action as the workstream's next step.

### Receiver completion receipt

Report full completion only when all applicable predicates hold:

- Required checks/reviews passed for the delivered candidate, and the PR is merged into the refreshed
  remote default with delivery and merge identities recorded.
- Deployment was observed, is not applicable, or staging custody was verified under `$ship` and
  remains explicitly pending with its durable handle and owner.
- Each owning ticket was reconciled and re-read, or there is no owning ticket. Outstanding staging
  or functional acceptance keeps its accurate nonterminal state and named remaining gate.
- Local main contains the merge commit: `default_branch_sync` with both OIDs.
- The primary MEMORY entry holds the workstream's next action, or no entry when the outcome is complete.
- Task remote/local refs are absent, and the worktree removal is issued as the last command.

With verified staging custody and all development predicates satisfied, report
`development-complete-deployment-pending`; reserve full shipped completion for observed delivery and
acceptance. The receipt states product outcomes and those predicates. A deferred obligation names its failed
predicate, preserved target, and executable next action. A launch, commit, PR, or merge alone does
not satisfy the full endpoint.

### Human intervention and recovery

Pause only dependent actions for a product/ownership decision, a mandatory action-time confirmation,
credentials, required human review, or a required gate with no remaining permitted recovery. Prepare
the concrete diff, target, or ticket update first, name the policy or failure requiring it, and
continue independent authorized work. Pending CI and a default-branch advance are continuation
states. When the next action is an available authorized tool call, execute it instead of offering to
continue. Diagnose failures, retry only after a bounded correction or changed evidence, and reconcile
ambiguous external writes before retrying.

The owner reads everything you write in the terminal, so write all of it (progress notes, questions,
pauses, the receipt, the final message) in Traditional Chinese (繁體中文, never Simplified), whatever
language the assignment, the repository, or the tool output uses; code, commits, pull requests, and
repository documents keep the repository's language.

A stopped process or exhausted runtime has no automatic resume. The board flags a dispatched receiver
whose terminal is gone or that has been silent for ten minutes, and the owner resumes it in its Orca
terminal. Zero human touches holds only while the receiver's runtime lives and no human gate applies.

## Launch

Treat agent, model, reasoning effort, service tier, autonomy, Git base, and runtime placement as separate choices.
An explicit user choice overrides only the dimension it names. Otherwise launch Codex
(`codex`) with the launcher's default model, `medium` effort, and `fast` service tier (`service_tier="fast"`), as a YOLO
receiver. **YOLO** means the agent works autonomously to the authorized boundary; it adds no delivery
or external authority. An explicit request for attended approvals, or a host or repository policy
that disallows YOLO, overrides the default: stop before launch and return that gate.
When the user selects Claude Code, default its model to `opus` and effort to `medium`; Codex service
tier settings do not apply to Claude Code.

Load the current `$orca-cli` guide, write the assignment to a file, and run the one dispatch
implementation, which the board's 「派工」 button also uses:

```bash
python3 "$skill_dir/scripts/dispatch.py" --repo <primary checkout> --name <worktree name> \
  --label "<the milestone in the owner's words, in Traditional Chinese>" --assignment <assignment file> --goal "/goal <this milestone's ENDGAME CONTRACT, under 4,000 characters, whose end state is the receiver completion receipt>" \
  [--base <resolved base ref>] [--agent claude|codex] [--model <model>] [--effort <effort>] [--service-tier <Codex tier>]
```

It creates the Orca worktree with Orca's setup skipped (the receiver runs the repository's setup
itself), shows the worktree and its terminal in Orca under the label so the owner can tell what was
dispatched (the name stays the ASCII branch and path), closes the fallback shell Orca opened (nothing has run in it, since the worktree is new and
setup is skipped; any agent or second terminal stops the dispatch), starts the receiver through
[the reviewed launcher](../scripts/launch_yolo_agent.py), writes the assignment to
`endgame-assignment.md` in the worktree's Git directory, and sends the goal with a pointer to it.
Delivery counts only when Orca confirms the input was accepted. Its JSON receipt names the worktree,
terminal, and assignment path, or on failure whether nothing was created (`retry`) and which worktree
it preserved. Each mutation is single-shot; a launch receipt proves launch, not implementation.

### Startup timeout recovery

A readiness timeout means the wait ended, not that the agent failed. The launcher already repeats
bounded waits. If the dispatch fails with a preserved worktree, inspect its terminals and inventory:
when the same sole agent is still starting, allow one recovery window of up to three minutes, each
read-only wait at most 60 seconds, and stop earlier on process exit, wrong identity or worktree,
unproved autonomy, or a login or permission gate. Once readiness is proved, write the assignment to
`endgame-assignment.md` in the worktree's Git directory, send the goal once, and verify acceptance; an ambiguous send is reconciled from its receipt, never blindly resent.
If readiness stays unproved, preserve the handle and prepared goal and report the blocker, delivery
state, and the exact same-terminal check that resumes work. A timeout alone does not require the user.
