---
name: board
description: "Reconcile workstream notes against current evidence, then open the project manager page with outcomes, decisions and dispatch buttons. Use for the board, 看板, cross-project 總覽, or what needs the owner’s attention."
---

# Board

Give the owner a manager's view on one page: what changed, what waits on them, and what to do
first, so they learn a project's state without a catch-up. The script collects the facts and renders
the page; you write the plain-language briefs it cannot.

## Steps

1. Read [references/refresh.md](references/refresh.md) and complete its reconciliation for the
   requested project (or every Orca-registered project with `--all`). Opening the board authorizes
   this bounded notes refresh. Done when each selected entry is reconciled or has a specific
   unresolved reason; a new file timestamp alone is not completion.
2. Run from the session's working directory, as a plain command that returns at once:

   ```bash
   python3 ~/.agents/skills/board/scripts/board.py --open
   ```

   The project is the primary checkout of the repository containing that directory. Add `--all` when
   the user asks for every project, the overview, or 總覽 (when Orca is not running it exits with the
   fix, `orca open`). Exit 0 means the page is rendered and open in Orca's browser (a `not shown in Orca` line names why
   it is not): go to step 5. Exit 3 means briefs
   are missing and it printed a `.pending.json` path.
3. Read the pending file and [references/plain-language.md](references/plain-language.md), then
   write one brief per item, keyed by its `id`, to a JSON file in the scratchpad. Done when every
   item has a brief that passes the contract's closing check.
4. Rerun the same command with `--briefs <file>` until it exits 0. An invalid brief exits with each
   problem named and saves nothing: fix those and rerun with the whole file. An exit 3 means a
   source changed meanwhile: brief the newly pending items into the same file and rerun.
5. Reply with the page URL and the lines the script printed after it: the counts, each `focus` line
   as that project's 「建議先做」 with its reason, and each `stale` line as a warning that the
   project's notes miss that many updates. Report any remaining 筆記可能過時 cards with their
   unresolved reason; 更新筆記 runs the same reconciliation as step 1. Report
   each `behind` line as merged work that is not live on this machine until local main syncs, which
   the page's 更新筆記 button does. Each `since` line is what changed since the owner last looked;
   name the finished dispatches' results. Each `error` line is the board itself failing since the
   last run: tell the owner in one line what broke and offer to fix it. Each `loose` line names notes
   written outside any workstream entry, which no card shows until 更新筆記 sorts them.
   Leave the cards on the page.

## Wrong facts

Correct facts in the original `MEMORY.md` entry through the refresh contract, then regenerate its
brief. A renderer-only invocation collects Git/PR facts but does not perform agent reconciliation.
Read [references/page.md](references/page.md) when the owner asks how a section or button works,
when a launch fails, or before changing the page or its launcher.
