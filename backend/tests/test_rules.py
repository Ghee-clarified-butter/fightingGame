"""Tests for the pure game rules (spec §4)."""

import pytest

from game.fighters import UnknownFighterError, new_fighter
from game.moves import ACTION_ORDER
from game.rules import legal_actions, new_match


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
