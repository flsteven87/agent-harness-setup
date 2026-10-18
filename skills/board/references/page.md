# How the Page Works

Read when the owner asks how a section or button works, when a launch fails, or before changing
`scripts/board.py` or `scripts/launch.py`.

## Sources

Before rendering, the agent follows [refresh.md](refresh.md) to reconcile selected MEMORY entries.
The same contract owns 更新筆記. Direct execution of the renderer only collects and renders facts.

`board.py` reads each primary checkout's `MEMORY.md` (every `###` entry, its section as its class,
the `- Stale:` lines under Current State, and items written outside any entry in a section the
handoff format does not reserve for notes, which the header names and 更新筆記 sorts), the
last seven days of first-parent commits on the remote default branch after `git fetch --prune origin`
(so merges made elsewhere count and unpushed local commits do not), and `gh pr list`. An entry's
`- Priority:` line (a number, lower first, written when the owner ranks work) orders every card list
and the status table within its class, with unranked entries after in file order, and fixes the
「建議先做」 pick to the top-ranked card that is not deferred (owner, 2026-10-01). A commit whose
author is a bot (`[bot]`, such as an image bump) counts nowhere on the page: not in the week, the notes'
freshness, or what local main lacks, since it changes nothing the owner reads or runs. Beyond those
remote refs it writes only under `~/.local/state/board/`: `<project>-<path hash>.html`, or `index.html`
with `--all`, whose project list comes from `orca repo list`. Briefs are cached per project path by
source hash in `briefs/`; a pending item carries the card's `previous` brief, matched by workstream
key.

## Sections

- **Header:** counts (the owner's items, stuck items, workstreams an agent is working, and those an
  agent could take but nobody is on), then each project's 「建議先做」 card from its product brief,
  linked to the card.
- **你上次看之後:** each board dispatch that finished since the owner's last visit, with what its agent
  did (a `receipt` brief from the agent's own report, checked against the pull request its branch
  opened and the notes it left: a receiver writes its completion receipt to `receipts/<launch id>.md`
  before removal closes its terminal, and an upkeep run's report is its result), then each card whose objective,
  state, next step, blocker, or decision changed, naming those fields, and each new card. A visit is a
  page rendered with `--open`; its snapshot lives in `visits/`. Before the first visit it lists
  finished dispatches started this week and marks no cards. The visit is recorded only once the page
  is shown in Orca.
- **輪到你:** decision cards from a workstream's `- Decision:` line (written by `handoff` when the
  next step waits on the owner), then every other card whose brief gives the next step to the owner,
  each project's 「建議先做」 card first.
- **卡住:** a `- Blocker:` line that does not start with `None` when the owner cannot clear it, and open
  pull requests whose CI failed.
