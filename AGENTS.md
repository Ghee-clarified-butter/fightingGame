# AGENTS.md — Fighting Game operational reference

## Commands (always use these; keep them working)
- `./script/setup`  — install backend + frontend deps, init DB if present
- `./script/server` — run Flask on :5000 and Vite on :5173
- `./script/test`   — run pytest (backend) and vitest (frontend); MUST pass before you commit
- `./script/lint`   — flake8 + eslint

## Conventions
- Turn resolution is server-authoritative. The frontend never computes damage.
- Pure functions for game rules (backend/game/rules.py) so they are unit-testable without HTTP.
- No stubs, no placeholders, no TODOs left in committed code.
- Conventional Commits ("feat:", "fix:", "test:", "chore:").

## Definition of done
Only print `<promise>DONE</promise>` when: every unchecked item in IMPLEMENTATION_PLAN.md is done,
`./script/test` passes with zero failures, and every acceptance criterion in the relevant spec
under specs/ is met. Otherwise pick the next task and keep going.
