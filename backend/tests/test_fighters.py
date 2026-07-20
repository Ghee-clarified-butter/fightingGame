"""Tests for the starter fighter templates (spec §2.1)."""

import pytest

from game.fighters import FIGHTERS, STARTING_KI, UnknownFighterError, new_fighter


def test_only_the_two_starters_exist():
    assert sorted(FIGHTERS) == ["kaito", "vega"]


def test_kaito_matches_the_spec_table():
    kaito = FIGHTERS["kaito"]
    assert kaito == {
        "id": "kaito",
        "name": "Kaito",
        "hp_max": 100,
        "ki_max": 100,
        "atk": 22,
        "def": 8,
        "spd": 14,
    }


def test_vega_matches_the_spec_table():
    vega = FIGHTERS["vega"]
    assert vega == {
        "id": "vega",
        "name": "Vega",
        "hp_max": 130,
        "ki_max": 100,
        "atk": 16,
        "def": 14,
        "spd": 9,
    }


@pytest.mark.parametrize("fighter_id", ["kaito", "vega"])
def test_new_fighter_starts_at_full_hp_and_30_ki(fighter_id):
    fighter = new_fighter(fighter_id)
    assert fighter["hp"] == fighter["hp_max"] == FIGHTERS[fighter_id]["hp_max"]
    assert fighter["ki"] == STARTING_KI == 30
    assert fighter["ki_max"] == 100
    assert fighter["guarding"] is False
    assert fighter["ascended"] is False
    assert fighter["ascend_used"] is False


@pytest.mark.parametrize("fighter_id", ["kaito", "vega"])
def test_new_fighter_has_exactly_the_spec_fields(fighter_id):
    assert set(new_fighter(fighter_id)) == {
        "id", "name", "hp", "hp_max", "ki", "ki_max",
        "atk", "def", "spd", "guarding", "ascended", "ascend_used",
    }


def test_two_copies_are_equal_but_independent():
    """Mirror-match independence (§2.1)."""
    a = new_fighter("kaito")
    b = new_fighter("kaito")
    assert a == b
    assert a is not b

    a["hp"] = 1
    a["ascended"] = True
    assert b["hp"] == 100
    assert b["ascended"] is False


def test_mutating_an_instance_does_not_touch_the_template():
    fighter = new_fighter("vega")
    fighter["atk"] = 999
    assert FIGHTERS["vega"]["atk"] == 16


def test_unknown_id_raises():
    with pytest.raises(UnknownFighterError):
        new_fighter("goku")
