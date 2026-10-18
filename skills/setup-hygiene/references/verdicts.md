# Setup Hygiene Verdicts

Use this catalogue only after `scan.py` enumerates the live surface. A scan record is evidence to
triage, not permission to mutate.

## Terminal verdicts

- `clean`: the enumerated item passed its check or a candidate was dismissed with evidence.
- `repaired`: an observed defect received a permitted repair with post-change proof.
- `review`: evidence exists; mutation needs human judgment or new authority.
- `handoff`: another named workflow owns the finding.
- `blocked`: the check could not reach a verdict; name its discharge condition.

## Record accounting

Assign one verdict to each collector array index, including clean and aggregate records. Keep the
index, verdict, and confirmation in the temporary run ledger; repeated link occurrences remain
separate records. A dismissed candidate is `clean` with its false-positive class and evidence.

For an aggregate, name the child indices it summarizes. Use `clean` when all children are clean or
verified repaired; otherwise use the first applicable unresolved verdict in this order: `blocked`,
`review`, `handoff`. An aggregate is never itself `repaired`. Compute counts from this ledger and
verify that its index set is exactly `range(len(records))` and its total equals `summary.records`.
Collector hint counts and inventory quantities are separate from terminal verdict counts.

Record repair receipts separately from record verdicts: routine checkpoint refresh can change a
file while its freshness finding stays `clean`. The report owns post-write verification; the
checkpoint records the completed scan and triage, rather than predicting its own write verification.

## Pointer integrity

### Skill symlink

- Confirm with `readlink` plus target existence and a valid target `SKILL.md`.
- Re-point only an existing Claude skill symlink when exactly one same-named canonical Agents skill
  exists. This is the sole artifact repair class.
- A missing target, two plausible targets, or a real directory is `review`.
- Symlink spelling, a relative target, or a target outside the canonical tree is not itself a defect
  when resolution and ownership are intentional.

### Markdown pointer

- Confirm the link outside fenced examples and resolve it relative to the source document.
- Missing live documentation is `review`; authored content is never rewritten unattended.
- Dismiss illustrative links, templates, glob-like paths, generated-output examples, URI schemes, and
  project pointers that the workflow must not enter. A project pointer is `handoff`, not broken merely
  because the projectless scan does not resolve it.

### Settings path or command

- Confirm the exact key and resolve only the executable or path component; never print the whole value.
- A missing user-level hook, statusline, command, output style, agent, or rule target is `review`.
- Bare command names that resolve through the current process PATH are clean. Shell compounds and
  placeholders require human inspection rather than automatic parsing.

## Ownership integrity

### Skill identity

- Frontmatter `name` must match the containing skill folder after parsing quoted YAML scalars.
- A malformed entrypoint, folder mismatch, or invocation-policy disagreement is `review` and should
  name the validator evidence.
- `name: "value"` is equivalent to `name: value`; quote characters are not part of the name.

### Duplicate skill owner

- Compare both real directories and determine whether one is an adapter, a vendored copy, or a stale
  duplicate. A same-named real directory in Agents and Claude is only a candidate until that role is
  known.
- Report file-level divergence and the proposed survivor. Consolidation is a separate approved
  housekeeping change; this workflow does not choose or delete an owner.

### Instruction contradiction or sprawl

- Compare live meanings, not shared words. A rule duplicated with different authority or outcome is
  `review`.
- Line count is a routing signal only. Refactor when shared steps are buried by branch-specific
  reference, pointers are weak, or one meaning has multiple owners—not merely because a file is long.
- `$writing-for-agents` and `$skill-creator` own the authoring change after approval.

## Shell and configuration integrity

### Codex runtime homes and doctor

- Multiple Codex homes are clean when each is tied to an observed role such as default state,
  environment override, or active Orca runtime. Count alone is not drift.
- Use the collector's redacted doctor summary. A doctor warning or failure is `handoff` to the daily
  development-tool updater unless the evidence is an authored config pointer owned here.
