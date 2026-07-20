"""Tests for the pure game rules (spec §4)."""

import copy
import random

import pytest

from game.fighters import UnknownFighterError, new_fighter
from game.moves import ACTION_ORDER
from game.rules import (
    compute_damage,
    effective_spd,
    legal_actions,
    new_match,
    resolve_turn,
    roll_turn_order,
)


def test_fresh_match_has_the_spec_shape():
    match = new_match("kaito", "vega")
    assert set(match) == {"status", "turn", "player", "opponent", "log"}
    assert match["status"] == "in_progress"
    assert match["turn"] == 0
    assert match["log"] == []


def test_fresh_match_fighters_start_full():
    match = new_match("kaito", "vega")
    for side in ("player", "opponent"):
        fighter = match[side]
        assert fighter["hp"] == fighter["hp_max"]
        assert fighter["ki"] == 30
        assert fighter["guarding"] is False
        assert fighter["ascended"] is False
        assert fighter["ascend_used"] is False

    assert match["player"]["id"] == "kaito"
    assert match["opponent"]["id"] == "vega"


def test_mirror_match_sides_are_independent():
    """kaito vs kaito is legal and shares no state (§2.1)."""
    match = new_match("kaito", "kaito")
    assert match["player"] == match["opponent"]
    assert match["player"] is not match["opponent"]

    match["player"]["hp"] = 1
    assert match["opponent"]["hp"] == 100


def test_two_matches_share_no_state():
    first = new_match("kaito", "vega")
    second = new_match("kaito", "vega")
    first["log"].append({"turn": 1})
    first["opponent"]["ki"] = 0
    assert second["log"] == []
    assert second["opponent"]["ki"] == 30


@pytest.mark.parametrize(
    ("player_id", "opponent_id"),
    [("goku", "vega"), ("kaito", "goku")],
)
def test_unknown_fighter_raises(player_id, opponent_id):
    with pytest.raises(UnknownFighterError):
        new_match(player_id, opponent_id)


def _fighter(ki, *, ascend_used=False):
    fighter = new_fighter("kaito")
    fighter["ki"] = ki
    fighter["ascend_used"] = ascend_used
    return fighter


def test_zero_ki_leaves_only_the_free_moves():
    """Guard is legal at 0 ki because it costs nothing (§4.3)."""
    assert legal_actions(_fighter(0)) == ["strike", "charge", "guard"]


def test_fifteen_ki_unlocks_ki_blast_only():
    assert legal_actions(_fighter(15)) == ["strike", "ki_blast", "charge", "guard"]


@pytest.mark.parametrize("ki", [14, 15, 39, 40])
def test_ki_blast_threshold_is_exactly_fifteen(ki):
    assert ("ki_blast" in legal_actions(_fighter(ki))) is (ki >= 15)


def test_forty_ki_unlocks_surge_beam_and_ascend():
    assert legal_actions(_fighter(40)) == ACTION_ORDER


def test_ascend_drops_out_once_used_but_surge_beam_stays():
    actions = legal_actions(_fighter(40, ascend_used=True))
    assert "ascend" not in actions
    assert actions == ["strike", "ki_blast", "surge_beam", "charge", "guard"]


def test_ascend_still_needs_the_ki_even_when_unused():
    assert "ascend" not in legal_actions(_fighter(39))


def test_result_is_a_list_in_canonical_order():
    for ki in range(0, 101):
        actions = legal_actions(_fighter(ki))
        assert isinstance(actions, list)
        assert actions == sorted(actions, key=ACTION_ORDER.index)


def test_legal_actions_does_not_mutate_the_fighter():
    fighter = _fighter(40)
    before = dict(fighter)
    legal_actions(fighter)
    assert fighter == before


# --- Damage formula (§4.1) -------------------------------------------------
#
# Expected values are hand-computed from P * (A.atk / (A.atk + D.def)):
# Kaito into Vega the ratio is 22/36, Vega into Kaito it is 16/24.


