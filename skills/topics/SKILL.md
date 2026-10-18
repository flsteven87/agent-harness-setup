---
name: topics
description: Compare engineering topics as business outcomes and recommend which one deserves the next unit of attention, from current repository, tracker, delivery, and ownership evidence. Use when the decision spans workstreams.
---

# Topics

Choose the business outcome that deserves the next unit of engineering attention. A **topic** is one
user or operator outcome, not a ticket cluster or an implementation mechanism.

This skill is read-only. Its recommendation authorizes no change to code, trackers, worktrees,
agents, deployments, production, or other external state.

Hand off when the decision is not actually between topics: `$milestone-dispatch` owns program scope,
dependencies, the execution frontier, and the next implementation slice once the outcome is
selected; `$strategy-review` owns cross-system causes, target contracts, and the execution spine for
one selected topic; `$audit-pr-topics` owns one contributor's pull requests; name `$wayfinder` when
an idea is still too unclear to state as a product promise.

## Form the topics

Read repository instructions and use the evidence surfaces they configure. Reconcile current source,
Git, tracker, delivery, and active ownership, treating prior reports and recommendations as locators
to revalidate. Start with cheap metadata and active artifacts, group explicit hierarchy and shared
delivery evidence into business outcomes, then hydrate only the candidates that could plausibly win.
Widen the horizon when an older or quiet topic could change the choice: a user-supplied window bounds
the report, not what counts as material contrary evidence.

Establish for each candidate the affected user or operation and its observable outcome, the
remaining outcome delta independent of ticket count, the consequence of waiting and the
reversibility of harm, closure or unlock leverage, current evidence and its confidence, and active
ownership, dependencies, and required authority. Current source and delivery evidence decide what
exists; tracker state describes tracker workflow and product intent, and never proves delivery.

**Done when:** every candidate that could change the choice is one distinct outcome with a verified
remaining delta, or is excluded for a visible reason.

## Choose the next topic

Use judgment rather than a score. Give priority to material harm, irreversible risk, closure of a
nearly finished outcome, and bounded work that unlocks several valuable successors. Prefer the
user's declared priority unless current evidence shows it delivered, stale, already owned, blocked,
or dominated by a more consequential outcome.

Challenge the apparent winner:

- Would it still win without recency, ticket volume, or current-session momentum?
- Is its claimed outcome present in current code and delivery evidence?
- Does another topic carry more irreversible or better-confirmed harm?
- Can it proceed under current ownership and authority?
- Is it a product promise rather than a proposed mechanism?

Inspect more evidence only where it could change the winner. When no responsible choice survives,
state the decision gap instead of manufacturing a ranking.

## Deliver the brief

Lead with the recommendation, then the chosen outcome and why it matters now, what remains and the
evidence grounding it, the runner-up and why it waits, the evidence or decision that would change
the choice, and the tentative boundary, authority gaps, and next skill. Treat the brief as a
hypothesis for `$milestone-dispatch` to revalidate against live evidence.

**Complete when:** one topic wins, the runner-up loses for an evidence-backed reason or the exact
gap preventing a responsible choice is explicit, and the downstream skill can rediscover the
supporting evidence without this analysis transcript.
