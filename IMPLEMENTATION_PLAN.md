# Implementation Plan — Step 2, AI Opponent + Persistent Tournament

Derived from `specs/extension.md` (active spec), which builds on `specs/base.md` (still
authoritative for the fighter model, the six moves, the damage formula and the base REST contract).
Rewritten by the plan loop; consumed one task per iteration by `PROMPT_build.md`.

**Rules for the builder:**
- Do exactly one unchecked task per iteration, top to bottom. Do not skip ahead.
- `./script/test` must pass at the end of **every** task. A task that leaves the suite red is not
  done — which is why the two contract-breaking tasks (1.1, 1.2) update the spec, the code and the
  assertion together rather than in separate steps.
- `./script/lint` must be clean at the end of every task (`max-line-length = 100`).
- No stubs, no placeholders, no TODOs (AGENTS.md).
- Section references: `§n` → `specs/base.md`, `En` → `specs/extension.md`.

---

## Current state (verified against the tree, not assumed)

Step 1 is complete and green: `backend/game/{fighters,moves,rules}.py`, `backend/app.py` (in-memory
match store, three endpoints), `backend/tests/{test_rules,test_api,test_fuzz,test_moves,
test_fighters,test_imports}.py`, and a React 18 + TS + Vite + Tailwind frontend with Vitest specs.
Nothing of Part A or Part B exists yet: no `difficulty`, no `passive_streak`, no AI module, no
SQLAlchemy dependency, no tournament code, no bracket UI.

Relevant existing shapes the plan has to move:
- `rules.play_turn(state, player_action, rng)` calls `rules.choose_opponent_action` internally
  (`backend/game/rules.py:130`), and is referenced 26 times across `test_rules.py` (15) and `test_fuzz.py` (11).
- `rules._apply_attack` draws its own spread via `rng.uniform` (`backend/game/rules.py:197`).
- The §5.5 exact-shape assertion is `STATE_KEYS` / `FIGHTER_KEYS` at `backend/tests/test_api.py:13`,
  asserted by `test_the_payload_has_exactly_the_spec_keys` (`backend/tests/test_api.py:226`).
- `.gitignore` already ignores `*.db` (line 21), so E6 needs no gitignore change.

---

## A. Decisions this plan pins down

