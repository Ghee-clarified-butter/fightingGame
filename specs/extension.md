# specs/extension.md — Fighting Game, Extension (Step 2)

Status: active spec for Step 2. Builds on `specs/base.md`, which stays authoritative for the
fighter model, the six moves, the damage formula, turn resolution and the base REST contract.
Section references like §4.8 refer to `specs/base.md` unless prefixed with `E`.

Two additions:

- **(A) A real AI opponent** replacing the random move-picker — a heuristic policy, then a shallow
  expectimax search, selected by a difficulty setting.
- **(B) A persistent single-elimination tournament** — SQLAlchemy models, bracket endpoints,
  SQLite storage that survives a server restart, and a bracket view in the UI.

---

# PART A — AI OPPONENT

## E1. Difficulty levels

`difficulty` is chosen at match creation and stored with the match.

| Value | Policy | Notes |
|---|---|---|
| `random` | Uniform over legal moves (§4.7) | The Step 1 behaviour. Kept, and kept as the default, so every Step 1 acceptance criterion still passes unchanged. |
| `heuristic` | Rule-based policy (E2) | Fast, deterministic, no search. |
| `search` | Depth-limited expectimax (E3) | Deterministic. Falls back to the heuristic for its leaf ordering. |

Unknown values are rejected with `400 unknown_difficulty`.

## E2. The heuristic policy

A deterministic priority list. The **first** rule whose condition holds selects the move; the move
must be legal (§5.4) or the rule is skipped. `self` is the AI, `foe` is its opponent.

1. **Finish.** If an affordable attack's *minimum* damage (spread `0.90`) would reduce `foe.hp`
   to 0, play the cheapest such attack. Minimum damage, not expected — a "finisher" that only wins
   on a good roll is a gamble, not a finish.
2. **Panic guard.** If `foe` can afford Surge Beam and that beam's *maximum* damage (spread `1.10`,
   unguarded) would reduce `self.hp` to 0, play Guard. Surviving beats trading.
3. **Ascend.** If Ascend is legal, `self.hp / self.hp_max >= 0.50`, and `self.ki >= 65`, play
   Ascend. Requiring 65 (not 40) means the buff does not leave the AI at 0 ki and helpless; the
   HP floor stops it buying a long-term buff it will not live to use.
4. **Beam.** If Surge Beam is legal and `self.ki >= 80`, play Surge Beam. The ki floor keeps a
   beam from emptying the pool when a Ki Blast would do.
5. **Poke.** If Ki Blast is legal, play Ki Blast.
6. **Recover.** If `self.ki < 15`, play Charge.
7. **Fallback.** Strike (always legal).

### E2.1 Stalemate prevention (mandatory)

Rules 3 and 6 are non-attacking. Two heuristic AIs facing each other (tournament matches are AI vs
AI) could otherwise alternate Charge and Guard indefinitely and be decided by the 100-turn cap,
which would make most tournament results meaningless.

**Hard rule: a policy must never select a non-attacking move (`charge`, `guard`, `ascend`) on more
than two consecutive turns.** On the third consecutive turn it must select an attack; Strike is
always affordable, so an attack always exists.

This requires per-fighter state: `passive_streak`, an integer on each fighter, incremented when
that fighter's chosen action is non-attacking and reset to 0 on any attack. It is part of the
match state and is serialized (E6.1).

The rule binds **all** policies including `random`, so no policy can stall a match.

## E3. Expectimax search

### E3.1 Shape

A depth-limited expectimax over the existing `resolve_turn`. Nodes alternate:

- **MAX** — the AI picks the action maximizing the value below it.
- **MIN** — the opponent is assumed to pick the action *minimizing* the AI's value. Modelling the
  opponent as an adversary rather than as random is the conservative choice and keeps the search
  from walking into punishing lines.
- **CHANCE** — the damage spread, averaged (E3.2).

`depth` counts **full turns** (one MAX + one MIN + resolution). Default `depth = 2`.

### E3.2 Averaging the spread

The spread is continuous on `[0.90, 1.10]` (§4.1) and cannot be enumerated. It is approximated by
**three equally weighted samples: `0.90`, `1.00`, `1.10`** — the midpoint plus both extremes,
weight `1/3` each.

A turn where **neither** side attacks has no spread and produces exactly one child, not three.
This matters for cost as well as correctness: mixed charge/guard lines are cheap.

The samples are fixed constants, not draws. **The search consumes no RNG** — see E3.4.

### E3.3 Evaluation function

Evaluated at leaves, from the AI's perspective:

