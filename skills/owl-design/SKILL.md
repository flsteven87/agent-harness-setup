---
name: owl-design
description: Use only when the user names Owl, such as "use Owl", "switch to Owl", or 「切到 Owl」. Replaces the Refero-baseline/Impeccable-refinement route for that task.
---

# Owl Design

Use the installed Owl Designer Skills Pack as a decision library, without exposing its individual
skills as independent top-level skills. The upstream source is `../../vendor/owl-designer-skills`,
resolved from this skill directory.

Verify that the source contains `INDEX.md` before applying Owl guidance. If it is absent, stop and
tell the human to run `git submodule update --init -- vendor/owl-designer-skills` from the agent
setup repository root, rather than substituting improvised design guidance.

While Owl is selected it supplies the creative design decisions in place of the default
Refero-baseline/Impeccable-refinement route. Keep product and brand constraints; leave
`$refero-design`, `$impeccable`, and other creative frontend skills out of the task. Take evidence
from engineering, accessibility, browser, and test skills without giving them design authority,
and stop applying Owl once the user switches back.

## Method

1. Inspect the product context, requested surface, current user-visible behavior, and incumbent
   design system before proposing components or styling.
2. Frame the affected user, their goal, entry and exit points, decisions, and the loading, empty,
   error, permission, and recovery states that matter. Surface implementation state only where it
   changes what the user can understand or do.
3. Read `INDEX.md` at the upstream root and select the smallest useful set of upstream skills it
   names, usually one to four. It routes by situation, lists the pairs most often confused, and
   stays current with the submodule. Treat the selected skills as decision aids rather than a
   lifecycle, and leave the rest unread. When the specialty you need is unlisted, search the upstream
   descriptions and take the narrowest match.
4. Produce one coherent information hierarchy, component model, and interaction direction. Implement
   it when the request authorizes changes; otherwise return the design decision and its evidence.
5. Verify the resulting flow and rendered states in proportion to the task.

Skip artifacts that do not improve the decision. A flow diagram or state machine earns its place only
where real branching or interaction complexity makes it useful.

## Decision priorities

- Start from the user's job and real usage scene. Choose components after the flow and content
  priority are clear.
- Give visual prominence to what helps the user decide, act, follow progress, or recover. Keep
  internal identifiers, implementation status, and operational metadata secondary unless the user's
  task depends on them.
- Prefer familiar platform and product conventions where convention reduces learning or error risk.
  For Apple-platform work, verify the current official Human Interface Guidelines; Owl's static
  guidance helps interpret them and does not replace them.
- Preserve the product's factual copy, constraints, and working behavior unless the user authorizes a
  change.

## Completion

Complete when one design direction covers the requested surface and its material states, each
non-obvious choice names the upstream skill or platform guideline behind it, verification matches the
task's size, and anything left open names the decision the user still owns.
