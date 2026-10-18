# Plain-Language Briefs

The board's reader is a manager: they decide without reading code, and they read the page to learn
what changed, what waits on them, and what to do first. Each brief reads like an outcome in an
engineering report: the exact thing affected, what it was before, what it is now, why that matters,
and who acts next. Write in Traditional Chinese, following `narrate`.

## Rules

- Ground every sentence in the item's own fields: `source` for a workstream; `workstreams`
  and `shipped` for a project. The cache is keyed to those fields, so a brief that draws
  on anything else goes stale unseen. `why` may state the consequence that follows directly from
  those facts; never invent results, dates, or numbers. When a field is too thin to say who is
  affected, say what is known; the fix is a fuller `MEMORY.md` entry at the next `handoff`.
- Start from the person or thing affected (a player, a customer, the operator, the monthly bill)
  and what changes for them, then why the business cares. Mechanism comes last or not at all.
- Keep code identifiers, file paths, ticket and PR numbers, branch names, and commands out of every
  field. Names of products, vendors, services, and devices stay as they are (Orca, Codex,
  Cloudflare, LINE); the owner recognizes them. Name any other technical term only after one plain
  clause says what it does.
- Write one sentence per field, about 80 characters at most, counting each Latin word or number as
  one. The `title` names the exact object and its changed behavior in about 24 characters or fewer
  (「新玩家第一次就能完成付款」, not 「Stripe webhook 重構」 or 「改善付款體驗」); it must still say what
  changed when read without `why`.
- `before` and `now` are one pair: the concrete behavior or gap before the work (with its cause when
  the source gives one), and what is true now, including what is still unproved. A reader comparing
  the two sees the change without reading anything else; "better", "improved", or "optimized" alone
  fails.
- Page chrome already explains the buttons and sections; a brief never describes what the page or a
  button does.
- Name who acts in `next`: 「工程會…」「你要…」「等外部回覆…」, with steps for several actors in order.
  `next` is this card's own step: each card carries its own button, so never send the owner to
  press another card's button or to dispatch work no card on the page offers.
- `actor` is who can move the card forward now. It is `you` only when the owner has a concrete step
  today; when both can, it is `you`, since the owner's step is the one that waits. A card that waits
  on a future event, a date, real usage, or a pause the owner set, with nothing to do today, is
  `external`; one whose date
  or event has already passed is `engineering`, since an agent can check it now. A step only the
  owner can take (a decision, an approval in their own account or app, facts only they hold) is
  `you`; a step that needs the owner only if a condition holds (「approve X if it is pending」,
  「confirm Y still fails」) is `engineering` when an agent can check that condition, and the
  worktree agent raises the owner's part only if it is still needed. Every `you` card
  lands in the owner's queue, so a wrong `you` costs the owner attention.
- When the source asks the owner to choose between options, put the options and the source's
  recommendation in `next`, so the owner can answer from the card. (A decision card with option
  buttons comes only from a `- Decision:` line that `handoff` writes; the brief does not mention it.)
- An item with `previous` is a rewrite of a card the owner has already seen. Keep its `title` while
  the outcome is the same, and change only the fields whose source changed, so the owner spots the
  difference instead of re-reading the card.

## Shapes

Every item in the pending file has an `id`, a `kind`, and a `project`; write one brief per id.

`workstream` (all statuses):

```json
{"title": "…", "who": "影響對象", "before": "原本的行為或缺口", "now": "現在的狀況", "why": "為什麼重要", "next": "下一步由誰做什麼", "actor": "engineering"}
```

`who` is the person or thing affected (「派工出去的每件工作」「教練的新增成員清單」), a noun phrase, not
a sentence. The page adds the pull requests and commits the source's State cites as evidence; do not
repeat them.

