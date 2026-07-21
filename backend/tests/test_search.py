"""Tests for the expectimax search (extension E3).

This file starts with E3.3's evaluation function: the leaf value the whole
search is an argument about. Every assertion is written against the spec's
constants (100 / 10 / 8 / ±1000) rather than against numbers copied out of a
first run, so a re-tuned weight fails here instead of silently changing how the
AI plays.
"""

import copy
import inspect
import random
import time

import pytest

from game import search
from game.ai import DIFFICULTIES, choose_action
from game.moves import ACTION_ORDER, MOVES
from game.rules import new_match
from game.search import (
    DEFAULT_DEPTH,
    HP_WEIGHT,
    KI_SCALE,
    KI_WEIGHT,
    MEAN_SPREAD,
    SPREAD_SAMPLES,
    SPREAD_WEIGHT,
    TEMPO_WEIGHT,
    TERMINAL_VALUE,
    chance_children,
    choose,
    evaluate,
    spread_samples,
)

SIDES = ("player", "opponent")


def _match_with(player: dict | None = None, opponent: dict | None = None) -> dict:
    """A fresh Kaito-vs-Vega match with the given fighter fields overwritten."""
    match = new_match("kaito", "vega")
    match["player"].update(player or {})
    match["opponent"].update(opponent or {})
    return match


# --- The constants are the spec's, not a previous run's ----------------------


def test_the_weights_are_the_spec_constants():
    """E3.3 verbatim: hp 100, ki 10 per 100, tempo 8, terminal ±1000."""
    assert (HP_WEIGHT, KI_WEIGHT, KI_SCALE, TEMPO_WEIGHT) == (100.0, 10.0, 100.0, 8.0)
    assert TERMINAL_VALUE == 1000.0


# --- Terminal short-circuits (E3.3) ------------------------------------------


@pytest.mark.parametrize("side", SIDES)
def test_being_knocked_out_is_minus_the_terminal_value(side):
    state = _match_with(player={"hp": 40}, opponent={"hp": 40})
    state[side]["hp"] = 0
    assert evaluate(state, side) == -TERMINAL_VALUE


@pytest.mark.parametrize("side", SIDES)
def test_knocking_the_foe_out_is_plus_the_terminal_value(side):
    state = _match_with(player={"hp": 40}, opponent={"hp": 40})
    state["player" if side == "opponent" else "opponent"]["hp"] = 0
    assert evaluate(state, side) == TERMINAL_VALUE


def test_a_win_beats_every_material_advantage_a_live_position_can_hold():
    """±1000 must dwarf the terms, or the search would trade a win for tempo."""
    best_material = _match_with(
        player={"hp": 100, "ki": 100, "ascended": True},
        opponent={"hp": 1, "ki": 0, "ascended": False},
    )
    assert evaluate(best_material, "player") < TERMINAL_VALUE
    won = _match_with(player={"hp": 1, "ki": 0}, opponent={"hp": 0, "ki": 100, "ascended": True})
    assert evaluate(won, "player") > evaluate(best_material, "player")


def test_a_loss_is_worse_than_the_worst_live_position():
    worst_material = _match_with(
        player={"hp": 1, "ki": 0, "ascended": False},
        opponent={"hp": 130, "ki": 100, "ascended": True},
    )
    lost = _match_with(player={"hp": 0}, opponent={"hp": 1})
    assert evaluate(lost, "player") < evaluate(worst_material, "player")


def test_a_dead_fighters_ki_and_tempo_earn_it_nothing():
    """The short-circuit runs before the material terms, so both score alike."""
    poor = _match_with(player={"hp": 0, "ki": 0}, opponent={"hp": 50})
    rich = _match_with(player={"hp": 0, "ki": 100, "ascended": True}, opponent={"hp": 50})
    assert evaluate(poor, "player") == evaluate(rich, "player") == -TERMINAL_VALUE


def test_both_sides_down_scores_as_a_loss_for_the_side_asked():
    """Unreachable in play (§4.4 stops at the first KO); pinned so it cannot drift."""
    state = _match_with(player={"hp": 0}, opponent={"hp": 0})
    assert evaluate(state, "player") == -TERMINAL_VALUE
    assert evaluate(state, "opponent") == -TERMINAL_VALUE


# --- Sign and symmetry -------------------------------------------------------


