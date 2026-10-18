# Strategic Investigation Contract

Read this reference after the initiating subject has been split into atomic threads. Finish the evidence
ledger before reading the strategy contract.

## Evidence authority

Assign authority by question:

| Question | Primary evidence |
| --- | --- |
| What did the user observe? | Original message, image, screen recording, or support record with time |
| What happened to this occurrence? | Identity-scoped stored state, runtime trace, or delivery receipt |
| Why can the system behave this way? | Current source, focused reproduction, and tests |
| When and why did behavior change? | Merged history, review record, release artifact, and deployment record |
| What work is tracked? | Live configured-tracker record, relations, status, and comments |
| How broad is the impact? | Bounded read-only production census with cohort and timestamp |

An earlier report is narrative evidence. The configured tracker is workflow truth, not implementation or deployment
proof. A merged change is not a deployed artifact; a deployed artifact is not user verification.

## Thread ledger

Maintain one row per atomic thread:

| Field | Required content |
| --- | --- |
| Thread | Initiating claim or objective and exact observable outcome |
| Consequence | Concrete user, operator, integrity, reliability, or commercial effect |
| Verdict | Confirmed, contradicted, unresolved, expected, partial, or adjacent |
| Confidence | Confirmed, strong inference, bounded inference, or unknown |
| Chain | Originating boundary, carriers, observer, and current user-facing surface |
| Delivery | Code, merged, deploy-ready, deployed-unverified, verified, or residual |
| Scale | Cohort, period, numerator, denominator, unit, and query timestamp—or explicit unknown |
| Tracking | Exact configured-tracker defect/remediation relationship or untracked finding |
| Closure | Identity, reproduction, delivery, metric, or production evidence still required |

Use `confirmed` only when a direct observation, reproduction, stored occurrence, or causal source path
supports the claim. A system contract gap can be confirmed while one user's root cause or a broader
business outcome remains unresolved.

## Investigation passes

### 1. Establish the current promise and behavior

State the intended user or operating promise, then verify the current behavior. Recreate every
deterministic number, payload, navigation result, or workflow state that changes the interpretation.
Prefer the narrowest existing helper or test seam and save the command plus redacted output. Preserve
healthy neighboring behavior instead of treating the whole topic as failed.

### 2. Walk the user journey

Record the action, product surface, expected feedback, actual feedback, and consequence at each step.
Identify the lowest-trust step: where the user can no longer tell whether the system fulfilled the
promise.

### 3. Trace the program chain

Map authoring, authoritative objects, asynchronous delivery, per-user snapshots, execution, and
measurement as applicable. For each boundary, record input, output, identity key, mutation timing,
failure response, replay behavior, and observability.

Distinguish:

- **origin** — creates the wrong or ambiguous state;
- **carrier** — preserves and transmits that state;
- **observer** — displays or measures it;
- **adjacent** — causes a similar symptom through another path.

### 4. Reconcile current delivery

Inspect source, focused tests, merged history, review records, release evidence, and the configured
tracker. Give each relevant record a current delivery verdict. Name the undelivered slice when a
record is partial or residual.
Do not infer production verification from `Done`, merged code, or a successful queue response.

### 5. Measure scale

Use production data only through an authorized read-only path. Define the cohort and time range before
querying. Report:

- total population inspected;
- affected population and distinct affected identities;
- severity bands with exact thresholds;
- completed or user-visible subset;
- exclusions, ambiguous rows, and known query blind spots.

Never repair data during the census. When access, identity, or a safe predicate is missing, retain the
unknown and state what would resolve it.

### 6. Prove tracker coverage

Every confirmed cause or capability, unresolved claim, historical repair, deployment verification, and
recurrence-prevention slice needs one of these dispositions:

- covered by an exact configured-tracker record whose remaining acceptance matches the slice;
- intentionally included as acceptance evidence for another issue;
- untracked, with the minimal proposed record and relationship;
- excluded, with the reason it cannot change this topic's outcome gate.

Follow repository defect-record rules: one escaped cause is one defect record; implementation,
backfill, observability, and verification work can be child remediation. Create or edit records only
with explicit tracker-write authority.

## Investigation completion test

The investigation is complete only when:

1. Every initiating claim or objective appears in the thread ledger.
2. Every confirmed verdict has direct causal evidence.
3. Every unresolved verdict names the missing identity or observation.
4. Correct neighboring behavior is protected from over-broad conclusions.
5. Every scale figure has cohort, denominator, unit, timestamp, and source.
6. Every delivery claim distinguishes code, merge, deployment, and user verification.
7. Every material finding has a tracking disposition.
8. The program chain names authorities, origin, carriers, observers, and adjacent work.
