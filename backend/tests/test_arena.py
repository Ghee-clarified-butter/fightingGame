"""Tests for the headless AI-vs-AI match runner (extension E7, plan 4.1).

The arena is what the tournament will call once per bracket slot, so what
matters here is that a matchup at a seed is a *function* — same inputs, same log
— and that a match played with no human in it still obeys every rule the HTTP
path enforces: legal moves only, the streak cap on both sides, and the §4.6 turn
cap as a hard bound on the loop.
"""

import random

import pytest

from game import rules
from game.ai import PASSIVE_CAP, UnknownDifficultyError
from game.arena import SIDE_OF, run_ai_match
from game.fighters import FIGHTERS, UnknownFighterError
from game.moves import MOVES
from game.rules import TURN_CAP

DIFFICULTIES = ("random", "heuristic", "search")

RESULT_KEYS = {"winner", "winner_side", "turns", "status", "log"}


def _passive_runs(log: list[dict], actor: str) -> list[int]:
    """Return the length of every consecutive non-attacking run by ``actor``."""
    runs = []
    current = 0
    for entry in log:
        if entry["actor"] != actor:
            continue
        if MOVES[entry["action"]]["is_attack"]:
            runs.append(current)
            current = 0
        else:
            current += 1
    runs.append(current)
    return runs


# --- Shape and outcome -------------------------------------------------------


def test_the_result_has_exactly_the_documented_keys():
    result = run_ai_match("kaito", "vega", "heuristic", 1)
    assert set(result) == RESULT_KEYS


@pytest.mark.parametrize("difficulty", DIFFICULTIES)
def test_a_match_runs_to_a_conclusion(difficulty):
    """The loop terminates and leaves a settled §4.6 status, never in_progress."""
    result = run_ai_match("kaito", "vega", difficulty, 7)
    assert result["status"] in (
        rules.STATUS_PLAYER_WON,
        rules.STATUS_OPPONENT_WON,
        rules.STATUS_DRAW,
    )
    assert result["turns"] >= 1


@pytest.mark.parametrize("difficulty", DIFFICULTIES)
def test_the_turn_count_never_exceeds_the_cap(difficulty):
    for seed in range(12):
        result = run_ai_match("kaito", "vega", difficulty, seed)
        assert 1 <= result["turns"] <= TURN_CAP


def test_side_a_is_the_rules_player_and_side_b_the_opponent():
    """A wins exactly when the *player* side won, so the bracket's A/B is stable."""
    assert SIDE_OF == {"a": "player", "b": "opponent"}
    for seed in range(20):
        result = run_ai_match("kaito", "vega", "random", seed)
        if result["status"] == rules.STATUS_PLAYER_WON:
            assert result["winner"] == "a"
            assert result["winner_side"] == "player"
        elif result["status"] == rules.STATUS_OPPONENT_WON:
            assert result["winner"] == "b"
            assert result["winner_side"] == "opponent"
        else:
            assert result["winner"] is None
            assert result["winner_side"] is None


def test_a_decisive_match_always_names_a_winner():
    result = run_ai_match("kaito", "vega", "heuristic", 3)
    assert result["status"] != rules.STATUS_DRAW
    assert result["winner"] in ("a", "b")


def test_a_mirror_matchup_runs_to_a_conclusion():
    """Identical fighters tie on speed every turn, so every order is a coin flip."""
    for fighter_id in FIGHTERS:
        result = run_ai_match(fighter_id, fighter_id, "heuristic", 11)
        assert result["status"] in (
            rules.STATUS_PLAYER_WON,
            rules.STATUS_OPPONENT_WON,
            rules.STATUS_DRAW,
        )
        assert result["turns"] <= TURN_CAP


# --- Determinism (E7.3's premise) -------------------------------------------


@pytest.mark.parametrize("difficulty", DIFFICULTIES)
def test_the_same_seed_reproduces_the_match_exactly(difficulty):
    first = run_ai_match("kaito", "vega", difficulty, 2024)
    second = run_ai_match("kaito", "vega", difficulty, 2024)
    assert first == second


def test_different_seeds_diverge_under_a_drawing_policy():
    """Not a determinism claim — a seed that never mattered would be a bug."""
    logs = {
        tuple(str(entry) for entry in run_ai_match("kaito", "vega", "random", seed)["log"])
        for seed in range(8)
    }
    assert len(logs) > 1


def test_a_heuristic_match_still_depends_on_the_seed():
    """The policy draws nothing, but the order flips and spreads still do."""
    results = {run_ai_match("kaito", "kaito", "heuristic", s)["turns"] for s in range(12)}
    assert len(results) > 1


# --- Rule compliance ---------------------------------------------------------


@pytest.mark.parametrize("difficulty", DIFFICULTIES)
def test_no_illegal_action_appears_in_any_log(difficulty):
    """Replay each match and check every logged move was legal when chosen."""
    for seed in range(4):
        log = run_ai_match("kaito", "vega", difficulty, seed)["log"]
        state = rules.new_match("kaito", "vega", difficulty)
        rng = random.Random(seed)
        turn_actions: dict[int, dict[str, str]] = {}
        for entry in log:
            turn_actions.setdefault(entry["turn"], {})[entry["actor"]] = entry["action"]
        for turn in sorted(turn_actions):
            actions = turn_actions[turn]
            for side, action in actions.items():
                assert action in rules.legal_actions(state[side])
            order = rules.roll_turn_order(state, rng)
            # A side KO'd mid-turn logs nothing, so fall back to its own choice
            # being irrelevant: any legal move reproduces the same terminal state.
            state, _ = rules.resolve_turn(
                state,
                actions.get("player", "strike"),
                actions.get("opponent", "strike"),
                rng,
                order=order,
            )


@pytest.mark.parametrize("difficulty", DIFFICULTIES)
def test_both_sides_obey_the_streak_cap_over_a_full_match(difficulty):
    """E2.1 binds every policy, and the arena drives both sides through it."""
    for seed in range(6):
        log = run_ai_match("kaito", "vega", difficulty, seed)["log"]
        for actor in ("player", "opponent"):
            assert max(_passive_runs(log, actor)) <= PASSIVE_CAP


def test_the_log_entries_carry_consecutive_turn_numbers():
    log = run_ai_match("kaito", "vega", "heuristic", 5)["log"]
    turns = sorted({entry["turn"] for entry in log})
    assert turns == list(range(1, len(turns) + 1))


def test_the_reported_turn_count_matches_the_log():
    result = run_ai_match("kaito", "vega", "heuristic", 9)
    assert max(entry["turn"] for entry in result["log"]) == result["turns"]


# --- Validation is the callee's, not the arena's -----------------------------


def test_an_unknown_difficulty_raises():
    with pytest.raises(UnknownDifficultyError):
        run_ai_match("kaito", "vega", "impossible", 1)


def test_an_unknown_fighter_raises():
    with pytest.raises(UnknownFighterError):
        run_ai_match("kaito", "nobody", "heuristic", 1)