def test_an_exactly_equal_position_is_zero():
    """Same hp fraction, same ki, same tempo — nothing to prefer either way."""
    state = _match_with(player={"hp": 50, "ki": 40}, opponent={"hp": 65, "ki": 40})
    assert evaluate(state, "player") == pytest.approx(0.0)
    assert evaluate(state, "opponent") == pytest.approx(0.0)


def test_the_two_perspectives_are_exact_negations():
    state = _match_with(
        player={"hp": 80, "ki": 55, "ascended": True},
        opponent={"hp": 40, "ki": 90, "ascended": False},
    )
    assert evaluate(state, "player") == pytest.approx(-evaluate(state, "opponent"))


def test_a_winning_position_scores_positive_and_a_losing_one_negative():
    winning = _match_with(player={"hp": 90, "ki": 60}, opponent={"hp": 20, "ki": 60})
    losing = _match_with(player={"hp": 20, "ki": 60}, opponent={"hp": 120, "ki": 60})
    assert evaluate(winning, "player") > 0
    assert evaluate(losing, "player") < 0


# --- The individual terms ----------------------------------------------------


def test_hp_is_compared_as_a_fraction_of_each_pool():
    """Kaito 50/100 and Vega 65/130 are both at half, so hp contributes nothing."""
    level = _match_with(player={"hp": 50}, opponent={"hp": 65})
    assert evaluate(level, "player") == pytest.approx(0.0)
    # Equal *absolute* hp is not level: 50/100 beats 50/130.
    absolute = _match_with(player={"hp": 50}, opponent={"hp": 50})
    assert evaluate(absolute, "player") > 0


def test_a_full_health_bar_of_advantage_is_worth_the_hp_weight():
    level = _match_with(player={"hp": 100}, opponent={"hp": 130})
    assert evaluate(level, "player") == pytest.approx(0.0)
    ahead = _match_with(player={"hp": 100}, opponent={"hp": 65})
    assert evaluate(ahead, "player") == pytest.approx(HP_WEIGHT * 0.5)


def test_a_full_pool_of_ki_advantage_is_worth_ten_points():
    state = _match_with(player={"hp": 50, "ki": 100}, opponent={"hp": 65, "ki": 0})
    assert evaluate(state, "player") == pytest.approx(KI_WEIGHT)


def test_ki_is_worth_about_a_tenth_of_a_health_bar():
    """The whole point of the 10 weight: ki is latent damage, not damage."""
    ki_ahead = _match_with(player={"hp": 50, "ki": 100}, opponent={"hp": 65, "ki": 0})
    # Level on ki, 11 points of hp fraction ahead — that alone outweighs a full pool.
    hp_ahead = _match_with(player={"hp": 61, "ki": 40}, opponent={"hp": 65, "ki": 40})
    assert evaluate(ki_ahead, "player") == pytest.approx(KI_WEIGHT)
    assert evaluate(hp_ahead, "player") > evaluate(ki_ahead, "player")


def test_having_ascended_is_worth_the_tempo_weight():
    state = _match_with(
        player={"hp": 50, "ki": 40, "ascended": True},
        opponent={"hp": 65, "ki": 40, "ascended": False},
    )
    assert evaluate(state, "player") == pytest.approx(TEMPO_WEIGHT)
    both = _match_with(
        player={"hp": 50, "ki": 40, "ascended": True},
        opponent={"hp": 65, "ki": 40, "ascended": True},
    )
    assert evaluate(both, "player") == pytest.approx(0.0)


def test_the_terms_add_rather_than_override_one_another():
    state = _match_with(
        player={"hp": 100, "ki": 90, "ascended": True},
        opponent={"hp": 65, "ki": 40, "ascended": False},
    )
    expected = HP_WEIGHT * (1.0 - 0.5) + KI_WEIGHT * (90 - 40) / KI_SCALE + TEMPO_WEIGHT
    assert evaluate(state, "player") == pytest.approx(expected)


# --- Purity (E3.4) -----------------------------------------------------------


def test_evaluating_consumes_no_rng_and_mutates_nothing():
    rng = random.Random(12345)
    before_rng = rng.getstate()
    state = _match_with(player={"hp": 70, "ki": 55}, opponent={"hp": 90, "ki": 20})
    snapshot = {"player": dict(state["player"]), "opponent": dict(state["opponent"])}
    evaluate(state, "player")
    evaluate(state, "opponent")
    assert rng.getstate() == before_rng
    assert state["player"] == snapshot["player"]
    assert state["opponent"] == snapshot["opponent"]


