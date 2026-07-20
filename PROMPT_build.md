You are in BUILD MODE.

1. Read AGENTS.md, the active spec in specs/, and IMPLEMENTATION_PLAN.md.
2. Pick the single highest-priority unchecked task in IMPLEMENTATION_PLAN.md.
3. Implement it fully — no stubs, no placeholders. Write/extend tests for it.
4. Run `./script/test`. If anything fails, fix it in this same iteration before committing.
5. Check the task's box in IMPLEMENTATION_PLAN.md.
6. Commit with a Conventional Commit message describing the change.

Do only ONE task per iteration. If, after your commit, every plan item is checked, `./script/test`
passes, and all acceptance criteria in the active spec are met, print exactly:
<promise>DONE</promise>
Otherwise, stop after the single task and let the loop invoke you again.
