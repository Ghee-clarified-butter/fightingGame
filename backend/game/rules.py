"""Pure game rules (spec §4, §6).

No Flask, no globals, no I/O — every function here takes state in and hands
state back, so the whole rule set is unit-testable without HTTP.

A match state is a plain dict so serialization is a no-op:

    {"status": ..., "turn": 0, "player": {...}, "opponent": {...}, "log": []}

``match_id`` is deliberately absent: it belongs to the HTTP store, not to the
rules. The app layer adds it when serializing (§5.5).

This module holds no *policy*: who picks which move, and how, lives entirely in
``game.ai`` (extension B1). Nothing here imports it, so the dependency runs one
way — ``ai`` → ``rules`` — and the streak cap has exactly one code path to guard.
"""

import copy

from game.fighters import new_fighter
from game.moves import ACTION_ORDER, MOVES

STATUS_IN_PROGRESS = "in_progress"
STATUS_PLAYER_WON = "player_won"
STATUS_OPPONENT_WON = "opponent_won"
STATUS_DRAW = "draw"

TURN_CAP = 100

CHARGE_KI = 25
CHARGE_KI_ASCENDED = 30
GUARD_KI = 8


def new_match(player_id: str, opponent_id: str, difficulty: str = "random") -> dict:
    """Return a fresh match state (§4.4, §5.5).

    Creation consumes no RNG draws — §4.8 allows a draw only when the step that
    needs it actually occurs — so no ``rng`` argument is taken.

    ``difficulty`` (extension E1, B5) is stored at the top level of the state so
    serialization stays a no-op and every later turn can read the policy the
    match was created with. It is **not** validated here: the set of accepted
    values is an HTTP concern (§6, no rules in the routes and no routing in the
    rules), so the app layer rejects an unknown one before it ever gets this far.

    Raises ``UnknownFighterError`` for an unknown fighter id.
    """
    return {
        "status": STATUS_IN_PROGRESS,
        "turn": 0,
        "difficulty": difficulty,
        "player": new_fighter(player_id),
        "opponent": new_fighter(opponent_id),
        "log": [],
    }


def legal_actions(fighter: dict) -> list[str]:
    """Return the actions ``fighter`` may take right now, in ``ACTION_ORDER``.

    A move is legal when the fighter can pay its ki cost (§3, §4.2), so Strike,
    Charge and Guard are always available — including at 0 ki (§4.3). Ascend
    carries the extra once-per-match precondition (§3).

    The result is a list, never a set: the opponent's uniform choice draws from
    it, and a set's iteration order would break seeded reproducibility (§4.8).
    """
    actions = []
    for action in ACTION_ORDER:
        move = MOVES[action]
        if fighter["ki"] < move["cost"]:
            continue
        if action == "ascend" and fighter["ascend_used"]:
            continue
        actions.append(action)
    return actions


def compute_damage(attacker: dict, defender: dict, power: int, spread: float) -> int:
    """Return the damage ``attacker`` deals to ``defender`` (§4.1).

    ``spread`` is passed in rather than drawn here so the formula stays a pure
    function of its arguments: the RNG belongs to the caller, which owns the
    §4.8 draw order.

    ``atk / (atk + def)`` is a ratio, never a subtraction, so it cannot go
    negative; the ``max(1, ...)`` floor then guarantees no matchup stalls at
    zero. Rounding is Python's built-in ``round`` — half-to-even — exactly as
    the spec writes it.
    """
    base = power * (attacker["atk"] / (attacker["atk"] + defender["def"]))
    ascend_mul = 1.25 if attacker["ascended"] else 1.0
    guard_mul = 0.5 if defender["guarding"] else 1.0
    return max(1, round(base * ascend_mul * spread * guard_mul))


def effective_spd(fighter: dict) -> int:
    """Return ``fighter``'s speed for turn-order purposes (§3, §4.4).

    Ascend's permanent +5 counts as soon as the buff is on the fighter.
    """
    return fighter["spd"] + (5 if fighter["ascended"] else 0)


def roll_turn_order(state: dict, rng) -> tuple[str, str]:
    """Return the two sides in resolution order, fastest first (§4.4).

    Speeds are read **entering** the turn, before any of this turn's actions
    resolve: the tie flip is draw #1 in §4.8's order, and the opponent's move —
    which is what could add an Ascend +5 — is only drawn at #2. So a fighter
    that ascends on turn *n* gets its speed edge from turn *n+1* onwards.

    A draw is consumed only when the speeds actually tie (§4.8, no dummy
    draws); the tie is settled by ``rng.random() < 0.5`` → player first.
    """
    player_spd = effective_spd(state["player"])
    opponent_spd = effective_spd(state["opponent"])
    if player_spd > opponent_spd:
        return ("player", "opponent")
    if opponent_spd > player_spd:
        return ("opponent", "player")
    return ("player", "opponent") if rng.random() < 0.5 else ("opponent", "player")


