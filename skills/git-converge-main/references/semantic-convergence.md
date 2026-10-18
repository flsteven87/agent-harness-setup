# Semantic Convergence

Use this reference only when reachability, current task evidence, and exact merged-PR proof cannot
settle an owned candidate. Its outcome is a defensible answer to three questions:

- What valuable behavior or knowledge remains unique?
- Does that value belong in the current local default branch?
- What evidence makes delivery, cleanup, or preservation safe?

Other-owned work stays outside semantic review unless the human names that exact item.
For owned documentation-only work, apply the KEEP/DROP exception in `../SKILL.md`; its local
retention and source-to-destination proof replace the DELIVER routing below.

## Evidence ladder

Prefer the strongest applicable evidence:

1. Exact tip reachability from the relevant local or remote default.
2. Exact merged-PR head plus matching cumulative stable patch.
3. Tree equivalence at the original comparison boundary.
4. Complete mapping from every unique commit to landed successors.
5. Behavioral supersession proved by current source and regression tests.
6. Negative proof that the delta contradicts current contracts, migrations, or tests.

Levels 5–6 require a written rationale and the repository's applicable review gate. Subjects, age,
file counts, shortstats, branch names, and `git cherry` remain discovery signals.

## Comparison boundary

The proof must explain the history that produced the candidate. Relevant facts include its original
base, merge-time head, current tip, merge method, stacked ancestry, post-merge movement, and split
delivery. Comparing an old source directly with today's default is insufficient when those histories
do not share the same authored boundary.

Patch mismatch means the boundary or delivery mapping remains unresolved; it does not prove unique
value by itself.

## Valuable delta

Account for behavior, tests, requirements, migrations, data contracts, documentation, and operational
knowledge. A candidate is cohesive only when its remaining value has one current intent and one safe
destination.

Historical implementation may be obsolete while tests or requirements remain valuable. Preserve
the source until that value has an explicit destination or the human rejects it. Mixed branches do
not become DELIVER merely because one part is useful.

## Direction contracts

### DELIVER

DELIVER requires current intent, a coherent delta, and a supported destination in local default.
Record the source tip, accepted behavior, validation evidence, and intentionally excluded content,
then follow the implementation and delivery branch in `../SKILL.md` under existing authorization.

When only part belongs, resolve an extraction destination and acceptance boundary for that component,
then prepare and deliver it when authorized. Retained unique work keeps its source; retire the
original only when every component has landed evidence or an executed documentation disposition.

### CLEAN

CLEAN requires proof that no valuable unique content remains outside local default, or stronger
remote or semantic evidence makes the artifact redundant. Semantic CLEAN records both the comparison
boundary and why current behavior, tests, contracts, migrations, documentation, and operational
knowledge cover the old delta.

Rewrite predecessors may share one CLEAN family when repository evidence proves lineage, a later
successor is itself proven landed, and the predecessor-to-successor delta contains no unique value.
Matching metadata alone is insufficient lineage.

### LEAVE

LEAVE is the truthful result for other-owned, unresolved, intentionally parked, or currently
irrelevant work. Record the ownership or evidence gap and the narrow condition that would justify a
future pass.

## Recovery and open-review edges

Treat stash and reflog-only commits as possible last copies. Recovery cleanliness requires a complete
accounting of the relevant family; bounded samples never prove absence. Unreferenced objects remain
for normal Git garbage collection after classification.

An open PR is delivery state, not cleanup proof. Remote closure, deletion, dirty rescue, semantic
supersession, and unmerged remote work follow
[safety and authorization edges](safety-and-authorization.md).

## Decision record

The record must let another agent reproduce the decision without inheriting the original session:

| Item | Ownership | Comparison boundary | Unique value | Delivery risk | Direction | State | Release condition or receipt |
|---|---|---|---|---|---|---|---|

Every Waiting result names an observable release condition. Every completed DELIVER identifies its
delivery receipt. Every executed CLEAN identifies the removed artifact and its proof.
