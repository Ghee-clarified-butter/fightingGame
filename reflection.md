# Reflection

> RAW NOTES — not prose. Pick what's useful, write the paragraph yourself, delete the rest.
> Uncommitted on purpose.

## The strongest through-line (if you want one thesis)

- The loop's autonomy came from **specification quality and a hard definition of done**, not from
  the model. Where the spec was precise, the agent converged alone. Where it was vague or
  self-contradictory, the agent either stopped and said so, or picked a plausible answer that then
  had to be pinned down by hand.
- Cost of a defect scaled with how late it was caught: a paragraph (Stage 2) → a plan decision
  (Stage 3) → nothing at all in code, because it never got written wrong.

## Defects caught, and where

- **Stage 2 (Review) found 9 defects in a spec I had just written.** The three that mattered:
  - The opponent's random move was drawn *before* the player's action was validated, so a rejected
    (400) turn still advanced the match RNG and silently changed all future damage rolls. The
    obvious test — compare state before and after — passes anyway, because RNG position isn't in
    the state payload. Fixed the ordering *and* specified a test that can actually catch it.
  - Nothing addressed cross-origin: client on :5173, API on :5000. Every endpoint could have been
    correct, both suites green, and the app still wouldn't work in a browser.
  - Determinism was promised via a `seed` parameter, but the RNG *consumption order* was never
    fixed — so the criterion could only ever verify an implementation against itself.
- **Stage 3 (Plan) found a contradiction between two sections of the already-reviewed spec.**
  §4.8 fixed the RNG draw order as (1) speed-tie flip, (2) opponent's move; but §6 pinned
  `resolve_turn(state, player_action, opponent_action, rng)` — the opponent's action is already an
  argument, so any natural implementation consumes draw #2 before draw #1. Reviewing a spec against
  itself did not surface this; *attempting to plan an implementation* did.
- Point worth making: no commit "fixes" the RNG bug, because it never reached the code. It was
  corrected while it was still one paragraph of prose.

## Where the agent behaved better than expected

- **It refused to fake progress.** Three consecutive iterations were blocked by a permissions
  problem. Each time it wrote the files, failed to run `./script/test`, and explicitly declined to
  tick the checkbox or commit — because it could not honestly claim the suite was green. Zero
  commits, three clear reports. The safety rail that mattered was the definition of done in
  `AGENTS.md`, not the permission system.
- **It disclosed the limits of its own verification.** Task 4.1 required a browser pass. It did a
  real HTTP-level check through the live proxy, then wrote into `running.md` that this "did not
  cover a human clicking through a real browser and reading its console" — rather than ticking the
  box silently.
- **It caught things the plan didn't ask for**: `isinstance(True, int)` is `True` in Python, so
  `seed: true` needs explicit rejection; a `busy` state flag doesn't stop a double-click (two clicks
  in one tick read the same stale value) so it used a `useRef`; a KO'd fighter must not pay ki for
  the attack it never landed.
- **It wrote tests that could actually fail.** The draw-order test uses a *mirror* match, because
  Kaito (14 spd) vs Vega (9) never ties, so the coin flip would never be drawn and the two orderings
  would be indistinguishable — a naive version of that test passes vacuously.

## Where it needed a human

- **Environment, not reasoning.** Every real stall was environmental and invisible from inside the
  loop:
  - A project `.claude/settings.json` allowlist is ignored in non-interactive `claude -p` until the
    workspace is trusted — and the trust dialog never appears in that mode.
  - Port 5000 was held by a `registry:2` Docker container inside WSL. WSL2 mirrors its listening
    socket onto Windows `localhost`, so Windows `netstat` showed nothing while connections
    succeeded. Flask couldn't bind; Vite proxied `/api` to the registry; the registry answered 404;
    the React app correctly reported "Request failed with status 404". Every layer behaved
    correctly and the result still looked like an application bug.
  - Vite silently falls back to :5174 when :5173 is taken, so you can end up reading a stale tab
    proxying to a different backend than the one you just started. Fixed with `--strictPort`.
- Judgement calls stayed human: whether to commit, whether to push, how far to let the loop run.

## Process observations

- **Checkpointed batches (`-n 3`, `-n 10`, `-n 6`) beat running uncapped.** Cheap inspection points,
  and a bounded blast radius when something went wrong.
- **Verifying by re-running `./script/test` myself**, rather than trusting the agent's summary,
  caught nothing — but it's the only reason the green result means anything.
- One task per iteration + tests-green-before-commit produced a history where every commit is a
  working state. 42 commits, no broken intermediate.
- The permission fix that mattered was *scoping*: trusting one project directory kept the
  allow/deny policy in force, where `--dangerously-skip-permissions` would have discarded the deny
  list entirely.

## Numbers (if useful)

- Step 1: 4 stages, 30 plan tasks, 42 commits, 226 backend + 34 frontend tests.
- `specs/base.md`: 341 lines after Stage 1 → 415 after review.
- Build loop: ~27 productive iterations; 3 wasted on the trust problem; 1 to declare done.

## Your notebook

- Fold in whatever you wrote by hand — none of it is captured anywhere in this repo.
