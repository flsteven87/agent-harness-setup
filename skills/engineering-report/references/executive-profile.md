# Weekly Report Contract

`$html-report-system` owns report identity, thesis, conversation-derived material, packaging,
rendering, and the rendering gate. This contract owns
engineering evidence reconciliation, outcome selection, and the report's business reading path.

## Evidence hierarchy

1. Configured tracker record and relations: originating symptom, investigation, decisions, status.
2. Git first-parent commit and diff: code or configuration actually merged to `main`.
3. Review attachment/body and recorded verification: intended scope and existing test evidence.
4. Current source and targeted checks: resolve discrepancies only.

Do not use commit titles alone when a tracker record or diff is available.

Reconcile review identifiers from Git references and tracker attachments. A count of review numbers found in commit messages is a lower bound, not the total delivery count.

## Executive lens

Lead with the strongest evidenced change for users or operations, then explain the business
consequence and remaining decision. Keep implementation detail in proof unless it explains safety,
recurrence, or a release condition.

Every item headline names the affected user or product object and the exact behavior enabled,
prevented, or still blocked. A reader should answer `現在什麼會／不會發生？` from the headline alone.
For example, `同一個 email 不會再建立兩個帳戶` identifies the change; `保護帳戶信任` belongs in
its business consequence. Put the intervention sequence in the action, not the headline.

Use the repository's specific product nouns and plain language a founder, commercial lead, or
operations lead can explain without repository knowledge. Preserve the distinction between a
customer outcome, reduced operating work, business exposure, and a future capability; support each
with the evidence appropriate to that claim.

Business intuition remains evidence-bound. Distinguish:

- `已觀察 / Observed` — runtime, customer, support, or measured evidence confirms the result.
- `已交付 / Shipped` — code or configuration merged; runtime or customer outcome remains unverified.
- `下一關 / Next gate` — the release, evidence, external action, or decision still required.
- `推論 / Inference` — a business implication derived from evidence; label it explicitly.

Use the reader's language for visible labels. Do not mix English claim labels into a Chinese report.

## Identity and attribution

Use the requested title in both the document title and heading. For an untitled weekly report,
use `Weekly Report` or its reader-language equivalent; keep the contributor and dates in header
metadata. The business conclusion belongs in the thesis and summary.

Once the header establishes the contributor, describe actions directly. Use neutral labels such as
`本期改動`; name people within an item only when shared responsibility changes its attribution.
State the verified attribution method and its limits in evidence coverage, using display names in
the report and keeping raw author emails in working notes.

## Claim rules

- Use `confirmed` only when the issue or source contains evidence, not a hypothesis.
- Treat an issue marked `Done` as workflow state, not proof of runtime recovery.
- Treat a review attachment as traceability, not proof that all tracker-record symptoms were implemented.
- When one tracker record mentions multiple symptoms but the attached diff fixes one, name the fixed symptom and mark the others `未拆分` or `待確認`.
- When an incident leads to an architecture program, show the chain in one main item instead of listing every child record separately.
- State backlog rollout gates explicitly; never describe an in-progress umbrella as closed.

## Coverage and selection

Default to a concise executive summary followed by all distinct material work in the window.
The summary may emphasize three to five outcomes; that is an editorial guide for the opening,
not a limit on body items. An explicit highlights-only request permits a shorter selection.

Reconcile every candidate to a named body item or an explicit omission reason in working notes.
Combine repeated commits, reports, and releases supporting the same outcome. Keep work distinct
when its user behavior, causal mechanism, data owner, preserved facts, or rollout gate differs.
Group a long report by user workflow or operating purpose and provide an item index. Each group
contains named work items with their own evidence and state.

Include internal maintenance when its operating consequence is established. Use a compact item
when its scope warrants one; a catch-all heading cannot replace an item's behavior, contribution,
and proof. Under an explicit complete-items request, keep every selected item in the full capsule
format. Preserve gaps for candidates whose consequence or attribution cannot be established.

Every full capsule contains:

1. **Outcome and state** — a concrete headline plus `已觀察`, `已交付`, `下一關`, or `推論`.
2. **Why it matters** — the consequence for users, business, or operating work.
3. **Before → after** — observable behavior on both sides, with the causal explanation or original
   capability gap beside the before-state, following the causal-evidence check below.
4. **What stays safe** — preserved user-owned behavior, fallback, or explicit `沒有行為需要保留`.
5. **What actually changed** — the plain-language change fingerprint, retaining the exact field or
   object in `code` only when it distinguishes the intervention.
6. **Data and reach** — repair, release, and observation boundaries that materially limit the claim.
7. **Proof** — compact source anchors supporting the cause, delivered change, and result separately.

Keep the internal candidate ledger in working notes; the body explains business changes.

## Causal evidence

For a defect, establish the chain **trigger → failing rule or assumption → user consequence**.
Read the investigation or incident record, relevant PR body and full commit message, then check
that account against the pre-change behavior and diff. A cause label or a fix alone is insufficient.
Use fixed revisions and source anchors when available.

Record the supported mechanism, its evidence, and unresolved origin in the working ledger before
writing the item. Explain the mechanism next to the symptom in plain language: which information,
rule, or sequence was wrong, and how that produced the user's problem. For example, replace
`the dashboard showed no sessions` with `a failed lookup and a successful empty lookup returned the
same value, so the dashboard treated an unavailable schedule as no sessions`.

