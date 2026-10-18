---
name: narrate
description: "Explain one subject through user experience and business consequences. Use for 「白話說明」, a quick understanding of a technical case, a walkthrough of a system, or a visual explanation of a design decision."
---

# Narrate

Make one subject understandable to someone who did not participate in the engineering work.
The reader should understand what happens to people, why it matters, and what a proposed change
would mean. This skill explains available evidence; it does not authorize implementation,
tracker changes, or a new strategy exercise.

## Build the explanation

Start from a concrete user situation: who is trying to do what, and what they actually experience.
For a working feature, explain what it enables. For a problem, contrast expected and observed
behavior. Translate business impact into consequences such as missed work, repeated effort,
incorrect information, or a lost choice; use only consequences the evidence supports.

Connect the cause to that experience in ordinary language. Keep the causal detail that explains
the consequence, including timing or ownership when it matters. For example, “the old request
arrives after the date changed” explains more than either “a race condition” or “a sync issue.”
Introduce a technical term only when the reader needs it, after explaining its meaning.

When a proposed fix has a tradeoff, show what each affected person would experience. A short,
clearly illustrative scenario or imagined user reaction can make the tradeoff concrete. Keep
observed behavior, plausible consequences, and recommendations distinct; an illustration is not
a customer quote or proof that an incident happened that way.

End with the practical implication: what the fix would improve, what is already resolved, or
which decision remains. If a user decision is genuinely needed, explain the consequence of the
choices and give an evidence-backed recommendation before asking the smallest necessary question.
An explanation request alone does not create an approval gate; reuse decisions already made.

## Choose the presentation

Default to a few connected paragraphs in the user's language, readable within one screen.
Use the situation, cause, consequence, and next implication as a reasoning guide, not mandatory
headings. Scale detail to the reader's request.

Use a diagram when requested or when relationships are easier to see than read: a user journey
for a flow, before/after for a change, or roles and ownership for architecture. Label nodes with
plain-language responsibilities. Show unresolved choices as alternatives, not chosen/rejected.
Add a small location table only when the reader needs to navigate the implementation.

For a complete walkthrough, start with the short explanation, then trace the requested scope.
Put supporting paths, APIs, and code identifiers after the user-facing explanation where useful.

## Grounding and completion

For a plain-language restatement, reuse the evidence already established in the conversation.
Verify fresh ticket, delivery, or implementation claims before presenting them as current; verify
paths before linking them. State uncertainty at the point where it changes the explanation.
Preserve distinctions such as local tests passing versus a fix being deployed, and a reproduced
failure mechanism versus a confirmed historical cause.

Before finishing, check that a reader without code knowledge can identify the affected person,
the relevant behavior, and its practical consequence. Include a recommendation or question only
when the subject needs one. Simplification is complete when the causal story remains accurate
without requiring the reader to decode the implementation.

## Example: a missing class

“The coach adds a class, then changes its date before everyone has received it. Some athletes
receive the old date; others receive no class. We want late requests to use the latest date and
to fill genuine gaps. But an empty calendar slot can also mean the athlete deliberately deleted
the class. Filling every gap could bring that class back. We recommend remembering deliberate
deletions so automatic repair can preserve that choice.”

Use this example for its causal shape. Deletion policy and the need for confirmation come from
the actual case, not from this example.
