"""Tests for the pure game rules (spec §4)."""

import pytest

from game.fighters import UnknownFighterError, new_fighter
from game.moves import ACTION_ORDER
from game.rules import compute_damage, legal_actions, new_match


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