```
if self.hp == 0:  return -1000
if foe.hp  == 0:  return +1000

hp_term    = 100 * (self.hp / self.hp_max - foe.hp / foe.hp_max)
ki_term    =  10 * (self.ki - foe.ki) / 100
tempo_term =   8 * (int(self.ascended) - int(foe.ascended))

value = hp_term + ki_term + tempo_term
```

- **HP dominates** at weight 100, as fractions so the 100/130 pool difference doesn't bias it.
- **Ki is worth something but much less** — 100 ki of advantage is worth 10 points, about a tenth
  of a full health bar. Ki is only latent damage.
- **Tempo** rewards having ascended, which no hp/ki term captures.
- Terminal values (±1000) dwarf everything, so the search always prefers a win to any material
  advantage.

### E3.4 Determinism and the RNG (critical)

§4.8 fixes the match RNG's draw order. Draw #2 is "the opponent's random move choice".

**The `heuristic` and `search` policies consume zero RNG draws.** Both are pure functions of the
state. Draw #2 therefore occurs **only** when `difficulty == "random"`, and §4.8's order becomes:

1. `spd` tie coin flip, only when effective speeds are equal.
2. Opponent's move choice — **only for `difficulty == "random"`**.
3. Damage spread for the first attack to resolve.
4. Damage spread for the second attack, if the defender survived.

Consequences that must hold:

- Ties inside the heuristic are impossible by construction (an ordered priority list).
- Ties inside the search are broken by the **canonical action order**
  `["strike","ki_blast","surge_beam","charge","guard","ascend"]`, never randomly.
- Seeded reproducibility (§5.1) holds at every difficulty.
- The search must never be handed the live match RNG. It operates on copies and passes fixed
  spreads; `resolve_turn` must accept a supplied spread so the search never draws.

### E3.5 Cost bound

Per turn, at `depth = 2`, worst case: 6 AI actions × 6 opponent actions × 3 spreads = 108 nodes at
ply 1, and 108 × 108 ≈ 11,664 leaves. Legal-move filtering typically cuts branching to 4–5, and
non-attacking pairs collapse their chance node to one child.

**Requirement: a `search` move must be chosen in under 100 ms on the reference machine, and this
is asserted by a test.** If depth 2 cannot meet it, the depth is lowered — the budget wins, not the
depth. Depth 3 is permitted only if it also fits the budget.

Memoization is optional; if used, the cache must be per-move-selection, never across turns, since
stale entries would break determinism.

## E4. API changes for Part A

`POST /api/match` gains an optional `difficulty`:

```json
{ "player_fighter": "kaito", "opponent_fighter": "vega", "difficulty": "search", "seed": 12345 }
```

Absent ⇒ `"random"`, so every Step 1 request stays valid and behaves identically.

The match state object (§5.5) gains `"difficulty"` and each fighter gains `"passive_streak"`.

New error: `unknown_difficulty` (400) for a value outside the three.

## E5. Frontend changes for Part A

A difficulty selector on the match screen, defaulting to `random`, disabled once a match is in
progress (difficulty is fixed at creation). The current difficulty is shown during the match.

---

# PART B — PERSISTENT TOURNAMENT

## E6. Storage

SQLAlchemy over SQLite. The database file lives at `backend/data/fightinggame.db` and is
gitignored (`*.db`). `./script/setup` creates the directory and the schema; the app creates the
schema on startup if it is absent, so a fresh clone works without a migration step.

Step 1's in-memory match store is **unchanged**. Single matches stay ephemeral; only tournaments
persist. Mixing the two would force a rewrite of working, tested code for no requirement.

### E6.1 Models

**`Fighter`** — the roster, seeded from `backend/game/fighters.py` on first run.

| Column | Type | Notes |
|---|---|---|
| `id` | str, PK | `"kaito"` |
| `name` | str | |
| `hp_max`, `ki_max`, `atk`, `def_`, `spd` | int | `def` is reserved in Python; column name `def_`, JSON key `def` |

**`Tournament`**

| Column | Type | Notes |
|---|---|---|
| `id` | str, PK | UUID4 hex |
| `name` | str | |
| `difficulty` | str | Applies to every match in it |
| `seed` | int | Root seed; per-match seeds derive from it (E7.3) |
| `size` | int | Bracket size — a power of two ≥ roster size |
| `status` | str | `pending` / `in_progress` / `complete` |
| `champion_id` | str, FK → Fighter, nullable | Set when the final resolves |
| `created_at` | datetime | |

**`TournamentMatch`**

