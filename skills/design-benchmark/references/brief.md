# Track brief

Write one self-contained brief per track from the intake note. Include these parts, with record
fields and coverage matched to the track's question.

## Parts

1. **Role and date.** `You are a senior <product|UI|AI-UX> designer doing a <benchmark|pattern|evidence> study. Today is <date>.`
2. **Evidence and tool boundary.** Use WebSearch to find sources and WebFetch to inspect them; verify every claim about current products and guidance rather than recalling it. Attach the URL and, where it matters, the date or version, plus the evidence type: first-party text, inspected image, secondary report, search snippet, inference. Distinguish "not found" from "absent". Name the shared browser tools reserved for the main session. Repository access is read-only; the assigned report is the only file written.
3. **Context.** Three to six sentences: what the product is, its sitemap and vocabulary, what the owner just rejected and confirmed, and that the owner wants the design target fully satisfying before implementation.
4. **Read first (read-only).** Paths to the product contract, vocabulary, the interface contract sections that bind, the latest decision-log entries, the screenshots (`use the Read tool to view them`) with their viewport, appearance, locale and scale, and the existing research the track must go beyond, one line each on what it already covers.
5. **Scope and coverage.** The owned question, its exclusions, the adjacent tracks, and the gap beyond existing research. A prioritized source list with a coverage floor the question justifies; direct competitors and contrasting exemplars; verify whether each product ships on the target platform and label historical examples.
6. **Record unit and fields.** Choose the unit that answers the question: product, component situation, or mechanism. Name its required fields and how to mark unavailable evidence. Keep exact labels where wording matters. Cite inspected images separately from image links merely found. For measurements, name the screenshot, viewport, appearance, locale, scale and method, and separate measured values from source values and estimates.
7. **Judgment.** Convergence, meaningful counterexamples, and fit to the named product constraints. Each recommendation carries a stable ID (`<track>-R<n>`), its evidence, the affected surface, the expected reader consequence and any contract it depends on. Classify each divergence from the current target as a defect, a defensible divergence, or a proposal needing an owner decision. Name the supported choices to preserve. Every assigned question ends in a recommendation, a supported preserve judgment, or a specific gap.
8. **Output contract.** `Write the report to <scratchpad>/research-<track>.md in <owner language> (product names, labels and quotes stay in original language), with a sources list of every URL used and a verification-boundary (查證邊界) section naming what you could not verify. Substance over length: each finding once. Then reply with a short summary of the strongest findings; the report file carries the detail.`

## Track slots

| Track | Question | Source families | Record unit and fields |
| --- | --- | --- | --- |
| Flows | How the category's best products structure the whole user loop on this platform | product docs, changelogs, store listings, help centers, tours | product: navigation verbatim; first screen finite or feed; how the lead choice is made and explained; detail composition top to bottom; decisions and what follows acting; library and search; empty and first-run; capture or entry; visual language |
| Components | Component and visual language against first-party guidance | platform HIG pages and their data endpoints, platform sessions, design-award lists, pattern galleries, design notes of design-forward apps | component situation: dominant pattern with one or two exemplars and URLs; what is dated; a blunt, measured critique of the screenshots; a proposed type ramp and control heights |
| Differentiator | The unresolved mechanism outside the other two tracks | products with an analogous mechanism, applicable first-party guidance, binding regulation, usability research | mechanism: inputs, user control, visible result, correction, failure and downstream consequence; for AI presentation also grounding, caveat placement and attribution |

## Research boundary

Stop widening the sample when the coverage floor is met and further sources repeat the same
decision-relevant evidence; continue only for a named gap or contradiction. When access or quota
ends first, save the completed evidence and list the unanswered questions with their consequences.