- **Overview index (`--all`):** one row per project with its summary, activity, and counts.
- **Project:** the summary, when the notes were last written and how many
  default-branch commits landed after them (commits that write `MEMORY.md` excluded), how many merged
  commits local main still lacks (skills and tools run from the primary checkout, so those merges
  are not live on this machine yet), then 這 7 天: the week's commits as one to five outcomes, each with
  its stage (已合併 or 已上線), what it was and what it is now, and the commits behind it. Then 工作: a
  status table and every workstream card, laid out like an engineering-report outcome: status and
  title, 影響對象, 為什麼重要, 原本 → 現在, 下一步, and 證據 (the pull requests and commits the
  workstream's State, Blocker, or Decision cites). Beyond those references the page carries no Git,
  pull request, or MEMORY source text.
- **Status table:** one row per workstream, classed by what moves it now, in this order: 輪到你 (a
  decision, an owner step, or a live dispatch whose agent is silent, gone, or left a failed launch's
  worktree), 卡住 (a blocker the owner cannot clear, nobody on it), 可以派工，沒人在做 (an agent could
  start it), agent 在做 (a live dispatch), 等外部或實際使用 (an `external` actor). Each row shows how
  long since the workstream last moved: the latest of its last dispatch, the visit that first saw its
  notes change (dated by the MEMORY.md write), and, until a visit has seen it, the latest past date in
  its notes; a waiting row
  that waits on the owner, is stuck, or sits idle a week or more shows its days in the warning color. The card's pill uses the same class.
  A blocker whose brief actor is `external` reads 等外部, not 卡住. A live dispatch reads 輪到你 when its
  own entry changed after launch (the launch records the entry's digest) and now hands the step to the
  owner: the agent waits on them. Entries under a Deferred section read 暫緩, last, and stay out of
  every queue, count, focus pick, and button.
- **Notes gaps:** a card whose entry has no Next, or lines no field reads, says so, and a card with an unresolved `- Stale:` line carries 筆記可能過時. A duplicate key shows as a read error and keeps
  the first card.

## Buttons

Each decision option and each card whose next step is the owner's or engineering's shows a button that
launches it (the owner chose one click over copy and paste on 2026-09-29), with the task its agent
receives, verbatim, collapsed under 交代內容 beside it (the owner chose collapsed on 2026-09-30). The
worktree shows in Orca under the card's title, so the owner can tell dispatches apart; its branch and
path keep an ASCII name from the workstream key. Every card button dispatches a worktree agent, so no card's work runs in the primary checkout
(the owner chose this on 2026-09-30); only upkeep, whose skill acts on the primary checkout itself, runs there:

- **派工** (every card with a step, failing checks): creates an Orca worktree with Orca's setup skipped
  (the receiver runs the repository's `orca.yaml` setup itself and sees its failures), starts a YOLO
  Claude receiver through `milestone-dispatch`'s reviewed launcher, writes the assignment with the
  owner's authority block into the worktree's Git directory, and sends a short `/goal` that names the
  dispatch and its end state and points to that file. The assignment is the only full statement of
  the task: the card's task verbatim, how to meet the owner, grounding, endpoint, authority. The receiver
  follows the milestone-dispatch receiver contract through merge, as the owner chose on 2026-09-29.
  A failing check is fixed only when its work is not waiting on the owner.
- **派工 on an owner card:** the same dispatch, but the terminal line is an `/endgame` prompt instead
  of a `/goal`, since a goal keeps pushing while the agent waits on the owner, and
  Orca switches to that terminal. The receiver first checks whether the step still needs the owner,
  does what an agent can verify or do, asks the owner one question at a time for the rest, then
  continues to the same endpoint.
- **更新筆記** (always offered, since notes drift in ways Git cannot show; its task names the detected
  gaps; it sits in the page header beside the notes' freshness line, since every card is only as current
  as the notes, the owner chose on 2026-09-30) and **清理殘留** (when linked worktrees or local branches exist that no live board dispatch
  holds): run [the refresh contract](refresh.md) or `$git-converge-main` as one headless `claude -p` agent in the primary
  checkout, with no worktree (the owner chose this on 2026-09-30), keyed `notes-refresh` and
  `leftover-cleanup` so one of each runs at a time. It is live while its process runs without a result;
  its JSON result under `~/.local/state/board/upkeep/` is the card's progress and the receipt's
  `report`, and what it printed to stderr sits beside it as `.err`, which the card names when a run
  ends without a result. Upkeep delivers only notes: its assignment runs the skill with no pull request, merge,
  or ticket write, pushes only where MEMORY.md is tracked in Git (there it commits exactly MEMORY.md, so the
  primary checkout keeps no uncommitted notes, and ships that commit only while it is the one commit
  the remote lacks), and stops at any step that needs the owner. One headless run works in a primary
  checkout at a time; a second press while one runs offers 「再試一次」.
- **No drop button** (owner, 2026-09-30): the owner drops work in a session, where `handoff` removes the
  entry, as new work is added; a per-card 不做了 repeated on every card and competed with its one step.
- **選這個** (decision options): dispatches the chosen option as a goal; the receiver records the
  decision in the workstream and carries out what follows. The other options of that question then
  show that it was answered.

A task is the source's Next as written (its Blocker when Next is empty), the chosen option, or the
failing pull request. `--open` serves the page from `launch.py` on `127.0.0.1` with a
per-run token; it accepts only the actions embedded in the page it serves, exits after two idle
hours or within a minute of a newer server starting for the same page, and records each launch in `launches.json`, so a card launches once. Only a failure that
created nothing, or whose preserved worktree the owner has cleared in Orca, offers 「再試一次」. A launch
that failed after its receiver started keeps that receiver's terminal; once the receiver is seen
working or finished, the record turns into a delivered dispatch, since what the receiver did outranks
what the launcher could prove. Its log is `launcher.log`. An unexpected launcher error is written to
`errors.log`, which the next board run prints once as `error:` lines, and a page that cannot read
its progress says so under the header stamp instead of freezing its cards. The page opens in Orca's browser, never
the system browser, so the owner stays in Orca (owner choice 2026-09-30): in the project's primary
checkout, or the active worktree with `--all`, reusing the tab an earlier board run left there.

A dispatch is in flight while its worktree exists: the receiver removes it last, and a failed launch that
preserved one holds it until the owner clears it in Orca. While in flight,
no card of the same workstream can dispatch again, even after its text changes, and each such card
shows the receiver's progress: no PR yet, PR open with its checks, merged and finishing, or finished
once the worktree is gone, MEMORY.md was written after the launch, and local main holds every merged
commit. Those are the observable part of the
[receiver completion receipt](../../milestone-dispatch/references/handoff-contract.md#receiver-completion-receipt);
anything short of them is a warning, since removal alone proves nothing. A finished dispatch's
receipt under 你上次看之後 reads 已合併，還沒生效 instead of 派工結束 while local main lacks its merge
commit, and a sync the launcher cannot read counts as unproved, not finished. A card that showed a dispatch keeps showing it after it finishes,
pointing to a fresh `/board` for the next step, instead of offering the step it was rendered with. The launcher reads it from `orca terminal list` and `gh pr view` at most
every 20 seconds, and the page refreshes it every 30. A receiver whose terminal is gone, whose PR
closed unmerged, or that has printed nothing for ten minutes shows in the warning color with a
prompt to look in Orca.
