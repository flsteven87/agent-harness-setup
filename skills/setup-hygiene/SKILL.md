---
name: setup-hygiene
description: Audit and safely reconcile projectless user-level agent setup integrity without performing software or plugin updates.
---

# Setup Hygiene

Keep the user-level agent harness coherent after installers, updaters, schedulers, and manual
maintenance change it. The leading word is **integrity**: current evidence, one owner per reusable
rule or scheduled purpose, and live pointers that resolve in every active runtime home.

This is an explicit periodic or human-invoked workflow. It is not a general cleanup permission.

## Ownership boundary

- Setup Hygiene owns structural drift under `$HOME`: agent instructions, personal skills and aliases,
  user-level settings pointers, shell startup composition, scheduler ownership evidence, backup
  candidates, and its own bounded state.
- It may run official read-only diagnostics in every discovered Codex home. Runtime warnings are
  evidence for the daily development-tool updater, not permission to repair runtime state here.
- The daily development-tool updater owns versions, installs, upgrades, marketplaces, plugins, MCP
  registry currency, and runtime health. Hand those findings to that workflow without acting on them.
- `$housekeeping` owns project-local agent artifacts. `$git-converge-main` owns classification and a
  human-invoked exact cleanup pass for branches, worktrees, stashes, commits, and history. Stop at
  either overlap; Setup Hygiene performs no Git mutation.
- Permission policy, credentials, OAuth state, product repositories, Orca workspaces, graph data,
  conversation recovery, and the macOS Trash retain their current owners. A scheduler edit requires
  an active request that names that operation; a scheduled hygiene run cannot edit its own schedule.

## Verdicts

Read [references/verdicts.md](references/verdicts.md) when assigning verdicts. It owns the five
terminal verdicts, record accounting, evidence bar, false positives, and destinations.

## Run

### 1. Collect current evidence

Run from `$HOME`. Read the job's current state at
`~/.local/state/setup-hygiene/state.md` when it exists. Choose the doctor scope before running:
use `active` for a daily scheduled run, or `all` after a Codex version/config change or a human
full audit. The daily command is:

```bash
python3 ~/.agents/skills/setup-hygiene/scripts/scan.py --format json --doctor-scope active
```

The collector is the only bulk-enumeration path. It runs redacted `codex doctor --json` separately
for discovered Codex homes, checks strict config and explicitly enabled feature maturity, measures
state freshness, and reconciles scheduler ownership. Every record's `status`, including `candidate`,
is a triage hint; step 2 assigns terminal verdicts.
Do not repeat its scans with ad hoc session parsing or unbounded filesystem searches.

Save the collector JSON once in the run's temporary evidence directory and reuse it for confirmation
and counting. Complete when the JSON parses and each discovered Codex home has a doctor result,
an explicit scope exclusion, or a bounded reason it could not be measured. `active` probes only
the identified Orca runtime; an unidentified runtime or timeout remains `blocked` for this run.

### 2. Confirm drift

For every non-clean record, use one independent check on the exact artifact needed to distinguish a
live pointer from an example, a duplicate owner from an intentional adapter, a current checkpoint
from stale state, and a real scheduler conflict from disabled historical registration. Never print
secret-like values or raw doctor details.

Compare confirmed findings with the prior state. Keep standing user preferences; compare
artifact-specific exemptions against their recorded paths and fingerprints. Reopen an exemption
when that evidence changes; mark a missing baseline unverified rather than inventing one. Close
resolved retry keys with evidence; retain open keys only with concrete discharge conditions.

Use a temporary ledger keyed by the collector record's array index. Follow
[record accounting](references/verdicts.md#record-accounting) for dispositions, aggregates, and
counts. Complete when each record has exactly one terminal verdict, each non-clean verdict has
the required exact-artifact evidence, and computed verdict counts sum to `summary.records`.

### 3. Name the bounded repair set

The unattended repair class is deliberately narrow:

1. Re-point an existing `~/.claude/skills/<name>` symlink when it is broken or stale and exactly one
   matching canonical `~/.agents/skills/<name>` target exists.
2. Refresh this workflow's checkpoint at `~/.local/state/setup-hygiene/state.md` in step 4's shape.

Before repair, name every path in the set and record the pre-change observation. For settings,
configs, hooks, or Git status whose unchanged state the report will claim, capture a hash-only or
status baseline on those exact already-inventoried paths. Multiple plausible
targets, real-directory duplicates, authored content, settings, shell files, backups, plans, runtime
state, permissions, and Git state are `review` or `handoff`.

Complete when every proposed write is in the two classes above and has exactly one resolution;
otherwise leave it untouched.

### 4. Repair and prove

Apply the named set only. For each symlink repair, verify `readlink`, canonical resolution, and the
target `SKILL.md` with the active skill-creator validator. Observe the repaired skill in the runtime's
read-only discovery output; unavailable discovery is `blocked` with a named retry condition.

Write state atomically with schema version, scan/triage outcome, instruction digest, current runtime
and scheduler-owner maps, standing preferences/exemption evidence, and open retry keys. Each key
holds only its current path, observation, verdict, owner, and discharge condition. Keep repair
receipts, comparisons with previous runs, closed keys, and narrative in run history. Routine
checkpoint refresh keeps a current freshness record `clean`.

After writing, read back the exact bytes and compare the named protected baselines. Report these
post-write results separately from the checkpoint's scan/triage outcome. Complete when every
artifact repair is verified or `blocked` with recoverable state, the checkpoint matches its intended
bytes, and every claimed unchanged surface has matching evidence. Preserve all other owned surfaces.

### 5. Report

Return a standalone Traditional Chinese report that lets the user decide what to act on next: which
findings are settled, which need their judgment and what taking or leaving each one would cost or
lose, and which now belong to another workflow. Collapse clean surfaces to one counted line, lead a
scheduled run with changed evidence and material warnings, and keep secret-like values and raw doctor
details out of it. Scheduler registration, cadence, and automation mutation remain outside the run.

Include ledger totals and post-write proof. Remove disposable run evidence after reporting;
retain unique evidence only with a named owner and unresolved discharge condition.
