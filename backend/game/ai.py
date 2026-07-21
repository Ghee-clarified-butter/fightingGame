"""AI move selection (extension E1, E2.1, B1).

Every AI policy lives here and nowhere else. ``rules.py`` keeps the game's
arithmetic — what a move costs, what it does, who swings first — and knows
nothing about who is choosing; this module keeps the policy and knows nothing
about HTTP. That split is what lets E2.1's stalemate cap be stated once: there
is exactly one code path that picks an AI move, so no policy can slip past it.

``choose_opponent_action`` and ``play_turn`` used to live in ``rules.py``; they
were moved here rather than copied (B1). Leaving a second, uncapped chooser
behind would mean the fuzz suite exercised a path the server never takes.

Nothing here imports anything that imports this module, so there is no cycle:
``ai`` → ``rules`` → ``fighters``/``moves``, one direction only.
"""

from game.moves import MOVES
from game.rules import legal_actions, resolve_turn, roll_turn_order


class UnknownDifficultyError(ValueError):
    """Raised when a difficulty outside :data:`DIFFICULTIES` is selected (E4).

    The value is carried in ``args[0]`` so the HTTP layer can quote it back in
    the §5.4 envelope without re-deriving it.
    """


#: The most consecutive non-attacking moves a policy may select (E2.1). On the
#: turn after this many, an attack is forced — Strike costs 0 ki, so one always
#: exists.
PASSIVE_CAP = 2


def attacking_candidates(fighter: dict, actions: list[str]) -> list[str]:
    """Return the moves a policy may pick from, applying E2.1's streak cap.

    Below the cap this is ``actions`` unchanged — the same list object, so a
    caller can tell the two cases apart if it needs to. At or above the cap the
    non-attacks are filtered out, which is what stops two AIs alternating Charge
    and Guard until the 100-turn cap decides the match for them.

    The cap outranks every rule that would otherwise fire, including the
    heuristic's panic guard: an invariant with an exception is not an invariant
    (E2.1). The AI may die because of this, and that is the stated price.

    ``fighter`` is the *chooser*, not its foe: ``passive_streak`` is per-fighter
    bookkeeping maintained by ``rules.resolve_turn`` (B4). This never touches
    ``legal_actions``, so the human player is unconstrained (E2.1).
    """
    if fighter["passive_streak"] < PASSIVE_CAP:
        return actions
    attacks = [action for action in actions if MOVES[action]["is_attack"]]
    # Strike is always legal (0 ki, no precondition), so ``attacks`` is only
    # ever empty if the caller passed a list that excluded it. Falling back to
    # the unfiltered list keeps this a filter, never a source of illegal moves.
    return attacks or actions


def _choose_random(state: dict, side: dict, rng) -> str:
    """Uniform over the legal moves left after the cap (§4.7, E2.1).

    Exactly one ``rng.choice`` call, in the same position in the draw order as
    Step 1's ``choose_opponent_action``, whether or not the cap shortened the
    list (B2). The list is ``ACTION_ORDER``-ordered because ``legal_actions``
    returns a list, never a set — a set would iterate differently between runs
    and the same seed would stop reproducing the same match (§4.8, A4).

    Shortening the list does change *which* move a given seed picks, since
    ``rng.choice`` scales its draw to the list length. That is E2.1 binding the
    random policy as the spec says it must (B3), not a determinism break: the
    same seed still replays the same match.
    """
    fighter = state[side]
    return rng.choice(attacking_candidates(fighter, legal_actions(fighter)))


#: difficulty -> policy. ``choose_action`` dispatches through this rather than a
#: chain of ``if``s so adding a policy cannot forget to register it, and so
#: :data:`DIFFICULTIES` can never drift from what is actually implemented.
_POLICIES = {
    "random": _choose_random,
}

#: The difficulty values the API accepts (E1), in the spec's order.
DIFFICULTIES = tuple(_POLICIES)


def choose_action(state: dict, side: str, difficulty: str, rng=None) -> str:
    """Return ``side``'s move under ``difficulty`` (E1).

    ``side`` is ``"player"`` or ``"opponent"``: the tournament runs AI against AI
    (E8), so the AI is not always the opponent.

    ``rng`` is optional because only the ``random`` policy draws — the heuristic
    and the search are pure functions of the state (E3.4), and handing them a
    generator they must promise not to touch invites exactly the bug that
    promise exists to prevent.

    Raises :class:`UnknownDifficultyError` for any other value, so an unvalidated
    difficulty fails loudly here rather than silently defaulting to a policy the
    caller did not ask for.
    """
    policy = _POLICIES.get(difficulty)
    if policy is None:
        raise UnknownDifficultyError(difficulty)
    return policy(state, side, rng)


def play_turn(state: dict, player_action: str, rng) -> tuple[dict, list[dict]]:
    """Play one full turn from the player's action alone (§4.4, §4.8, B2).

    Composes the rule entry points in the exact order §4.8 fixes, as revised by
    E3.4: the tie coin flip (#1), the opponent's choice (#2, *only* a draw when
    the match's difficulty is ``random``), then the attack spreads (#3, #4)
    inside ``resolve_turn``. The rolled order is handed to ``resolve_turn`` so it
    does not roll a second one, which would consume draw #1 twice.

    The policy comes from ``state["difficulty"]`` (B5), so a match plays out
    under the difficulty it was created with and no caller has to remember it.

    ``player_action`` is assumed already validated (§5.4); this is the app
    layer's single call per turn request.
    """
    order = roll_turn_order(state, rng)
    opponent_action = choose_action(state, "opponent", state["difficulty"], rng)
    return resolve_turn(state, player_action, opponent_action, rng, order=order)