def deterministic_order(state: dict) -> tuple[str, str]:
    """Return the resolution order without ever flipping a coin (extension B6).

    Identical to ``roll_turn_order`` except that a tie resolves to
    ``("player", "opponent")`` instead of drawing. The expectimax search needs an
    order for positions it explores on copies of the state, and E3.4 forbids it
    from touching the live match RNG — so it needs a tie-break that costs no
    draw. This is deliberately *not* what the live match uses: §4.4's flip stays
    random, and only the search calls this.
    """
    player_spd = effective_spd(state["player"])
    opponent_spd = effective_spd(state["opponent"])
    if opponent_spd > player_spd:
        return ("opponent", "player")
    return ("player", "opponent")


def _restore_ki(fighter: dict, amount: int) -> int:
    """Add ``amount`` ki to ``fighter``, clamped at ``ki_max`` (§4.2).

    Returns the ki actually gained, which is less than ``amount`` at the cap —
    the log quotes this number rather than the nominal one, so a Charge into a
    nearly full bar does not claim ki it never restored (§4.2).
    """
    before = fighter["ki"]
    fighter["ki"] = min(fighter["ki_max"], before + amount)
    return fighter["ki"] - before


def _apply_ascend(fighter: dict) -> None:
    """Pay for and latch Ascend (§3, §4.4 step 2).

    ``ascend_used`` is separate from ``ascended`` because the buff is permanent
    but the *permission* is once per match: nothing ever clears either flag, and
    ``legal_actions`` reads ``ascend_used`` to reject a second attempt.
    """
    fighter["ki"] -= MOVES["ascend"]["cost"]
    fighter["ascended"] = True
    fighter["ascend_used"] = True


def _apply_support(fighter: dict, action: str) -> int:
    """Apply Charge or Guard and return the ki gained (§3, §4.4 step 3)."""
    if action == "charge":
        amount = CHARGE_KI_ASCENDED if fighter["ascended"] else CHARGE_KI
        return _restore_ki(fighter, amount)
    if action == "guard":
        gained = _restore_ki(fighter, GUARD_KI)
        fighter["guarding"] = True
        return gained
    return 0


SPREAD_MIN = 0.90
SPREAD_MAX = 1.10

_OTHER_SIDE = {"player": "opponent", "opponent": "player"}


def _apply_attack(
    attacker: dict, defender: dict, action: str, rng, spread: float | None = None
) -> int:
    """Resolve one attack and return the damage dealt (§4.1, §4.2, §4.4 step 4).

    The ki cost is paid first, before damage is computed (§4.2). The spread is
    drawn here rather than by ``compute_damage`` so the draw happens exactly
    once per attack that actually resolves — §4.8 forbids dummy draws.

    When ``spread`` is supplied it is used as-is and **no** draw happens, so a
    caller exploring hypothetical turns never advances the live match RNG
    (E3.4, B6). ``rng`` is not touched at all on that path and may be ``None``.
    """
    move = MOVES[action]
    attacker["ki"] -= move["cost"]
    if spread is None:
        spread = rng.uniform(SPREAD_MIN, SPREAD_MAX)
    damage = compute_damage(attacker, defender, move["power"], spread)
    defender["hp"] = max(0, defender["hp"] - damage)
    return damage


_ATTACK_VERBS = {
    "strike": "strikes for",
    "ki_blast": "fires a Ki Blast for",
    "surge_beam": "unleashes a Surge Beam for",
}


def _entry_text(attacker: dict, defender: dict, action: str, damage: int, ki_gained: int) -> str:
    """Render the sentence the client displays verbatim (§5.5).

    The text is built here, once, so no client ever has to reassemble a fighter
    name and a number into a sentence of its own.
    """
    if action in _ATTACK_VERBS:
        return (
            f"{attacker['name']} {_ATTACK_VERBS[action]} {damage}. "
            f"{defender['name']}: {defender['hp']} HP."
        )
    if action == "charge":
        return f"{attacker['name']} charges, recovering {ki_gained} ki."
    if action == "guard":
        return f"{attacker['name']} guards, recovering {ki_gained} ki."
    return f"{attacker['name']} ascends, surging with power."


def _log_entry(
    turn: int,
    actor: str,
    action: str,
    attacker: dict,
    defender: dict,
    damage: int,
    ki_gained: int,
) -> dict:
    """Build one §5.5 log entry.

    ``target_hp`` is always the hp of the *actor's* opponent once this entry has
    resolved (A7) — for a non-attack it is that same value unchanged, since only
    the actor's own attack can move it.
    """
    return {
        "turn": turn,
        "actor": actor,
        "action": action,
        "damage": damage,
        "target_hp": defender["hp"],
        "text": _entry_text(attacker, defender, action, damage, ki_gained),
    }