@pytest.mark.parametrize(
    ("power", "expected"),
    # spread             0.90  1.00  1.10
    [
        (14, (8, 9, 9)),      # Strike:     14 * 22/36 = 8.556
        (26, (14, 16, 17)),   # Ki Blast:   26 * 22/36 = 15.889
        (48, (26, 29, 32)),   # Surge Beam: 48 * 22/36 = 29.333
    ],
)
def test_kaito_into_vega(power, expected):
    kaito = new_fighter("kaito")
    vega = new_fighter("vega")
    spreads = (0.90, 1.00, 1.10)
    assert tuple(compute_damage(kaito, vega, power, s) for s in spreads) == expected


@pytest.mark.parametrize(
    ("power", "expected"),
    # spread             0.90  1.00  1.10
    [
        (14, (8, 9, 10)),     # Strike:     14 * 16/24 = 9.333
        (26, (16, 17, 19)),   # Ki Blast:   26 * 16/24 = 17.333
        (48, (29, 32, 35)),   # Surge Beam: 48 * 16/24 = 32.0
    ],
)
def test_vega_into_kaito(power, expected):
    kaito = new_fighter("kaito")
    vega = new_fighter("vega")
    spreads = (0.90, 1.00, 1.10)
    assert tuple(compute_damage(vega, kaito, power, s) for s in spreads) == expected


def test_ascend_multiplies_damage_by_a_quarter():
    kaito = new_fighter("kaito")
    vega = new_fighter("vega")
    plain = compute_damage(kaito, vega, 26, 1.0)

    kaito["ascended"] = True
    assert compute_damage(kaito, vega, 26, 1.0) == 20  # 15.889 * 1.25 = 19.861
    assert plain == 16


def test_ascend_on_the_defender_changes_nothing():
    """×1.25 is a buff to damage *dealt*, not a penalty to damage taken."""
    kaito = new_fighter("kaito")
    vega = new_fighter("vega")
    before = compute_damage(kaito, vega, 26, 1.0)
    vega["ascended"] = True
    assert compute_damage(kaito, vega, 26, 1.0) == before


def test_guard_halves_incoming_damage():
    kaito = new_fighter("kaito")
    vega = new_fighter("vega")
    assert compute_damage(kaito, vega, 26, 1.0) == 16

    vega["guarding"] = True
    assert compute_damage(kaito, vega, 26, 1.0) == 8  # 15.889 * 0.5 = 7.944


def test_guarding_attacker_deals_full_damage():
    """Only the *defender's* guard matters."""
    kaito = new_fighter("kaito")
    vega = new_fighter("vega")
    kaito["guarding"] = True
    assert compute_damage(kaito, vega, 26, 1.0) == 16


def test_ascend_and_guard_stack_multiplicatively():
    kaito = new_fighter("kaito")
    vega = new_fighter("vega")
    kaito["ascended"] = True
    vega["guarding"] = True
    # 15.889 * 1.25 * 0.5 = 9.931
    assert compute_damage(kaito, vega, 26, 1.0) == 10


def test_damage_floors_at_one():
    """A featherweight into a wall still lands for 1 (§4.1)."""
    weakling = dict(new_fighter("kaito"), atk=1)
    wall = dict(new_fighter("vega"), **{"def": 1000})
    assert compute_damage(weakling, wall, 1, 0.90) == 1


def test_floor_survives_guard_and_the_lowest_spread():
    weakling = dict(new_fighter("kaito"), atk=1)
    wall = dict(new_fighter("vega"), guarding=True, **{"def": 1000})
    assert compute_damage(weakling, wall, 1, 0.90) == 1


@pytest.mark.parametrize(
    ("power", "expected"),
    # Half-to-even, not half-away-from-zero: 6.5 -> 6 and 7.5 -> 8 (A5).
    [(13, 6), (15, 8)],
)
def test_exact_halves_round_to_even(power, expected):
    """A 50/50 atk-def split makes the product land exactly on .5."""
    attacker = dict(new_fighter("kaito"), atk=10, ascended=False)
    defender = dict(new_fighter("vega"), guarding=False, **{"def": 10})
    assert compute_damage(attacker, defender, power, 1.0) == expected


