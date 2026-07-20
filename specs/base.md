# specs/base.md — Fighting Game, Base Arena (Step 1)

Status: active spec for Step 1.
Scope: a playable turn-based 1v1 battle arena with **server-authoritative** turn resolution.
Out of scope (Step 2): the real AI opponent and the persistent tournament bracket.

---

## 1. Overview

Two fighters trade turns until one is knocked out. Every strong action costs **ki**, and the only
way to get ki back is to spend a turn not attacking. That resource tension — burst now, or charge
and risk eating a hit — is the entire game.

The browser client is a **thin renderer**. It sends a chosen action and draws whatever state comes
back. It never computes damage, never rolls randomness, and never decides legality. The Flask
backend owns all of it.

---

## 2. Fighter model

| Field | Type | Meaning |
|---|---|---|
| `id` | string | Stable slug, e.g. `"kaito"` |
| `name` | string | Display name |
| `hp` | int | Current health; match ends at 0 |
| `hp_max` | int | Starting health |
| `ki` | int | Current ki; spent by moves, restored by Charge/Guard |
| `ki_max` | int | Ki ceiling (100 for both starters) |
| `atk` | int | Offense; scales damage dealt |
| `def` | int | Defense; reduces damage taken |
| `spd` | int | Determines who acts first within a turn |
| `guarding` | bool | Set by Guard; consumed during this turn's resolution |
| `ascended` | bool | Whether the Ascend buff is currently active |
| `ascend_used` | bool | Whether Ascend has been used this match (once per match) |

`hp` is clamped to `[0, hp_max]`, `ki` to `[0, ki_max]`.

### 2.1 Starter fighters

| | Kaito (glass cannon) | Vega (tank) |
|---|---|---|
| `hp_max` | 100 | 130 |
| `ki_max` | 100 | 100 |
| starting `ki` | 30 | 30 |
| `atk` | 22 | 16 |
| `def` | 8 | 14 |
| `spd` | 14 | 9 |

Kaito hits harder and almost always acts first; Vega absorbs far more and wins long games. Neither
is strictly better — see §4.5.

**Mirror matches are legal.** `player_fighter` and `opponent_fighter` may be the same id; the two
sides are independent copies of the template and share no state. Kaito-vs-Kaito is in fact the
cleanest test of the `spd` tie-break rule (§4.4), so it must not be rejected.

---

## 3. Moves

Six moves. Every move is legal only if its precondition holds (§5.4).

| Move | `action` value | Ki cost | Power | Effect |
|---|---|---|---|---|
| Strike | `strike` | 0 | 14 | Basic attack. Always legal. |
| Ki Blast | `ki_blast` | 15 | 26 | Ranged attack, the default poke. |
| Surge Beam | `surge_beam` | 40 | 48 | Heavy attack. |
| Charge | `charge` | 0 | — | Restore **25** ki (30 if ascended). No attack. |
| Guard | `guard` | 0 | — | Halve incoming damage this turn; restore **8** ki. |
| Ascend | `ascend` | 40 | — | Once per match. Permanent: ×1.25 damage dealt, `spd` +5, Charge restores 30. |

Charge, Guard and Ascend deal no damage.

---

## 4. Rules

### 4.1 Damage formula

For an attacking move with power `P`, attacker `A`, defender `D`:

```
base       = P * (A.atk / (A.atk + D.def))
ascend_mul = 1.25 if A.ascended else 1.0
spread     = uniform random float in [0.90, 1.10]
guard_mul  = 0.5 if D.guarding else 1.0
damage     = max(1, round(base * ascend_mul * spread * guard_mul))
```

Damage is always at least **1**, so no matchup can stall at zero.

`atk / (atk + def)` is deliberately a ratio, not a subtraction: it cannot go negative, and it makes
high `def` valuable without ever making a fighter immune.

### 4.2 Ki

- Costs are paid **when the action resolves**, before damage is computed.
- An action whose ki cost exceeds current ki is **illegal** and rejected (§5.4). It is never
  silently downgraded to Strike — silent substitution would make the log lie about what happened.
- Charge restores 25 ki (30 while ascended). Guard restores 8 ki. Both clamp at `ki_max`.
- Ki is never restored passively. Doing nothing is not an option; the turn must be spent.

