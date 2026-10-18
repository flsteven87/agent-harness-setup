# Synthesis note

One note in the repository's research location; a new one is `<topic>-benchmark-<date>.md`,
status `evidence note — not an owner decision`, in the owner's language. Keep the eight sections
below in this order, headings translated, "not applicable" stated where a section has nothing.
The first screen carries the diagnosis and the decisions, because the owner acts from it.

## Head

Research date, the tracks and what each covered, where the full reports sit (appended), and the
baseline compared against: the design target at its revision and the contract. Then the
spot-check paragraph: which claims you inspected yourself, which repository claims you confirmed,
and what was qualified or excluded.

## 一 Diagnosis

The strongest supported explanation, connecting observations to reader consequences. Separate
contract drift from a proposed contract change and from unresolved causes; keep multiple causes
separate when the evidence supports more than one. Add a positioning finding only when the
research supports it.

## 二 Supported changes

Numbered findings. Each states the observed problem, the reader consequence, the source or
measurement, the contract it touches, and the proposed correction, with direct evidence separated
from inference. Record consequential disagreement here and why the adopted reading is stronger.

## 三 Visual layer

Which values are right and stay, which usages are wrong, what is dated, and what the platform
changed since the contract was written.

## 四 Preserve

A table of existing choices the evidence supports, each with its evidence. It protects the
owner's earlier decisions from a pass that would relitigate them.

## 五 Owner decisions

At most three for the current pass. Each states the evidence on both sides, the cost of changing a
hard rule or prior decision, one recommendation, and the changes that depend on it. Further
decisions are listed as deferred with their dependent changes.

## 六 Change table

Stable change IDs. Each row: the change, the finding and recommendation IDs it rests on, the
affected surface and owner files, its decision dependency, an observable acceptance condition, and
status. The table defines the proposed pass; the gate decides which rows enter it.

## 七 Verification boundary（查證邊界）

What no track could verify, secondary sources, quota exhaustion, and what the note did not compare
against: native code, other locales, accessibility sizes.

## 八 Per-surface plan and execution order

The design principle in one bold sentence, then each affected surface's composition, controls and
states by change ID, the matrix to render (widths, appearances, locales, states), and the work
ordered by dependency with documentation reconciliation and final verification last. Downstream
implementation stays outside the pass.

## Appendix

Each dispatched track's report appended whole under its track ID and title, heading levels
demoted to nest. The synthesis owns the merged judgment; the reports keep their evidence and
disagreements.
