# Strategic Review Report Contract

Read this reference after the evidence ledger, program chain, and strategy are complete. Also read
[`../../../references/business-first-engineering-reporting.md`](../../../references/business-first-engineering-reporting.md)
and apply its evidence, data-work, attribution, precision, and business-chain rules.
`$html-report-system` owns report identity, conversation-derived material, rendering, and the
rendering gate.

## Reading contract

The report serves PM, engineering, and the operation that received the user report. The visible path
starts with consequence and decision; technical evidence remains close enough for an engineer to
challenge the causal model.

The first viewport must answer:

- What topic, episode, or user experience is being reviewed, and why now?
- What is now confirmed, contradicted, and unresolved?
- Which intended outcomes are real, partial, or still unproven?
- What action should happen first, and why?

## Narrative structure

Use the following reading order. Omit a body section only when it has no decision-changing content;
retain the evidence gap in the limitations.

1. **Executive verdict** — one causal synthesis, closure state, and top recommendation.
2. **Topic reading** — each initiating claim or objective, what evidence changed, and concrete impact.
3. **User journey** — actions, surfaces, expected promise, actual result, and lowest-trust step.
4. **Program connection** — responsibility boundaries from authoring through delivery and measure.
5. **Findings and root causes** — one card per material capability, gap, or cause with confidence,
   current status, mechanism, and limitation.
6. **Business impact** — separate effects on users, operators, delivery, and the operating model.
7. **Current status** — product promises grouped as verified, partial, unresolved, or residual with
   tracker and delivery evidence.
8. **Evidence at scale** — bounded populations, severity, exclusions, and historical-state status.
9. **Future contracts** — current gap, recommended authority or truth contract, and observable result.
10. **Strategy spine** — gated phases, owners, dependencies, exit gates, and parked work.
11. **PM decisions** — product rules requiring approval and their tradeoffs.
12. **Outcome gate** — exact evidence required before claiming the intended result; include incident
    closure criteria when an incident is part of the subject.
13. **Scope, limitations, and evidence** — timestamps, identity gaps, validation, source paths,
    tracker census, and consultation reconciliation.

## Visual grammar

Use two or three visuals only when they explain relationships better than prose:

- a user journey or trust curve;
- a responsibility or data-flow diagram showing where each break originates;
- a phased execution spine or current-to-target contract comparison.

Use inline SVG only when it materially clarifies a relationship, and include a readable fallback.

Prefer one strong executive panel, clear section numbers, restrained status chips, compact evidence
tables, and generous spacing. Depth comes from the causal and evidence model, not from dense cards.

## Evidence presentation

- Label claims as confirmed, strong inference, bounded inference, unresolved, or adjacent.
- Put tracker links and local evidence paths beside the claim they support.
- State source, cohort, denominator, unit, and timestamp for every scale number.
- Show implementation, merged, deployed, and user-verified as distinct states.
- Preserve correct neighboring behavior beside each defect so the strategy does not broaden harm.
- Put full tracker and source ledgers in native `<details>` appendices when they interrupt the PM path.
- Redact personal data and secrets. Use the minimum identifiers needed for closure.

## Output mode

Use the resolved project destination. When the repository declares a governed strategic-report
owner, read it completely and use governed mode:

1. Find the stable topic Anchor at the policy-owned path and treat it as the prior position, not proof
   that every claim remains current.
2. Ask whether the investigation changes the direction, a material claim, the responsibility
   boundary, or the next evidence. Update the Anchor to the depth those answers justify; leave it
   alone when the consequence is immaterial.
3. Keep the complete narrative and evidence in Markdown. Generate the sibling `report.html` with the
   repository template; the HTML is a human Mirror, never a second editable source.
4. State incomplete evidence plainly. Let the report remain useful without forcing a settled verdict
   or a lifecycle label.

The repository guidance owns stewardship, paths, and presentation. Prefer the stable Anchor over
`latest`, `r2`, or dated parallel copies; Git preserves earlier positions.

When policy instead assigns a derived HTML destination, start from `$html-report-system`'s neutral
foundation and follow that path's naming and lifecycle rules. Do not overwrite another report.

## Rendering gate

Pass `$html-report-system`'s gate once after the last edit; it owns layout, first-viewport placement,
and print disclosure. Confirm in the source that the first viewport block answers the reading
contract.

## Integrity review

Before delivery, use the questions that matter for the report's evidence and decision scope:

1. Can the reader find each initiating claim or objective in the topic reading?
2. Can each material finding be traced to evidence and a responsibility boundary?
3. Do current-status totals and tracker IDs agree with the supporting evidence?
4. Do consequential scale numbers explain cohort, denominator, unit, time, and source?
5. Do production claims explain how and when they were verified?
6. Does the strategy address the confirmed causes without merging incompatible authority gates?
7. Does each PM decision change a product contract instead of restating implementation?
8. Does the outcome gate cover the initiating objectives and distinguish deployed from verified?
9. Are secrets, unnecessary personal identifiers, and broken paths absent?
10. Can the first viewport be understood without repository vocabulary?
11. In governed mode, do the Markdown Anchor and HTML Mirror communicate the same conclusions,
    uncertainty, and next decision to their different readers?
