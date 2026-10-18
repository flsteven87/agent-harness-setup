# Topic Strategy Contract

Read this reference only after the investigation ledger and program chain are complete. Strategy
starts from the established causes; it does not fill evidence gaps with architecture preferences.

## Design the target contracts

For each responsibility boundary that owns a strategic outcome, originated a confirmed failure, or
can prevent recurrence, define one target contract:

| Contract field | Decision |
| --- | --- |
| Authority | Which object or role owns the truth |
| Identity | Keys required to resolve the exact user, occurrence, version, or variant |
| Input and output | Minimal information crossing the boundary |
| Unknown state | How missing or ambiguous information is represented without invention |
| Success | Observable terminal condition, not acceptance or queueing |
| Failure | Stable reason, affected identity, and safe recovery path |
| Replay | What remains immutable and what may be recomputed |
| Evidence | Receipt, fingerprint, version, reason, or measurement proving the outcome |
| Repair | Authority and rollback required to change historical state |

Prefer one authoritative path and explicit unknowns over compatibility fallbacks. Preserve correct
behavior and user-owned facts identified by the investigation.

## Build the execution spine

Use only the phases the evidence requires. These four strategic moves are the default vocabulary,
not a mandatory count:

1. **Stabilize** — remove proven harm or ambiguity and restore an identity-scoped user state when safe.
2. **Establish truth** — add the identity, receipt, fingerprint, or measurement needed to distinguish
   accepted work from terminal delivery.
3. **Consolidate authority** — move responsibility behind the smallest precise module or data
   contract that eliminates conflicting paths.
4. **Scale and verify** — repair historical state when needed, remove repeated operating work, and
   make delivery or recurrence visible before another user report.

For every phase state:

- user or operating outcome;
- exact tracker records and included slices;
- prerequisite and decision gates;
- owner role rather than a guessed person;
- rollout and rollback unit;
- observable exit gate;
- work parked for later and why.

Separate the current outcome gate, residual historical data, prevention, deployment proof, and
identity-specific verification when their permissions or completion evidence differ.

## Prioritize

Use the user's principles first. Otherwise rank:

1. current user harm, integrity, security, or irreversible risk;
2. a small reversible change that stops a confirmed misleading output;
3. a truth or authority prerequisite that unlocks several user-facing repairs;
4. bounded noise reduction with a measurable operating result;
5. the smallest architecture that removes a whole failure class.

Do not group work merely because it shares an incident. A phase or future worktree is coherent only
when it shares one authority boundary, acceptance surface, rollout unit, and outcome.

## Extract PM decisions

Write decisions in product semantics. Common decision classes include:

- whether unknown is a legal product state;
- what a success message promises;
- which object owns a personalized value;
- when historical state may change;
- which verification becomes a release gate;
- what evidence operations needs to close a user case.

For each decision provide the recommended rule, user consequence, engineering consequence, and
tradeoff. Do not ask PM to choose function names, worker topology, or schema mechanics unless those
change the product contract.

## Define the outcome gate

The outcome gate is the evidence required to claim that the topic's intended product or operating
result is real. For an incident, it also defines what is required to tell the initiating reporter
that the incident is complete. It normally covers:

- the exact affected identity and occurrence;
- current user-visible state;
- one representative change reaching terminal delivery;
- preserved correct neighboring behavior;
- downstream measurement or display;
- deployed artifact identity and cross-role verification;
- no new anomaly in the bounded post-deploy observation window.

Tailor the gate to the thread ledger. Ticket creation, code merge, deployment, and a successful toast
are intermediate states unless the intended promise ends there.

## Strategy completion test

The strategy is complete only when:

1. Every confirmed cause is removed, contained, or explicitly accepted.
2. Every unresolved individual case has a minimal evidence-acquisition step.
3. Target contracts name authority, unknown, success, failure, replay, and evidence semantics.
4. Each phase has one checkable outcome and no hidden permission expansion.
5. Historical repair and future prevention are independently gated.
6. PM decisions are stated without implementation vocabulary.
7. The outcome gate traces back to every initiating objective or claim.
