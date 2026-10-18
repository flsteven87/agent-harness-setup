# Issue tracker: GitHub

Issues for this repository live as GitHub issues in `flsteven87/agent-harness-setup`.

Use `~/.local/bin/gh` with repository context and the intended GitHub account authenticated.
Prefer a connected GitHub app for discovery, metadata, and summaries when one is available;
use the CLI for Actions logs, GraphQL review-thread state, and any workflow that requires it.

## Conventions

- Infer the repository from `git remote -v`.
- Treat create, comment, label, close, and assignment as external writes and confirm they are within
  the user's request.
- Read the issue body and relevant comments before acting.
- Make issue bodies cold-start ready: problem, evidence, desired outcome, constraints, acceptance
  criteria, and source pointers.

## Pull requests as a triage surface

**PRs as a request surface: no.**

GitHub shares one number space across issues and pull requests. Resolve a bare number against both
types before assuming which surface it identifies.

## When a skill says "publish to the issue tracker"

Create a GitHub issue.

## When a skill says "fetch the relevant ticket"

Read the issue and its comments through `gh issue view <n> --repo flsteven87/agent-harness-setup`.

## Wayfinding operations

Used by `/wayfinder`. The map is one GitHub issue with child issues as tickets.

- **Map:** label it `wayfinder:map`.
- **Child ticket:** use GitHub sub-issues when available. Otherwise link it from the map task list
  and add `Part of #<map>` to the child.
- **Ticket type:** use `wayfinder:<type>`, where type is `research`, `prototype`, `grilling`, or
  `task`.
- **Blocking:** use GitHub native issue dependencies. If unavailable, add a `Blocked by: #<n>` line
  to the child.
- **Frontier:** an open, unassigned child whose blockers are all closed.
- **Claim:** assign the current GitHub user.
- **Resolve:** comment with the answer, close the issue, and add the resulting context pointer to the
  map's Decisions-so-far section.
