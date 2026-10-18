# Business-First Engineering Reporting Contract

Daily and multi-day engineering reports explain why work mattered, what changed, what the contributor
directly did, and what proves the claim. Engineering activity is evidence, not the story.

## Business chain

Build one chain for every candidate:

1. **Why now** — customer workflow, operating burden, commercial constraint, or material risk.
2. **Completed change** — shipped action or completed production operation.
3. **Result** — exact behavior or stored state that changed.
4. **Proof** — runtime evidence, before/after measurement, or bounded shipped scope.
5. **Next gate** — only when it changes what the business can claim.

The first four links require evidence. Record a gap instead of filling one with inference. Centralize
next gates rather than repeating them beneath outcomes.

## Evidence ledger

For every candidate, record:

- affected user or operating object, before-state, and why it mattered;
- contributor's direct action and merged or executed scope;
- **change fingerprint**: the smallest exact implementation or data-shape fact that distinguishes this
  intervention from adjacent work—changed field or object, old ownership/shape, new ownership/shape,
  and the user-owned facts deliberately retained;
- data state: `none`, `prevented`, `inventoried`, `repaired`, or `verified`;
- proof and status: `已觀察`, `已交付`, `下一關`, or labeled `推論`;
- next business gate and configured tracker or review anchors.

Use the configured tracker and incident evidence for problems and causes; first-parent Git diffs for
merged scope; review records for intended scope and validation; runtime observations or independent
measurements for production results. Authored work or a recorded operational action proves
contribution. Assignment, tracker status, and review attachment alone do not.

Classify every candidate as selected, combined, or omitted. Keep the ledger in working notes.

## Data work

Treat migrations, repairs, backfills, cleanup, reconciliation, dry-run/execute sequences, production
re-scans, and operational scripts as data-work candidates. Establish:

1. total population inspected;
2. affected population and newly discovered subgroups;
3. inventoried, proposed, executed, or independently verified state;
4. material safeguards;
5. before/after state, conflicts, refusals, and failures;
6. restored customer or operating workflow.

Separate prevention from historical correction. Lead with the total repair, then qualify risk
subsets. If `{risk_band_count}` is part of `{repaired_total}`, write `已修正 {repaired_total} 個既有
項目，其中 {risk_band_count} 個高風險項目已降為 0`—not `{risk_band_count} 個項目已修復`.

Name thresholds precisely: measured value, numerator, denominator, unit, internal safety budget, and
hard limit. Call a dry-run preparation; call data repaired only after an executed, verified run.

## Selection and writing

Rank outcomes by:

1. customer or commercial workflow enabled or restored;
2. production data corrected or trust restored;
3. repeated operating work removed;
4. risk reduction protecting a named workflow;
5. internal maintenance with a concrete consequence.

Cluster by business chain, not commit, review, tracker record, or architecture layer. Completed or observed
results dominate the opening; remaining work stays in its dedicated section and is shorter.

Lead with the user or object and what happens now. Follow with why the company cares. Keep mechanisms,
tracker and review anchors, and validation machinery in quiet evidence. Use the exact product nouns
owned by the repository's domain vocabulary. Attribute shared work neutrally and use numbers only
with a source and interpretable baseline.

### Change-fingerprint gate

Business compression preserves the mechanism detail that changes how a reader interprets safety,
recurrence, or the next decision. Surface the change fingerprint immediately under the outcome when
it does any of the following:

- distinguishes two interventions that would otherwise both read as `瘦身`, `修復`, `改成有界`, or
  another generic action;
- explains why data could be removed, moved, or recomputed without losing a user-owned fact;
- identifies which growth path was closed and which materially different path remains open;
- explains why a backfill was safe, partial, unnecessary, or still separately gated.

Write the plain-language ownership change and retain the exact field or object in `code`, for example:
`移除會員計畫 content[].map 的路線副本；Activity 保留唯一可讀版本`. List sibling fields only
when the set defines the safety boundary; otherwise name the representative field and the retained
facts. Keep lower-level call paths and helper names in quiet evidence.

Before publishing, compare every pair of related outcomes after mentally removing dates, counts, and
tracker identifiers. If two materially different changes collapse to the same description, restore the
minimum change fingerprint that makes their different data owner, shape, or protected fact explicit.

## Audits

- **Chain:** supported why, action, result, and proof.
- **Data:** every data-work candidate accounted for; prevention and repair separated.
- **Balance:** completed outcomes dominate; open work is centralized.
- **Attribution:** direct, shared, and inferred outcomes remain distinct.
- **Precision:** statuses, populations, units, thresholds, and before/after values match evidence.
- **Fingerprint:** related changes remain distinguishable by exact data owner, shape, or field, and
  every removal names the user-owned facts retained.
- **Gate:** each gate names the business condition and observable done state.
- **Reader:** a founder, commercial lead, or operations lead can explain why each item matters without
  repository vocabulary.
