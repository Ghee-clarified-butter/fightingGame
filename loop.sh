#!/usr/bin/env bash
# Ralph-style loop for Claude Code. Runs an agent against a prompt file until it
# prints the DONE promise, hits max iterations, or you Ctrl+C.
set -uo pipefail

MODE="build"; MAX=0; STOP="<promise>DONE</promise>"; PROMPT=""
while getopts "m:n:s:p:" opt; do
  case $opt in
    m) MODE="$OPTARG" ;;
    n) MAX="$OPTARG" ;;
    s) STOP="$OPTARG" ;;
    p) PROMPT="$OPTARG" ;;
  esac
done

if [ -z "$PROMPT" ]; then
  [ "$MODE" = "plan" ] && PROMPT="PROMPT_plan.md" || PROMPT="PROMPT_build.md"
fi

i=0
while :; do
  i=$((i+1))
  echo "=== iteration $i (mode=$MODE, prompt=$PROMPT) ==="
  OUT=$(claude -p "$(cat "$PROMPT")" --dangerously-skip-permissions 2>&1)
  echo "$OUT"
  git push origin HEAD 2>/dev/null || true    # agent commits inside the iteration; we push it
  if echo "$OUT" | grep -qF "$STOP"; then
    echo "Completion promise seen. Stopping."; break
  fi
  if [ "$MAX" -ne 0 ] && [ "$i" -ge "$MAX" ]; then
    echo "Max iterations ($MAX) reached. Stopping."; break
  fi
done
