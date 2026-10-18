---
name: html-report-system
description: Place, render, and validate self-contained HTML reports under repository documentation policy, tuned for laptop browser reading. Use for a delivered report, an HTML mirror, or a report template.
---

# HTML Report System

Own the placement and rendering quality shared by self-authored HTML reports. The active domain
skill owns what the report claims, which evidence supports it, and its report-specific sections.

## 1. Resolve the destination

Read [the output policy](references/output-policy.md) and resolve the exact artifact owner, project
path, naming rule, and lifecycle before writing.

## 2. Write the report

Resolve visual authority. A product surface inherits its repository design system. A standalone
editorial report keeps the token set owned by its report template. Preserve an owned domain template;
when none exists, start from [the neutral foundation](assets/report-foundation.html) and replace its
tokens.

Read [the rendering contract](references/rendering-contract.md) when writing document structure, CSS,
layout, tables, diagrams, disclosures, or print behavior. Read
[the writing contract](references/writing-contract.md) when writing the identity, thesis, summary, or
narrative organization.

## 3. Pass the rendering gate once

The validator is the **rendering gate**: it renders the report in a real browser at 768 and 1200 px
and fails on the layout defects the rendering contract names. A clean run is the rendered
observation report delivery requires.

Run the gate once, after the last edit:

- A domain skill with its own validator runs that one command; it includes this gate.
- Otherwise run `python3 <skill-dir>/scripts/validate_html_report.py <report.html>`.
- Add `--portable` when mobile or print reading is in scope; add `--template --portable` for an
  owned unfilled template.

Fix every reported error in one batch, then rerun. Open or screenshot the page only to locate a
finding the error message does not pinpoint, or when the user asks for a visual design review.
When the browser pass cannot run, report that the layout is unverified.

## Completion

Complete when the gate exits clean for the delivered file with every warning reviewed; the identity,
thesis, and summary satisfy the writing contract when they changed; and the delivered paths satisfy
the output policy.
