"""Pure game rules (spec §4, §6).

No Flask, no globals, no I/O — every function here takes state in and hands
state back, so the whole rule set is unit-testable without HTTP.

A match state is a plain dict so serialization is a no-op:

    {"status": ..., "turn": 0, "player": {...}, "opponent": {...}, "log": []}

``match_id`` is deliberately absent: it belongs to the HTTP store, not to the
rules. The app layer adds it when serializing (§5.5).
"""

from game.fighters import new_fighter
from game.moves import ACTION_ORDER, MOVES

STATUS_IN_PROGRESS = "in_progress"


def new_match(player_id: str, opponent_id: str) -> dict:
    """Return a fresh match state (§4.4, §5.5).

    Creation consumes no RNG draws — §4.8 allows a draw only when the step that
    needs it actually occurs — so no ``rng`` argument is taken.

    Raises ``UnknownFighterError`` for an unknown fighter id.
    """
    return {
        "status": STATUS_IN_PROGRESS,
        "turn": 0,
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
