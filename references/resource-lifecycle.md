# Resource Lifecycle

Before launching a local service, test runner, browser, emulator, or tool server, inspect existing
instances and reuse one only when its owner, environment, and isolation scope match the task.
Start only the components needed for the current check. Keep the handles needed to stop each
task-created resource and its descendants through its owning manager or stop command.

Arrange cleanup when creating the resource, using the runner's teardown, `finally`, or a shell
trap for success, failure, and interruption. Release it when its last task consumer finishes.
Before deleting temporary directories or reporting completion, verify that owned processes and
descendants have exited, containers are stopped, and their listeners are gone. A failed stop is
unfinished cleanup; preserve the handle and report the exact retry action.

For a pre-existing or shared resource, establish ownership, task completion, and current consumers
before stopping it; age or an idle connection snapshot alone is insufficient. Preserve resources
used by active work. An intentionally retained runtime needs an owner, reason, and stop command
in the existing task checkpoint; closing an agent turn or terminal is not proof of release.

Clean up agent-created development artifacts automatically when their development or verification
task is complete. This includes local Docker images, build caches, disposable test containers,
temporary files, and generated build outputs. This is standing authorization, including artifacts
from earlier sessions when ownership and task completion are established; neither a merged commit
nor a registry copy is required. Check current references and active tasks, then verify and report
removal. Preserve active resources, deliverables, unique source changes, and persistent data; the
profile's confirmation rules still apply to protected deletions.
