---
name: session-insights
description: Mine Claude Code and Codex session history for recurring failures and friction, then turn verified patterns into AI-layer fixes. Use when the user asks to analyze past sessions or transcripts, find what keeps failing across agents, measure a setup change, or tune rules, skills, hooks, and MCP config from evidence.
---

# Session Insights

Past sessions are the evidence base for the AI layer. One local SQLite warehouse normalizes Claude
Code transcripts (`~/.claude/projects/**/*.jsonl`) and Codex rollouts (`~/.codex/sessions/**` plus
each Orca account home's `sessions/`, where Orca-launched Codex runs) into the same tables, so one
query answers for both runtimes. Nothing leaves the machine.

## Warehouse

- Database: `~/.local/state/session-insights/sessions.db` (mode 600). Rows outlive their source
  files, so history survives Claude Code's 30-day transcript cleanup.
- Freshness: every command ingests changed files first (about a minute cold, seconds warm). A
  Claude Code `SessionEnd` hook in `~/.claude/settings.json` also refreshes it in the background.
- Tables, all keyed by `session_id` and carrying `agent` (`claude` | `codex`):
  - `sessions`: `origin` (`interactive` | `exec` | `subagent`), `parent_id`, `cwd`, `model`,
    `started_at`, `ended_at`, counts, `input_tokens` (cache included), `cached_tokens`,
    `cache_write_tokens`, `output_tokens`, `compactions`, `interrupts`, `api_calls`, and
    `first_context` / `peak_context` (prompt tokens of the first and largest request; the first is
    the fixed setup baseline).
  - `prompts`: human or dispatching prompts, `text` clipped to 2,000 characters. Slash and `$`
    skill invocations appear as typed.
  - `tool_calls`: `tool` (Claude tool name; Codex `shell`, `apply_patch`, `mcp:<server>.<tool>`,
    `collab:<tool>`, `sleep`, `wait`), `detail` (command, path, or arguments), `is_error`, `error`
    (400 characters), `duration_ms` (Codex only), `output_chars` (text returned into context;
    about 4 characters per token), `images`.
  - `events`: `interrupt`, `compaction` (`size` = tokens before compaction, Claude), `turn_aborted`,
    `api_error`, `skill_load` (Claude Skill tool; `detail` = skill, `size` = characters).
    `endgame` (`detail` = `contract`, `DONE`, `BLOCKED`, or `DROPPED`, from plain-text lines in
    agent replies). Claude transcripts can store text written before a tool call as a thinking
    summary, so a missing `contract` in an interactive Claude session may be unrecorded, not
    skipped; close lines end a turn and are recorded.
- SQL helpers: `sig(error)` normalizes an error to a signature; `regexp(pattern, text)` is
  case-insensitive.

## Run

```bash
python3 ~/.agents/skills/session-insights/scripts/insights.py report --days 14
python3 ~/.agents/skills/session-insights/scripts/insights.py sql "SELECT ..."
```

The report covers volume and error rate by agent and origin, the tools with the most errors,
recurring error signatures, friction signals (bare 「繼續」/ack prompts, missing-path errors, sleep
polling, hook and permission denials, repeated failing calls), autonomy and understanding (「什麼意思」
asks per 100 prompts against the previous window; `/endgame` runs, contracts, and closes), the
heaviest sessions, and the most frequent prompts. Scope the window to the question: 14 days for tuning, the days since a change for
measuring it.

## Token questions

Cost follows tokens read, and cache reads dominate it: every request re-reads its whole context.
Split a token question into three levers before proposing a fix: the fixed baseline
(`first_context` times `api_calls`), context growth from tool output (`output_chars`, weighted by
the calls that follow it in the session), and long sessions (`peak_context`, compactions). Measure
a compaction or baseline change by comparing periods before and after it, not by totals alone.

## From signal to fix

1. Rank patterns by sessions affected, then by wasted calls. A signature seen in one session is an
   anecdote; skip it.
2. Before deciding, read the rows behind each candidate with `sql`: the failing `detail`, the full
   `error`, and the session's `cwd` and first prompt. Count the success rate of the working
   alternative too (for example, bare versus absolute filenames), so the fix rests on a contrast
   rather than a guess.
3. Assign each pattern to its owner:
   - Shared behavior of both runtimes: one line in `~/.agents/PROFILE.md`, or a shared skill
     here.
   - One runtime only: that runtime's profile, settings, or MCP config.
   - A product repository's hook, AGENTS.md, or config: a follow-up with the exact file and line.
   - A tool or vendor defect, or a guard that already self-corrects in one call: report it only.
4. Prefer the smallest change that removes the failure: a profile line, a config flag, a path fix.
   Widening a permission or file-access boundary needs the user's decision.
5. Put the baseline in the commit message or report (count, sessions, window), so the next run
   of this skill measures the effect with the same query.

## Known noise

- Codex `shell` errors with an empty signature are usually `grep` or `test` returning exit 1 on no
  match.
- Claude `Bash` guard blocks (`rm` → `trash`, blocked `sleep`) are working as designed unless they
  repeat within a session.
- `subagent` prompts are the parent agent's brief, not the user's words; human-prompt signals use
  non-subagent sessions.