| Column | Type | Notes |
|---|---|---|
| `id` | str, PK | UUID4 hex |
| `tournament_id` | str, FK, indexed | |
| `round` | int | 1 = first round |
| `slot` | int | Position within the round, 0-based |
| `fighter_a_id`, `fighter_b_id` | str, FK, nullable | Null = not yet determined, or a bye |
| `winner_id` | str, FK, nullable | |
| `status` | str | `pending` / `ready` / `complete` / `bye` |
| `turns` | int, nullable | Turns the match took |
| `log_json` | text, nullable | The finished match's battle log |

`(tournament_id, round, slot)` is **unique** — the bracket position identifies the match.

## E7. Bracket construction

### E7.1 Size and byes

For a roster of `n` fighters (`n >= 2`), bracket `size = 2^ceil(log2(n))` and
`byes = size - n`.

Round 1 has `size / 2` slots. Fighters are seeded in roster order (index 0 = top seed).
**Byes go to the top `byes` seeds** — the standard convention, and it makes advancement
deterministic rather than a matter of taste.

A round-1 slot with only one fighter is created with `status = "bye"` and its `winner_id` already
set to that fighter. Byes are never "played" and consume no RNG.

Worked example, `n = 5` → `size = 8`, `byes = 3`:

| Slot | A | B | Status |
|---|---|---|---|
| 0 | seed 1 | — | `bye` → seed 1 advances |
| 1 | seed 2 | — | `bye` → seed 2 advances |
| 2 | seed 3 | — | `bye` → seed 3 advances |
| 3 | seed 4 | seed 5 | `ready` |

### E7.2 Advancement

The winner of round `r` slot `s` occupies round `r+1` slot `s // 2`, as fighter **A** when `s` is
even and **B** when `s` is odd. A match becomes `ready` when both its fighters are known, and
`pending` before that.

The tournament is `complete` when the single round-`log2(size)` match resolves; its winner is
`champion_id`.

`n` must be `>= 2`; `n = 1` is rejected (`invalid_roster`). Duplicate ids in a roster are allowed —
a fighter may appear twice as two independent entrants — but the roster is capped at 16.

### E7.3 Per-match seeding

Each tournament match derives its seed deterministically:

```
match_seed = (tournament.seed * 1_000_003 + round * 1_009 + slot) % 2**32
```

So replaying a tournament from the same root seed reproduces every match exactly, and a match's
result does not depend on the order in which matches were played.

## E8. Tournament API

### `POST /api/tournament`
```json
{ "name": "Spring Cup", "roster": ["kaito","vega","kaito","vega"],
  "difficulty": "heuristic", "seed": 99 }
```
Creates the tournament and the **entire** bracket (all rounds, later ones `pending`), applying byes.
Response `201`: the bracket object (E8.1). Errors: `invalid_roster` (fewer than 2, more than 16),
`unknown_fighter`, `unknown_difficulty`, `invalid_seed`.

### `POST /api/tournament/<id>/advance`
Plays the **next** `ready` match to completion, AI vs AI, at the tournament's difficulty and the
derived seed, then propagates the winner. Returns `200` and the updated bracket.

"Next" is defined as **lowest round, then lowest slot** — total order, no ambiguity.

Errors: `tournament_not_found` (404), `tournament_complete` (409), `no_ready_match` (409).

### `GET /api/tournament/<id>`
Returns the bracket. Read-only.

### `GET /api/tournaments`
Lists tournaments (id, name, status, champion, created_at), newest first. This is what makes
persistence visible: restart the server, and the list is still there.

### E8.1 Bracket object

```json
{
  "tournament_id": "3f9a...", "name": "Spring Cup", "difficulty": "heuristic",
  "seed": 99, "size": 8, "status": "in_progress", "champion": null,
  "rounds": [
    { "round": 1, "matches": [
      { "match_id": "a1...", "slot": 0, "status": "bye",
        "fighter_a": {"id":"kaito","name":"Kaito"}, "fighter_b": null,
        "winner": {"id":"kaito","name":"Kaito"}, "turns": null }
    ]}
  ],
  "standings": [
    { "fighter": {"id":"kaito","name":"Kaito"}, "wins": 2, "losses": 0, "eliminated_in": null }
  ]
}
```

`standings` is derived, never stored: wins and losses counted over completed matches, sorted by
wins descending then name. `eliminated_in` is the round a fighter lost in, or `null`.

## E9. Frontend for Part B

A `/tournament` view: create a tournament from the roster with a difficulty, an **Advance** button
that plays the next match, and the bracket rendered by rounds with winners highlighted, byes
marked, and the champion called out when complete. A list of past tournaments demonstrates
persistence across restarts.

