# Running Fighting Game

A turn-based 1v1 arena. A Flask backend owns every rule; the React client only draws what the
server sends back.

## Prerequisites
- Python 3.12 or newer (developed and tested on 3.13.5)
- Node 20 or newer (developed and tested on 22.19.0)
- Git Bash if you are on Windows — the `script/*` entry points are shell scripts

## Setup
    git clone <your-repo-url> && cd fightingGame
    ./script/setup

Creates `.venv`, installs `backend/requirements.txt` into it, and installs the frontend packages.
Safe to re-run.

## Run
    ./script/server        # backend :5000, frontend :5173
    # open http://localhost:5173

Ctrl+C stops both. The client only ever requests relative `/api/...` paths; Vite proxies them to
Flask, so the browser makes same-origin requests and no CORS configuration exists anywhere in the
backend (specs/base.md §6).

### If port 5000 is already taken

Port 5000 is a popular default, so this is common. Flask exits immediately with *"Address already
in use"*, or on Windows *"An attempt was made to access a socket in a way forbidden by its access
permissions"*. Override it — the Vite proxy target follows the same variable:

    BACKEND_PORT=5055 ./script/server        # FRONTEND_PORT overrides :5173 the same way

Two things make this collision confusing enough to be worth spelling out:

- **The app still loads, and then reports `404`.** Vite happily proxies `/api` to whatever is on
  port 5000. If that is an HTTP service, the browser shows a running UI whose first request fails.
  On the development machine here it was a `registry:2` Docker container inside WSL — WSL2 mirrors
  its listening sockets onto Windows `localhost`, so Windows `netstat` showed *nothing* on 5000
  while connections to it succeeded. A `404` in this app is worth checking against the backend
  before assuming it is an application bug.
- **A busy `:5173` used to be silent.** Vite's default is to shift to the next free port, so you
  could end up reading a stale tab on `:5174`. `./script/server` now passes `--strictPort`, so a
  taken frontend port is a hard failure rather than a quiet redirection.

## Test
    ./script/test          # pytest (backend) + vitest (frontend)
    ./script/lint          # flake8 + eslint

## How to play

You are **Kaito**; the server plays **Vega**. Each turn you pick one of six moves, the server picks
the opponent's, and both resolve in speed order — so a turn can hurt you before your own move lands.

| Move | Ki | What it does |
|---|---|---|
| Strike | 0 | Light attack. Always available, even at 0 ki. |
| Ki Blast | 15 | Medium attack. |
| Surge Beam | 40 | Heavy attack. |
| Charge | 0 | Skip attacking to regain 25 ki (30 while ascended). |
| Guard | 0 | Halve the damage you take this turn and regain 8 ki. |
| Ascend | 40 | Once per match: +25% damage and +5 speed for the rest of the fight. |

Ki only comes back from Charge and Guard, so the whole game is deciding when to spend a turn not
attacking. Moves you cannot afford are greyed out — the button state comes from the server's
`legal_actions`, the client never decides legality itself.

First fighter to 0 HP loses. If both are still standing after 100 turns, the winner is whoever has
the larger share of their own max HP; exactly equal shares are a draw. When the match ends a result
screen appears with a **New match** button, which starts a fresh fight without reloading the page.

## Verified end to end

2026-07-21, on this repo at Phase 4: `./script/server` was started and a full match was played
against the running pair, every request going to a relative `/api/...` path on the frontend origin
(`:5173`) and reaching Flask through the Vite proxy.

- Vite served the app on `:5173`; `POST /api/match` returned 201 through the proxy.
- A seeded Kaito-vs-Vega match ran 13 turns to a terminal status (`opponent_won`), the final state
  reporting `legal_actions: []` — the result-screen state.
- Proxied responses carry **no `Access-Control-*` headers**, confirming the requests are same-origin
  and that no CORS handling is needed (§6, §8).
- A turn submitted on the finished match came back `409 match_over` in the §5.4 envelope; starting a
  new match left the finished one untouched.
- Port 5000 was occupied by an unrelated service on the verification machine, so the backend ran on
  `BACKEND_PORT=5055`; the proxy followed it, which is what that override exists for.

That HTTP-level pass could not cover a human in a real browser, so one followed (2026-07-21). The
app was opened at `http://localhost:5173` and rendered a live match: Kaito 100/100 HP and 30/100 ki
against Vega 130/130 HP, HP and ki bars showing both a filled width and the numbers, all six moves
listed with their ki costs, and an empty battle log at turn 0.

**Surge Beam and Ascend rendered disabled** — both cost 40 ki against a 30 ki pool — while Strike,
Ki Blast, Charge and Guard stayed enabled. That is the server's `legal_actions` driving the UI: the
client applies no rule of its own, it renders what the backend says is allowed (§6, §7).

The equivalent flow end to end (mount → play → result screen → new match, with no reload) is
asserted in `frontend/src/MatchScreen.test.tsx`, and CORS is ruled out at the HTTP level above.