def test_compute_damage_does_not_mutate_its_fighters():
    kaito = new_fighter("kaito")
    vega = new_fighter("vega")
    before = (dict(kaito), dict(vega))
    compute_damage(kaito, vega, 48, 1.10)
    assert (kaito, vega) == before


# --- 1.6 turn order and the tie coin flip (§4.4, §4.8; A2, A3) ----------------


class FixedRng:
    """A stand-in that returns a pinned value, to assert A3's *method*."""

    def __init__(self, value: float):
        self.value = value

    def random(self) -> float:
        return self.value


def test_effective_spd_adds_five_only_while_ascended():
    kaito = new_fighter("kaito")
    assert effective_spd(kaito) == 14
    assert effective_spd(dict(kaito, ascended=True)) == 19


def test_faster_fighter_goes_first_without_consuming_a_draw():
    """Kaito (14) beats Vega (9) outright, so §4.8 allows no coin flip."""
    match = new_match("kaito", "vega")
    rng = random.Random(1234)
    before = rng.getstate()
    assert roll_turn_order(match, rng) == ("player", "opponent")
    assert rng.getstate() == before


def test_slower_player_resolves_second_without_consuming_a_draw():
    match = new_match("vega", "kaito")
    rng = random.Random(1234)
    before = rng.getstate()
    assert roll_turn_order(match, rng) == ("opponent", "player")
    assert rng.getstate() == before


def test_mirror_match_consumes_exactly_one_draw():
    match = new_match("kaito", "kaito")
    rng = random.Random(7)
    probe = random.Random(7)
    probe.random()
    roll_turn_order(match, rng)
    assert rng.getstate() == probe.getstate()


def test_mirror_match_reaches_both_orders_across_seeds():
    match = new_match("kaito", "kaito")
    seen = {roll_turn_order(match, random.Random(seed)) for seed in range(50)}
    assert seen == {("player", "opponent"), ("opponent", "player")}


def test_tie_flip_method_is_random_below_one_half():
    """A3 pins the method, not just the outcome: < 0.5 → player first."""
    match = new_match("kaito", "kaito")
    assert roll_turn_order(match, FixedRng(0.49)) == ("player", "opponent")
    assert roll_turn_order(match, FixedRng(0.5)) == ("opponent", "player")


def test_ascended_vega_ties_kaito_and_triggers_a_flip():
    match = new_match("kaito", "vega")
    match["opponent"]["ascended"] = True  # 9 + 5 = 14, tying Kaito
    rng = random.Random(3)
    probe = random.Random(3)
    probe.random()
    roll_turn_order(match, rng)
    assert rng.getstate() == probe.getstate()


def test_ascending_this_turn_does_not_change_this_turns_order():
    """A2: order is read from start-of-turn speeds, so no draw happens here."""
    match = new_match("kaito", "vega")
    rng = random.Random(99)
    before = rng.getstate()
    order = roll_turn_order(match, rng)
    match["opponent"]["ascended"] = True  # resolves later in the same turn
    assert order == ("player", "opponent")
    assert rng.getstate() == before


def test_roll_turn_order_does_not_mutate_the_state():
    match = new_match("kaito", "kaito")
    before = copy.deepcopy(match)
    roll_turn_order(match, random.Random(5))
    assert match == before


# --- 1.7 resolve_turn, effects phase (§4.4 steps 2-3) ------------------------
#
# Only non-attack actions appear here so the assertions are about the effects
# phase alone.


def _match_with(player: dict | None = None, opponent: dict | None = None) -> dict:
    """A kaito-vs-vega match whose fighters carry the given field overrides."""
    match = new_match("kaito", "vega")
    match["player"].update(player or {})
    match["opponent"].update(opponent or {})
    return match


def test_charge_restores_exactly_twenty_five_ki():
    match = _match_with()
    new_state, _ = resolve_turn(match, "charge", "guard", random.Random(1))
    assert new_state["player"]["ki"] == 55


