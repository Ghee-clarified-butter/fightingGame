"""Tests for the move table (spec §3)."""

import pytest

from game.moves import ACTION_ORDER, MOVES


def test_exactly_six_moves():
    assert len(MOVES) == 6


def test_action_order_is_the_canonical_list():
    assert ACTION_ORDER == [
        "strike", "ki_blast", "surge_beam", "charge", "guard", "ascend",
    ]


def test_action_order_covers_the_move_table_exactly():
    assert sorted(ACTION_ORDER) == sorted(MOVES)


@pytest.mark.parametrize(
    "action,cost",
    [
        ("strike", 0),
        ("ki_blast", 15),
        ("surge_beam", 40),
        ("charge", 0),
        ("guard", 0),
        ("ascend", 40),
    ],
)
def test_ki_costs_match_the_spec_table(action, cost):
    assert MOVES[action]["cost"] == cost


@pytest.mark.parametrize(
    "action,power",
    [("strike", 14), ("ki_blast", 26), ("surge_beam", 48)],
)
def test_attack_powers_match_the_spec_table(action, power):
    assert MOVES[action]["power"] == power
    assert MOVES[action]["is_attack"] is True


@pytest.mark.parametrize("action", ["charge", "guard", "ascend"])
def test_charge_guard_and_ascend_are_not_attacks(action):
    """§3: Charge, Guard and Ascend deal no damage."""
    assert MOVES[action]["is_attack"] is False
    assert MOVES[action]["power"] is None


@pytest.mark.parametrize("action", ACTION_ORDER)
def test_every_move_has_exactly_the_expected_fields(action):
    assert set(MOVES[action]) == {"name", "cost", "power", "is_attack"}


@pytest.mark.parametrize(
    "action,name",
    [
        ("strike", "Strike"),
        ("ki_blast", "Ki Blast"),
        ("surge_beam", "Surge Beam"),
        ("charge", "Charge"),
        ("guard", "Guard"),
        ("ascend", "Ascend"),
    ],
)
def test_display_names(action, name):
    assert MOVES[action]["name"] == name