### 4.3 Guard

- `guarding` is set the moment Guard resolves and is cleared at the **end of that same turn**.
- It therefore halves damage from the opponent's attack **in the turn Guard was chosen**, including
  when the opponent is faster and already attacked earlier in that same turn — see §4.4 for why
  this is stated explicitly rather than left to resolution order.
- Guard has no ki cost, so it is always legal, including at 0 ki.
- Guarding while the opponent also guards or charges simply wastes the turn (both gain a little ki).

### 4.4 Turn order

Within a turn, the fighter with the higher effective `spd` resolves first (Ascend's +5 counts).
Ties are broken by a coin flip from the match RNG.

**If the first fighter's attack reduces the second to 0 hp, the second does not act.** This is what
makes `spd` and burst damage matter.

Guard is resolved out of order: **both fighters' non-attack effects (Guard, Charge, Ascend) apply
before either attack is computed.** Without this rule, guarding against a faster opponent would do
nothing, which would make Guard useless for the slower fighter — precisely the fighter who needs it.

So a turn resolves in this order:

1. Validate both actions (§5.4).
2. Apply Ascend for whoever chose it (pay ki, set flags).
3. Apply Charge / Guard for whoever chose them (restore ki, set `guarding`).
4. Attacks resolve in `spd` order, paying ki then applying damage. A KO stops resolution.
5. Clear `guarding` on both fighters.
6. Increment turn counter, append log entries, check win condition.

**Turn numbering.** A newly created match has `turn: 0` and an empty `log`. The first resolved turn
sets `turn: 1`. So `turn` always equals the number of turns actually resolved, and the log entries
for turn *n* carry `"turn": n`.

### 4.5 Balance intent (informative, not testable)

Sustained damage per turn, Kaito attacking Vega, over a repeating cycle:

| Cycle | Damage/turn |
|---|---|
| Ki Blast ×2 → Charge | ~10.6 |
| Surge Beam → Charge ×2 | ~9.8 |
| Strike only | ~8.6 |

No move dominates: Surge Beam trades sustained output for burst and KO reach, Strike is the floor
you fall back to at 0 ki. Ascend costs 40 ki (≈1.6 charge turns) and pays back over roughly ten
subsequent attacks, so it is strong early and a trap late.

Expected match length is ~12–20 turns.

### 4.6 Win condition

- A fighter at 0 hp is knocked out; the other wins. `status` becomes `player_won` or `opponent_won`.
- Because attacks resolve sequentially (§4.4), a double-KO is impossible.
- **Turn cap: 100.** If turn 100 completes with both alive, the winner is whoever has the higher
  remaining hp **as a fraction of `hp_max`** (fair across the 100/130 hp gap). The cap guarantees
  termination.

  Compare the fractions by **integer cross-multiplication**, never by dividing:

  ```
  player_score   = player.hp   * opponent.hp_max
  opponent_score = opponent.hp * player.hp_max
  ```

  Higher score wins; exactly equal is a `draw`. Comparing `hp/hp_max` as floats would make the
  `draw` case depend on binary rounding and produce a test that passes or fails by luck.

### 4.7 Opponent (base game only)

The opponent picks **uniformly at random from its currently legal moves**, drawn from the match RNG.
It has no strategy — replacing it is the whole point of Step 2. It must never pick an illegal move,
so a turn can never fail because of the opponent's choice.

**The opponent's move is drawn only after the player's action has been validated.** Drawing it
first would advance the RNG on a request that then returns 400, so a rejected turn would silently
change future damage rolls — violating "a rejected turn does not mutate the match" (§5.4) in a way
no state comparison would catch.

### 4.8 RNG draw order

The match owns a single seeded RNG. Determinism (§5.1) only holds if every implementation consumes
it in the same order, so the order is fixed here:

1. `spd` tie coin flip, **only** when effective speeds are equal.
2. The opponent's random move choice (§4.7).
3. Damage spread for the first attack to resolve.
4. Damage spread for the second attack, if the defender survived to act.

A draw is consumed only when the step actually occurs — no dummy draws. Two matches with the same
seed and the same player actions therefore produce identical logs.

---

## 5. Server API

Base path `/api`. JSON in, JSON out. All errors use the shape in §5.4.

### 5.1 `POST /api/match` — start a match

Request:
```json
{ "player_fighter": "kaito", "opponent_fighter": "vega", "seed": 12345 }
```
`seed` is optional; when present it must be an **integer**, and the match RNG is seeded with it,
making the whole match reproducible. This exists so tests can assert on exact damage numbers. A
non-integer `seed` is rejected with `invalid_seed`. When absent, the server seeds randomly and does
not report the seed back (Step 1 has no replay feature to need it).

Response `201`: the **match state object** (§5.5), with `turn: 0` and an empty `log`.

### 5.2 `POST /api/match/<match_id>/turn` — submit a turn

Request:
```json
{ "action": "ki_blast" }
```

The server picks the opponent's action itself (§4.7), resolves the turn, and returns the new state.
Submitting a turn to a finished match is an error (`match_over`).

Response `200`: the match state object, with `log` extended by this turn's entries.

### 5.3 `GET /api/match/<match_id>` — fetch state

Response `200`: the match state object. Read-only; safe to poll or reload.

### 5.4 Errors

```json
{ "error": { "code": "insufficient_ki", "message": "Surge Beam costs 40 ki; Kaito has 25." } }
```

| Code | HTTP | When |
|---|---|---|
| `unknown_fighter` | 400 | `player_fighter` / `opponent_fighter` is not a known id |
| `unknown_action` | 400 | `action` is not one of the six move ids, or `action` is missing |
| `invalid_seed` | 400 | `seed` is present but not an integer |
| `insufficient_ki` | 400 | Ki cost exceeds current ki |
| `already_ascended` | 400 | Ascend chosen when `ascend_used` is true |
| `match_over` | 409 | Turn submitted to a match whose `status` is not `in_progress` |
| `match_not_found` | 404 | Unknown `match_id` |

A rejected turn **does not mutate the match**. State after a 400 is byte-identical to state before,
*and* the match RNG must be unadvanced — see §4.7. Testing this requires more than comparing the
two state payloads: reject a turn, then play a legal turn, and assert the result matches what the
same seed produces without the rejected attempt in between.

### 5.5 Match state object

```json
{
  "match_id": "9f2c1e...",
  "status": "in_progress",
  "turn": 3,
  "player": {
    "id": "kaito", "name": "Kaito",
    "hp": 78, "hp_max": 100, "ki": 15, "ki_max": 100,
    "atk": 22, "def": 8, "spd": 14,
    "guarding": false, "ascended": false, "ascend_used": false
  },
  "opponent": { "...": "same shape, Vega" },
  "legal_actions": ["strike", "charge", "guard"],
  "log": [
    { "turn": 3, "actor": "player", "action": "ki_blast",
      "damage": 16, "target_hp": 92, "text": "Kaito fires a Ki Blast for 16. Vega: 92 HP." },
    { "turn": 3, "actor": "opponent", "action": "guard",
      "damage": 0, "target_hp": 78, "text": "Vega guards, recovering 8 ki." }
  ]
}
```

`status` ∈ `in_progress` | `player_won` | `opponent_won` | `draw`.

`legal_actions` is computed server-side for the **player**, so the UI can disable buttons without
duplicating rule logic. This is the one piece of rule knowledge the client is allowed to consume —
and it consumes it as data, not as reimplemented logic. It is **empty** whenever `status` is not
`in_progress`, so a finished match cannot present a playable button.

`guarding` is always `false` in a returned state, because Guard is set and cleared inside a single
turn's resolution (§4.3). It appears in the payload only so the fighter shape stays identical
everywhere; the client must not key any behavior off it.

`log` is append-only and cumulative for the whole match, oldest first. Each entry carries both
structured fields and a prerendered `text` so the client does no sentence-building.

---

## 6. Architecture constraints

- Pure game rules live in `backend/game/rules.py` as **pure functions** — no Flask imports, no
  globals, no I/O. `resolve_turn(state, player_action, opponent_action, rng) -> (new_state, entries)`
  is the single resolution entry point, and it must not mutate its input.
- Fighter definitions live in `backend/game/fighters.py`.
- HTTP layer in `backend/app.py` does validation → call rules → serialize. No rules in the routes.
- Step 1 stores matches **in memory** (a dict keyed by `match_id`). Persistence arrives in Step 2.
  `match_id` is a UUID4 hex string. Unknown ids return 404 rather than being created on demand.
- Frontend: React 18 + TypeScript + Vite + Tailwind. Components render `MatchState`; a single typed
  API module owns all `fetch` calls.
- **Cross-origin access must be solved explicitly.** The client runs on `:5173` and the API on
  `:5000`, so every request is cross-origin and will be blocked by the browser unless handled.
  Use a Vite dev-server proxy (`/api` → `http://localhost:5000`) so the browser sees a same-origin
  request; the frontend then calls relative `/api/...` paths and needs no base URL. If a proxy is
  not used, the backend must enable CORS for the Vite origin instead. Either way this is a
  requirement, not an implementation detail — without it the UI cannot talk to the server at all.

---

## 7. Frontend requirements

- HP bar and ki bar per fighter, showing current/max numerically as well as by width.
- Six move buttons. A button is disabled iff its action is absent from `legal_actions`, with the
  ki cost visible on each.
- Scrolling battle log, newest visible, rendered from `log[].text`.
- Win/lose/draw screen when `status` leaves `in_progress`, with a "new match" action.
- Buttons are disabled while a turn request is in flight, so a double-click cannot submit two turns.

---

## 8. Acceptance criteria

A reviewer can verify each of these directly.

- [ ] `POST /api/match` returns 201 and a state with both fighters at full hp and 30 ki,
      `turn: 0`, and an empty `log`.
- [ ] Two matches created with the same `seed` and given the same action sequence produce
      **identical** logs and final states.
- [ ] A rejected (400) turn does not advance the RNG: reject-then-play yields the same result as
      play alone, at the same seed.
- [ ] A mirror match (`kaito` vs `kaito`) is accepted and playable to a conclusion.
- [ ] `POST /api/match/<id>/turn` with `strike` reduces opponent hp by ≥1 and appends ≥1 log entry.
- [ ] Ki Blast deducts exactly 15 ki; Surge Beam exactly 40; Strike, Charge and Guard deduct 0.
- [ ] Charge raises ki by exactly 25 (30 ascended) and never above `ki_max`.
- [ ] Guard raises ki by 8 and halves the damage taken that turn, **including** when the opponent
      is faster.
- [ ] Requesting `surge_beam` with ki < 40 returns 400 `insufficient_ki` and leaves state unchanged.
- [ ] Requesting `ascend` twice returns 400 `already_ascended`; the second attempt changes nothing.
- [ ] Guard is legal at 0 ki.
- [ ] After Ascend, damage dealt rises by ~25% and `spd` by 5; `ascend_used` stays true for the
      rest of the match.
- [ ] When a fighter reaches 0 hp, `status` changes and the slower fighter does not act that turn.
- [ ] Submitting a turn to a finished match returns 409 `match_over`.
- [ ] A match forced to turn 100 ends with a winner by hp fraction, or `draw` when exactly equal.
- [ ] `legal_actions` always matches what the rules would actually accept, and is empty once
      `status` is not `in_progress`.
- [ ] The opponent never selects an illegal move across 1000 simulated random matches.
- [ ] Every simulated random match terminates within 100 turns, and **at least 95% end by KO
      rather than by hitting the cap** — the cap is a safety net, not the normal ending.
- [ ] The frontend plays a full match to a win screen without a page reload, served through the
      configured proxy (§6) with no CORS errors in the console.
- [ ] `./script/test` passes with zero failures.

---

## 9. Test plan

**Unit — `backend/tests/test_rules.py`** (no HTTP, seeded RNG):
- Damage formula at fixed seed for each attacking move, both directions.
- Ki costs and clamping: spend, restore, ceiling at `ki_max`, floor at 0.
- Guard halving, including the slower-defender case; `guarding` cleared after the turn.
- Ascend: multiplier, `spd` +5, `ascend_used` latching, rejection of a second Ascend.
- Turn order by `spd`, the tie coin flip, and the KO-stops-resolution rule.
- Turn cap: a match forced to 100 turns resolves by cross-multiplied hp comparison, including a
  constructed exactly-equal case that must yield `draw`.
- `resolve_turn` does not mutate its input state.
- **Property/fuzz:** 1000 seeded random-vs-random matches — every one terminates within 100 turns,
  ≥95% end by KO, hp and ki stay within `[0, max]`, and no illegal action is ever chosen.

**API — `backend/tests/test_api.py`** (Flask test client):
- Each endpoint's happy path and response shape.
- Every error code in §5.4, each asserting state is unchanged afterwards.
- Determinism: same seed + same actions ⇒ identical final state and log.
- RNG is not advanced by a rejected turn (the reject-then-play comparison from §5.4).
- A mirror match is accepted.
- `legal_actions` agrees with the rules layer across a played-out match, and empties on finish.

**Frontend — Vitest**:
- Bars render the right widths/values for a given `MatchState`.
- A move button is disabled exactly when its action is missing from `legal_actions`.
- The log renders entries oldest-first from `text`.
- The win screen appears when `status` leaves `in_progress`.
- Buttons are disabled while a request is in flight.

---

## 10. Review log (Step 1 / Stage 2)

A skeptical pass over §1–§9. Nine defects found; each is fixed above.

| # | Problem | Severity | Fix |
|---|---|---|---|
| 1 | The opponent's random move was drawn before the player's action was validated, so a turn rejected with 400 still advanced the match RNG. "A rejected turn does not mutate the match" was therefore false in a way comparing state payloads could never detect — an invalid request silently changed all future damage rolls. | **High** | §4.7: the opponent's move is drawn only after validation. §5.4 adds the reject-then-play test that can actually catch it. |
| 2 | Nothing solved cross-origin access. The client is served from `:5173` and the API from `:5000`; the browser blocks that by default. Every endpoint could be correct and the game still wouldn't work. | **High** | §6 requires a Vite `/api` proxy (or backend CORS), and the acceptance criteria require a clean console. |
| 3 | Determinism was promised but the RNG consumption order was never fixed. Two correct-looking implementations could disagree on damage at the same seed, making the determinism criterion untestable across a refactor. | **High** | New §4.8 fixes the draw order and forbids dummy draws. |
| 4 | The turn-cap tie compared `hp/hp_max` as floats, so the `draw` case hinged on binary rounding — a test that passes or fails by luck. | Medium | §4.6 switches to integer cross-multiplication. |
| 5 | `turn` was never given a starting value; the example showed `turn: 3` with no way to know whether a fresh match is 0 or 1, and the cap's meaning depended on the answer. | Medium | §4.4 defines `turn: 0` at creation. |
| 6 | `legal_actions` was undefined for a finished match, so a client could render live buttons on a won game. | Medium | §5.5: empty unless `status` is `in_progress`. |
| 7 | "Every simulated match terminates within 100 turns" is trivially satisfied by the cap itself — it would pass even if the game could never produce a KO. | Medium | §8/§9 additionally require ≥95% of fuzz matches to end by KO. |
| 8 | Mirror matches were neither permitted nor forbidden, leaving the `spd` tie-break — the rule most in need of testing — potentially unreachable. | Low | §2.1 explicitly permits them; §8 adds a criterion. |
| 9 | `guarding` is exposed in the API but, being set and cleared inside one turn, is always `false` to a client — an invitation to build UI on a field that never changes. | Low | §5.5 documents it as always false and off-limits for client behavior. |

### Checked and found sound

- **No dominant move.** Ki Blast ≈10.6, Surge Beam ≈9.8, Strike ≈8.6 damage/turn sustained; Surge
  Beam trades DPS for burst, which is the intended shape.
- **Matches end.** Turtling is not viable: guarding every turn still concedes ~8.5 damage/turn to
  Vega, killing Kaito in ~12 turns while dealing nothing. The cap is a backstop, not the norm.
- **Edge cases already covered.** Guard at 0 ki (legal, no cost), Surge Beam with insufficient ki
  (400, no downgrade), Ascend twice (400), ki clamping at `ki_max`, and the `max(1, …)` damage
  floor were all specified and survive review unchanged.
- **Double-KO is impossible** by construction, since attacks resolve sequentially — so `draw` has
  exactly one cause (the cap), which keeps the status enum honest.