## Extension features
- (Step 2) Choose AI difficulty on the match screen.
- (Step 2) Tournament bracket; results persist across server restarts.

### Verified in a browser (2026-07-21)

With `BACKEND_PORT=5055 ./script/server` running, both Step 2 features were exercised in a real
browser at `http://localhost:5173`:

- The **difficulty selector** (random / heuristic / search) on the match screen, with a match
  played against the `search` AI.
- The **tournament** flow: a bracket created from a roster, advanced match by match to a champion,
  the bracket rendering rounds, winners and byes. A tournament created earlier through the API was
  still listed — persistence across the session, backed by `backend/data/fightinggame.db`.

Note on platforms: `node_modules` are native to the OS that ran `./script/setup`. Install and run
in the **same** environment — on Windows use Git Bash, not WSL; a Windows install cannot be run
under WSL's Linux Node (rollup ships a per-platform binary) and vice versa.

## Step 2 acceptance sweep (plan task 11.1)

Every `specs/extension.md` §E10 criterion is proven by a named, passing test. The two Step 1
contract keys the extension adds — `difficulty` (top level) and `passive_streak` (per fighter) —
are present in `specs/base.md` §5.5 (lines 37, 260, 266) and asserted by
`backend/tests/test_api.py::test_the_payload_has_exactly_the_spec_keys`; no other Step 1 criterion
changed (E4.1).

### AI criteria (16)

| E10 criterion | Proving test (`file::test`) |
|---|---|
| `difficulty` defaults to `random`; Step 1 untouched | `test_api.py::test_a_match_created_without_a_difficulty_reports_random`, `::test_omitting_difficulty_matches_step_one_apart_from_the_two_new_keys` |
| `unknown_difficulty` → 400 | `test_api.py::test_an_unknown_difficulty_string_is_rejected`, `::test_a_non_string_difficulty_is_rejected` |
| Heuristic finishes on a min-damage-lethal attack | `test_ai.py::test_rule_1_finishes_with_the_cheapest_lethal_attack` (+ `::test_rule_1_falls_through_when_the_foe_survives_the_minimum_by_one`) |
| Heuristic guards a lethal max-damage beam | `test_ai.py::test_rule_2_guards_against_a_lethal_incoming_beam` (+ two fall-through tests) |
| No illegal move across 1000 crafted states | `test_ai.py::test_every_difficulty_only_ever_picks_a_legal_move` (1000 states × every policy) |
| Neither policy consumes RNG on a selection | `test_ai.py::test_the_heuristic_consumes_no_randomness`; `test_search.py::test_selecting_at_the_search_difficulty_consumes_no_rng` |
| Same seed + actions ⇒ identical logs at every difficulty | `test_api.py::test_same_seed_and_actions_are_identical_at_every_difficulty` |
| No AI goes passive three turns running, any policy | `test_ai.py::test_the_opponent_never_goes_passive_three_turns_running`, `::test_the_cap_forces_an_attack_at_every_streak_above_it`; `test_arena.py::test_both_sides_obey_the_streak_cap_over_a_full_match` |
| Player not bound by the cap; `legal_actions` byte-identical | `test_ai.py::test_the_player_is_not_bound_by_the_cap`, `::test_the_cap_does_not_touch_legal_actions`, `::test_legal_actions_ignores_the_streak_over_generated_states`, `::test_the_player_may_charge_four_turns_running_at_every_difficulty` |
| Third passive turn: AI attacks even when rule 2 would guard | `test_ai.py::test_the_cap_overrides_the_panic_guard` (+ `::test_the_cap_may_cost_the_ai_the_match`) |
| ≥95% of 200 heuristic-vs-heuristic matches end by KO | `test_ai_strength.py::test_heuristic_mirror_matches_end_by_ko_not_the_cap` (measured 100.0%) |
| `search` beats `random` ≥70% over 200 mirror seeds | `test_ai_strength.py::test_search_beats_random_by_a_wide_margin` (measured 82.0%) |
| `search` ≥45% vs `heuristic` (not a regression) | `test_ai_strength.py::test_search_is_not_a_regression_on_the_heuristic` (measured 48.0%) |
| Measured rate recorded in each strength docstring | docstrings of the three `test_ai_strength.py` tests above |
| A `search` move selected in under 150 ms, worst case | `test_search.py::test_a_worst_case_selection_fits_in_the_time_budget` (+ `::test_both_sides_are_inside_the_budget`, `::test_the_budget_is_met_through_the_difficulty_dispatch_too`) |
| Opponent-model tree is 12 root children / 71 leaves | `test_search.py::test_the_worst_case_tree_is_exactly_twelve_root_children_and_71_leaves` (+ `::test_the_tree_stays_inside_the_cost_bound` for the 108/3888 ceiling) |

### Tournament criteria (18)

