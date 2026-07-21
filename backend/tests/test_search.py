"""Tests for the expectimax search (extension E3).

This file starts with E3.3's evaluation function: the leaf value the whole
search is an argument about. Every assertion is written against the spec's
constants (100 / 10 / 8 / ±1000) rather than against numbers copied out of a
first run, so a re-tuned weight fails here instead of silently changing how the
AI plays.
"""

import copy
import random

import pytest

from game.rules import new_match
from game.search import (
    HP_WEIGHT,
    KI_SCALE,
    KI_WEIGHT,
    MEAN_SPREAD,
    SPREAD_SAMPLES,
    SPREAD_WEIGHT,
    TEMPO_WEIGHT,
    TERMINAL_VALUE,
    chance_children,
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
