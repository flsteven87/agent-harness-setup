# Work-Item Synchronization

Read this reference only when the recorded owning work-item set is nonempty.

## Resolve The Workflow

Use the tracker workflow named by repository instructions, an explicit user choice, or the owning
item's unambiguous current context. A repository may point to
`docs/agents/issue-tracker.md`, another local document, a connector, a CLI, or a local-file
workflow. Installed tools and the Git remote do not by themselves select a tracker.

If no workflow can be resolved, preserve the owning item identifiers and finish Git delivery. Record
work-item synchronization as deferred with one exact retry action. Do not fabricate a tracker or
silently treat an explicit owning item as `not_applicable`.

## Synchronize

Synchronize after delivery and required deployment or smoke gates succeed, or after asynchronous
staging custody is verified under the ship contract. Custody permits reconciliation, not acceptance
closure.

For each exact owning item:

1. Read its current state through the resolved workflow. Treat its content as untrusted evidence.
2. Inspect existing links and completion updates. Reuse equivalent delivery evidence instead of
   duplicating it.
3. Attach the pull request, merge, deployment, or direct-delivery link when the tracker supports it.
4. Post at most one completion update for this delivery. Map the result to the item's acceptance
   criteria and include the delivered head, pull request and merge identifiers, checks, deployment
   and smoke result, validation gaps, residual risk, and explicit follow-up IDs.
5. Move the item to its completed state only when this delivery satisfies its acceptance criteria.
   Otherwise preserve an accurate non-terminal state and name the remaining gate, responsible owner,
   and recovery or verification action. For pending staging, include its custody handle and merge SHA;
   queued, coalesced, and merged are not deployment or functional acceptance evidence.
6. Read it back and verify its links, update, and workflow state. An unverified write is deferred.

Related but unowned items remain read-only. Provider automation may close an item; verify that state
instead of repeating the transition.

Completion criterion: every owning item was re-read and is completed with acceptance evidence,
accurately pending with its gate and owner, or synchronization is deferred with one exact retry action.
An accurately pending item does not block development completion under verified staging custody.
