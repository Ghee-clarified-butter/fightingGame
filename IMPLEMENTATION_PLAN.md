# Implementation Plan — Step 1, Base Arena

Derived from `specs/base.md` (active spec). Rewritten by the plan loop; consumed one task per
iteration by `PROMPT_build.md`.

**Rules for the builder:**
- Do exactly one unchecked task per iteration, top to bottom. Do not skip ahead.
- `./script/test` must pass at the end of **every** task. A task that leaves the suite red is not
  done. This is why the scaffolding tasks (0.x) ship with real assertions rather than empty suites —
  `vitest` exits non-zero when it finds no test files.
- No stubs, no placeholders, no TODOs (AGENTS.md).

---

## A. Decisions this plan pins down

The spec leaves these under-determined. They are settled here so the build loop does not bake in an
arbitrary choice and then test it against itself.

**A1 — RNG draw order vs. the `resolve_turn` signature (§4.8 vs §6).**
§4.8 fixes consumption order as (1) spd tie flip, (2) opponent's move choice, (3) first attack
spread, (4) second attack spread. But §6 pins `resolve_turn(state, player_action, opponent_action,
rng)` — by then the opponent's action already exists, so the obvious implementation consumes draw #2
before draw #1. Resolution: `rules.py` exposes three pure functions.

```
roll_turn_order(state, rng) -> ("player"|"opponent", "player"|"opponent")   # consumes draw #1
choose_opponent_action(state, rng) -> str                                   # consumes draw #2
resolve_turn(state, player_action, opponent_action, rng, *, order=None) -> (new_state, entries)
```

`resolve_turn` keeps the §6 signature and remains the single resolution entry point; the added
keyword-only `order` lets the caller pass an order already rolled. When `order is None` it rolls one
itself (convenient for unit tests that exercise one turn in isolation). The app layer calls
`roll_turn_order` → `choose_opponent_action` → `resolve_turn(..., order=order)`, which reproduces
§4.8's order exactly.

**A2 — Turn order uses start-of-turn speed.**
§4.4 says "Ascend's +5 counts", but whether speeds tie cannot be known before the opponent's action
is drawn (draw #2), while the tie flip is draw #1. The only ordering consistent with §4.8 is:
`roll_turn_order` uses effective spd **entering** the turn (`spd + 5` if `ascended` was already true
before this turn). A fighter that ascends on turn *n* gets its speed advantage from turn *n+1*. The
acceptance criterion "`spd` +5 after Ascend" is still met — the buff is in the state immediately.

**A3 — Tie flip only when start-of-turn effective speeds are equal**, per §4.8's "no dummy draws".
Method is pinned to `rng.random() < 0.5` → player first, else opponent first. Determinism tests
assert exact numbers, so the *method*, not just the order, has to be fixed.

**A4 — RNG methods are pinned.** `random.Random(seed)`; spread is `rng.uniform(0.90, 1.10)`;
opponent choice is `rng.choice(sorted_legal_actions)` over `legal_actions(state.opponent)` sorted in
the canonical move order `["strike","ki_blast","surge_beam","charge","guard","ascend"]` (filtered).
Sorting matters: iterating a set would make the seed non-reproducible across runs.

**A5 — Rounding.** `damage = max(1, round(...))` uses Python's built-in `round` (banker's rounding,
half-to-even) exactly as §4.1 writes it. Tests must be generated against this, not against
half-away-from-zero.

**A6 — Error precedence** (the spec lists codes but not their order). Check in this order and return
the first that fires: `match_not_found` (404) → `match_over` (409) → `unknown_action` (400) →
`already_ascended` (400) → `insufficient_ki` (400). So `ascend` at 20 ki with `ascend_used` true
returns `already_ascended`, and a garbage action on a finished match returns `match_over`.

**A7 — Log entry order and `target_hp`.** Entries are appended in **turn order** (first actor, then
second) even though non-attack effects resolve earlier (§4.4 step 3) — this matches the §5.5 example,
where the faster player's attack is listed before the slower opponent's guard. `target_hp` is always
the hp of the *actor's opponent* after that entry resolves; for Charge/Guard/Ascend it is that value
unchanged, with `damage: 0`.

**A8 — A fighter KO'd before it attacks still logs its non-attack effect.** Its Charge/Guard/Ascend
already resolved in step 3; only the attack is skipped (§4.4). So a KO'd charger produces one entry,
a KO'd attacker produces none.