def test_charge_restores_thirty_ki_while_ascended():
    match = _match_with(player={"ascended": True, "ascend_used": True})
    new_state, _ = resolve_turn(match, "charge", "guard", random.Random(1))
    assert new_state["player"]["ki"] == 60


def test_charge_never_exceeds_ki_max():
    match = _match_with(player={"ki": 90}, opponent={"ki": 125})
    new_state, _ = resolve_turn(match, "charge", "charge", random.Random(1))
    assert new_state["player"]["ki"] == 100
    assert new_state["opponent"]["ki"] == 100


def test_guard_restores_exactly_eight_ki():
    match = _match_with()
    new_state, _ = resolve_turn(match, "guard", "charge", random.Random(1))
    assert new_state["player"]["ki"] == 38


def test_guard_ki_also_clamps_at_the_ceiling():
    match = _match_with(player={"ki": 95})
    new_state, _ = resolve_turn(match, "guard", "charge", random.Random(1))
    assert new_state["player"]["ki"] == 100


def test_both_sides_charging_each_gain_their_own_ki():
    match = _match_with()
    new_state, _ = resolve_turn(match, "charge", "charge", random.Random(1))
    assert new_state["player"]["ki"] == 55
    assert new_state["opponent"]["ki"] == 55


def test_ascend_pays_forty_ki_and_latches_its_flags():
    match = _match_with(player={"ki": 40})
    new_state, _ = resolve_turn(match, "ascend", "guard", random.Random(1))
    ascender = new_state["player"]
    assert ascender["ki"] == 0
    assert ascender["ascended"] is True
    assert ascender["ascend_used"] is True


def test_ascend_leaves_the_other_fighter_alone():
    match = _match_with(player={"ki": 40})
    new_state, _ = resolve_turn(match, "ascend", "charge", random.Random(1))
    assert new_state["opponent"]["ascended"] is False
    assert new_state["opponent"]["ascend_used"] is False
    assert new_state["opponent"]["ki"] == 55


def test_ascend_the_same_turn_does_not_boost_that_turns_charge():
    """The +5 ki only reaches a Charge on a *later* turn — one action per turn."""
    match = _match_with(opponent={"ki": 40})
    new_state, _ = resolve_turn(match, "charge", "ascend", random.Random(1))
    assert new_state["player"]["ki"] == 55


def test_both_sides_ascending_in_one_turn():
    match = _match_with(player={"ki": 40}, opponent={"ki": 100})
    new_state, _ = resolve_turn(match, "ascend", "ascend", random.Random(1))
    assert new_state["player"]["ki"] == 0
    assert new_state["opponent"]["ki"] == 60
    assert new_state["player"]["ascended"] is True
    assert new_state["opponent"]["ascended"] is True


def test_effects_phase_does_not_mutate_the_input_state():
    match = _match_with(player={"ki": 40})
    before = copy.deepcopy(match)
    new_state, _ = resolve_turn(match, "ascend", "charge", random.Random(1))
    assert match == before
    assert new_state is not match


def test_a_supplied_order_is_used_without_touching_the_rng():
    """A1: the app layer rolls the order first, so resolve_turn must not."""
    match = _match_with()
    new_state, _ = resolve_turn(
        match, "charge", "guard", None, order=("opponent", "player")
    )
    assert new_state["player"]["ki"] == 55
    assert new_state["opponent"]["ki"] == 38


def _first_spread(seed: int) -> float:
    """The spread the attack phase draws first at ``seed`` (§4.8)."""
    return random.Random(seed).uniform(0.90, 1.10)


def test_strike_always_takes_at_least_one_hp():
    match = _match_with()
    for seed in range(20):
        new_state, _ = resolve_turn(match, "strike", "guard", random.Random(seed))
        assert new_state["opponent"]["hp"] <= match["opponent"]["hp"] - 1


def test_strike_deals_the_damage_the_formula_predicts():
    match = _match_with()
    new_state, _ = resolve_turn(match, "strike", "charge", random.Random(7))
    expected = compute_damage(match["player"], match["opponent"], 14, _first_spread(7))
    assert new_state["opponent"]["hp"] == 130 - expected


