"""Tests for AI move selection (extension E1, E2.1).

The rules-level bookkeeping that feeds the cap — ``passive_streak`` incrementing
and resetting — is covered in ``test_rules.py``. This file is about what the
policies do with it.
"""

import random

import pytest

from game.ai import (
    DIFFICULTIES,
    PASSIVE_CAP,
    UnknownDifficultyError,
    attacking_candidates,
    choose_action,
    play_turn,
)
from game.moves import ACTION_ORDER, MOVES
from game.rules import legal_actions, new_match

ATTACKS = [action for action in ACTION_ORDER if MOVES[action]["is_attack"]]
PASSIVES = [action for action in ACTION_ORDER if not MOVES[action]["is_attack"]]


def _match_with(player: dict | None = None, opponent: dict | None = None, **top) -> dict:
    """A fresh Kaito-vs-Vega match with the given fields overwritten."""
    match = new_match("kaito", "vega")
    match.update(top)
    match["player"].update(player or {})
    match["opponent"].update(opponent or {})
    return match


# --- The cap itself (E2.1) ---------------------------------------------------


def test_the_cap_is_two_consecutive_passives():
    """E2.1 in one number: the *third* consecutive passive turn is forbidden."""
    assert PASSIVE_CAP == 2


def test_below_the_cap_every_legal_move_stays_a_candidate():
    fighter = new_match("kaito", "vega")["opponent"]
    fighter["ki"] = 100
    for streak in range(PASSIVE_CAP):
        fighter["passive_streak"] = streak
        assert attacking_candidates(fighter, legal_actions(fighter)) == ACTION_ORDER


def test_at_the_cap_only_attacks_remain():
    fighter = new_match("kaito", "vega")["opponent"]
    fighter["ki"] = 100
    fighter["passive_streak"] = PASSIVE_CAP
    assert attacking_candidates(fighter, legal_actions(fighter)) == ATTACKS


def test_the_cap_leaves_strike_when_nothing_else_is_affordable():
    """Strike costs 0 ki, so a forced attack always exists — even at 0 ki."""
    fighter = new_match("kaito", "vega")["opponent"]
    fighter["ki"] = 0
    fighter["passive_streak"] = 5
    assert attacking_candidates(fighter, legal_actions(fighter)) == ["strike"]


def test_the_cap_does_not_touch_legal_actions():
    """E2.1: the cap constrains policy selection, never the rules.

    Byte-identical output for a fighter with streak 0 and streak 5 is what makes
    "the player is not bound" true at the source rather than by convention.
    """
    zero = new_match("kaito", "vega")["player"]
    zero["ki"] = 100
    deep = dict(zero, passive_streak=5)
    assert legal_actions(zero) == legal_actions(deep)


# --- The random policy under the cap ----------------------------------------


def test_random_is_forced_to_attack_on_the_third_passive_turn():
    """Over many draws at the cap, a passive move never comes out."""
    match = _match_with(opponent={"ki": 100, "passive_streak": PASSIVE_CAP})
    rng = random.Random(1)
    drawn = {choose_action(match, "opponent", "random", rng) for _ in range(400)}
    assert drawn == set(ATTACKS)


@pytest.mark.parametrize("streak", [0, 1])
def test_random_may_still_go_passive_below_the_cap(streak):
    """Two consecutive passive turns are allowed; only the third is not."""
    match = _match_with(opponent={"ki": 100, "passive_streak": streak})
    rng = random.Random(2)
    drawn = {choose_action(match, "opponent", "random", rng) for _ in range(400)}
    assert drawn == set(ACTION_ORDER)


def test_random_consumes_exactly_one_choice_draw_below_the_cap():
    """B2: the draw is one ``rng.choice`` over the ordered candidate list.

    ``rng.choice`` scales its raw draws to the list length, so replaying the
    pinned call is what fixes both the count *and* the list it was made over.
    """
    match = _match_with(opponent={"ki": 100})
    rng = random.Random(6)
    probe = random.Random(6)
    chosen = choose_action(match, "opponent", "random", rng)
    assert chosen == probe.choice(ACTION_ORDER)
    assert rng.getstate() == probe.getstate()


