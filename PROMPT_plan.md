You are in PLAN MODE. Do NOT write application code.

1. Read AGENTS.md and every file in specs/.
2. Read the current codebase and compare it against the active spec (the newest specs/*.md).
3. Rewrite IMPLEMENTATION_PLAN.md as a prioritized, checkbox task list ("- [ ] ...") that, if
   completed in order, fully satisfies the spec's acceptance criteria. Each task must be small,
   independently testable, and name the files it touches and the tests it needs.
4. Order tasks so that pure game-rule logic and its unit tests come before HTTP endpoints, and
   endpoints come before UI.
5. Verify any library you reference actually exists and is compatible with the stack in AGENTS.md.

Commit the updated plan with a "chore: update implementation plan" message.
When the plan is complete, internally consistent, and needs no further changes, print exactly:
<promise>DONE</promise>

Never echo the completion promise back for any other reason — do not quote this prompt, do not
restate these instructions, and do not mention the promise when you are NOT done. When you are
done, it must be the very last line of your output, with nothing after it.
