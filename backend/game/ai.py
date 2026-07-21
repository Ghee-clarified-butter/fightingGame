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

from game.moves import ACTION_ORDER, MOVES
from game.rules import compute_damage, legal_actions, resolve_turn, roll_turn_order


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


#: The side each side faces. ``rules`` keeps its own copy of this mapping; policy
#: and arithmetic are separate modules and neither imports the other's privates.
_FOE = {"player": "opponent", "opponent": "player"}

#: The worst roll (§4.1). Rule 1 finishes only when the *minimum* damage kills —
#: a finisher that only lands on a good roll is a gamble, not a finish (E2).
FINISH_SPREAD = 0.90
#: The best roll, used by rule 2 to size the incoming beam at its worst case.
PANIC_SPREAD = 1.10
#: Rule 3's two guards: don't buy a long-term buff below half health, and don't
#: pay for it down to an empty pool (E2).
ASCEND_HP_FRACTION = 0.50
ASCEND_KI = 65
#: Rule 4's floor — above this a beam is affordable *and* leaves something behind.
BEAM_KI = 80
#: Rule 6's floor: below this the AI cannot even afford a Ki Blast, so it charges.
RECOVER_KI = 15

#: Attacks cheapest first, which is the order rule 1 scans for a finisher. It
#: happens to coincide with ``ACTION_ORDER`` today; sorting by cost says why.
_ATTACKS_BY_COST = sorted(
    (action for action in ACTION_ORDER if MOVES[action]["is_attack"]),
    key=lambda action: MOVES[action]["cost"],
)


def _rule_finish(me: dict, foe: dict) -> str | None:
    """Rule 1 — the cheapest attack whose minimum damage takes ``foe`` to 0.

    Cheapest, not strongest: spending 40 ki to win a fight a free Strike also
    wins throws away the ki the *next* tournament turn would have had. Legality
    is not checked here — the caller drops any rule whose move it cannot play,
    so an unaffordable finisher falls through to the next candidate cost.
    """
    for action in _ATTACKS_BY_COST:
        damage = compute_damage(me, foe, MOVES[action]["power"], FINISH_SPREAD)
        if damage >= foe["hp"]:
            return action
    return None


def _rule_panic_guard(me: dict, foe: dict) -> str | None:
    """Rule 2 — Guard when ``foe``'s best-case Surge Beam would be lethal (E2).

    ``compute_damage`` reads ``me["guarding"]``, which is always ``False`` at
    selection time (``resolve_turn`` clears it at the end of every turn), so this
    is the unguarded number the spec asks for. Surviving beats trading — but the
    streak cap still outranks this rule, and the AI may die because of that
    (E2.1).
    """
    beam = MOVES["surge_beam"]
    if foe["ki"] < beam["cost"]:
        return None
    if compute_damage(foe, me, beam["power"], PANIC_SPREAD) >= me["hp"]:
        return "guard"
    return None


def _rule_ascend(me: dict, foe: dict) -> str | None:
    """Rule 3 — Ascend while healthy enough to spend the buff and rich enough to pay."""
    if me["hp"] / me["hp_max"] >= ASCEND_HP_FRACTION and me["ki"] >= ASCEND_KI:
        return "ascend"
    return None


def _rule_beam(me: dict, foe: dict) -> str | None:
    """Rule 4 — Surge Beam once the pool can afford it without emptying."""
    return "surge_beam" if me["ki"] >= BEAM_KI else None


def _rule_poke(me: dict, foe: dict) -> str | None:
    """Rule 5 — Ki Blast whenever it is affordable."""
    return "ki_blast"


def _rule_recover(me: dict, foe: dict) -> str | None:
    """Rule 6 — Charge when there is not even a Ki Blast left in the tank."""
    return "charge" if me["ki"] < RECOVER_KI else None


def _rule_fallback(me: dict, foe: dict) -> str | None:
    """Rule 7 — Strike, which costs 0 ki and is therefore always available."""
    return "strike"


#: E2's priority list, in order. The first rule returning a move the AI may
#: actually play selects it; every other rule is skipped, including on grounds of
#: legality. Keeping it a list rather than a chain of ``if``s is what lets the
#: tests name a rule by index and what makes the "first match wins" reading
#: literal rather than a property of how the branches happen to nest.
_HEURISTIC_RULES = (
    _rule_finish,
    _rule_panic_guard,
    _rule_ascend,
    _rule_beam,
    _rule_poke,
    _rule_recover,
    _rule_fallback,
)


def _choose_heuristic(state: dict, side: str, rng=None) -> str:
    """Deterministic rule-based selection (E2).

    ``rng`` is accepted to match the policy signature and is never touched: this
    is a pure function of the state, which is what makes a heuristic match
    reproducible without a seed at all.

    Candidacy is checked once, against the cap-filtered legal moves, so a rule is
    skipped both when its move is illegal (§5.4) and when E2.1 has forbidden it
    this turn. That is why the cap "outranks every rule above it" needs no
    special case: on a third consecutive passive turn the panic guard simply is
    not a candidate, and the scan falls through to an attack.

    The scan always terminates: rule 7 returns Strike, which costs 0 ki and is an
    attack, so it survives both filters unconditionally.
    """
    me = state[side]
    foe = state[_FOE[side]]
    candidates = attacking_candidates(me, legal_actions(me))
    for rule in _HEURISTIC_RULES:
        action = rule(me, foe)
        if action is not None and action in candidates:
            return action
    raise AssertionError(f"no candidate for {side}: {candidates}")  # pragma: no cover


#: difficulty -> policy. ``choose_action`` dispatches through this rather than a
#: chain of ``if``s so adding a policy cannot forget to register it, and so
#: :data:`DIFFICULTIES` can never drift from what is actually implemented.
_POLICIES = {
    "random": _choose_random,
    "heuristic": _choose_heuristic,
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
