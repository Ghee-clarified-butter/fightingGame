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
  remaining hp **as a fraction of `hp_max`** (fair across the 100/130 hp gap). If those fractions
  are exactly equal, `status` becomes `draw`. The cap guarantees termination.

### 4.7 Opponent (base game only)

The opponent picks **uniformly at random from its currently legal moves**, drawn from the match RNG.
It has no strategy — replacing it is the whole point of Step 2. It must never pick an illegal move,
so a turn can never fail because of the opponent's choice.

---

## 5. Server API

Base path `/api`. JSON in, JSON out. All errors use the shape in §5.4.

### 5.1 `POST /api/match` — start a match

Request:
```json
{ "player_fighter": "kaito", "opponent_fighter": "vega", "seed": 12345 }
```
`seed` is optional; when present the match RNG is seeded with it, making the whole match
reproducible. This exists so tests can assert on exact damage numbers.

Response `201`: the **match state object** (§5.5).

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
| `unknown_action` | 400 | `action` is not one of the six move ids |
| `insufficient_ki` | 400 | Ki cost exceeds current ki |
| `already_ascended` | 400 | Ascend chosen when `ascend_used` is true |
| `match_over` | 409 | Turn submitted to a match whose `status` is not `in_progress` |
| `match_not_found` | 404 | Unknown `match_id` |

A rejected turn **does not mutate the match**. State after a 400 is byte-identical to state before.

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
and it consumes it as data, not as reimplemented logic.

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
- Frontend: React 18 + TypeScript + Vite + Tailwind. Components render `MatchState`; a single typed
  API module owns all `fetch` calls.

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

- [ ] `POST /api/match` returns 201 and a state with both fighters at full hp and 30 ki.
- [ ] Two matches created with the same `seed` and given the same action sequence produce
      **identical** logs and final states.
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
- [ ] `legal_actions` always matches what the rules would actually accept.
- [ ] The opponent never selects an illegal move across 1000 simulated random matches.
- [ ] Every simulated random match terminates within 100 turns.
- [ ] The frontend plays a full match to a win screen without a page reload.
- [ ] `./script/test` passes with zero failures.

---

## 9. Test plan

**Unit — `backend/tests/test_rules.py`** (no HTTP, seeded RNG):
- Damage formula at fixed seed for each attacking move, both directions.
- Ki costs and clamping: spend, restore, ceiling at `ki_max`, floor at 0.
- Guard halving, including the slower-defender case; `guarding` cleared after the turn.
- Ascend: multiplier, `spd` +5, `ascend_used` latching, rejection of a second Ascend.
- Turn order by `spd`, the tie coin flip, and the KO-stops-resolution rule.
- Turn cap: a match forced to 100 turns resolves by hp fraction, and the equal case is a `draw`.
- `resolve_turn` does not mutate its input state.
- **Property/fuzz:** 1000 seeded random-vs-random matches — every one terminates within 100 turns,
  hp and ki stay in range, and no illegal action is ever chosen.

**API — `backend/tests/test_api.py`** (Flask test client):
- Each endpoint's happy path and response shape.
- Every error code in §5.4, each asserting state is unchanged afterwards.
- Determinism: same seed + same actions ⇒ identical final state and log.
- `legal_actions` agrees with the rules layer across a played-out match.

**Frontend — Vitest**:
- Bars render the right widths/values for a given `MatchState`.
- A move button is disabled exactly when its action is missing from `legal_actions`.
- The log renders entries oldest-first from `text`.
- The win screen appears when `status` leaves `in_progress`.
- Buttons are disabled while a request is in flight.