def test_random_consumes_exactly_one_choice_draw_at_the_cap():
    """Still one draw when the cap shortened the list — just over a shorter one.

    That the *result* differs from the unfiltered draw at the same seed is B3:
    E2.1 binds the random policy, so a fixed seed can now yield a different
    match than it did in Step 1.
    """
    match = _match_with(opponent={"ki": 100, "passive_streak": PASSIVE_CAP})
    rng = random.Random(6)
    probe = random.Random(6)
    chosen = choose_action(match, "opponent", "random", rng)
    assert chosen == probe.choice(ATTACKS)
    assert rng.getstate() == probe.getstate()


def test_the_cap_reads_the_chooser_not_its_foe():
    """A passive player must not force the *opponent* to attack."""
    match = _match_with(
        player={"ki": 100, "passive_streak": 9},
        opponent={"ki": 100, "passive_streak": 0},
    )
    rng = random.Random(3)
    drawn = {choose_action(match, "opponent", "random", rng) for _ in range(400)}
    assert drawn == set(ACTION_ORDER)


def test_either_side_can_be_the_chooser():
    """Tournaments run AI against AI (E8), so the AI is not always ``opponent``."""
    match = _match_with(player={"ki": 0, "passive_streak": PASSIVE_CAP})
    rng = random.Random(4)
    drawn = {choose_action(match, "player", "random", rng) for _ in range(50)}
    assert drawn == {"strike"}


# --- Dispatch ----------------------------------------------------------------


def test_random_is_a_difficulty():
    assert "random" in DIFFICULTIES


@pytest.mark.parametrize("difficulty", ["", "hard", "Random", "RANDOM", None, 3])
def test_an_unknown_difficulty_raises(difficulty):
    match = new_match("kaito", "vega")
    with pytest.raises(UnknownDifficultyError) as excinfo:
        choose_action(match, "opponent", difficulty, random.Random(1))
    assert excinfo.value.args[0] == difficulty


# --- ``play_turn`` -----------------------------------------------------------


def test_play_turn_reads_the_difficulty_off_the_state():
    """B5: the policy comes from the match, not from the caller."""
    match = _match_with(difficulty="nonsense")
    with pytest.raises(UnknownDifficultyError):
        play_turn(match, "strike", random.Random(1))


def test_a_new_match_plays_under_the_random_policy():
    """The default is ``random``, so Step 1 matches keep their behaviour (E1)."""
    match = new_match("kaito", "vega")
    assert match["difficulty"] == "random"
    state, entries = play_turn(match, "strike", random.Random(5))
    assert state["turn"] == 1
    assert {entry["actor"] for entry in entries} <= {"player", "opponent"}


def test_the_opponent_never_goes_passive_three_turns_running():
    """E10: no AI takes a non-attacking action three turns in a row.

    Played through ``play_turn`` over many seeds, so this exercises the cap in
    the composition the server actually uses rather than on a crafted state. The
    ``forced`` counter keeps the assertion from passing vacuously: it counts the
    turns the opponent entered already at the cap, which are exactly the turns on
    which the filter did the work.
    """
    forced = 0
    for seed in range(60):
        state = new_match("kaito", "vega")
        rng = random.Random(seed)
        streak = 0
        while state["status"] == "in_progress":
            forced += streak == PASSIVE_CAP
            state, entries = play_turn(state, "charge", rng)
            action = next(e["action"] for e in entries if e["actor"] == "opponent")
            streak = 0 if MOVES[action]["is_attack"] else streak + 1
            assert streak <= PASSIVE_CAP, f"seed {seed}: opponent went passive {streak} times"
    assert forced > 0, "the cap never bound, so this proves nothing about it"


def test_the_player_is_not_bound_by_the_cap():
    """E10: charging four turns running is accepted, and stays accepted."""
    state = new_match("kaito", "vega")
    rng = random.Random(7)
    for turn in range(1, 5):
        assert "charge" in legal_actions(state["player"])
        state, _ = play_turn(state, "charge", rng)
        assert state["turn"] == turn
        assert state["player"]["passive_streak"] == turn


def test_play_turn_does_not_mutate_its_input():
    match = new_match("kaito", "vega")
    before = {"turn": match["turn"], "log": list(match["log"])}
    play_turn(match, "strike", random.Random(41))
    assert match["turn"] == before["turn"]
    assert match["log"] == before["log"]


def test_every_passive_move_is_filtered_by_the_cap():
    """All three of charge, guard and ascend are non-attacking (E2.1)."""
    assert PASSIVES == ["charge", "guard", "ascend"]