The spec leaves these under-determined, or states two things that cannot both be literally true.
They are settled here so the build loop does not bake in an arbitrary choice and then test it
against itself. (Step 1's decisions A1–A8 stand unchanged; these continue as B1–B12.)

**B1 — All policy moves into `backend/game/ai.py`; `rules.py` keeps no policy.**
E2.1 binds the streak cap to *every* AI policy including `random`, so there must be exactly one
code path that picks an AI move. `choose_opponent_action` and `play_turn` are **moved** out of
`rules.py` into `ai.py` as:

```
ai.choose_action(state, side, difficulty, rng) -> str          # dispatches on difficulty
ai.play_turn(state, player_action, rng) -> (new_state, entries)  # reads state["difficulty"]
```

`rules.py` keeps `legal_actions`, `compute_damage`, `effective_spd`, `roll_turn_order`,
`resolve_turn`, `check_status`, `new_match` — no imports of `ai`, so there is no cycle. Leaving a
second, uncapped random chooser behind in `rules.py` was rejected: the fuzz suite would then be
exercising a path the server does not use.

**B2 — The RNG draw order is preserved exactly.**
`ai.play_turn` calls `roll_turn_order` (draw #1) → `choose_action` (draw #2, *only* when
`difficulty == "random"`) → `resolve_turn` (draws #3/#4). The random policy makes exactly one
`rng.choice` call in the same position as today, whether or not the cap filtered its candidate list.
So E3.4's revised order holds and §4.8 is unviolated.

**B3 — The cap changes what `random` picks in a small number of seeded matches, and that is
correct.** E1 says `random` is "the Step 1 behaviour"; E2.1 says the cap binds it. E2.1 wins (E10
asserts "under any policy"). The candidate *list* shrinks on a third consecutive passive turn, so a
fixed seed can now yield a different match than it did in Step 1. Same-seed-vs-same-seed determinism
tests are self-comparisons and stay green; any Step 1 test that hardcodes a damage number at a seed
may need its expected value re-derived. That is a permitted consequence of E2.1 — re-derive the
number, never weaken the assertion. If a Step 1 test breaks for any *other* reason it is a genuine
regression and is fixed in the code (E4.1).

**B4 — `passive_streak` is bookkeeping in `resolve_turn`, tracked for both sides.**
`resolve_turn` increments the streak of whichever side chose `charge`/`guard`/`ascend` and resets it
to 0 for whichever chose an attack — including an attack that was skipped because its owner was
already KO'd (the fighter is dead; the value is inert). Tracking it for the human player too is what
E4 means by "each fighter gains `passive_streak`"; it never constrains the player, because only
`ai.choose_action` reads it and `rules.legal_actions` is untouched (E2.1).

**B5 — `difficulty` lives in the rules state dict**, so `serialize` reads it with no extra plumbing:
`rules.new_match(player_id, opponent_id, difficulty="random")` puts `"difficulty"` at the top level
of the state. Validation of the value stays in the HTTP layer (§6: no rules in the routes, no
routing in the rules) via a shared `DIFFICULTIES` tuple in `ai.py`.

**B6 — `resolve_turn` gains a keyword-only `spread`.**
`resolve_turn(state, player_action, opponent_action, rng, *, order=None, spread=None)`. When
`spread` is not `None` that fixed value is used for every attack this turn and **no** RNG draw
happens (E3.4: "the search must never be handed the live match RNG"). The search also needs an order
without a coin flip, so `rules.deterministic_order(state)` is added: identical to `roll_turn_order`
but breaks a tie as `("player", "opponent")` with no draw. The search passes `rng=None` together
with an explicit `spread` and `order`; `resolve_turn` must therefore never touch `rng` on that path.

**B7 — Search-node budget arithmetic, and what the leaf test asserts.**
E3.5's table (108 / 3,888) ignores E3.2's rule that a turn where neither side attacks yields one
child instead of three. E3.2 is normative; the table is an upper bound. With all six moves legal for
both sides, 3×3 = 9 of the 36 root action pairs are attack-free, so:

```
root ply children = 27*3 + 9*1 = 90        (<= 108)
depth-2 leaves    = 90 * 36    = 3240      (<= 3888)   -- upper bound, see below
resolve_turn calls = 90 + 3240 = 3330
```

**Corrected while building 3.3:** `90 * 36` assumes six legal moves for both sides at the second
ply, but Ascend is *spent* at the root — a child in which one side ascended offers that side five
moves, not six. Summing over the root pairs gives `2412 + 330 + 330 + 25 = 3097` leaves, 143 fewer.
The root figure of 90 is exact and unaffected. So the leaf-count test asserts exactly **90 and
3097** on a full-hp/full-ki position (no line can terminate from full hp at depth 2, so no
short-circuit perturbs the count) **and** asserts the E3.5 ceilings of 108/3888, which is the
"three-way at root, one-way deeper" criterion in E10. 3240 stands as an upper bound, as does 3888.

**B8 — The budget is 150 ms and the sample size is 200.**
E3.5/E10 say 150 ms; E11 says 100 ms. E3.5 is the derivation and E10 is the acceptance criterion, so
150 ms wins. E10 says 200 seeds for all three strength criteria; E11 says 100 for two of them. E10
wins. Where E11 and E10 disagree, E10 is the contract.

**B9 — Escalation if the strength suites are too slow.** 200 seeded matches × ~15 AI moves × a
sub-150 ms search is minutes, not seconds. Task 4.2 measures it. If the search-side strength tests
exceed a **180 s** combined budget, apply these in order and record which was used:
1. Per-move-selection memoization (explicitly permitted by E3.5; cache is discarded after each
   selection so it can never leak across turns).
2. Alpha–beta pruning over the deterministic (mean-only) deeper plies — it changes the work done,
   never the value returned, so every value-based test stays valid.
3. Drop the search depth to 1, which E3.5 names as the sanctioned fallback ("the budget wins, not
   the depth").
Never reduce the seed count: E10 fixes it at 200, and a 55% threshold measured over fewer matches is
a different claim.

**B10 — A tournament match that ends in `draw` is replayed, never awarded** (E7.4).
§4.6 permits `draw` at the turn cap; a bracket slot needs a winner, but awarding one to a fighter
that did not win is a lie in the record. So the drawn attempt is persisted with `result: "draw"`
and no winner, and the same pairing replays at `match_seed(attempt + 1)` until decisive.
`winner_seed` is set only from the decisive attempt.

- `TournamentMatch.attempts_json` holds `[{attempt, result, turns, log}]`, normally one entry.
- **Hard cap of 10 attempts**: then `status = "drawn_out"` and the tournament is `"stalled"`.
  An unbounded retry loop inside a request handler is not acceptable however unlikely the path is.
- Still fully deterministic, since `attempt` feeds the seed — a replayed tournament reproduces the
  same draws and the same eventual winner.
- The tests must **force** a draw with a crafted state rather than hoping to observe one; at
  ≥95% KO rate a natural draw will essentially never appear in a test run.

**B11 — Standings sort is total.** E8.1 says "wins descending then name"; with duplicate fighter ids
that is not a total order, so the tie-break continues to **seed number ascending**. Display name is
`"Kaito (2)"` — the fighter's name plus its seed number, per E7.2 — and is built server-side so the
client does no sentence-building, consistent with §5.5's `text`.

**B12 — Layering for Part B.** Pure bracket arithmetic (`backend/game/bracket.py`) and the AI-vs-AI
match runner (`backend/game/arena.py`) know nothing about SQLAlchemy and are unit-tested without a
database. `backend/models.py` is declarative only. `backend/tournament.py` is the service layer that
joins them (create / advance / serialize). `backend/app.py` stays validation → service → serialize.
Single matches stay in the in-memory store, untouched (E6).

**B13 — Library check (E5 requirement of this plan).** The venv is CPython 3.13.5. The only new
runtime dependency is **SQLAlchemy 2.0.x** (`SQLAlchemy>=2.0.36,<2.1`) — 2.0.36 is the first release
with cp313 wheels, and the 2.0 ORM (`DeclarativeBase`, `Mapped`, `mapped_column`) is the API this
plan uses. `sqlite3` is stdlib, so there is no driver to add. **Flask-SQLAlchemy is deliberately not
used**: it binds sessions to an app context, and E10 requires a persistence test that disposes the
session and rebuilds it against the same file outside any request. No new frontend dependency: E9
permits a state toggle instead of a router, so React 18 + Vite + Tailwind + Vitest as already
installed is the whole stack.

---

## B. Task list

### 1. State and rules groundwork (contract changes first, so the suite is green after each)

- [x] **1.1 — Add `passive_streak` to the fighter and maintain it in `resolve_turn`.**
  Files: `backend/game/fighters.py` (`new_fighter` → `"passive_streak": 0`), `backend/game/rules.py`
  (`resolve_turn` per B4), `specs/base.md` §5.5 (add the key to the fighter example — E4.1 requires
  the two specs to agree), `backend/tests/test_api.py` (`FIGHTER_KEYS`),
  `frontend/src/types.ts` (`Fighter.passive_streak: number`).
  Tests: `backend/tests/test_fighters.py` — a fresh fighter has `passive_streak == 0`.
  `backend/tests/test_rules.py` — the streak increments on `charge`, `guard` and `ascend`; resets to
  0 on each of the three attacks; is tracked independently per side; survives a turn in which the
  other side attacked. `test_api.py::test_the_payload_has_exactly_the_spec_keys` still passes with
  the widened `FIGHTER_KEYS`.

- [x] **1.2 — Add `difficulty` to the match state and the §5.5 payload.**
  Files: `backend/game/rules.py` (`new_match(player_id, opponent_id, difficulty="random")` per B5),
  `backend/app.py` (`serialize` emits `"difficulty"`), `specs/base.md` §5.5 (add the top-level key),
  `backend/tests/test_api.py` (`STATE_KEYS`), `frontend/src/types.ts` (`MatchState.difficulty`).
  Tests: `test_rules.py` — a new match defaults to `"random"` and carries a passed-in value.
  `test_api.py` — the exact-key assertion passes with the new key set, and a match created without a
  `difficulty` field reports `"random"`. This and 1.1 are the **only** Step 1 tests permitted to
  change (E4.1); note in the commit that the failure was the contract revision, not a regression.

- [x] **1.3 — Let `resolve_turn` take a fixed spread, and add `deterministic_order`.**
  Files: `backend/game/rules.py` (B6: keyword-only `spread`; `_apply_attack` takes the spread rather
  than drawing when one is supplied; new `deterministic_order(state)`).
  Tests: `test_rules.py` — with `spread=1.0` the damage equals the formula computed by hand for both
  attackers; passing a spread leaves `rng.getstate()` byte-identical (and works with `rng=None`);
  the default path still draws exactly one spread per resolved attack and none for a non-attack
  turn; `deterministic_order` returns `("player","opponent")` on a tie and consumes no RNG; the
  existing draw-order tests are unchanged.

### 2. AI policies (pure logic, no HTTP)

- [x] **2.1 — Create `backend/game/ai.py`: move `play_turn`/`choose_opponent_action`, add the
  difficulty dispatch and the streak cap.**
  Files: new `backend/game/ai.py` (`DIFFICULTIES = ("random", "heuristic", "search")`,
  `UnknownDifficultyError`, `attacking_candidates(fighter, actions)` implementing E2.1, the `random`
  policy, `choose_action`, `play_turn`), `backend/game/rules.py` (remove the two moved functions),
  `backend/app.py` (call `ai.play_turn`), `backend/tests/test_rules.py` and
  `backend/tests/test_fuzz.py` (repoint all 26 references to `game.ai`).
  Tests: new `backend/tests/test_ai.py` — the cap forces an attack on the third consecutive passive
  turn under `random`; two consecutive passive turns are still allowed; a reset mid-streak restarts
  the count; `choose_action` raises `UnknownDifficultyError` for an unknown value; the random policy
  consumes exactly one `rng.choice` draw whether or not the cap filtered the list.
  Also confirm per B3 which (if any) Step 1 seeded expectations moved, and re-derive them.

- [x] **2.2 — Implement the heuristic policy (E2 rules 1–7).**
  Files: `backend/game/ai.py`.
  Tests: `backend/tests/test_ai.py` — one test per rule on a crafted state where exactly that rule
  fires, each paired with a state where its guard is *just* unmet so the next rule fires instead:
  finish uses minimum damage at spread 0.90 and picks the **cheapest** lethal attack; a foe surviving
  minimum damage by 1 hp falls through; panic guard triggers on the foe's maximum-damage
  (spread 1.10, unguarded) Surge Beam and not when the foe cannot afford 40 ki; Ascend needs
  `hp/hp_max >= 0.50` **and** `ki >= 65` (both boundaries tested); beam needs `ki >= 80`; poke;
  recover at `ki < 15`; Strike as the fallback. Every rule skips itself when the move is illegal.

- [x] **2.3 — Cap precedence and legality fuzz.**
  Files: `backend/game/ai.py` if the tests find a gap; otherwise tests only.
  Tests: `test_ai.py` — on a third consecutive passive turn the heuristic **attacks even though rule
  2 would have it guard**, and may consequently die (E2.1's stated precedence, an E10 criterion);
  1000 generated states × every difficulty yield only moves in `rules.legal_actions`; a heuristic
  selection leaves `rng.getstate()` unchanged; `rules.legal_actions` output is byte-identical for a
  fighter with `passive_streak` 0 and 5, and a player may `charge` four turns running through
  `ai.play_turn` (the player-not-bound criterion).

### 3. Expectimax search

- [x] **3.1 — Evaluation function.**
  Files: new `backend/game/search.py` (`evaluate(state, side) -> float`, E3.3 verbatim).
  Tests: new `backend/tests/test_search.py` — terminal short-circuits to ±1000 and dominate any
  material term; sign and magnitude on hand-built winning / losing / exactly-equal positions;
  `hp_term` uses fractions so Kaito at 50/100 and Vega at 65/130 evaluate equal on hp; the ki and
  tempo weights match the spec's constants.

- [x] **3.2 — Chance node.**
  Files: `backend/game/search.py` (`SPREAD_SAMPLES = (0.9333, 1.0, 1.0667)`, a chance expansion that
  yields three equally weighted children when either side attacks and exactly one when neither does,
  and takes the mean-only sample below the root ply).
  Tests: `test_search.py` — three children for an attacking pair, one for `charge`/`guard`; the
  weights are 1/3 each and sum to 1; the samples are the interval midpoints, not `0.90/1.00/1.10`;
  no RNG is consumed.

- [x] **3.3 — Depth-limited expectimax with MAX/MIN/CHANCE and canonical tie-breaking.**
  Files: `backend/game/search.py` (`choose(state, side, depth=2)`), `backend/game/ai.py` (wire the
  `search` difficulty, applying the E2.1 cap **at the root only**, and using the heuristic for leaf
  ordering).
  Tests: `test_search.py` — a one-move-from-lethal position is solved at depth 1; equal-valued
  actions break to the earliest in `["strike","ki_blast","surge_beam","charge","guard","ascend"]`;
  `rng.getstate()` is unchanged across a selection and the live match RNG is never passed in; the
  root cap forces an attack after two passive turns; the instrumented counts are exactly 90 root
  children and 3097 leaves on a full-hp/full-ki position, and within E3.5's 108/3888 ceilings (B7).

- [ ] **3.4 — Time budget.**
  Files: `backend/game/search.py` only if it misses.
  Tests: `test_search.py` — a selection on the worst-case position (both sides full ki, all six moves
  legal) completes in **under 150 ms** (B8), timed with `time.perf_counter` over a warm call. If
  depth 2 cannot meet it, apply B9 and record in the test docstring which mitigation was used and the
  measured time.

### 4. AI-vs-AI harness and strength

- [ ] **4.1 — Headless match runner.**
  Files: new `backend/game/arena.py` — `run_ai_match(a_id, b_id, difficulty, seed) -> dict` with
  `{"winner": "a"|"b", "winner_side", "turns", "status", "log"}`, driving both sides through
  `ai.choose_action` and `rules.resolve_turn` with a single `random.Random(seed)`; side A is the
  rules state's `player`, side B its `opponent`. `arena` reports `status: "draw"` with
  `winner: None` and never resolves it — replaying is the tournament layer's job (B10 / E7.4), and
  a function that invents a winner would make the drawn attempt unrecordable.
  Tests: new `backend/tests/test_arena.py` — the same seed and difficulty reproduces log, turns and
  winner exactly; both sides obey the streak cap over a full match; `turns <= 100`; a mirror matchup
  runs to a conclusion; no illegal action appears in any log.

- [ ] **4.2 — Strength criteria.**
  Files: new `backend/tests/test_ai_strength.py`.
  Tests: `search` beats `random` in ≥70% of 200 fixed seeds; `search` beats `heuristic` in ≥55% of
  200 fixed seeds; ≥95% of 200 heuristic-vs-heuristic matches end by KO rather than the cap. Record
  the measured rates in each docstring (E10). Time the file; if the two search suites exceed 180 s
  combined, apply B9 in order and note the mitigation used.

### 5. Part A endpoints

- [ ] **5.1 — `difficulty` on `POST /api/match`.**
  Files: `backend/app.py` (`_parse_difficulty` → `unknown_difficulty` 400, absent ⇒ `"random"`).
  Tests: `backend/tests/test_api.py` — each of the three values is accepted and echoed in the
  payload; an unknown value returns 400 `unknown_difficulty` with the §5.4 envelope and creates **no**
  match (the store stays empty); a non-string value is rejected the same way; omitting the field
  still yields `"random"` and a byte-identical payload to Step 1's apart from the two new keys.

- [ ] **5.2 — Turns honour the match's difficulty.**
  Files: `backend/app.py` (pass `state["difficulty"]` through `ai.play_turn`).
  Tests: `test_api.py` — same seed + same player actions ⇒ identical logs and final states at *every*
  difficulty (E10); `legal_actions` is unaffected by difficulty; a rejected turn still leaves the RNG
  unadvanced at every difficulty (the reject-then-play comparison of §5.4); the AI's logged actions
  over a played-out heuristic match never break the streak cap.

### 6. Bracket arithmetic (pure, no database)

- [ ] **6.1 — `backend/game/bracket.py`.**
  Files: new `backend/game/bracket.py` — `bracket_size(n)`, `seed_order(size)` (E7.1's recursive
  interleave), `first_round_pairs(roster)` returning `(slot, seed_a, seed_b|None)` with byes on the
  top `size - n` seeds, `advance_position(round, slot) -> (round+1, slot//2, "a"|"b")`,
  `match_seed(root, round, slot)`, `round_count(size)`, `InvalidRosterError`.
  Tests: new `backend/tests/test_bracket.py` — `seed_order` is `[1,2]`, `[1,4,2,3]`,
  `[1,8,4,5,2,7,3,6]`, and for 16 every round-1 pair sums to `size+1`; sizes and bye counts for
  `n` in 2..16; `n = 4` gives 2 first-round matches, 1 final, 0 byes; `n = 5` gives size 8, 3 byes on
  seeds 1–3, matching E7.1's worked table exactly; seeds 1 and 2 land in opposite halves for sizes 4,
  8 and 16; `n = 2` gives exactly one match which is the final; `n` of 0, 1 and 17 raise
  `InvalidRosterError`; `advance_position` maps `s` to `s//2` as A for even and B for odd;
  `match_seed` matches the formula and is distinct across positions.

### 7. Persistence layer

- [ ] **7.1 — Dependency, engine and schema bootstrap.**
  Files: `backend/requirements.txt` (`SQLAlchemy>=2.0.36,<2.1`, B13), new `backend/db.py` (engine for
  `backend/data/fightinggame.db`, `sessionmaker`, `init_db(engine)`, and a `DATABASE_URL` override so
  tests can point at a temp file or `sqlite+pysqlite:///:memory:`), `script/setup` (create
  `backend/data/` and run `init_db`), `backend/app.py` (`init_db` on startup if the schema is absent,
  E6). Run `./script/setup` to install the dependency.
  Tests: new `backend/tests/test_db.py` — `init_db` is idempotent; a fresh temp path creates the file
  and every table; the override is honoured so no test ever writes the real database.

- [ ] **7.2 — Models.**
  Files: new `backend/models.py` — `Fighter(id)` only (E6.1: stats are never copied out of
  `fighters.py`), `Tournament`, `TournamentMatch` including `fighter_a_seed` / `fighter_b_seed` /
  `winner_seed` (E7.2) and the `(tournament_id, round, slot)` unique constraint; `seed_fighters`
  populating the registry from `game.fighters.FIGHTERS`.
  Tests: `backend/tests/test_db.py` — every E6.1 column exists with the right nullability; the unique
  constraint raises on a duplicate `(tournament_id, round, slot)`; `seed_fighters` is idempotent and
  inserts exactly the ids in `FIGHTERS`; no stat column exists on `Fighter` (asserted by name, so a
  later "helpful" addition fails).

### 8. Tournament service

- [ ] **8.1 — Creation.**
  Files: new `backend/tournament.py` — `create_tournament(session, name, roster, difficulty, seed)`
  building the **entire** bracket (later rounds `pending`), pre-resolving byes with `status="bye"`
  and a `winner_seed`, raising `InvalidRosterError` / `UnknownFighterError` /
  `UnknownDifficultyError` / invalid-seed.
  Tests: new `backend/tests/test_tournament.py` — for `n` in 2..16 the row count, round count, bye
  count and bye placement are right; byes carry a winner and are never played; duplicate ids give
  that many distinct entrants (a `["kaito","kaito"]` bracket has two rows keyed by seed, not one);
  every rejection leaves zero rows behind.

- [ ] **8.2 — Advance and propagation.**
  Files: `backend/tournament.py` — `advance(session, tournament_id)` picking the next `ready` match by
  lowest round then lowest slot, running it through `arena.run_ai_match` at the derived
  `match_seed`, storing `winner_*`, `turns` and `attempts_json`, replaying drawn attempts per E7.4, promoting the winner into
  `round+1, slot//2` as A/B by parity, flipping `pending` → `ready` when both sides are known, and
  setting `status="complete"` with `champion_id` when the final resolves; `TournamentComplete` and
  `NoReadyMatch` errors.
  Tests: `test_tournament.py` — advancing repeatedly reaches `complete` with a champion for roster
  sizes 2–16; the winner of `r,s` appears at `r+1, s//2` as A for even and B for odd; advancing a
  complete tournament raises `TournamentComplete`; two tournaments at the same roster/difficulty/seed
  produce identical champions, logs and turn counts; advancing the same bracket in two different
  orders produces identical per-position results (E7.3); **a forced draw is replayed, not awarded**
  — the drawn attempt is stored with `result: "draw"` and no winner, `winner_seed` comes from the
  decisive attempt, ten consecutive draws leave the match `drawn_out` and the tournament `stalled`,
  and a tournament containing a replayed draw still reproduces at the same root seed (B10 / E7.4);
  **persistence** — create, advance, `session.close()` + `engine.dispose()`, rebuild against
  the same file, and the bracket and standings compare equal.

- [ ] **8.3 — Bracket serialization and standings.**
  Files: `backend/tournament.py` — `serialize_bracket(tournament)` producing E8.1 exactly (rounds,
  per-match `fighter_a`/`fighter_b`/`winner` objects with `id`, `name` and `display` per B11, `turns`,
  `status`, `champion`), plus derived `standings` (never stored) with `wins`, `losses` and
  `eliminated_in`, sorted wins desc → name → seed.
  Tests: `test_tournament.py` — the payload's key set matches E8.1 exactly; standings arithmetic over
  a full playthrough including `eliminated_in` for every non-champion and `null` for the champion;
  byes count as neither a win nor a loss; two same-fighter entrants get two rows with distinct
  `display` strings (`"Kaito (1)"`, `"Kaito (2)"`) and never merge.

### 9. Tournament endpoints

- [ ] **9.1 — `POST /api/tournament` and `GET /api/tournament/<id>`.**
  Files: `backend/app.py` (validation → `tournament.py` → serialize; a request-scoped session).
  Tests: new `backend/tests/test_tournament_api.py` — 201 with the E8.1 bracket; `GET` returns the
  same object and is read-only; `invalid_roster` (sizes 0, 1, 17), `unknown_fighter`,
  `unknown_difficulty`, `invalid_seed` each 400 with the §5.4 envelope, and each asserting **no**
  tournament row was created; `tournament_not_found` → 404.

- [ ] **9.2 — `POST /api/tournament/<id>/advance` and `GET /api/tournaments`.**
  Files: `backend/app.py`.
  Tests: `test_tournament_api.py` — `advance` returns 200 and the updated bracket, and repeated calls
  reach a champion; `tournament_complete` → 409 and the bracket is unchanged afterwards;
  `no_ready_match` → 409; `tournament_not_found` → 404; the list endpoint returns
  `id, name, status, champion, created_at` newest first, and a second app instance built over the
  same database file still lists the tournament (the restart criterion, at the HTTP layer).

### 10. Frontend

- [ ] **10.1 — Types and API module.**
  Files: `frontend/src/types.ts` (`Difficulty`, `Bracket`, `BracketRound`, `BracketMatch`,
  `StandingsRow`, `TournamentSummary`, the new error codes), `frontend/src/api.ts`
  (`createMatch(..., difficulty)`, `createTournament`, `getTournament`, `advanceTournament`,
  `listTournaments`).
  Tests: `frontend/src/api.test.ts` — each new call hits the right relative `/api/...` path with the
  right method and body, parses the payload, and throws `ApiError` carrying the server's code.

- [ ] **10.2 — Difficulty selector (E5).**
  Files: new `frontend/src/components/DifficultySelect.tsx`, `frontend/src/MatchScreen.tsx`.
  Tests: new `DifficultySelect.test.tsx` and `MatchScreen.test.tsx` — the selector defaults to
  `random`, offers all three values, is **disabled** once a match is in progress, the current
  difficulty is displayed during the match, and starting a new match sends the chosen value.

- [ ] **10.3 — Bracket rendering (E9).**
  Files: new `frontend/src/components/Bracket.tsx`, `frontend/src/components/Standings.tsx`.
  Tests: new `Bracket.test.tsx`, `Standings.test.tsx` — rounds render in order with every match;
  winners are visibly marked; byes are labelled and show no turn count; the champion is called out
  when `status === "complete"` and not before; two same-fighter entrants render distinct
  `display` labels; standings rows show wins, losses and `eliminated_in`.

- [ ] **10.4 — Tournament screen and navigation.**
  Files: new `frontend/src/TournamentScreen.tsx`, `frontend/src/App.tsx` (a state toggle between
  Arena and Tournament — no router dependency, E9).
  Tests: new `TournamentScreen.test.tsx`, updated `App.test.tsx` — the create form posts roster,
  difficulty and seed; **Advance** calls the endpoint once per click, is disabled while a request is
  in flight and once the tournament is complete, and re-renders the returned bracket; the past
  tournaments list renders newest first; an API error renders a readable message without discarding
  the bracket on screen; the toggle switches views and back.

### 11. Acceptance sweep

- [ ] **11.1 — Walk every E10 criterion against the suite.**
  For each of the 30 checkboxes in E10 (15 AI, 15 tournament), name the test that proves it
  (file + test name) in
  `running.md`; anything unproven becomes a new test in this task, not a checked box. Confirm the
  `specs/base.md` §5.5 edits from 1.1/1.2 are in place and that no other Step 1 criterion changed.
  Then run `./script/setup`, `./script/test` and `./script/lint` from clean, and record in
  `running.md` the measured search-move time, the three strength rates, and the strength-suite
  runtime with any B9 mitigation applied.
