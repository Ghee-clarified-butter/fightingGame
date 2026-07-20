#!/usr/bin/env bash
# Ralph-style loop for Claude Code. Runs an agent against a prompt file until it
# prints the DONE promise, hits max iterations, or you Ctrl+C.
#
# Flags (-m/-n/-s/-p are the same as the class loop):
#   -m MODE    plan | build          (default: build; selects the default prompt file)
#   -n MAX     max iterations        (default: 0 = unlimited)
#   -s STOP    completion promise    (default: <promise>DONE</promise>)
#   -p PROMPT  prompt file           (default: PROMPT_<mode>.md)
#   -d         run with --dangerously-skip-permissions (see WARNING below)
#
# By default the agent is constrained by .claude/settings.json, which allow-lists the
# commands the loop needs and denies destructive ones. -d bypasses ALL of that,
# including the deny list -- only use it in a container, Codespace, or throwaway VM.
set -uo pipefail

MODE="build"; MAX=0; STOP="<promise>DONE</promise>"; PROMPT=""; DANGER=0
while getopts "m:n:s:p:d" opt; do
  case $opt in
    m) MODE="$OPTARG" ;;
    n) MAX="$OPTARG" ;;
    s) STOP="$OPTARG" ;;
    p) PROMPT="$OPTARG" ;;
    d) DANGER=1 ;;
    *) echo "usage: $0 [-m plan|build] [-n MAX] [-s STOP] [-p PROMPT] [-d]" >&2; exit 2 ;;
  esac
done

if [ -z "$PROMPT" ]; then
  [ "$MODE" = "plan" ] && PROMPT="PROMPT_plan.md" || PROMPT="PROMPT_build.md"
fi

# --- preflight: fail loudly now rather than burning iterations on a broken setup ---
if ! command -v claude >/dev/null 2>&1; then
  echo "ERROR: 'claude' is not on PATH. Install the Claude Code CLI first:" >&2
  echo "  npm install -g @anthropic-ai/claude-code" >&2
  echo "On Windows, run this script from Git Bash (not PowerShell or cmd)." >&2
  exit 127
fi
if [ ! -f "$PROMPT" ]; then
  echo "ERROR: prompt file '$PROMPT' not found (cwd: $PWD)." >&2
  exit 1
fi

ARGS=()
if [ "$DANGER" -eq 1 ]; then
  echo "WARNING: --dangerously-skip-permissions is ON; .claude/settings.json deny rules do NOT apply."
  ARGS+=(--dangerously-skip-permissions)
fi

i=0
while :; do
  i=$((i+1))
  echo "=== iteration $i (mode=$MODE, prompt=$PROMPT) ==="
  OUT=$(claude -p "$(cat "$PROMPT")" "${ARGS[@]+"${ARGS[@]}"}" 2>&1)
  echo "$OUT"
  git push origin HEAD 2>/dev/null || true    # agent commits inside the iteration; we push it
  # Only treat the promise as real if it lands at the END of the output. Otherwise the
  # agent merely quoting PROMPT_build.md back at us would stop the loop prematurely.
  if printf '%s\n' "$OUT" | tail -n 5 | grep -qF "$STOP"; then
    echo "Completion promise seen. Stopping."; break
  fi
  if [ "$MAX" -ne 0 ] && [ "$i" -ge "$MAX" ]; then
    echo "Max iterations ($MAX) reached. Stopping."; break
  fi
done
