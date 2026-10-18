---
name: audit-pr-topics
description: Group a contributor's pull requests into topics, then judge each topic's business intent, regression risk, data work, and remaining tickets. Use to find PR themes, assess PR risk in depth, or pick the next lower-risk topic.
---

# Audit PR Topics

Judge topics rather than isolated pull requests: the unit of decision is the deployed behavior a
group of PRs produces, not the merge event.

## Pin the scope

Read repository instructions, and read `docs/agents/issue-tracker.md` before the first ticket lookup
so the configured tracker workflow is used rather than one inferred from installed tools or the Git
remote. PR evidence stays on the repository host. When that file is missing and no explicit
repository instruction replaces it, mark ticket coverage incomplete and name
`$setup-matt-pocock-skills` for the user to run.

Resolve the contributor — prefer the explicit handle, and for "my PRs" the repository-aware GitHub
identity — and the horizon, which these words fix:

- "open" or "current" PRs means open PRs only.
- An unspecified topic audit means open PRs plus PRs merged in the last seven days.
- "next topic" continues newest-first through the horizon already declared; widening it requires
  saying so first.

State contributor, PR states, date window, repository, and review fixed point before analysis.

## Form topics

Group PRs sharing an issue, incident, subsystem outcome, data contract, or
implementation→revert→restoration chain, and treat the final deployed behavior as the topic head.
Adjacent merge times alone do not join two topics. When the user anchors one PR, follow its revert,
restoration, and supersession chain outside the horizon as context-only, distinct from the in-scope
count.

Per topic, gather PR metadata, bodies, commits, files, checks, reviews, and the exact diff; linked
tracker issues with their relations, comments, status history, and acceptance criteria; the specs,
ADRs, and rollout instructions that apply; and production observability or data evidence where
read-only access exists. Label every claim as repository fact, external-system fact, inference, or
unverified gap.

## Judge each topic

Run `$code-review` against the exact PR base/head or before/after merge commits for code-bearing
topics, preserving its Standards and Spec axes separately. Report the exact commands or suites run,
pass/fail/skip counts, whether failures touch the diff, and which real integrations remain
untested. Classify risk in three lanes that stay separate:

- **Change regression** — behavior newly changed by the topic.
- **Residual system risk** — known defects the topic deliberately leaves in place.
- **Delivery risk** — rollout, configuration, data, or operational uncertainty.

Then establish, for each topic, the plain-language user, revenue, support, compliance, or
operational outcome; a Low/Medium/High rating per risk lane with a confidence ceiling that names the
remaining integration and rollout gaps; whether the PR slice and the business topic are separately
complete; the migrations, backfills, queue drains, reconciliation, cleanup, retention, duplicate,
and irreversible-loss exposure plus the read-only evidence still needed before any mutation; and the
decisions and tickets that still gate the topic's true endpoint. When the user wants a lower-risk
next topic, keep High-risk topics in a visible skipped list and continue.

## Read ticket state as evidence

Trace identifiers from PRs, commits, ADRs, direct parent/child relations, and issue comments. Stop
after one relation hop, and include a related ticket only when its acceptance criteria change this
topic's completion condition; a shared parent stays context without expanding its siblings.

`Done` means that ticket's own acceptance criteria completed, so inspect its children before calling
the topic complete. `Canceled` means the work left scope: report from the comments whether the
defect still exists, and translate it as de-scoped unless evidence proves a fix. `Backlog`, `Todo`,
`In Progress`, `In Review`, and `In Testing` are unfinished. Mark inferred relationships as
inferred.

## Completion

Complete when every in-scope PR belongs to exactly one topic with evidence for the grouping, each
risk lane carries evidence, every failed or missing gate is accounted for, and the recommendation —
advance, advance after named gates, park, or skip to the next topic — distinguishes merge readiness
from production readiness from topic closure.