# --- The chance node (E3.2) --------------------------------------------------


def test_the_samples_are_the_interval_midpoints_not_the_endpoints():
    """The whole point of E3.2: 0.90/1.00/1.10 would put a third of the mass on
    each end of a *uniform* distribution and bias the search toward defence."""
    assert SPREAD_SAMPLES == (0.9333, 1.0, 1.0667)
    assert SPREAD_SAMPLES != (0.90, 1.00, 1.10)
    # Midpoints of the three equal-probability thirds of [0.90, 1.10] (§4.1).
    step = (1.10 - 0.90) / 3
    expected = tuple(round(0.90 + step * (i + 0.5), 4) for i in range(3))
    assert SPREAD_SAMPLES == expected
    assert MEAN_SPREAD == 1.0


def test_the_weights_are_a_third_each_and_sum_to_one():
    assert SPREAD_WEIGHT == pytest.approx(1 / 3)
    state = _match_with()
    children = chance_children(state, "strike", "strike", root=True)
    weights = [weight for weight, _ in children]
    assert weights == [pytest.approx(1 / 3)] * 3
    assert sum(weights) == pytest.approx(1.0)


@pytest.mark.parametrize(
    "player_action,opponent_action",
    [
        ("strike", "strike"),
        ("strike", "guard"),
        ("charge", "ki_blast"),
        ("ascend", "surge_beam"),
    ],
)
def test_an_attacking_pair_branches_three_ways_at_the_root(player_action, opponent_action):
    state = _match_with(player={"ki": 100}, opponent={"ki": 100})
    assert spread_samples(player_action, opponent_action, root=True) == SPREAD_SAMPLES
    assert len(chance_children(state, player_action, opponent_action, root=True)) == 3


@pytest.mark.parametrize(
    "player_action,opponent_action",
    [
        ("charge", "guard"),
        ("guard", "guard"),
        ("ascend", "charge"),
    ],
)
def test_a_turn_with_no_attack_in_it_has_exactly_one_child(player_action, opponent_action):
    """No spread is drawn, so three children would be three identical states."""
    state = _match_with(player={"ki": 100}, opponent={"ki": 100})
    assert spread_samples(player_action, opponent_action, root=True) == (MEAN_SPREAD,)
    children = chance_children(state, player_action, opponent_action, root=True)
    assert len(children) == 1
    assert children[0][0] == pytest.approx(1.0)


def test_below_the_root_ply_only_the_mean_sample_is_taken():
    """E3.2 restricts three-way branching to the root; deeper plies cost 1×."""
    state = _match_with(player={"ki": 100}, opponent={"ki": 100})
    assert spread_samples("surge_beam", "strike", root=False) == (MEAN_SPREAD,)
    children = chance_children(state, "surge_beam", "strike", root=False)
    assert len(children) == 1
    assert children[0][0] == pytest.approx(1.0)
    # And it is the *mean* child, identical to the middle root branch.
    root_children = chance_children(state, "surge_beam", "strike", root=True)
    assert children[0][1] == root_children[1][1]


def test_the_three_children_differ_only_by_the_spread():
    """Low, mean and high rolls must actually produce different damage, or the
    chance node would be averaging three copies of one number."""
    state = _match_with(player={"ki": 100}, opponent={"ki": 100})
    children = chance_children(state, "surge_beam", "surge_beam", root=True)
    hps = [child["opponent"]["hp"] for _, child in children]
    assert hps[0] > hps[1] > hps[2]


def test_expanding_consumes_no_rng_and_mutates_nothing():
    """E3.4: no generator is even passed in, so there is none to advance."""
    rng = random.Random(999)
    before_rng = rng.getstate()
    state = _match_with(player={"ki": 100}, opponent={"ki": 100})
    snapshot = copy.deepcopy(state)
    for root in (True, False):
        chance_children(state, "surge_beam", "ki_blast", root=root)
    assert rng.getstate() == before_rng
    assert state == snapshot


