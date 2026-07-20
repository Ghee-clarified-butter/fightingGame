"""Tests for the pure game rules (spec §4)."""

import pytest

from game.fighters import UnknownFighterError
from game.rules import new_match


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
