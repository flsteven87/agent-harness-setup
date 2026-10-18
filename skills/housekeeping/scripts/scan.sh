#!/usr/bin/env bash
# Read-only scan for Codex agent artifacts.

set -u
set -o pipefail

TARGET_PROJECT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project)
      TARGET_PROJECT="${2:-}"
      shift 2
      ;;
    *)
      shift
      ;;
  esac
done

if [[ -z "$TARGET_PROJECT" ]]; then
  GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || true)
  if [[ -n "$GIT_ROOT" ]]; then
    TARGET_PROJECT="$GIT_ROOT"
  else
    TARGET_PROJECT="$(pwd)"
  fi
fi

CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
AGENTS_HOME="${AGENTS_HOME:-$HOME/.agents}"
PROJECT_ENCODED=$(printf '%s' "$TARGET_PROJECT" | sed 's|/|-|g')

line_count() {
  if [[ -f "$1" ]]; then
    wc -l < "$1" | tr -d ' '
  else
    printf '0'
  fi
}

size_kb() {
  if [[ -f "$1" ]]; then
    local bytes
    bytes=$(wc -c < "$1" | tr -d ' ')
    printf '%s' "$(( bytes / 1024 ))"
  else
    printf '0'
  fi
}

mtime_days() {
  local path="$1"
  local now mtime
  now=$(date +%s)
  if [[ "$(uname)" == "Darwin" ]]; then
    mtime=$(stat -f %m "$path" 2>/dev/null || printf '0')
  else
    mtime=$(stat -c %Y "$path" 2>/dev/null || printf '0')
  fi
  printf '%s' "$(( (now - mtime) / 86400 ))"
}

print_file_status() {
  local label="$1"
  local path="$2"
  if [[ -f "$path" ]]; then
    local lines kb age
    lines=$(line_count "$path")
    kb=$(size_kb "$path")
    age=$(mtime_days "$path")
    printf '  %s: %s lines, %sKB, %sd old, %s\n' "$label" "$lines" "$kb" "$age" "$path"
    if (( lines > 220 )); then
      printf '    WARN: large agent-facing file; review it for stale or duplicated configuration.\n'
    fi
  else
    printf '  %s: not found\n' "$label"
  fi
}

printf '==========================================\n'
printf ' Codex Housekeeping Scan\n'
printf ' %s\n' "$(date '+%Y-%m-%d %H:%M')"
printf ' Project: %s\n' "$TARGET_PROJECT"
printf '==========================================\n'

printf '\n## 1. Instruction Surfaces\n'
print_file_status "Global AGENTS.override.md" "$CODEX_HOME/AGENTS.override.md"
print_file_status "Global AGENTS.md" "$CODEX_HOME/AGENTS.md"
print_file_status "Repo AGENTS.override.md" "$TARGET_PROJECT/AGENTS.override.md"
print_file_status "Repo AGENTS.md" "$TARGET_PROJECT/AGENTS.md"

printf '\n## 2. Codex Config And Local Surfaces\n'
print_file_status "Codex config.toml" "$CODEX_HOME/config.toml"
if [[ -d "$TARGET_PROJECT/.codex" ]]; then
  find "$TARGET_PROJECT/.codex" -maxdepth 2 -type f | sort | while IFS= read -r f; do
    printf '  .codex file: %s lines, %sd old, %s\n' "$(line_count "$f")" "$(mtime_days "$f")" "$f"
  done
else
  printf '  Repo .codex/: not found\n'
fi

printf '\n## 3. Skills\n'
for dir in "$AGENTS_HOME/skills" "$TARGET_PROJECT/.agents/skills" "$CODEX_HOME/skills"; do
  if [[ -d "$dir" ]]; then
    count=$(find "$dir" -mindepth 2 -maxdepth 2 -name SKILL.md -type f 2>/dev/null | wc -l | tr -d ' ')
    printf '  %s: %s skills\n' "$dir" "$count"
    find "$dir" -mindepth 2 -maxdepth 2 -name SKILL.md -type f 2>/dev/null | sort | while IFS= read -r skill; do
      rel=${skill#"$dir/"}
      printf '    %s: %s lines\n' "$rel" "$(line_count "$skill")"
    done
  else
    printf '  %s: not found\n' "$dir"
  fi
done

printf '\n## 4. Memory And Handoffs\n'
for dir in "$TARGET_PROJECT/.agents/handoffs" "$TARGET_PROJECT/.codex/handoffs"; do
  if [[ -d "$dir" ]]; then
    count=$(find "$dir" -type f -name '*.md' 2>/dev/null | wc -l | tr -d ' ')
    printf '  %s: %s markdown files\n' "$dir" "$count"
    find "$dir" -type f -name '*.md' 2>/dev/null | sort | while IFS= read -r f; do
      lines=$(line_count "$f")
      age=$(mtime_days "$f")
      printf '    %s lines, %sd old, %s\n' "$lines" "$age" "$f"
      if (( lines > 100 )); then
        printf '      WARN: large memory/handoff; consider trimming.\n'
      fi
      if (( age > 60 )); then
        printf '      WARN: stale memory/handoff; review relevance.\n'
      fi
    done
  else
    printf '  %s: not found\n' "$dir"
  fi
done

printf '\n## 5. Plans And Scratch Docs\n'
plans=$(find "$TARGET_PROJECT" -maxdepth 4 \( -name '*.plan.md' -o -name 'PLAN.md' -o -path '*/plans/*.md' \) -type f 2>/dev/null || true)
if [[ -n "$plans" ]]; then
  while IFS= read -r p; do
    [[ -z "$p" ]] && continue
    done_count=$(grep -Eci '\[x\]|COMPLETED|DONE' "$p" 2>/dev/null || true)
    todo_count=$(grep -Eci '\[ \]|TODO|PENDING|IN PROGRESS' "$p" 2>/dev/null || true)
    printf '  %s: %s lines, done=%s, pending=%s\n' "${p#"$TARGET_PROJECT/"}" "$(line_count "$p")" "$done_count" "$todo_count"
    if (( todo_count == 0 && done_count > 0 )); then
      printf '    CANDIDATE: completed plan; safe to review for archive/delete.\n'
    fi
  done <<< "$plans"
else
  printf '  No plan files found within depth 4.\n'
fi

printf '\n## 6. Git Snapshot\n'
if git -C "$TARGET_PROJECT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git -C "$TARGET_PROJECT" status -sb
else
  printf '  Not a git repository.\n'
fi

printf '\n==========================================\n'
printf ' Scan complete. This script made no changes.\n'
printf '==========================================\n'