def test_the_children_are_resolved_states_a_turn_further_on():
    state = _match_with(player={"ki": 100}, opponent={"ki": 100})
    for _, child in chance_children(state, "strike", "charge", root=True):
        assert child["turn"] == state["turn"] + 1
        assert len(child["log"]) == 2


# --- Selection (E3.1) --------------------------------------------------------


def _worst_case_position() -> dict:
    """Both sides at full hp and full ki, so all six moves are legal for both.

    This is E3.5's worst case: nothing is filtered by legality at the root and no
    line can terminate within two turns (the largest single-turn hit available is
    Vega's ascended Surge Beam at 43, against a 100 hp bar), so the tree is the
    full-width one the cost bound is derived from.
    """
    return _match_with(player={"ki": 100}, opponent={"ki": 100})


def test_a_one_move_from_lethal_position_is_solved_at_depth_one():
    """Only Surge Beam kills through a Guard, so only Surge Beam is worth +1000.

    Kaito is on 15 hp. Vega's guarded damage is 4 / 8 / 15 for Strike / Ki Blast /
    Surge Beam at the lowest sample, so a MIN player answers anything cheaper by
    guarding and survives. Kaito also swings first (spd 14 vs 9) and cannot kill
    Vega from 130 hp in one turn, so the beam is a clean win rather than a trade.
    """
    state = _match_with(player={"hp": 15}, opponent={"ki": 100})
    assert choose(state, "opponent", depth=1) == "surge_beam"


def test_the_search_prefers_the_move_that_wins_over_the_move_that_hits_hardest():
    """Kaito can finish with a free Strike, so spending 40 ki on a beam is waste."""
    state = _match_with(player={"ki": 100}, opponent={"hp": 4, "ki": 0})
    assert choose(state, "player", depth=1) == "strike"


def test_equal_valued_actions_break_to_the_earliest_canonical_action(monkeypatch):
    """E3.4: ties are broken by ``ACTION_ORDER``, never by a draw.

    ``evaluate`` is flattened to a constant so that *every* line is worth exactly
    the same — the only thing left to decide the move is the tie-break rule.
    """
    monkeypatch.setattr(search, "evaluate", lambda state, side: 0.0)
    state = _worst_case_position()
    assert choose(state, "opponent") == ACTION_ORDER[0] == "strike"


def test_the_tie_break_ignores_the_order_the_candidates_arrive_in(monkeypatch):
    """Canonical means canonical: a shuffled candidate list picks the same move."""
    monkeypatch.setattr(search, "evaluate", lambda state, side: 0.0)
    state = _worst_case_position()
    assert choose(state, "opponent", candidates=["guard", "ascend", "charge"]) == "charge"
    assert choose(state, "opponent", candidates=["ascend", "guard", "charge"]) == "charge"
    assert choose(state, "opponent", candidates=["ascend", "surge_beam"]) == "surge_beam"


def test_a_naturally_tied_position_also_breaks_canonically():
    """Every move wins from a position already won, so all six are worth +1000."""
    state = _match_with(player={"hp": 0}, opponent={"ki": 100})
    assert choose(state, "opponent", depth=1) == "strike"


def test_candidates_restrict_the_root_and_are_never_widened():
    """Whatever the search would rather play, it may only answer with what it was
    offered — which is what makes E2.1's cap enforceable from ``game.ai``."""
    state = _worst_case_position()
    for offered in (["charge"], ["guard", "ascend"], ["ki_blast", "charge"]):
        assert choose(state, "opponent", candidates=offered) in offered


def test_the_default_depth_is_two_full_turns():
    assert DEFAULT_DEPTH == 2
    state = _worst_case_position()
    assert choose(state, "opponent") == choose(state, "opponent", depth=DEFAULT_DEPTH)


@pytest.mark.parametrize("side", SIDES)
def test_a_selection_is_deterministic_and_mutates_nothing(side):
    state = _worst_case_position()
    snapshot = copy.deepcopy(state)
    first = choose(state, side)
    assert choose(state, side) == first
    assert state == snapshot


# --- Purity of the selection (E3.4) ------------------------------------------


def test_the_search_takes_no_generator_at_all():
    """Structural, not a promise: there is no parameter to hand the match RNG to."""
    parameters = inspect.signature(choose).parameters
    assert "rng" not in parameters
    assert list(parameters) == ["state", "side", "depth", "candidates"]


