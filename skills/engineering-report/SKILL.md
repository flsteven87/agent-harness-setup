---
name: engineering-report
description: Report engineering work as business outcomes from Git, review, tracker, runtime, and data-work evidence. Use for a standup, morning update, weekly report, engineering review, or a named date-range review.
---

# Engineering Report

Explain why the work mattered, what changed for users or operations, what the named contributor or
team completed, and which conditions still gate the next business claim.

## Resolve the window and profile

An explicit window, title, format, or request for highlights or full coverage overrides the default.
Apply one profile.

- **Standup** — a daily standup, morning update, or single-day request. Read
  [the standup profile](references/standup-profile.md) and return its block inline unless the user
  asks for a file.
- **Executive** — a weekly report, engineering review, multi-day window, or HTML request. Read
  [the executive profile](references/executive-profile.md).

## Resolve adapters from the repository

Read each target repository's `AGENTS.md` and the context files it names. Take the contributor and
their Git author aliases, the inclusive start and exclusive end plus timezone, the repositories and
branches, the tracker and review-host adapters, domain vocabulary and privacy rules, and report
authority from the request and the repository rather than from a default carried in here. Default
repository scope to the current repository, and disclose any identity or timezone you had to assume.

## Gather evidence

Discover aliases with `git shortlog -sne --all`, then run
[the bundled collector](scripts/collect_git_activity.py) once per repository; its `--help` carries
the current flags. It reads local refs and never fetches, so remote staleness is an evidence gap
unless fetching is separately authorized. Keep its JSON in a temporary file rather than in context.

Attribute development from the original non-merge commits and their actual changes. For a PR,
inspect its constituent commits; for a merge, inspect the merged branch's commits. Record exact
Git author identities and the supported delta in working notes. A PR opener, merger, or squash
commit identity alone does not establish who developed its contents. Exclude other authors' work
from the contributor's accomplishments even when the contributor opened or merged the PR. For a
mixed-author change, include only the selected author's identifiable development; mark unresolved
ownership as a gap. Attribute a follow-up fix to that fix, keeping the pre-existing feature as context.

Honor the contribution scope. A development-only report includes authored code, tests, tools, and
configuration changes; documentation-only, observation-only, and release-only activity stays out
of its accomplishments. Operational results may substantiate an authored change, but attribute
personal execution only when the operation record identifies the actor. A broader engineering
report may include documented operations and maintenance when requested by its scope.

Account for every in-window mainline commit by the selected identities, reading full commit bodies
and first-parent diffs for delivered scope. Sweep separately for data work — repairs, backfills,
migrations, cleanup, reconciliation, dry-run and execute records, production scans — and establish
for each whether it was proposed, executed, or independently verified. Tracker status and PR
attachment are business context; neither proves implementation, deployment, or user outcome. When
the configured tracker transport is unavailable, continue only on bounded claims the remaining
evidence supports, and name the coverage gap.

## Synthesize and publish

Read
[the shared reporting contract](../../references/business-first-engineering-reporting.md)
and complete its evidence ledger for every candidate, including candidates later combined or
omitted. Cluster by user or operating outcome across repositories, tracker records, reviews, and
days, keeping recurrence prevention distinct from historical correction. Apply the profile only
after the ledger is complete.

Update an existing report in place. A new Executive HTML artifact starts from
[the report template](assets/report-template.html) — translate its fixed labels when the report
language is not Traditional Chinese — and passes
[the format validator](scripts/validate_report.py) once after the last edit; it includes the shared
rendering gate. `$html-report-system` owns that artifact's destination, lifecycle, and rendering
contract.

## Completion

Complete when every candidate and data-work operation is selected, combined, or omitted in working
notes; the selected profile's coverage and causal-evidence checks are complete; every published
outcome carries a why, an action, a result, and either proof or a named evidence gap; the contributor
scope, window, evidence cutoff, and source gaps are visible in the report itself; and the selected profile's acceptance checks pass.