Separate an initiating event from the recovery defect that let damage persist. Cases with the
same symptom may have different causes; preserve those differences even inside one outcome.
An established mechanism does not establish why the original author chose it, why tests missed it,
or why the first interruption occurred. Label those origins unknown when evidence ends there.

For new capabilities, audits, rollout preparation, and documentation work, explain the prior
capability or evidence gap; use `原有缺口與背景` when appropriate. A discovered defect within such
work still follows the causal check. Keep proposed behavior conditional until its release is proven.

Complete this check when every defect item has a sourced causal explanation or an explicit cause
gap, every non-defect item has its original need, and prevention remains distinct from historical
repair. Review this semantically; the HTML validator checks structure, not causal truth.

## Before-and-after precision

- Write observable behavior, not sentiment: `缺少心率區間時仍收到訓練回饋` is useful;
  `體驗更穩定` is not.
- State the comparison at the same level on both sides. Do not compare an old user symptom with a new
  internal class name.
- Name preserved fallback behavior whenever the change narrows, filters, deletes, or relocates data.
- For removals, state which user-owned facts remain readable and which object now owns them.
- For data work, separate recurrence prevention from inventory, repair, backfill, and verification.
- If historical records require no action, cite the contract or inventory that makes that conclusion
  safe. Otherwise say `未確認`, not `不需要 backfill`.
- If an after state is merged but not deployed or observed, write it in delivered scope and keep the
  visible status `已交付`.

## Language

Prefer outcome verbs: `保護`, `降低`, `解鎖`, `縮短`, `讓`, `避免`, `限制`, `保留`, `驗證`.

Write for a business-literate reader who does not need repository vocabulary. Put implementation
names, test machinery, data stores, and internal service boundaries in the evidence line unless they
change the business decision.

Main copy must be plain business language. Terms such as `queue`, `DLQ`, `runtime`, `provider`,
`projection`, `cohort`, `provisioning`, `preflight`, `reconciliation`, `feature flag`, `entitlement`,
and internal model or service names are evidence vocabulary, not executive vocabulary. Translate them,
for example:

- `queue / DLQ are zero` → `待處理與失敗佇列皆已清空`;
- `provider rollout gate` → `跨資料來源上線條件`;
- `feature flag / entitlement` → `功能開關與使用資格`;
- `preflight / reconciliation` → `安全檢查與資料核對`.

Visible non-reference copy describes customer outcomes, operating leverage, business risk, product
leverage, or management decisions. When a sentence can be removed without
changing a business decision, remove it.

Plain does not mean generic. Prefer the most specific domain noun supported by evidence; remove only
repository and implementation jargon. A reader should be able to repeat each headline as a concrete
product or operating change without opening the evidence line.

Avoid ratings and promotional language, including:

- 高產出、高影響、亮眼、完整、成熟、穩健
- 做得很好、工程品質良好、值得肯定
- 顯著提升 unless a measured before/after value is cited
- 成功解決 unless the reported user outcome was verified

Counts describe scope only. Never use review, commit, line, or test counts as a productivity score.
Label lower-bound counts precisely, for example `Git-referenced reviews`, until all review sources
are reconciled.

## Validation wording

- Prefer verification recorded on the relevant tracker record or review.
- If local checks are run, list exact pass/fail counts and environmental blockers.
- Do not collapse a partially failing gate into `tests passed`.
- Do not attribute broad failures to the contributor without a failing assertion tied to an in-scope diff.

## Default visual layout

1. **First viewport:** stable report identity, this window's thesis, contributor, exact window,
   evidence cutoff, and three signals for customer change, operating change, and top open gate.
2. **Work items:** named items grouped and ordered by business consequence under the coverage rule
   above. The lead outcome may use more space; every full capsule exposes the same seven fields.
3. **Business gates:** centralized observable conditions that limit what can be claimed. Do not repeat
   the same gate in every capsule.
4. **Evidence coverage:** sources, verified attribution basis, omissions, tests, and interpretation
   limits.

Use the owned HTML template and preserve its semantic landmarks and
`data-report-section` / `data-outcome-field` attributes. Keep status visible without interaction.
Evidence details may use native `<details>`, but every business claim and current state remains visible
when details are collapsed.

Accept multiple sections when the selected outcomes require them. Keep before/after meaning intact
and use a restrained executive brief: no verdict, score, rating, praise, or decorative qualitative
badges.

Reject the visual if removing `為什麼重要` leaves a headline that could describe many unrelated
projects. Headline specificity must survive on its own.

## Artifact contract

- Keep one region each for `executive`, `outcomes`, `gates`, and `evidence`.
- Give every main outcome its own `data-report-outcome` container and all required
  `data-outcome-field` markers: `status`, `before`, `after`, `consequence`, `preserved`, `fingerprint`,
  `data`, and `proof`.
- Use semantic tables only for exact repeated mappings.
- Remove unused example blocks rather than leaving empty chrome.

## Privacy

Keep configured tracker and review identifiers. Remove personal names from support records when not
necessary, and never include raw email addresses, user IDs, request IDs, tokens, or private attachment
URLs.