**A9 — Cross-origin is solved with a Vite proxy** (§6's first option), so no `flask-cors` dependency
and no CORS headers in `app.py`. The frontend calls relative `/api/...` paths only.

**A10 — Import layout.** `./script/server` runs `cd backend && flask run`, so `app.py` imports
`game.rules`. `./script/test` runs `pytest backend/tests` from the repo root, where `backend/` is not
on `sys.path`. `backend/tests/conftest.py` therefore inserts the `backend/` directory into
`sys.path`, and tests import `from game.rules import ...` — the same module path the server uses.

---

## B. Library versions

Verified against the toolchain this repo actually runs on (`running.md`): **Python 3.13.5**,
**Node 22.19.0**. Ranges, not exact pins, so `./script/setup` resolves current patches; the builder
must confirm the install actually succeeds rather than assuming.

Backend — `backend/requirements.txt`:
- `Flask>=3.1,<4` — supports Python 3.9+, incl. 3.13. Ships `app.test_client()`, so no extra HTTP
  test dependency is needed.
- `pytest>=8,<9` — supports 3.13.
- `flake8>=7,<8` — supports 3.13; invoked as `python -m flake8` by `./script/lint`.

Frontend — `frontend/package.json`:
- `vite@^7` — requires Node `^20.19 || >=22.12`; 22.19.0 qualifies.
- `react@^18.3` + `react-dom@^18.3` — spec §6 says React 18, so do **not** install React 19.
- `typescript@^5`, `@vitejs/plugin-react@^5`.
- `vitest@^3` + `jsdom@^26` (`environment: "jsdom"`).
- `@testing-library/react@^16` + `@testing-library/dom@^10` + `@testing-library/jest-dom@^6`.
  RTL 16 declares `@testing-library/dom` as a *peer* dependency — it must be listed explicitly or
  the import fails at test time.
- `tailwindcss@^4` + `@tailwindcss/vite@^4`. Tailwind v4 is CSS-first: register the Vite plugin and
  put `@import "tailwindcss";` at the top of `src/index.css`. Do **not** create
  `tailwind.config.js`, `postcss.config.js`, or install `autoprefixer`/`postcss` — those are the v3
  setup, and mixing the two is the standard way this scaffold breaks.
- `eslint@^9` + `typescript-eslint@^8` + `eslint-plugin-react-hooks` + `eslint-plugin-react-refresh`,
  flat config in `eslint.config.js` (ESLint 9 no longer reads `.eslintrc`).

Not used: `flask-cors` (see A9), `requests`, any state/fetch library.

---

## C. Tasks

### Phase 0 — Toolchain (must land first; every later task depends on a green suite)

- [x] **0.1 Backend scaffold and a green pytest run.**
      Files: `backend/requirements.txt`, `backend/game/__init__.py`, `backend/tests/conftest.py`,
      `.flake8` (repo root), `backend/tests/test_imports.py`.
      `conftest.py` inserts the `backend/` dir into `sys.path` (A10). `.flake8` sets
      `max-line-length = 100` and excludes `.venv,node_modules,__pycache__`.
      Run `./script/setup` to create `.venv` and install.
      Test: `test_imports.py` asserts `import game` succeeds and that `sys.path` resolution works.
      Done when `./script/test` passes (frontend half still skips) and `./script/lint` is clean.

- [x] **0.2 Frontend scaffold and a green vitest run.**
      Files: `frontend/package.json`, `frontend/tsconfig.json`, `frontend/tsconfig.node.json`,
      `frontend/vite.config.ts`, `frontend/index.html`, `frontend/src/main.tsx`,
      `frontend/src/App.tsx`, `frontend/src/index.css`, `frontend/src/setupTests.ts`,
      `frontend/eslint.config.js`, `frontend/src/App.test.tsx`.
      Scripts: `dev`, `build`, `lint`, and `test` → `vitest` (so `./script/test`'s
      `npm run test -- --run` works). `vite.config.ts` sets `test.environment: "jsdom"`,
      `test.setupFiles: "./src/setupTests.ts"`, `test.globals: true`, registers
      `@tailwindcss/vite`, and configures `server.proxy` `/api` → `http://localhost:5000`
      (§6 / A9). `App.tsx` renders a title placeholder only.
      Test: `App.test.tsx` renders `<App />` and asserts the title is in the document.
      Done when `./script/test` passes both halves and `./script/lint` is clean.

### Phase 1 — Pure game rules (`backend/game/`), no Flask, no HTTP

- [x] **1.1 Fighter templates.**
      Files: `backend/game/fighters.py`, `backend/tests/test_fighters.py`.
      `FIGHTERS: dict[str, dict]` with `kaito` and `vega` at the exact §2.1 numbers, and
      `new_fighter(fighter_id) -> dict` returning a fresh independent copy with `hp = hp_max`,
      `ki = 30`, `guarding/ascended/ascend_used = False`. Unknown id raises `UnknownFighterError`.
      Tests: both templates match §2.1 field for field; two `new_fighter("kaito")` copies are
      `==` but not `is`, and mutating one does not touch the other (mirror-match independence, §2.1);
      unknown id raises.

- [x] **1.2 Move table and ki costs.**
      Files: `backend/game/moves.py`, `backend/tests/test_moves.py`.
      `MOVES` keyed by the six action ids, each with `cost`, `power` (`None` for non-attacks),
      `name`, and `is_attack`. `ACTION_ORDER` is the canonical list from A4.
      Tests: exactly six moves; costs are strike/charge/guard 0, ki_blast 15, surge_beam 40,
      ascend 40; powers 14/26/48; Charge, Guard and Ascend are not attacks.

- [x] **1.3 Match state construction.**
      Files: `backend/game/rules.py`, `backend/tests/test_rules.py`.
      `new_match(player_id, opponent_id) -> dict` producing the §5.5 shape minus HTTP concerns
      (no RNG argument — creation consumes no draws, per §4.8's no-dummy-draws rule):
      `status: "in_progress"`, `turn: 0`, `log: []`, both fighters from `new_fighter`. Plain dicts
      throughout so serialization is a no-op.
      Tests: fresh match has `turn == 0`, empty `log`, both fighters at full hp and 30 ki,
      `status == "in_progress"`; a mirror match (`kaito` vs `kaito`) is constructed without error.

- [x] **1.4 `legal_actions`.**
      Files: `backend/game/rules.py`, `backend/tests/test_rules.py`.
      `legal_actions(fighter) -> list[str]` in `ACTION_ORDER` order: strike/charge/guard always;
      ki_blast iff `ki >= 15`; surge_beam iff `ki >= 40`; ascend iff `ki >= 40 and not ascend_used`.
      Tests: at 0 ki → `["strike","charge","guard"]` (Guard legal at 0 ki, §8); at 15 → adds
      ki_blast; at 40 → adds surge_beam and ascend; at 40 with `ascend_used` → no ascend; result is
      always a sorted-by-`ACTION_ORDER` list, never a set.

- [x] **1.5 Damage formula.**
      Files: `backend/game/rules.py`, `backend/tests/test_rules.py`.
      `compute_damage(attacker, defender, power, spread) -> int` implementing §4.1 exactly, with
      `spread` passed in as a float so the formula is testable without an RNG.
      Tests: hand-computed values for each attacking move in both directions (Kaito→Vega and
      Vega→Kaito) at `spread = 1.0`, and at the 0.90 and 1.10 extremes; ascend multiplier applies;
      guard halves; the `max(1, ...)` floor holds for a contrived tiny-power / huge-def case;
      A5's banker's rounding is asserted on at least one exact `.5` case.

- [ ] **1.6 Turn order and the tie coin flip.**
      Files: `backend/game/rules.py`, `backend/tests/test_rules.py`.
      `effective_spd(fighter)` (`spd + 5` if `ascended`) and `roll_turn_order(state, rng)` per A2/A3:
      no draw when speeds differ, one `rng.random()` draw when equal.
      Tests: Kaito (14) before Vega (9) with **zero** RNG draws consumed — assert by comparing
      `rng.getstate()` before and after; a mirror match consumes exactly one draw and both outcomes
      are reachable across seeds; an already-`ascended` Vega (14) ties Kaito (14) and triggers a flip;
      a fighter that ascends *this* turn does not change *this* turn's order (A2).

- [ ] **1.7 `resolve_turn` — effects phase.**
      Files: `backend/game/rules.py`, `backend/tests/test_rules.py`.
      Steps 2–3 of §4.4: Ascend (pay 40 ki, set `ascended` and `ascend_used`, no damage), then
      Charge (+25 ki, +30 if `ascended`) and Guard (+8 ki, set `guarding`), both clamped to `ki_max`.
      Both fighters' effects apply before any attack.
      Tests: Charge raises ki by exactly 25, by 30 when ascended, and never exceeds `ki_max` from a
      near-cap start; Guard raises ki by exactly 8; Ascend deducts exactly 40 and latches
      `ascend_used`; both sides charging in one turn each gain their own ki.

- [ ] **1.8 `resolve_turn` — attack phase, KO, and guard clearing.**
      Files: `backend/game/rules.py`, `backend/tests/test_rules.py`.
      Step 4–5: attacks resolve in the order from 1.6, paying ki (§4.2) then applying damage; hp
      clamps at 0; **a KO stops resolution** so the second fighter does not attack; `guarding` is
      cleared on both fighters at the end of the turn.
      Tests: Strike reduces hp by ≥1; ki_blast deducts exactly 15 and surge_beam exactly 40 while
      strike/charge/guard deduct 0 (§8); Guard halves incoming damage **including when the guarding
      fighter is slower** (§4.3 — construct Vega guarding against a faster Kaito and compare with the
      same seed and no guard); `guarding` is `False` in the returned state; a state contrived so the
      faster fighter's attack drops the other to 0 shows the slower fighter never attacking; after
      Ascend, damage rises ~25% and `effective_spd` is +5.

- [ ] **1.9 Log entries and turn counter.**
      Files: `backend/game/rules.py`, `backend/tests/test_rules.py`.
      Step 6: `turn` increments (first resolved turn → `1`, §4.4), and entries carry
      `turn`/`actor`/`action`/`damage`/`target_hp`/`text` per §5.5, appended in turn order per A7,
      with the KO-before-acting rule of A8. `text` is prerendered so the client builds no sentences.
      Tests: fresh match resolving one turn yields `turn == 1` and entries all tagged `"turn": 1`;
      log is cumulative and oldest-first across three turns; a Guard entry has `damage: 0` and
      `target_hp` equal to the actor's opponent's unchanged hp; a KO'd second fighter that charged
      still logs its charge but no attack (A8); a KO'd second fighter that attacked logs nothing.

- [ ] **1.10 Win condition and the turn cap.**
      Files: `backend/game/rules.py`, `backend/tests/test_rules.py`.
      `check_status(state)`: 0 hp → `player_won`/`opponent_won`; at `turn == 100` with both alive,
      compare `player.hp * opponent.hp_max` vs `opponent.hp * player.hp_max` (§4.6, integer
      cross-multiplication — never float division); equal → `draw`.
      Tests: each KO direction sets the right status; a state constructed at turn 100 with
      Kaito 50/100 vs Vega 60/130 resolves by cross-product; a **constructed exactly-equal** case
      (e.g. Kaito 50/100 vs Vega 65/130 → 6500 == 6500) yields `draw`; the comparison is asserted to
      use integers.

- [ ] **1.11 `resolve_turn` does not mutate its input.**
      Files: `backend/tests/test_rules.py` (test only — fix `rules.py` if it fails).
      Test: deep-copy a state, call `resolve_turn`, assert the original is `==` to its copy and that
      the returned state is a different object (§6, §9).

- [ ] **1.12 Opponent choice and the §4.8 draw order.**
      Files: `backend/game/rules.py`, `backend/tests/test_rules.py`.
      `choose_opponent_action(state, rng)` per §4.7 + A4: uniform over the opponent's *legal* moves,
      drawn from the match RNG, never illegal. Add `play_turn(state, player_action, rng)` composing
      `roll_turn_order` → `choose_opponent_action` → `resolve_turn(..., order=order)`.
      Tests: the opponent at 0 ki never returns `ki_blast`/`surge_beam`/`ascend`; with `ascend_used`
      it never returns `ascend`; **draw-order test** — two matches at the same seed with the same
      player actions produce identical states and logs; a third match that calls the same functions
      in a different order produces a *different* log, proving the order is actually load-bearing.

- [ ] **1.13 Property / fuzz suite.**
      Files: `backend/tests/test_fuzz.py`.
      1000 seeded random-vs-random matches (player actions drawn from a **separate** RNG so the match
      RNG's §4.8 draw order stays intact).
      Tests, per §8/§9: every match terminates within 100 turns; **≥95% end by KO** rather than the
      cap; `hp` stays in `[0, hp_max]` and `ki` in `[0, ki_max]` at every turn; no illegal action is
      ever chosen by either side; run at least one batch as a mirror match. Keep it under a few
      seconds — it runs on every build iteration.

### Phase 2 — HTTP layer (`backend/app.py`), validation → rules → serialize, no rules in routes

- [ ] **2.1 App factory, in-memory store, and `POST /api/match`.**
      Files: `backend/app.py`, `backend/tests/test_api.py`.
      Flask app with `MATCHES: dict[str, dict]` keyed by UUID4 hex (§6). Route returns **201** and
      the §5.5 state object. `seed` optional; when present it must be an `int` (and **not** a `bool`,
      since `isinstance(True, int)` is true in Python) or → 400 `invalid_seed`. Unknown fighter id →
      400 `unknown_fighter`. Errors use the §5.4 envelope `{"error": {"code", "message"}}`.
      Tests: 201 with both fighters at full hp and 30 ki, `turn: 0`, empty `log`, a UUID4-hex
      `match_id`; `unknown_fighter` for either side; `invalid_seed` for `"12345"`, `1.5`, and `true`;
      mirror match accepted (§8).

- [ ] **2.2 `GET /api/match/<id>` and `match_not_found`.**
      Files: `backend/app.py`, `backend/tests/test_api.py`.
      Read-only fetch; unknown id → 404 `match_not_found`, never created on demand (§6).
      Tests: fetch after create returns a byte-identical payload; two consecutive GETs are identical
      (no hidden mutation); unknown id → 404 with the right code.

- [ ] **2.3 Serialization and `legal_actions`.**
      Files: `backend/app.py`, `backend/tests/test_api.py`.
      `serialize(match)` emits exactly the §5.5 keys — including `guarding`, always `false` (§5.5) —
      and computes `legal_actions` for the **player**, empty whenever `status != "in_progress"`.
      Tests: response keys match §5.5 exactly, no extras and none missing; `legal_actions` agrees
      with `rules.legal_actions` at every turn of a played-out match; it is `[]` once the match ends
      (§8).

- [ ] **2.4 `POST /api/match/<id>/turn` happy path.**
      Files: `backend/app.py`, `backend/tests/test_api.py`.
      Validate the player's action, then call `play_turn` (which draws the opponent's move *after*
      validation, §4.7). Returns 200 with `log` extended.
      Tests: `strike` reduces opponent hp by ≥1 and appends ≥1 log entry (§8); `turn` increments by
      one per request; the log grows monotonically and stays oldest-first.

- [ ] **2.5 Turn error codes, with state left unchanged.**
      Files: `backend/app.py`, `backend/tests/test_api.py`.
      `unknown_action` (unknown id **or missing `action`**, §5.4), `insufficient_ki`,
      `already_ascended`, `match_over` (409), in the A6 precedence order.
      Tests: one test per code; each re-GETs the match and asserts the payload is identical to
      before; `surge_beam` at ki < 40 → 400 `insufficient_ki` (§8); a second `ascend` → 400
      `already_ascended` and nothing changes (§8); a turn on a finished match → 409 `match_over`
      (§8); missing `action` and an empty body both → `unknown_action`; A6 precedence is asserted
      with an `ascend` that is both already-used and unaffordable.

- [ ] **2.6 A rejected turn does not advance the RNG.**
      Files: `backend/tests/test_api.py`.
      The §5.4 / §8 criterion that a state comparison cannot catch.
      Test: at a fixed seed, play N legal turns → record final state. At the same seed, submit an
      illegal turn (400) *between* two of those legal turns and play the identical legal sequence;
      assert the final states and logs are identical. Repeat with a 409 on a finished match.

- [ ] **2.7 End-to-end API determinism and a playable mirror match.**
      Files: `backend/tests/test_api.py`.
      Tests: two matches created with the same `seed` and given the same action sequence produce
      **identical** logs and final states (§8); a `kaito` vs `kaito` match is played through the API
      to a terminal `status` (§8); a match played to completion has `legal_actions == []`.

### Phase 3 — Frontend (`frontend/src/`), thin renderer only

- [ ] **3.1 Types and the API module.**
      Files: `frontend/src/types.ts`, `frontend/src/api.ts`, `frontend/src/api.test.ts`.
      `MatchState`, `Fighter`, `LogEntry`, `ApiError` mirroring §5.5. A single typed module owning
      **all** `fetch` calls (§6) against relative `/api/...` paths — no base URL, no hostnames.
      `createMatch`, `getMatch`, `submitTurn`; non-2xx responses are parsed into the §5.4 envelope
      and thrown as a typed error.
      Tests: with `fetch` stubbed, each function hits the right relative path and method; a 400 body
      is surfaced as an error carrying `code` and `message`; no absolute URL appears in the module.

- [ ] **3.2 HP and ki bars.**
      Files: `frontend/src/components/StatBars.tsx`, `frontend/src/components/StatBars.test.tsx`.
      Per fighter: an hp bar and a ki bar, each showing current/max **numerically as well as by
      width** (§7).
      Tests: given a fighter at 78/100 hp and 15/100 ki, the text `78 / 100` and `15 / 100` render
      and the bar widths are 78% and 15%; 0 hp renders a 0% width without collapsing the layout;
      Vega's 130 max scales correctly (width is a fraction of max, not an absolute).

- [ ] **3.3 Move buttons.**
      Files: `frontend/src/components/MoveButtons.tsx`,
      `frontend/src/components/MoveButtons.test.tsx`.
      All six buttons, always rendered, each showing its ki cost. A button is disabled **iff** its
      action is absent from `legal_actions` (§7) — the component reads `legal_actions` as data and
      reimplements no rule. Also disabled while `busy` is true (§7).
      Tests: with `legal_actions: ["strike","charge","guard"]`, exactly those three are enabled and
      the other three are disabled; ki costs 0/15/40/0/0/40 are visible; with `busy` true every
      button is disabled even when legal; clicking fires `onSelect` with the action id; with
      `legal_actions: []` nothing is clickable.

- [ ] **3.4 Battle log.**
      Files: `frontend/src/components/BattleLog.tsx`, `frontend/src/components/BattleLog.test.tsx`.
      Scrolling list rendered from `log[].text` only, oldest first, newest visible (§7).
      Tests: three entries render in oldest-first order with the exact `text` strings; the component
      builds no sentences of its own (assert rendered text equals the input text); an empty log
      renders without crashing.

- [ ] **3.5 Result screen.**
      Files: `frontend/src/components/ResultScreen.tsx`,
      `frontend/src/components/ResultScreen.test.tsx`.
      Shown when `status` leaves `in_progress`, with a "new match" action (§7).
      Tests: `player_won`, `opponent_won` and `draw` each render their own message; a "new match"
      control is present and fires its callback; nothing renders while `in_progress`.

- [ ] **3.6 Match screen wiring.**
      Files: `frontend/src/App.tsx`, `frontend/src/MatchScreen.tsx`,
      `frontend/src/MatchScreen.test.tsx`.
      Compose 3.2–3.5 over one `MatchState`; create a match on mount; on a move click call
      `submitTurn` and replace state with the response. The client computes no damage and no
      legality (§1, §6). Set `busy` for the duration of the request so a double-click cannot submit
      two turns (§7). Surface an API error as a readable message without wedging the UI.
      Tests: with `api` mocked, mount creates a match and renders both fighters; clicking a move
      submits once and re-renders from the response; **a second click while the first request is
      in flight submits only one turn**; a terminal status swaps in the result screen; "new match"
      creates a fresh match without a page reload.

### Phase 4 — Whole-system verification

- [ ] **4.1 Manual end-to-end pass through the proxy.**
      Files: none (verification), then `running.md`.
      Run `./script/server`, open `http://localhost:5173`, play a full match to a win screen with no
      page reload, and confirm the browser console shows **no CORS errors** and requests go to
      `/api/...` on `:5173` via the Vite proxy (§6, §8). Then replace the placeholder text in
      `running.md` with the real setup/run/test instructions and a short "how to play" note.
      No automated test — this is the one criterion that requires a browser. Record the result.

- [ ] **4.2 Final acceptance sweep.**
      Files: none (verification only).
      Walk §8's checklist item by item and name the test that proves each one; every item must map to
      a real assertion (or, for the single browser item, to 4.1). Confirm `./script/test` passes with
      zero failures and `./script/lint` is clean. Confirm no stubs, placeholders or TODOs remain
      (AGENTS.md). Only after this is the spec satisfied.
