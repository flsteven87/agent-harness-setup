---
name: mac-space
description: "Free disk space on this Mac through the shared cleanup script, its run log and owner rules. Use for 清理 Mac 空間, low disk space, deep cleanup, or the scheduled Mac 空間維護 run."
---

# Mac space

Reclaim disposable development artifacts and explain persistent disk pressure. One script owns
deletion rules; one log owns measurements:

- Script: `~/.local/share/orca/system-automations/scripts/mac-space-maintenance`
  (dry run by default, `--apply` to clean, `--due` for the Orca precheck). Its tests:
  `scripts/test-mac-space-maintenance` beside it.
- Run log: `~/.local/state/mac-space/runs.jsonl`, one JSON record per `--apply`.

## Disposable and owned

Every byte is **disposable** or **owned**.

- **Disposable**: cache entries their manager releases, development leftovers whose owner has
  released them (task complete, worktree gone, owning process exited, or container removed), or
  artifacts which a newer copy in use supersedes. Prove release and check consumers before
  removal. Rebuildability, age, a shutdown simulator or an idle process alone does not establish release.
- **Owned**: data a person or project still holds. Codex sessions and databases, project folders
  and their data or build directories (`var/`, `.build/`, `~/.local/state/<project>`), Docker named
  volumes, the Trash, browser profiles, the canonical simulators (one per project) and the Xcode
  DerivedData of a live workspace. Only the owner frees these; report the retaining owner,
  blocking condition and next executable inspection or authorized release command.

Read host-specific retention decisions from the owning workspace's private operating record before
cleaning. Preserve owned data when that record or the current release authorization is unavailable;
report its current size and the missing ownership evidence. Keep those personal/project decisions
out of the shared skill.

## Measurements

`free_kib.after - free_kib.before` is the run's observed net change. `freed_kib` records each
section's df change; concurrent development can make a section negative or larger than its target.
Report these as observed changes, with concurrent activity when present. `du`, Docker reclaimable
sizes and `size_kib` locate growth; APFS clones, hardlinks and sparse disks make them estimates,
not additive reclaim promises. In particular, Chrome code-sign clones share app blocks.

## Steps

1. **Baseline.** Read the last three run records and run the script without arguments. Consult
   only the `mac-space-maintenance` checkpoint in the workspace's `MEMORY.md` when resolving an
   ownership question. Done when current free space, exact preview targets and known consumers
   are accounted for. Orca run history retains reports; earlier transcripts are not a prerequisite.
2. **Clean.** Run the script with `--apply`; it holds a lock, and exit 3 means another run holds
   it, so report and stop. Done when the new record is appended and every `failed` entry has a
   cause from its command output; a held target names its retaining owner. Retry once only after
   a bounded correction or observed change. Hold targets whose ownership or measurement is unavailable.
3. **Check pressure.** Continue to growth tracing when the user requests deep cleanup, recorded
   free space after cleanup is below 25 GiB, or a comparable logged source grew at least 1 GiB
   since the previous run. Otherwise report. Reclaiming 1 GiB alone does not resolve low space.
   Done when the selected branch is supported by the run record.
4. **Trace growth.** Compare `size_kib` and `top_caches_kib` with the newest record at least six
   days older. If none exists, use the earliest earlier record and label the actual elapsed days;
   normalize to GiB/week using that interval. A missing field is unknown, not zero; without two
   comparable timestamps, report size with an unavailable rate.
   Rank positive growth, merging overlapping paths before selecting the top three. Inspect those
   directories one level down; use `docker system df -v` for the Docker disk. If logged sources
   leave pressure unexplained, inspect one level under the home and Library directories and the
   user's macOS temporary roots from `getconf DARWIN_USER_TEMP_DIR`, including sibling `X/`.
   Drill only into the largest unexplained branch. Done when each leading source has measured
   growth or an explicit baseline gap, ownership evidence, and a safe action or named retaining owner.
5. **Make rules.** A disposable source of at least 1 GiB, or one that recurs across runs, gets a
   rule in the script: a deterministic safe-to-remove test from the disposable definition, a dry
   run listing exactly the intended targets and nothing owned, a test in
   `scripts/test-mac-space-maintenance` when the rule has pure logic, passing tests, a commit of
   exactly the rule and its test in the system-automations repository, then `--apply`. Done when a
   fresh dry run lists no eligible targets left in the new category. If a category is held, record
   its owner and release condition; other safe categories can finish. The script remains the sole
   deletion path, so new discoveries become reviewed rules rather than one-off shell removals.
6. **Report** in Traditional Chinese: observed net change and current free space; per-section
   changes, failures and causes; leading growth sources and their measurement window; rules added
   and preview verification; retained data with owner and next action. Remaining low space ends
   with its cause and executable next action, rather than a successful-cleanup label alone.
   For the largest owned source without a recorded decision, ask once in an interactive session;
   scheduled runs report it for the owner. Finish when the run record exists, the cleanup lock is
   released, and every eligible new category is cleared or held for a stated owner condition.
