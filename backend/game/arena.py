"""Headless AI-vs-AI match runner (extension E7, B12).

The tournament needs to play a whole match with no human in it and no HTTP
around it. That is all this module does: it drives both sides through
``ai.choose_action`` and hands the pair to ``rules.resolve_turn`` until §4.6 says
the match is over.

It knows nothing about SQLAlchemy, brackets or seeds-as-bracket-positions (B12);
it takes an integer seed and returns a plain dict, so it is unit-testable without
a database and reusable by anything that wants a match played out.

Sides are named ``"a"`` and ``"b"`` rather than ``"player"``/``"opponent"``
because neither is a player here. Side A *is* the rules state's ``player`` and
side B its ``opponent`` — the mapping is fixed, not rolled, so a matchup replays
identically and A/B carry the bracket's meaning rather than the rules'.

A draw is reported as a draw. ``run_ai_match`` never picks a winner for an
undecided match: replaying it is the tournament layer's job (E7.4, B10), and a
runner that invented a winner would make the drawn attempt unrecordable.
"""

import random

from game import ai, rules

#: Which rules-state side each arena side plays. Fixed, so the same matchup at
#: the same seed always reproduces — swapping A and B would change the turn
#: order tie-break and therefore the match.
SIDE_OF = {"a": "player", "b": "opponent"}

#: The arena side that won, keyed by the §4.6 status that says so. ``draw`` and
#: ``in_progress`` are deliberately absent: ``.get`` returns ``None`` for them.
_WINNER_OF_STATUS = {
    rules.STATUS_PLAYER_WON: "a",
    rules.STATUS_OPPONENT_WON: "b",
}


def run_ai_match(a_id: str, b_id: str, difficulty: str, seed: int) -> dict:
    """Play a full AI-vs-AI match and return its outcome.

    Returns ``{"winner", "winner_side", "turns", "status", "log"}`` where
    ``winner`` is ``"a"``, ``"b"`` or ``None``, ``winner_side`` is the
    corresponding rules side (``"player"``/``"opponent"``) or ``None``,
    ``status`` is the §4.6 status the match ended on, and ``log`` is the §5.5
    entry list.

    One ``random.Random(seed)`` drives the whole match, and every draw comes off
    it in §4.8's order: the turn-order tie flip, then A's choice, then B's, then
    the attack spreads inside ``resolve_turn``. Only the ``random`` policy draws
    at all (E3.4), so a heuristic or search match consumes the generator for
    order flips and spreads alone — which is still deterministic, and still a
    different sequence per seed.

    Termination is guaranteed twice over: §4.6's 100-turn cap bounds the loop
    regardless of what the policies do, and E2.1's streak cap means neither side
    can spend those 100 turns refusing to attack.

    Raises :class:`ai.UnknownDifficultyError` for an unknown difficulty and
    ``fighters.UnknownFighterError`` for an unknown fighter id — both from the
    layers that own those vocabularies, so the arena adds no validation of its
    own.
    """
    rng = random.Random(seed)
    state = rules.new_match(a_id, b_id, difficulty)

    while state["status"] == rules.STATUS_IN_PROGRESS:
        order = rules.roll_turn_order(state, rng)
        a_action = ai.choose_action(state, "player", difficulty, rng)
        b_action = ai.choose_action(state, "opponent", difficulty, rng)
        state, _ = rules.resolve_turn(state, a_action, b_action, rng, order=order)

    winner = _WINNER_OF_STATUS.get(state["status"])
    return {
        "winner": winner,
        "winner_side": SIDE_OF[winner] if winner else None,
        "turns": state["turn"],
        "status": state["status"],
        "log": state["log"],
    }