Routing may be a simple state toggle rather than a router dependency.

---

## E10. Acceptance criteria

**AI**

- [ ] `difficulty` defaults to `random`; every Step 1 acceptance criterion still passes untouched.
- [ ] `unknown_difficulty` → 400 for any other value.
- [ ] The heuristic finishes when a minimum-damage attack is lethal, rather than poking.
- [ ] The heuristic guards when the foe's maximum-damage Surge Beam would kill it.
- [ ] The heuristic never picks an illegal move, at any state, across 1000 crafted states.
- [ ] Neither policy consumes RNG: `rng.getstate()` is unchanged across a move selection.
- [ ] Same seed + same player actions ⇒ identical logs at **every** difficulty.
- [ ] No fighter ever takes a non-attacking action three turns in a row, under any policy.
- [ ] Over 200 seeded heuristic-vs-heuristic matches, **≥95% end by KO**, not the turn cap.
- [ ] `search` beats `random` in at least 70% of 100 seeded matches.
- [ ] `search` beats `heuristic` in at least 55% of 100 seeded matches — the search must justify
      its cost, or it is not worth having.
- [ ] A `search` move is selected in under 100 ms.

**Tournament**

- [ ] A 4-fighter roster produces 2 first-round matches, 1 final, no byes.
- [ ] A 5-fighter roster produces `size = 8` with 3 byes on the top 3 seeds, and those byes are
      pre-resolved with a winner and never played.
- [ ] A 2-fighter roster produces exactly one match, which is the final.
- [ ] Rosters of size 0, 1 and 17 are rejected with `invalid_roster`.
- [ ] Advancing repeatedly reaches `complete` with a `champion` for roster sizes 2–16.
- [ ] `advance` on a complete tournament → 409 `tournament_complete`.
- [ ] The winner of round `r` slot `s` appears in round `r+1` slot `s // 2`, as A for even `s`
      and B for odd `s`.
- [ ] **Results survive a restart**: create a tournament, advance it, dispose of the session and
      rebuild it against the same file, and the bracket and standings are identical.
- [ ] Two tournaments with the same roster, difficulty and seed produce identical champions,
      logs and turn counts.
- [ ] Match order does not matter: the result of a given bracket position is the same regardless
      of the order matches were advanced in.
- [ ] `standings` counts wins and losses correctly and marks `eliminated_in`.
- [ ] The UI renders a full bracket, marks byes, and names the champion.
- [ ] `./script/test` passes with zero failures; `./script/lint` clean.

## E11. Test plan

**Unit — `backend/tests/test_ai.py`** (crafted states, no HTTP):
- One test per heuristic rule, each on a state where exactly that rule should fire, plus a state
  where its guard condition is *just* unmet so the next rule fires instead.
- Legality fuzz across 1000 generated states at every difficulty.
- `passive_streak` increments, resets on an attack, and forces an attack on the third turn.
- RNG untouched by heuristic and search selection (`rng.getstate()` comparison).

**Unit — `backend/tests/test_search.py`**:
- The evaluation function's sign and magnitude on hand-built positions (winning, losing, equal).
- Terminal states short-circuit to ±1000.
- The chance node produces three children for an attack and one when neither side attacks.
- A one-move-from-lethal position is solved correctly at depth 1.
- Tie-breaking follows canonical action order.
- The 100 ms budget, asserted on a worst-case position (both sides at full ki, all moves legal).

**Strength — `backend/tests/test_ai_strength.py`** (seeded, so results are stable):
- search vs random over 100 seeds, ≥70% wins.
- search vs heuristic over 100 seeds, ≥55% wins.
- heuristic vs heuristic over 200 seeds, ≥95% end by KO.

**DB — `backend/tests/test_tournament.py`** (in-memory or a temp file):
- Bracket construction for `n` in 2..16: size, bye count, bye placement, round count.
- Advancement placement (`s // 2`, A/B by parity).
- Full playthrough to a champion for several roster sizes.
- Persistence: write, dispose the session, reopen against the same file, compare.
- Determinism across two tournaments at the same root seed.
- Order independence: advance a bracket in two different orders, compare results.
- Standings arithmetic including `eliminated_in`.

**API — `backend/tests/test_tournament_api.py`**: every endpoint's happy path, every error code,
and each error asserting the tournament is unchanged.

**Frontend — Vitest**: difficulty selector present and disabled mid-match; bracket renders rounds,
byes and champion; advance button calls the endpoint and re-renders; tournament list renders.
