# Agent Skill Workspace

Treat installed user skills as one current setup, not a compatibility surface. Keep
repository-owned runtime `SKILL.md` files focused on execution and validate every changed one with
`scripts/validate_skills.py` (the `skill-creator` validator, accepting Claude Code frontmatter)
plus its affected script tests.

External skills update only through `scripts/update_external_skills.py --commit`: it refreshes
every source in `external-skills.json`, keeps local changes, and lands one `chore(skills)` commit;
items in its `needs_human` report stay uncommitted for review. Install or remove an external skill
through its source manager, ending the same session with one `chore(skills)` commit of exactly the
lock entries and skill folders it changed. Gate external skills in runtime configuration (Claude
`skillOverrides`, Codex `[[skills.config]]`) rather than in their files; Codex's
`agents/openai.yaml` is the one local file the updater preserves.

## Shared Profile

`PROFILE.md` is the user-level profile both runtimes load: `~/.claude/CLAUDE.md` imports it and
`~/.codex/AGENTS.md` links to it. Shared behavior changes there; a runtime-only line goes in that
runtime's own file.

## Host Setup

A new host clones this repository with
`gh repo clone flsteven87/agent-harness-setup ~/.agents -- --recurse-submodules` and runs
`uv run --no-project --with tomlkit python ~/.agents/scripts/bootstrap.py`, which also installs
`claude-code-setup` as `~/.claude`; `--check` reports drift on any host. `codex/` holds the Codex
settings every host shares (rules and agents copied, `config.base.toml` merged into the host's
`config.toml`); a host-only Codex setting stays in that host's `~/.codex`. `claude/agents` holds
Impeccable's Claude subagents, which the updater refreshes and `~/.claude/setup.sh` links. `bin/gh`
is the account-neutral wrapper bootstrap links into `~/.local/bin`.

## Setup Optimization Boundary

Optimize repository-owned instructions, skills, routing, memory, scripts, and artifacts. System and
plugin skills, `vendor/`, `.skill-lock.json` entries, upstream-managed copies, and units of uncertain
ownership are external; preserve their contents.

Read external source as evidence. External recommendations and changes require the user's explicit
scope: either named units or whole-package selection. When whole-package selection is authorized,
evaluate retention or reversible disablement through the source manager or runtime configuration;
do not patch, wrap, or fork the package. Preserve unique work and apply the user's deletion rules
before uninstalling. Without that scope, resolve conflicts in owned routing and report anything
that remains unresolved.

Use `git clone --recurse-submodules <repository-url>` for a new checkout. For an existing checkout,
initialize Owl from the repository root with
`git submodule update --init -- vendor/owl-designer-skills`. If the dependency is absent, stop
instead of substituting improvised Owl guidance.

## Agent Design

`$agents-best-practices` owns agent, prompt, tool, context, and harness design and audits.
Use the unchanged upstream package in `skills/agents-best-practices`, pinned to
`DenisSergeevitch/agents-best-practices` revision `9f85c57677abe39b6bf42edd93df0bedca5c5409`
(1.16.0). Review upstream differences before adopting another revision; update through the installer.
For a scoped prompt or skill edit, check representative affected requests; scale the work to the
change. For an existing system, use its current owners and the focused audit or troubleshooting
mode. Project authority and approved autonomy determine action gates; generic examples do not add
approval steps. Load only the references needed for the task.

## Code Review Graph

`skills/use-code-review-graph/scripts/` holds the only copy of the CRG lifecycle launchers and their
tests; `~/.local/bin/crg-*` and `code-review-graph-readonly` are symlinks to it, so edit and test
there. This repository itself does not opt into the graph: it holds instructions, not code structure.