def test_selecting_at_the_search_difficulty_consumes_no_rng():
    """E3.4: draw #2 happens only for ``random``, so the probe must not advance."""
    state = _worst_case_position()
    probe = random.Random(4242)
    before = probe.getstate()
    assert choose_action(state, "opponent", "search", probe) == choose(state, "opponent")
    assert probe.getstate() == before


# --- The cap is applied at the root, by game.ai (E2.1, E3) -------------------


def _guard_preferring_position(streak: int = 0) -> dict:
    """A position the search answers with Guard when it is free to choose.

    Kaito is at full hp with a full ki pool, so a Surge Beam is coming; Vega is at
    30 of 130 and survives it behind a Guard. Exactly the shape E2.1 calls out —
    "guard when about to die" is the condition that can recur forever.
    """
    return _match_with(
        player={"hp": 100, "ki": 100},
        opponent={"hp": 30, "ki": 100, "passive_streak": streak},
    )


def test_the_search_alone_would_guard_here():
    assert choose(_guard_preferring_position(), "opponent") == "guard"


def test_the_root_cap_forces_an_attack_after_two_passive_turns():
    """E2.1 outranks the search exactly as it outranks the heuristic's rule 2."""
    action = choose_action(_guard_preferring_position(streak=2), "opponent", "search")
    assert MOVES[action]["is_attack"]
    assert choose_action(_guard_preferring_position(streak=0), "opponent", "search") == "guard"


def test_two_consecutive_passive_turns_are_still_allowed():
    assert choose_action(_guard_preferring_position(streak=1), "opponent", "search") == "guard"


def test_the_search_itself_never_reads_the_streak():
    """The cap lives in ``game.ai``; E3 enforces it at the root only, so the tree
    must be blind to ``passive_streak`` — otherwise a line would be pruned inside
    the search for a rule that binds one single move."""
    for streak in (0, 2, 5):
        assert choose(_guard_preferring_position(streak), "opponent") == "guard"


def test_search_is_a_registered_difficulty_in_the_specs_order():
    assert DIFFICULTIES == ("random", "heuristic", "search")


# --- The cost bound (E3.5, B7) -----------------------------------------------


def _count_children(state: dict, side: str, monkeypatch) -> dict[bool, int]:
    """Run one selection with ``chance_children`` instrumented per ply."""
    counts = {True: 0, False: 0}
    original = search.chance_children

    def counting(state, player_action, opponent_action, *, root):
        children = original(state, player_action, opponent_action, root=root)
        counts[root] += len(children)
        return children

    monkeypatch.setattr(search, "chance_children", counting)
    choose(state, side)
    # Restored so a second call in the same test wraps the real function rather
    # than the first counter, which would credit its children to both tallies.
    monkeypatch.setattr(search, "chance_children", original)
    return counts


#: The exact tree of a full-hp/full-ki depth-2 selection.
#:
#: Root: 36 action pairs; 27 contain an attack and branch three ways on the
#: spread, 9 are attack-free and yield one child (E3.2) — 27*3 + 9 = **90**.
#:
#: Second ply: 36 pairs per child, mean sample only, **except** that Ascend is
#: spent at the root. A child in which one side ascended offers that side 5 moves,
#: not 6. Summing over the root pairs: 2412 leaves from the 25 ascend-free pairs,
#: 330 + 330 from the two single-ascend groups, 25 from the double-ascend pair —
#: **3097**. B7's 90 * 36 = 3240 ignores the spent Ascend and over-counts by 143;
#: it stands as an upper bound, as does E3.5's own 3,888.
ROOT_CHILDREN = 90
LEAVES = 3097
E3_5_ROOT_CEILING = 108
E3_5_LEAF_CEILING = 3888


def test_the_worst_case_tree_is_exactly_ninety_root_children_and_3097_leaves(monkeypatch):
    counts = _count_children(_worst_case_position(), "opponent", monkeypatch)
    assert counts[True] == ROOT_CHILDREN
    assert counts[False] == LEAVES


def test_the_tree_stays_inside_the_cost_bound(monkeypatch):
    """E3.5's table is an upper bound: three-way at the root, one-way deeper."""
    counts = _count_children(_worst_case_position(), "player", monkeypatch)
    assert counts[True] <= E3_5_ROOT_CEILING
    assert counts[False] <= E3_5_LEAF_CEILING
    # Had every ply branched three ways the leaf count would be 3x this and the
    # 150 ms budget would be unmeetable, which is why E3.2 restricts it.
    assert counts[False] * 3 > E3_5_LEAF_CEILING