def check_status(state: dict) -> str:
    """Return the status ``state`` has reached (§4.6).

    A KO takes precedence over the cap: attacks resolve sequentially (§4.4), so
    at most one fighter can be at 0 hp and ``draw`` has exactly one cause — the
    turn cap with both alive.

    The cap comparison is integer cross-multiplication, never ``hp / hp_max``:
    dividing would make the ``draw`` case hinge on binary rounding, so an
    exactly-equal pair would tie or not by luck.
    """
    player = state["player"]
    opponent = state["opponent"]
    if player["hp"] == 0:
        return STATUS_OPPONENT_WON
    if opponent["hp"] == 0:
        return STATUS_PLAYER_WON
    if state["turn"] < TURN_CAP:
        return STATUS_IN_PROGRESS

    player_score = player["hp"] * opponent["hp_max"]
    opponent_score = opponent["hp"] * player["hp_max"]
    if player_score > opponent_score:
        return STATUS_PLAYER_WON
    if opponent_score > player_score:
        return STATUS_OPPONENT_WON
    return STATUS_DRAW


def resolve_turn(
    state: dict,
    player_action: str,
    opponent_action: str,
    rng,
    *,
    order: tuple[str, str] | None = None,
    spread: float | None = None,
) -> tuple[dict, list[dict]]:
    """Resolve one turn and return ``(new_state, entries)`` (§4.4, §6).

    The input state is never mutated: everything happens on a deep copy, so a
    caller that rejects the result still holds its original (§5.4).

    ``order`` is keyword-only and optional. §4.8 puts the tie coin flip *before*
    the opponent's move choice, so the app layer rolls the order first and
    passes it in; when it is ``None`` this rolls one itself, which keeps a
    single-turn unit test to one call.

    ``spread`` is keyword-only too. When it is given, every attack this turn uses
    that fixed value and nothing is drawn — which is how the expectimax search
    enumerates its chance node without ever being handed the live match RNG
    (E3.4, B6). Combined with an explicit ``order`` this makes the whole call
    RNG-free, so ``rng`` may then be ``None``.

    Both actions are assumed already validated (§4.4 step 1); validation is the
    HTTP layer's job (§5.4).
    """
    if order is None:
        order = roll_turn_order(state, rng)

    new_state = copy.deepcopy(state)
    actions = {"player": player_action, "opponent": opponent_action}
    entries: list[dict] = []

    # Steps 2 and 3 run as two passes over both fighters, in the spec's order:
    # every non-attack effect lands before any attack is computed, which is what
    # lets a slower fighter's Guard halve a faster opponent's hit (§4.3).
    for side in order:
        if actions[side] == "ascend":
            _apply_ascend(new_state[side])
    ki_gained = {side: _apply_support(new_state[side], actions[side]) for side in order}

    # Step 6's counter is bumped before the entries are built so each carries the
    # number of the turn it belongs to: the first resolved turn is 1 (§4.4).
    turn = new_state["turn"] + 1
    new_state["turn"] = turn

    # Step 4: attacks in speed order, which is also the order entries are logged
    # in (A7) even though the effects above already resolved. A KO stops
    # resolution outright, so the slower fighter never swings back — which is
    # what makes spd and burst damage worth paying for (§4.4).
    for side in order:
        attacker = new_state[side]
        defender = new_state[_OTHER_SIDE[side]]
        action = actions[side]
        is_attack = MOVES[action]["is_attack"]
        if attacker["hp"] == 0 and is_attack:
            # A8: only the attack is skipped. A fighter KO'd before its turn to
            # swing still logs the Charge/Guard/Ascend it already resolved.
            continue
        damage = _apply_attack(attacker, defender, action, rng, spread) if is_attack else 0
        entries.append(
            _log_entry(turn, side, action, attacker, defender, damage, ki_gained[side])
        )

    # Step 5: Guard lasts exactly one turn (§4.3), so it is cleared on both
    # fighters whether or not it was ever used to halve anything.
    for side in ("player", "opponent"):
        new_state[side]["guarding"] = False

    # Passive-streak bookkeeping (extension E2.1, B4). Tracked for both sides
    # off the *chosen* action, so an attack that was skipped because its owner
    # was already KO'd still resets the count — the fighter is dead and the
    # value is inert. Nothing here constrains the player: only an AI policy
    # reads the streak, and ``legal_actions`` never does.
    for side in ("player", "opponent"):
        fighter = new_state[side]
        if MOVES[actions[side]]["is_attack"]:
            fighter["passive_streak"] = 0
        else:
            fighter["passive_streak"] += 1

    new_state["log"].extend(entries)

    # The rest of step 6: the win condition is checked once the turn is fully
    # resolved, so a KO landed this turn — or the cap being reached by this very
    # increment — is already visible in the state it is read from (§4.6).
    new_state["status"] = check_status(new_state)
    return new_state, entries