`actor` is `you` (the owner decides, approves, or does it), `engineering` (an agent can start it
now), or `external` (a vendor, a reviewer, a date, real usage that has to accrue, an owner's pause).
A decision's actor is always `you`. A `you` card lands in the page's 「輪到你」 section and dispatches
a worktree agent that asks the owner first; an `engineering` card dispatches one that works on its
own; an `external` card gets no button.

- `status: "active"` and `status: "waiting"` use this shape as it is.
- `status: "deferred"` (parked on purpose) uses it too; the page shows it only in the status table
  with no button, so `now` says why it is parked and `next` its resume condition.
- An `external` brief that waits on a date adds `"until": "YYYY-MM-DD"`; the board asks for a new
  brief once that date has passed, since an agent can then check it.
- `status: "stuck"` adds `"stuck"`, one sentence that opens with 「卡在」 and names what it waits on and who: 「卡在正式環境權限的變更，在等你確認。」
- `status: "decide"` adds a decision the owner can make from this card alone:

```json
"decision": {
  "question": "要不要…？",
  "options": [
    {"label": "先做 A", "consequence": "選了之後會發生什麼、誰受影響", "reversible": true},
    {"label": "維持現狀", "consequence": "…", "reversible": false}
  ],
  "recommended": 0
}
```

Give two or three options with their consequences. The owner answers from the question and options
alone, so write them in words the owner already uses: when the choice turns on a technical term, that
same field says in plain words what it does (「讓每次測試結果註明測的是哪個版本」, not 「版本綁定」).
`reversible` says whether the choice can be undone cheaply later. `recommended` indexes the option the source recommends. Use `null` when the
source gives no recommendation; do not invent one.

`product`:

```json
{
  "summary": "這個產品現在在做什麼、離下一個里程碑多遠",
  "shipped": [
    {"title": "…", "stage": "已合併", "before": "原本…", "after": "現在…", "commits": ["<sha from shipped>"]}
  ],
  "focus": {"key": "<one of this project's workstream keys>", "why": "現在做它能換到什麼，或拖著會付出什麼"}
}
```

- `shipped` (omit it when the item's `shipped` is empty) clusters the week's commits into one to five
  outcomes by who notices the change, most consequential first, each titled like a card. Every
  outcome lists in `commits` the `commit` values it covers; commits with no evidenced consequence
  (notes, chores, reverts undone in the same week) belong to no outcome. `stage` is `已合併` unless a
  subject says the change was released or deployed (`已上線`): merged into the main line is not live
  for users.
- `focus` (required when the project has workstreams that are not deferred) is the one card the owner should act on
  first. When a workstream carries a `priority`, the focus is the lowest-numbered one that is not
  deferred (the board refuses any other), and `why` says what doing it now buys. Otherwise it is
  the one that costs the most while it waits, a deadline or harm users already feel coming first. Among cards that cost alike, an owner step that holds engineering back comes first. When
  every card waits on something outside, `why` says what the focus card waits for instead of asking
  the owner to act.
- When `shipped` shows work the workstreams do not mention, or contradicts a card, the notes are
  behind: say in `summary` which card may be out of date, and leave the cards as they are. The page
  flags stale notes itself.

`receipt` (a dispatch that finished since the owner last looked):

```json
{"title": "這次派工完成了什麼", "did": "agent 做了什麼、結果如何、下一步落在誰身上"}
```

- Ground `did` in `report`, the agent's own account: a receiver's completion receipt, or an upkeep
  run's final message. Check it against `pr` (the pull request its branch opened: title, state, body;
  `null` when it opened none) and `notes` (the workstream's entry after it, or `"entry removed"` when
  the agent closed the workstream). `chore` names an upkeep button (更新筆記, 清理殘留) instead of a
  workstream. When `report` says there is none, say what `pr` and `notes` show and that the agent left
  no report.
- Keep `card_title` as the `title` when it is set, so the owner recognizes the card.
- A `pr` state other than `MERGED` means the change is not in the main line; say so. When
  `notes_written` is false, say the agent left no notes and the owner should look at where it stopped.

## Check before submitting

A reader who knows no code can say, for each card, who is affected, what they experience, and what
happens if nothing is done; for each decision, what each option means from its words alone; and, for
each project, what changed this week and what to do first.
Write the briefs as one JSON object keyed by id, then rerun the board with `--briefs FILE`.
