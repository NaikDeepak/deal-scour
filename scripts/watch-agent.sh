#!/usr/bin/env bash
# Watch an interactive agent running in a tmux session, so the lead agent (or you) doesn't have to.
#
#   scripts/watch-agent.sh <tmux-session> <agent-name> <lead-name> [minutes]
#   e.g. scripts/watch-agent.sh agy agy claude 40
#
# Every 15 s it looks at the agent's screen and the notepad, and exits (so the lead wakes up) when:
#   - the agent wrote a HANDOFF to the lead in the notepad          → "HANDOFF"
#   - the agent asks permission for something not on the safe list  → "PROMPT (needs decision): <command>"
#   - time is up                                                    → "TIMEOUT"
# Safe read-only/test commands are approved automatically and logged to .collab/approvals.log.
#
# The approval option is chosen by READING THE OPTION TEXT, never by a hard-coded number: some prompts are
# "1 Yes / 2 No", others "1 Yes / 2 Yes, always this conversation / 3 … / 4 No". Pressing "2" blindly once
# declined a test run and left the agent idle.
#
# Tuned for the Antigravity CLI prompt ("Requesting permission for:"). For another CLI set PROMPT_RE,
# CMD_AFTER (the line after which the command is printed), and QUESTION_RE. Extend SAFE_RE for your stack's test commands.
set -euo pipefail

SAFE_RE="${SAFE_RE:-^(ls|cat|head|tail|wc|find|grep|rg|pwd|echo|git status|git diff|git log|git show|git grep|git branch|npm test|npm run test|npm run typecheck|npm run lint|npx vitest run|npx tsc --noEmit|pytest|go test|cargo test|scripts/collab\.sh|\./scripts/collab\.sh)( |$)}"
PROMPT_RE="${PROMPT_RE:-Requesting permission for:}"
CMD_AFTER="${CMD_AFTER:-Requesting permission for:}"
QUESTION_RE="${QUESTION_RE:-^ *Run this command\?}"

COMMON="$(git -C "$(dirname "$0")" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
if [[ -n "$COMMON" ]]; then ROOT="$(dirname "$COMMON")"; else ROOT="$(cd "$(dirname "$0")/.." && pwd)"; fi
PAD="${COLLAB_DIR:-$ROOT/.collab}/notepad.md"
LOG="${COLLAB_DIR:-$ROOT/.collab}/approvals.log"

handoffs() { grep -c "$AGENT → $LEAD | HANDOFF" "$PAD" || true; }

