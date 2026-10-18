---
name: use-code-review-graph
description: Use only in repositories whose local AGENTS.md enables Code Review Graph. Answer whole-repository architecture, dependency, impact, ownership, and broad-review questions from the graph index; read source directly for one file or one symbol.
---

# Use Code Review Graph

CRG is a lifecycle-managed structural index of one Git worktree — symbols, files, and the edges
between them — served by the `code-review-graph` MCP server. It answers relationship questions in a
few hundred tokens that would otherwise cost many file reads. It is derived state, so it locates code
and never proves it.

## Opt-in gate

Repository-local instructions own CRG enrollment. Without an explicit opt-in in the current
repository's `AGENTS.md`, answer from `git diff`, `rg`, and targeted reads, and leave that
repository's graph uninspected and unqueued.

## Freshness gate

Resolve the exact Git worktree root, then run this before the first query of a pass:

```bash
~/.local/bin/crg-lifecycle inspect "$repo_root" --json
```

Query only when it returns `usable=true` and its built commit equals current `HEAD`. On
`usable=false`, work from `git diff`, `rg`, and targeted reads — an empty graph reads as unknown,
never as low risk — and in an opted-in repository the root agent may enqueue one provisioning request
and continue on that fallback in the same turn:

```bash
~/.local/bin/crg-lifecycle enqueue "$repo_root" "agent:graph-needed"
```

`coverage=partial` means the graph covers tracked source while `excluded_sources` lists parseable
untracked files: read each of those directly, and treat any symbol or edge that could live in one as
unresolved. Every response carries `_graph` provenance, and `head_matches_build=false` marks a stale
answer — re-run the freshness check instead of reporting from it.

## Calling the tools

The server's own tool descriptions carry the current tools, their arguments, and the query patterns.
Three things they do not tell you:

- Pass `detail_level="minimal"` to every tool that accepts it. The server default is `standard`, and
  the difference is not cosmetic: on a 4,200-file repository one `get_review_context_tool` call
  returns roughly 189 tokens at `minimal` and 160,000 at the default, and `get_impact_radius_tool`
  behaves the same way.
- Pass `repo_root` explicitly on every call. This machine runs many worktrees of the same repository.
- The `base` default of `HEAD~1` is rarely the review base you want, and review context returns full
  source unless you pass `include_source=false`.

Open a pass with `get_minimal_context_tool` on the real review base, then call the single narrowest
tool the question needs. Skip the graph when you already know the file, the symbol, or the exact
string: `rg` plus a targeted read is faster and needs no freshness check.

## Completion criterion

The graph is done when you can name the files and symbols the task turns on. Confirm every material
claim in the current diff or source before reporting or editing: CRG never proves behavior, tests,
review completion, or authority. Budget roughly five calls and 800 returned graph-context tokens;
past that, the question was a reading task.

## Writer boundary

- Consumers are read-only. `crg-lifecycle` and `crg-safe-refresh` own every write, rebuild, and
  recovery. Leave `code-review-graph build|update|watch` and `crg-daemon` to them, and leave every
  WAL and SHM sidecar in place.
- In an opted-in repository, the root agent enqueues one `agent:change-batch` event after one
  completed tracked-file change batch. Subagents never enqueue.
- A nonzero WAL, a lock error, a failed integrity check, or a low-disk stop is lifecycle recovery
  work, not a reason to retry the write.
