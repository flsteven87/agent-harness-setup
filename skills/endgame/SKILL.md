---
name: endgame
description: "Define and execute an ENDGAME CONTRACT when the user asks for the endgame (終局), execution of a best-practice path, or work through a delivery or dispatch endpoint."
---

# Endgame

The user's standing bar is the cleanest, most precise endgame with nothing over-engineered; this
skill applies it by default, so the user never restates it. Invoking it with an endpoint authorizes
the work through that endpoint.

## Authority

Use the working profile's finish line unless the user names an endpoint such as `commit`, `PR`,
`ship`, or `dispatch`. Record that resolved endpoint in the contract. Reversible steps toward it
proceed without asking. Pause only at the working
profile's action-time confirmations and at a product tradeoff only the user can settle, with the
prepared action in hand. A request phrased purely as analysis has the contract as its endpoint: after
step 3, close with `ENDGAME: DONE — contract delivered`.

## 1. Ground

Read the repository instructions, the owning tickets, and the code the outcome touches, this turn.
Plans, handoffs, and tickets are claims; the code is the evidence. Done when every precondition the
outcome needs has a current state backed by a file or command output.

## 2. Distill the endgame

State the end state as one sentence of real user or operator experience plus three to five
invariants that must always hold. Choose the simplest shape that reaches that end state directly:
the final design built minimally, rather than a patch on the current shape or a transitional layer
to remove later. When a choice turns on current best practice, check primary sources (vendor docs,
the library's own guidance, repository conventions) before choosing. Done when each rejected
alternative has a one-line reason.

## 3. Write the contract

Print the contract as plain text lines, outside any code fence; its heading line opens the
keep-going gate in Claude Code:

```text
ENDGAME CONTRACT
- End state: <observable result>
- Checks: <commands or observations that prove it>
- Invariants: <what must not change on the way>
- Endpoint: <resolved working-profile finish line or explicit user endpoint>
- Human gates: <applicable action-time confirmations, or none>
```

In Codex, then call `create_goal` with the contract as the objective; the goal keeps the thread
working and audits completion.

Every run writes the contract, small tasks included: it is what keeps the work moving and what the
close is checked against. Done when the contract is in the chat, and in Codex `create_goal` has
returned, before the first file edit.

## 4. Execute

Work one writer finishes in this session runs here. Independent milestones, or an explicit
dispatch, go through `milestone-dispatch`, each assignment carrying its own contract as the
receiver's goal. Run the checks as the work lands.

## 5. Close

Before the endpoint's final step, apply the working profile's review gate. When formal review is
required, use `code-review`; a `consult` verdict does not replace it. Otherwise review in this
session, using `consult` when the user requests a second opinion. Reuse the current frozen review
and its one fix pass rather than starting another round. When the change gives
the user a new mental model, alters behavior they rely on, or they ask to see it, build the change
page from [references/change-page.md](references/change-page.md) once those findings have landed.
Then close with one plain-text line:

- `ENDGAME: DONE — <each check with its observed result>` once the endpoint is reached and every
  check passed in this session, with the change page's path when one was built. In Codex, also call
  `update_goal` with `complete`.
- `ENDGAME: BLOCKED — <the human gate and the prepared action>` when only a listed gate remains.
- `ENDGAME: DROPPED — <reason>` when the user redirects the work.
