---
name: strategy-review
description: Investigate a topic, delivery episode, or incident into an evidence-backed product and engineering strategy. Use for cross-system causes, target contracts, and a gated execution spine.
---

# Strategy Review

Turn one topic, delivery episode, or incident into a strategy grounded in current evidence. Keep the
initiating user or operating concern in view, and expand only as far as corroborated causes,
affected data, delivery contracts, or strategic dependencies require.

This skill is read-only. Recommendations, consultations, and reports authorize no tracker, data,
deployment, instrumentation, production, or other external write without separate authority.

## Route the request

- Continue here when a topic, episode, incident, support thread, or change cluster needs a
  cross-system inventory, a target state, and a next-step plan.
- `$diagnosing-bugs` owns one bounded defect needing a tight reproduction and fix.
- `$milestone-dispatch` owns program scope, dependencies, the current execution frontier, and the
  next implementation slice once the program is selected.
- `$engineering-report` owns time-boxed contributor or team reporting.

## Anchor the subject

Read the target repository's `AGENTS.md` and the startup or context files it names, and resolve its
configured tracker, review host, production evidence path, domain vocabulary, report policy, and
authorization boundaries rather than assuming a vendor or artifact location. Where repository policy
names a governed strategic-report owner, read its current report as a prior position and decide
whether current evidence changes its direction, risk, or next decision.

Split the subject into atomic **threads** — user promises, observed symptoms, delivered
capabilities, data states, architectural boundaries, open decisions — each carrying its affected
person or operation, expected outcome, current claim, time horizon, and missing evidence. Record the
evidence timestamp and which surfaces can be inspected. Prior reports and tracker prose are
hypotheses. Keep personal data out of working notes and the artifact, using stable internal
identifiers only where the outcome gate needs them and displaying them is safe.

## Build the evidence ledger

Read [the investigation contract](references/investigation-contract.md) and execute it.

Live tracking evidence comes from the repository-configured adapter, merged and release history from
the configured review host. Reach for `$use-code-review-graph` on broad code fan-out only where the
repository enables it and its freshness gate passes, then confirm every material claim in current
source. Production inspection stays read-only; missing access is an evidence gap, never an inferred
result. Use a tight reproduction for numerical or deterministic behavior that would change the
conclusion, and hand a hard bounded cause to `$diagnosing-bugs` rather than weakening its
reproduction standard inside this review.

**Done when:** each thread carries a consequence, verdict, confidence, causal chain, delivery state,
affected-scale evidence or explicit unknown, tracking disposition, and checkable closure evidence.

## Model the program

Connect the threads into one **chain** from the user's or operator's action through authoring,
persistence, projection or delivery, execution, and measurement, naming responsibility boundaries by
product object rather than by service or file. At each boundary identify the authority that owns the
truth, the handoff that carries it, what success currently means, what evidence proves terminal
success, and whether the boundary originated the wrong state, faithfully carried it, or merely
exposed it. Adjacent work enters the strategy only when it changes user value, operating risk,
delivery order, outcome evidence, or the target contract.

**Done when:** a reader can trace every material outcome or failure to its boundary, distinguish
origin from carrier from observer, and see which causal or delivery claim is still open.

## Form and challenge the strategy

Once the ledger and the chain meet their criteria, read
[the strategy contract](references/strategy-contract.md) and convert the causal model into target
product contracts, PM decisions, a gated execution spine, and outcome gates. Preserve the user's
stated priority principles, and keep stabilizing behavior, proving delivery, consolidating
authority, repairing historical data, enabling scale, and preventing recurrence separate unless one
change under one authority gate genuinely closes more than one.

Form the primary conclusion — verdict, strongest evidence, assumptions, unresolved threads, proposed
strategy — before inviting challenge; an independent consultation receives the raw artifacts and
reconciled evidence paths without the proposed ranking. Reconcile every decision-changing challenge
against current sources, and record adopted corrections, rejected claims with reasons, and
unresolved disagreements in the evidence appendix.

## Publish

When the output is a report artifact, read [the report contract](references/report-contract.md).
`$html-report-system` owns the destination, lifecycle, rendering contract, and validation; reconcile
a governed source or create the permitted derived HTML view as repository documentation policy
directs. Keep the narrative useful to product and operations while retaining enough causal and
interface detail for engineers to challenge it, with implementation paths, queries, tracking census,
and consultations in quiet evidence near their claims or in disclosed appendices.

## Completion

Complete when the strategy traces from the initiating concern through current behavior, causal
findings, affected scale, target contracts, and execution gates to the evidence required to claim
the intended outcome; the target state removes the confirmed cause rather than adding a fallback;
each phase has a business outcome, scope, prerequisites, owner role, observable exit gate, and
parked work; every challenge that could move a root cause, affected scale, contract, phase order, or
closure gate is resolved or displayed as uncertainty; and the user has the artifact paths plus the
remaining evidence and authority gaps. Tracking coverage alone never satisfies this.

When the output includes a report artifact, completion also requires its integrity review and the
shared rendering gate to pass, and its first viewport to state the verdict and recommendation.