def test_ki_blast_deducts_exactly_fifteen_ki():
    match = _match_with()
    new_state, _ = resolve_turn(match, "ki_blast", "guard", random.Random(1))
    assert new_state["player"]["ki"] == 15


def test_surge_beam_deducts_exactly_forty_ki():
    match = _match_with(player={"ki": 40})
    new_state, _ = resolve_turn(match, "surge_beam", "guard", random.Random(1))
    assert new_state["player"]["ki"] == 0


def test_strike_deducts_no_ki():
    match = _match_with()
    new_state, _ = resolve_turn(match, "strike", "strike", random.Random(1))
    assert new_state["player"]["ki"] == 30


def test_guard_halves_damage_from_a_faster_attacker():
    """§4.3: the slower fighter's Guard still counts, which is the whole point."""
    match = _match_with()
    guarded, _ = resolve_turn(match, "strike", "guard", random.Random(3))
    unguarded, _ = resolve_turn(match, "strike", "charge", random.Random(3))

    taken_guarded = 130 - guarded["opponent"]["hp"]
    taken_unguarded = 130 - unguarded["opponent"]["hp"]
    assert taken_guarded == max(1, round(taken_unguarded / 2))
    assert taken_guarded < taken_unguarded


def test_guarding_is_cleared_on_both_fighters_after_the_turn():
    match = _match_with()
    new_state, _ = resolve_turn(match, "guard", "guard", random.Random(1))
    assert new_state["player"]["guarding"] is False
    assert new_state["opponent"]["guarding"] is False


def test_hp_clamps_at_zero_rather_than_going_negative():
    match = _match_with(player={"ki": 40}, opponent={"hp": 2})
    new_state, _ = resolve_turn(match, "surge_beam", "charge", random.Random(1))
    assert new_state["opponent"]["hp"] == 0


def test_a_ko_stops_the_slower_fighter_from_attacking():
    match = _match_with(opponent={"hp": 1})
    new_state, _ = resolve_turn(match, "strike", "strike", random.Random(1))
    assert new_state["opponent"]["hp"] == 0
    assert new_state["player"]["hp"] == 100


def test_a_ko_still_leaves_the_dead_fighters_charge_applied():
    """A8: the non-attack effects of step 3 resolved before the KO landed."""
    match = _match_with(opponent={"hp": 1})
    new_state, _ = resolve_turn(match, "strike", "charge", random.Random(1))
    assert new_state["opponent"]["hp"] == 0
    assert new_state["opponent"]["ki"] == 55


def test_a_slower_ko_victim_never_lands_its_attack():
    """Speed only helps if you survive to swing — here Vega moves first."""
    match = _match_with(player={"hp": 1}, opponent={"spd": 20})
    new_state, _ = resolve_turn(match, "strike", "strike", random.Random(1))
    assert new_state["player"]["hp"] == 0
    assert new_state["opponent"]["hp"] == 130


def test_ascend_raises_damage_by_about_a_quarter_and_speed_by_five():
    plain = _match_with(player={"ki": 40})
    buffed = _match_with(player={"ki": 40, "ascended": True, "ascend_used": True})

    plain_state, _ = resolve_turn(plain, "surge_beam", "charge", random.Random(5))
    buffed_state, _ = resolve_turn(buffed, "surge_beam", "charge", random.Random(5))

    plain_damage = 130 - plain_state["opponent"]["hp"]
    buffed_damage = 130 - buffed_state["opponent"]["hp"]
    assert abs(buffed_damage - plain_damage * 1.25) <= 1
    assert effective_spd(buffed_state["player"]) == (
        effective_spd(plain_state["player"]) + 5
    )


def test_a_turn_without_attacks_consumes_no_spread_draw():
    """§4.8 allows a draw only when the step it belongs to actually happens."""
    rng = random.Random(1)
    before = rng.getstate()
    resolve_turn(_match_with(), "charge", "guard", rng, order=("player", "opponent"))
    assert rng.getstate() == before