- A doctor timeout, invalid JSON contract, or undiscoverable home is `blocked` with the exact probe
  and retry condition. Never inspect auth files or raw doctor details to compensate.
- An explicitly enabled experimental, under-development, removed, or unknown feature is `review`.
  Merely available non-stable features and explicitly disabled removed features are clean inventory.

### Scheduler ownership

- Disabled LaunchAgent and paused automation registrations are historical context, not duplicate
  owners. A purpose conflicts only when more than one measured scheduler is enabled for it.
- A duplicate enabled owner is `review`; name the purpose and owners. Editing registration, cadence,
  provider, workspace, or prompt requires an active request that names that operation.
- If Orca is a possible owner but its automation inventory cannot be measured, use `blocked`; do not
  infer ownership from old prompts or run history.

### Shell startup

- Syntax failure, duplicate effective PATH entries, missing managed-tool directories, dead aliases,
  and secret-like global exports are `review` with variable names only.
- Do not print values, source shell startup into the reporting process, or edit startup files
  unattended. Project-specific paths are `handoff`.

### MCP and plugin configuration

- Check only referential integrity and ownership: duplicate logical entries, missing local commands,
  stale absolute runtime paths, and enabled names absent from the local inventory.
- Versions, registry metadata, marketplace refresh, plugin update, server startup, health probes, and
  OAuth belong to the daily updater or the user. Mark them `handoff` without performing them.

## Sediment

### Setup Hygiene state freshness

- A missing, expired, or instruction-digest-mismatched checkpoint is `repaired` only after the live
  scan reconciles and this workflow atomically writes its own current state.
- A current checkpoint's freshness record remains `clean` after routine refresh; the write is not
  an additional finding or a repair. A failed checkpoint write is a separate `blocked` action.
- State age is a trigger for re-observation, not evidence that the recorded decision is wrong. Keep a
  standing decision until its evidence changes; keep an open retry key only with a discharge condition.
- The state records schema version, current digests and owner maps, standing decisions, open retry
  keys, and latest result. Session narrative and full doctor output belong elsewhere.

### Backup, temporary, cache, or quarantine candidate

- Confirm the current replacement exists and parses, identify the producer, record size and age, and
  state what information would disappear.
- All removal remains `review`. Filename patterns such as `.bak-pre-*`, `.pre-*`, `.tmp-*`, and
  quarantine are candidates, not proof that the data is disposable.
- Conversation recovery, session history, runtime snapshots, product decisions, and the macOS Trash
  are measure-only or excluded.

### Plan or decision record

- Completion markers do not prove disposability. Determine whether the file carries product decisions,
  release gates, regression evidence, or an unresolved action.
- Any removal or consolidation is `review` under `$housekeeping`.

### Memory or checkpoint growth

- Measure lines, bytes, oldest retained decision, active retry keys, and duplicated narrative.
- The daily updater's two memories are review-only. Preserve durable decisions and active discharge
  conditions; run history owns full narrative.
- This workflow may replace only its own state and keeps no historical transcript.

### Runtime-state growth

- Report count, size, and oldest modification time without reading content.
- Conversation, file-history, rollout, session, and recovery trees are telemetry only. Do not propose
  deletion merely to reclaim disk space.

## Ownership handoffs

- Version or installer currency → daily development-tool updater.
- Project-local agent artifact → `$housekeeping` with the exact project supplied by the user.
- Branch, worktree, stash, commit, or history → `$git-converge-main`.
- Permission, OAuth, credential, or source-trust decision → `review` for the user.
- Product repository, Orca workspace, graph data, or project state → out of scope and untouched.

## Verdict proof

A non-clean verdict is complete only with an exact path, observed state, expected state, owner, and
discharge condition. A `repaired` verdict additionally requires post-change observation. A proposed
removal additionally requires size, age, and an information-loss statement.
