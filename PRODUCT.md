# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

One owner who runs several products at once through Claude Code and Codex agents. The user-facing
surfaces of this workspace are local HTML pages the owner reads on a Mac laptop browser: at the
start of the day and at a few fixed checkpoints (for example 11:00, 15:00, 18:00).

## Product Purpose

Let the owner work as a manager rather than a switchboard: see every product's state, the decisions
waiting on them, and what is stuck, without opening each repository and running `/catchup` or
asking an agent "what is the status now?". Success is that those per-repository catch-ups and status
questions stop being how the owner learns the state of their products.

## Operating Context

- Repositories are the ones registered in Orca (`orca repo list`); each keeps its shared checkpoint
  in `<primary-checkout>/MEMORY.md`, written by `handoff`.
- Agents work in the primary checkout or in dispatched Orca worktrees; pull requests live on GitHub.
- The owner answers a decision inside the owning repository's session; the page's button opens that
  session in Orca with the choice already stated.

## Capabilities and Constraints

- Pages are generated from repository evidence (MEMORY.md, Git with remote refs fetched from origin,
  `gh`); they never send data to an external service.
- A page's buttons launch work through a launcher on this machine: only the actions the page shows,
  each with its exact text visible before the click, and each launched once.
- Traditional Chinese for page copy; repository identifiers and commit subjects stay as written.

## Product Principles

- Decisions first: what waits on the owner leads every page.
- Key points only: objective and next action in plain language; engineering detail stays in the
  repository, not on the page.
- Evidence over claims: every row traces to a file, a commit, or a pull request.
