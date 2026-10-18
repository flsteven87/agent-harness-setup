# Agent Harness Setup

Shared skills and configuration for a Claude Code / Codex engineering workflow.

The repository includes task-completion contracts (`skills/endgame`), milestone delivery
(`skills/milestone-dispatch`), review, shipping and session continuity, together with host setup
scripts. Skill instructions describe a workflow; actual permissions and repository delivery
policy remain authoritative.

## Setup

Read `AGENTS.md` before installing. The expected location is `~/.agents`:

```sh
gh repo clone flsteven87/agent-harness-setup ~/.agents -- --recurse-submodules
uv run --no-project --with tomlkit python ~/.agents/scripts/bootstrap.py
```

Bootstrap also installs the separately maintained `claude-code-setup` companion configuration.
Review both configurations before running it. Authentication, required command-line tools and
host-specific integrations are configured on each host; copying configuration does not sign in.
The gh wrapper uses the caller's current authentication and contains no organization/account map.

## Local operating information

Company host instructions, account routing, project audits, archives, credentials and session
state belong outside the shared tracked tree. Personal research, `private/` and MEMORY.md are
ignored. Use neutral examples in shared instructions and test fixtures. Keep private host settings
in the runtime's local configuration rather than adding them to this repository.

## External packages

External skills and the Owl submodule retain their upstream provenance. See `.skill-lock.json`,
`external-skills.json` and `.gitmodules`; update through their existing source-management route.
Third-party licenses and notices remain attached to their respective packages.
