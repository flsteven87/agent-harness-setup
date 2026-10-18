---
name: design-benchmark
description: "Benchmark an existing design target (the SSOT HTML or equivalent) against current industry evidence: parallel research tracks on the strongest model, one synthesis, an owner decision gate, one verified redraw. Use when the owner asks to research or benchmark how the category designs a surface (派 Opus 研究業界、派 agent 研究業界), when polish rounds on a design have stalled and the owner wants outside evidence, or to apply an approved benchmark synthesis."
argument-hint: "[surface or design question to benchmark]"
---

# Design benchmark

Parallel **tracks** gather evidence. One **synthesis** turns it into decisions. The **decision
gate** records the owner's authorization. One **pass** applies and verifies the approved design.
Rounds of local polish stall for a reason polish cannot see: the design has drifted from its own
contract, or the contract is wrong, and only outside evidence says which.

## Entry

- New benchmark: start at step 1.
- Synthesis exists, authorization pending: start at step 5.
- Synthesis exists and is authorized: read the note, the current target and contract, and the
  authorization; when the approved changes still apply, start at step 6 and reuse the research.

## 1. Intake

Write one intake note in the scratchpad holding:

- the affected user task, the owner's concern, and the observable outcome to improve;
- the design target, its revision and relevant uncommitted changes, its contract and vocabulary
  owners, and the repository's gate and rendering entry points;
- the owner's relevant confirmations and rejections with source locations, exact words where
  they exist and paraphrases labelled as such;
- screenshots covering the named surfaces and states, each with viewport, appearance, locale and
  scale; reuse captures that match the current target, render the missing or stale ones;
- the repository's existing research, with what each note already establishes and the gap left.

Done when each input is present or marked unavailable, each screenshot is tied to the recorded
revision, and each research question carries enough context to dispatch on its own.

## 2. Dispatch the tracks

Define a **Flows** track (the user loop and information architecture across the category's
shipping products) and a **Components** track (platform guidance, visual language, measurements
of the screenshots). Add a **Differentiator** track only for a distinct unresolved mechanism the
two cannot cover, such as a product's AI-understanding presentation or its change-preview-publish
loop.

Write each brief from [`references/brief.md`](references/brief.md): an owned question,
exclusions, source families, record unit, output path. Launch the tracks together as
independent read-only research subagents on the strongest configured model (in Claude Code, `general-purpose` on `model: opus`), and name the shared browser tools they leave to you.
While they run, own the baseline: the claim-comparison structure for step 3 and any measurement
only the main session can take.

Done when every assigned question has an evidence-backed answer or a named gap, every report
carries recommendations with stable IDs, a sources list and a verification boundary.

## 3. Spot-check

Identify the claims that support a proposed change or an owner decision, then:

- inspect their sources yourself: wording, context, date, applicability to this product;
- check repository claims against the recorded revision and measurements against their stated
  conditions;
- rule on consequential disagreements by evidence quality and product fit; two tracks citing the
  same source count as one source.

Done when every premise behind a proposed change is confirmed, qualified or excluded with its
reason recorded, and each unresolved premise is written down as a research gap or an owner
tradeoff.

## 4. Synthesis

Read [`references/synthesis.md`](references/synthesis.md) and write one note in the repository's
research location, in the owner's language; continue the existing note when the benchmark already
has one.

Done when every proposed change has evidence, a decision dependency and an observable acceptance
condition, every consequential disagreement has a disposition, and the surface plan contains only
changes present in the change table.

## 5. Decision gate

Report on one screen: the diagnosis, the strongest findings, what to preserve, and the decisions
the proposed pass depends on, each with a recommendation. Record the owner's authorization and
each decision's disposition: accepted, rejected or deferred. Explicit full authority (「全權授權」)
means the recommended option on every open decision, recorded as accepted under that authority.

Done when the pass has an authorized change list and every decision it depends on is resolved;
otherwise stop here with the pending decisions. A deferred decision keeps its dependent changes
out of the pass.

## 6. The pass

Apply the authorized change IDs in the synthesis's execution order:

1. Record the baseline gate result, then change the SSOT and the affected contract together. A
   gate assertion changes only when an accepted contract change supersedes it; checks for
   behaviour still required stay.
2. Write one decision-log entry: accepted choices, rejected alternatives, evidence. Respect the
   repository's design-to-native boundary: change a mechanically coupled native value only when
   that specific change is authorized, otherwise record it as pending.
3. Run the gate and render the agreed surface, appearance and locale matrix. Read every capture,
   collect the corrections into one batch, apply them, then rerun the affected checks and captures.
   A new design question at this point is escalated, not polished.
4. Commit the research note and the design pass separately; reuse an existing unchanged research
   commit.

Done when every accepted change ID has final verification evidence on the final candidate, the
gate passes on it, the final captures match it, and the contract and log agree with the design.
Close with the commit IDs and the deferred work: native implementation, vocabulary changes,
positioning. Incomplete verification is reported as incomplete.