# Safe only if single-line and every part of a chain (&&, ||, ;) is on the safe list. Inside double quotes
# &, |, ; are plain text, but $… and backticks still need a human; inside single quotes everything is plain text.
# Pipes, redirects (<, >), lone &, and dangerous flags need a human decision.
is_safe() {
  local s="$1" len i=0 state="none" c c2 c_next
  local current_masked="" current_literal=""
  local masked_parts=() literal_parts=()
  local m_part l_part idx parts_checked=0
  local var_re='^[a-zA-Z_{0-9(]'

  [[ "$s" == *$'\n'* ]] && return 1
  [[ -z "${s//[[:space:]]/}" ]] && return 1
  # anything that names a secret-looking file is shown to a human, even a read: the agent's model would see it
  printf '%s' "$s" | grep -qiE '(\.env|\.pem|\.key|id_[a-zA-Z0-9*]|\.ssh/|credentials|secret|\.npmrc|\.netrc)' && return 1

  len=${#s}
  while (( i < len )); do
    c="${s:i:1}"
    c2="${s:i:2}"

    if [[ "$state" == "single" ]]; then
      if [[ "$c" == "'" ]]; then
        state="none"
        current_masked="${current_masked}Q"
      else
        current_literal="${current_literal}${c}"
      fi
      (( i++ ))
    elif [[ "$state" == "double" ]]; then
      if [[ "$c" == '"' ]]; then
        state="none"
        current_masked="${current_masked}Q"
        (( i++ ))
      elif [[ "$c" == '`' ]]; then
        return 1
      elif [[ "$c" == '$' ]]; then
        c_next="${s:i+1:1}"
        if [[ "$c_next" =~ $var_re ]]; then return 1; fi
        current_literal="${current_literal}${c}"
        (( i++ ))
      else
        current_literal="${current_literal}${c}"
        (( i++ ))
      fi
    else
      # state == "none" (outside quotes)
      if [[ "$c" == "'" ]]; then
        state="single"
        (( i++ ))
      elif [[ "$c" == '"' ]]; then
        state="double"
        (( i++ ))
      elif [[ "${s:i:11}" == "2>/dev/null" ]]; then
        current_masked="${current_masked} "
        current_literal="${current_literal} "
        (( i += 11 ))
      elif [[ "${s:i:4}" == "2>&1" ]]; then
        current_masked="${current_masked} "
        current_literal="${current_literal} "
        (( i += 4 ))
      elif [[ "$c" == '\' || "$c" == '`' || "$c" == '<' || "$c" == '>' || "$c" == '{' || "$c" == '}' || "$c" == '$' ]]; then
        return 1
      elif [[ "$c2" == '&&' || "$c2" == '||' ]]; then
        masked_parts+=("$current_masked")
        literal_parts+=("$current_literal")
        current_masked=""
        current_literal=""
        (( i += 2 ))
      elif [[ "$c" == ';' ]]; then
        masked_parts+=("$current_masked")
        literal_parts+=("$current_literal")
        current_masked=""
        current_literal=""
        (( i++ ))
      elif [[ "$c" == '&' || "$c" == '|' ]]; then
        return 1
      else
        current_masked="${current_masked}${c}"
        current_literal="${current_literal}${c}"
        (( i++ ))
      fi
    fi
  done

  # ending inside a quote -> human
  [[ "$state" != "none" ]] && return 1
  masked_parts+=("$current_masked")
  literal_parts+=("$current_literal")

  for idx in "${!masked_parts[@]}"; do
    m_part=$(printf '%s' "${masked_parts[idx]}" | sed 's/^ *//; s/ *$//')
    l_part=$(printf '%s' "${literal_parts[idx]}" | sed 's/^ *//; s/ *$//')
    [[ -z "$m_part" && -z "$l_part" ]] && continue
    (( parts_checked++ ))
    printf '%s' "$m_part" | grep -qE "$SAFE_RE" || return 1
    # "safe" commands that can still write or delete
    if printf '%s' "$m_part" | grep -qE '^git branch( |$)'; then
      printf '%s' "$l_part" | grep -qE '^git branch( +(--show-current|--list|-a|-r|-v|-vv|--all|--remotes|--verbose))* *$' || return 1
    fi
    printf '%s' "$l_part" | grep -qE '(^find .*-(exec|execdir|ok|delete|fprint|fls))|(^git (diff|log|show) .*(--output|--ext-diff))|(^git grep .*(-[a-zA-Z]*O|--op))|(^rg .*--pre(=| |$))|(^tail .*(-[a-zA-Z0-9]*[fF]|--follow))' && return 1
  done

  [[ $parts_checked -eq 0 ]] && return 1
  return 0
}

# Collect command lines after CMD_AFTER up to the first blank line or QUESTION_RE. Not at an option-looking line:
# a wrapped command can continue with "1.txt && rm …", and the options always come after the question anyway.
extract_cmd() {
  local screen="$1" found=0 line trimmed res=""
  while IFS= read -r line || [[ -n "$line" ]]; do
    if [[ "$line" == *"$CMD_AFTER"* ]]; then
      found=1; res=""
      continue
    fi
    if [[ $found -eq 1 ]]; then
      trimmed=$(printf '%s' "$line" | sed 's/^ *//; s/ *$//')
      if [[ -z "$trimmed" || "$line" =~ $QUESTION_RE ]]; then
        found=0
        continue
      fi
      if [[ -z "$res" ]]; then res="$trimmed"; else res="$res"$'\n'"$trimmed"; fi
    fi
  done < <(printf '%s\n' "$screen")
  printf '%s' "$res"
}

# Pick the option number to approve: prefer "this conversation/session", else plain "Yes". Never "always"
# persisted to settings, never "No".
pick_option() {
  local screen="$1" n
  n=$(printf '%s\n' "$screen" | grep -iE '^[> ]*[0-9]+\. .*yes.*(this conversation|this session)' | grep -viE 'persist|settings' | head -1 | sed -E 's/^[> ]*([0-9]+)\..*/\1/')
  [[ -z "$n" ]] && n=$(printf '%s\n' "$screen" | grep -iE '^[> ]*[0-9]+\. yes' | grep -viE 'always|persist' | head -1 | sed -E 's/^[> ]*([0-9]+)\..*/\1/')
  printf '%s' "$n"
}

screen_tail() { echo "--- screen:"; tmux capture-pane -t "$SESSION" -p 2>/dev/null | grep -v '^\s*$' | tail -14 || true; }

# Tests source this file with WATCH_AGENT_LIB=1 to check is_safe / pick_option without tmux.
[[ "${WATCH_AGENT_LIB:-}" == 1 ]] && return 0

SESSION="${1:?tmux session}"; AGENT="${2:?agent name}"; LEAD="${3:?lead name}"; MINUTES="${4:-40}"
mkdir -p "$(dirname "$PAD")"; touch "$PAD"
start=$(handoffs); approved=0
INTERVAL="${WATCH_INTERVAL:-15}"   # seconds between looks (tests use 1)
for _ in $(seq 1 $((MINUTES * 60 / INTERVAL))); do
  sleep "$INTERVAL"
  if [[ "$(handoffs)" -gt "$start" ]]; then echo "HANDOFF (auto-approved $approved)"; exit 0; fi
  screen=$(tmux capture-pane -t "$SESSION" -p 2>/dev/null || true)
  if printf '%s' "$screen" | grep -q "$PROMPT_RE"; then
    cmd=$(extract_cmd "$screen")
    opt=$(pick_option "$screen")
    if is_safe "$cmd" && [[ -n "$opt" ]]; then
      tmux send-keys -t "$SESSION" "$opt"; sleep 1; tmux send-keys -t "$SESSION" Enter
      approved=$((approved + 1))
      printf '%s | %s | option %s | %s\n' "$(date '+%Y-%m-%d %H:%M')" "$AGENT" "$opt" "$cmd" >> "$LOG"
      sleep 3; continue
    fi
    echo "PROMPT (needs decision): $cmd"; screen_tail; exit 0
  fi
done
echo "TIMEOUT after $MINUTES min (auto-approved $approved)"; screen_tail