| E10 criterion | Proving test (`file::test`) |
|---|---|
| 4-fighter roster: 2 first-round matches, 1 final, no byes | `test_bracket.py::test_four_fighter_bracket_has_two_matches_a_final_and_no_byes`; `test_tournament.py::test_four_fighter_bracket_has_no_byes` |
| 5-fighter roster: size 8, 3 byes on top 3 seeds, pre-resolved | `test_bracket.py::test_five_fighter_bracket_matches_the_spec_worked_table`; `test_tournament.py::test_five_fighter_bracket_matches_the_worked_table`, `::test_byes_carry_a_winner_and_are_never_played` |
| Round-1 seed placement (1v8/4v5/2v7/3v6) for sizes 4/8/16 | `test_bracket.py::test_seed_order_matches_the_spec_examples`, `::test_top_two_seeds_land_in_opposite_halves`, `::test_size_sixteen_round_one_pairs_each_sum_to_size_plus_one` |
| Duplicate ids ⇒ that many distinct entrants / rows | `test_tournament.py::test_duplicate_fighter_ids_are_distinct_entrants`, `::test_duplicate_entrants_get_distinct_display_strings`; `test_tournament_api.py::test_duplicate_ids_yield_distinct_entrants_with_distinct_display` |
| 2-fighter roster: exactly one match, the final | `test_bracket.py::test_two_fighter_bracket_is_a_single_match_which_is_the_final`; `test_tournament.py::test_two_fighter_bracket_is_a_single_final` |
| Sizes 0, 1, 17 rejected with `invalid_roster` | `test_bracket.py::test_bracket_size_rejects_out_of_range_rosters`; `test_tournament.py::test_invalid_roster_size_is_rejected`; `test_tournament_api.py::test_an_invalid_roster_size_is_rejected_and_creates_nothing` |
| Advancing reaches `complete` + `champion` for sizes 2–16 | `test_tournament.py::test_advancing_reaches_a_champion`; `test_tournament_api.py::test_advancing_repeatedly_reaches_a_champion` |
| A forced draw is replayed, not awarded | `test_tournament.py::test_a_drawn_attempt_is_replayed_not_awarded` |
| Ten consecutive draws → `drawn_out` / `stalled` | `test_tournament.py::test_ten_consecutive_draws_stall_the_tournament` |
| A replayed draw reproduces at the same root seed | `test_tournament.py::test_a_replayed_draw_reproduces_at_the_same_root_seed` |
| `advance` on a complete tournament → 409 | `test_tournament.py::test_advancing_a_complete_tournament_raises`; `test_tournament_api.py::test_advance_on_a_complete_tournament_is_409_and_leaves_it_unchanged` |
| Winner of `r,s` lands at `r+1, s//2`, A even / B odd | `test_bracket.py::test_advance_position_maps_slot_to_half_as_a_for_even_b_for_odd`; `test_tournament.py::test_winner_propagates_to_the_right_parent_slot_and_side` |
| Results survive a restart (dispose + reopen same file) | `test_tournament.py::test_results_survive_a_restart`; `test_tournament_api.py::test_a_second_app_over_the_same_file_still_lists_the_tournament` |
| Same roster/difficulty/seed ⇒ identical champions/logs/turns | `test_tournament.py::test_two_tournaments_at_the_same_seed_are_identical` |
| Match order does not change per-position results | `test_tournament.py::test_advance_order_does_not_change_results` |
| `standings` counts wins/losses and marks `eliminated_in` | `test_tournament.py::test_standings_arithmetic_over_a_full_playthrough`, `::test_byes_count_as_neither_a_win_nor_a_loss` |
| UI renders a full bracket, marks byes, names the champion | `frontend/src/components/Bracket.test.tsx` — renders every round, labels a bye, calls out the champion only when `status === "complete"` |
| `./script/test` passes; `./script/lint` clean | Run below |

### Measured metrics (2026-07-21, this repo, CPython 3.13.5 / Windows 11)

- **Search move-selection time (worst case, both sides full ki, all six moves legal):** 2.4 ms
  (budget 150 ms — E3.5/B8). Well inside budget, so **no B9 mitigation is applied**: no
  memoization, no alpha-beta, depth stays at 2.
- **Strength rates (200 seeded mirror matches, Kaito vs Kaito, sides alternated):**
  - `search` vs `random`: **82.0%** (≥70% required).
  - `search` vs `heuristic`: **48.0%** (≥45% required — parity, not a regression).
  - `heuristic` vs `heuristic` ending by KO: **100.0%** (≥95% required).
- **Strength-suite runtime (`test_ai_strength.py`, 3 tests):** ~12.4 s. B9 escalation not needed.

### Clean run (2026-07-21)

- `./script/setup` — completed; venv deps satisfied, DB schema created, frontend packages installed.
- `./script/test` — **625 backend + 71 frontend tests pass, zero failures.**
- `./script/lint` — flake8 and eslint both clean.