def test_legal_move_filtering_shrinks_the_tree(monkeypatch):
    """E3.5: "legal-move filtering usually cuts 6 to 4-5". An empty pool leaves
    Strike, Charge and Guard, so the tree collapses by well over half."""
    poor = _match_with(player={"ki": 0}, opponent={"ki": 0})
    counts = _count_children(poor, "opponent", monkeypatch)
    assert counts[True] < ROOT_CHILDREN
    assert counts[False] < LEAVES


def test_a_decided_line_is_not_expanded_any_further(monkeypatch):
    """A KO ends the line: expanding past it would let a dead fighter swing back
    and dilute the ±1000 the whole evaluation rests on."""
    lethal = _match_with(player={"hp": 1, "ki": 0}, opponent={"ki": 100})
    counts = _count_children(lethal, "opponent", monkeypatch)
    full = _count_children(_worst_case_position(), "opponent", monkeypatch)
    assert counts[False] < full[False]


#: E3.5 / B8's budget for one ``search`` move selection, in milliseconds. E11
#: says 100 ms; E3.5 is the derivation and E10 is the acceptance criterion, so
#: 150 wins (B8).
BUDGET_MS = 150.0

#: Timed repeats after the warm-up call. The fastest is the one asserted on: a
#: slower sample only ever means the machine was doing something else at the
#: time, so taking the minimum measures the search rather than the scheduler.
#: Five is enough to shake off a stray GC pause without making the suite slow.
TIMED_REPEATS = 5


def _fastest_selection_ms(state: dict, side: str, depth: int = DEFAULT_DEPTH) -> float:
    """Milliseconds for the quickest of :data:`TIMED_REPEATS` warm selections."""
    choose(state, side, depth)  # Warm: import, bytecode and caches are not the subject.
    best = float("inf")
    for _ in range(TIMED_REPEATS):
        started = time.perf_counter()
        choose(state, side, depth)
        best = min(best, (time.perf_counter() - started) * 1000.0)
    return best


def test_a_worst_case_selection_fits_in_the_time_budget():
    """E3.5: under 150 ms on both sides at full ki, with all six moves legal.

    Measured at 90-99 ms per selection on the reference machine (CPython 3.13.5,
    Windows 11), so depth 2 meets the budget with roughly a third of it to spare
    and **no B9 mitigation is applied**: no memoization, no alpha-beta, and the
    depth stays at :data:`DEFAULT_DEPTH` rather than dropping to 1.

    The margin is real but not vast, which is the point of asserting it here: a
    change that widens the tree — chance branching below the root, a third ply,
    a costlier ``evaluate`` — trips this test rather than showing up later as a
    laggy turn endpoint.
    """
    elapsed = _fastest_selection_ms(_worst_case_position(), "opponent")
    assert elapsed < BUDGET_MS, f"worst-case selection took {elapsed:.1f} ms"


def test_both_sides_are_inside_the_budget():
    """The search plays either side (AI vs AI in E8), and Vega's bigger hp pool
    and cheaper beam are not the reason the tree is the size it is — so the
    player side has to hold the same budget, not merely the opponent side the
    single-match endpoint uses."""
    elapsed = _fastest_selection_ms(_worst_case_position(), "player")
    assert elapsed < BUDGET_MS, f"player-side selection took {elapsed:.1f} ms"


def test_the_budget_is_met_through_the_difficulty_dispatch_too():
    """What the server actually calls is ``ai.choose_action``, not ``choose``.

    The cap check and the legal-move filter it adds are O(6), so this is the same
    measurement plus a rounding error — asserted anyway, because the budget is a
    claim about picking a move in a real match, not about a function in isolation.
    """
    state = _worst_case_position()
    rng = random.Random(7)
    choose_action(state, "opponent", "search", rng)
    best = float("inf")
    for _ in range(TIMED_REPEATS):
        started = time.perf_counter()
        choose_action(state, "opponent", "search", rng)
        best = min(best, (time.perf_counter() - started) * 1000.0)
    assert best < BUDGET_MS, f"dispatched selection took {best:.1f} ms"
