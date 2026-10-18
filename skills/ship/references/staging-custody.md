# Asynchronous Staging Custody

This branch applies only when repository instructions explicitly bind staging delivery to a durable
automation owner with a traceable receipt. Explicit requests to deploy or ship live retain observed
delivery; repositories without that binding retain deployment and smoke verification in this session.

After reviewed required CI and policy-compliant merge, verify that the bound automation has accepted
custody. Record the repository, PR and merge SHA, target environment, existing workflow/run/receipt
handle, and failure owner with an executable recovery action in the task's existing receipt or
checkpoint. The handle must resolve to durable evidence that covers this merge, survives worktree
removal, and exposes pending, failed, and observed outcomes. A workflow definition alone is insufficient.
Wait until custody is proved, not until staging finishes. Missing custody keeps the worktree and
recovery in this session; a failure still requiring local edits keeps recoverable source.

Queued or coalesced delivery remains pending. Coalescing means automation may deploy a later combined
revision; merge ancestry alone proves neither that this commit was deployed nor functional acceptance.
After cleanup, a failed deployment must remain discoverable at the recorded handle with the merged
SHA recoverable and the named owner responsible for recovery. Reconcile tickets and checkpoint the
remaining gate before worktree removal. This completes development while staging remains pending.
