"""Property / fuzz suite over the rules layer (§8, §9).

Thousands of turns of random-vs-random play, checking the invariants that no
single hand-written case can cover: every match ends, almost all of them by KO,
and no fighter ever leaves its legal hp/ki range or takes a move it could not
afford.

Two RNGs, deliberately:

* the **match** RNG is the one the rules consume, so its draw order stays
  exactly the §4.8 sequence a real match would produce;
* a **separate** driver RNG picks the player's action.

Sharing one RNG would interleave the driver's draws with the match's and make
the fuzz runs unreproducible against anything else in the suite.

The driver calls ``roll_turn_order`` → ``choose_opponent_action`` →
``resolve_turn`` rather than ``play_turn`` for one reason: it needs to *see* the
opponent's move to assert it was legal. ``test_driver_matches_play_turn`` pins
the two paths together so this is not a second, divergent implementation.
"""

import random

import pytest

from game.rules import (
    STATUS_DRAW,
    STATUS_IN_PROGRESS,
    STATUS_OPPONENT_WON,
    STATUS_PLAYER_WON,
    TURN_CAP,
    choose_opponent_action,
    legal_actions,
    new_match,
    play_turn,
    resolve_turn,
    roll_turn_order,
)

MATCHES_PER_BATCH = 1000
MIRROR_MATCHES = 200
TERMINAL_STATUSES = {STATUS_PLAYER_WON, STATUS_OPPONENT_WON, STATUS_DRAW}


def _check_fighter(fighter: dict) -> None:
    """Assert one fighter's pools are inside their declared bounds (§8)."""
    assert 0 <= fighter["hp"] <= fighter["hp_max"], fighter
    assert 0 <= fighter["ki"] <= fighter["ki_max"], fighter


def _play_match(seed: int, player_id: str, opponent_id: str) -> dict:
    """Play one random-vs-random match, asserting per-turn invariants.

    Returns a summary: the terminal status, the turn it ended on, and whether it
    ended by KO rather than by the cap.
    """
    match_rng = random.Random(seed)
    driver_rng = random.Random(~seed)
    state = new_match(player_id, opponent_id)
    _check_fighter(state["player"])
    _check_fighter(state["opponent"])

    while state["status"] == STATUS_IN_PROGRESS:
        assert state["turn"] < TURN_CAP, "a capped match must not be asked for another turn"

        player_legal = legal_actions(state["player"])
        opponent_legal = legal_actions(state["opponent"])
        player_action = driver_rng.choice(player_legal)

        order = roll_turn_order(state, match_rng)
        opponent_action = choose_opponent_action(state, match_rng)
        assert opponent_action in opponent_legal, (opponent_action, opponent_legal)

        state, entries = resolve_turn(
            state, player_action, opponent_action, match_rng, order=order
        )

        chosen = {"player": player_action, "opponent": opponent_action}
        for entry in entries:
            assert entry["action"] == chosen[entry["actor"]]
        _check_fighter(state["player"])
        _check_fighter(state["opponent"])

    assert state["turn"] <= TURN_CAP
    ko = state["player"]["hp"] == 0 or state["opponent"]["hp"] == 0
    return {"status": state["status"], "turn": state["turn"], "ko": ko}


@pytest.fixture(scope="module")
def batch() -> list[dict]:
    """1000 seeded Kaito-vs-Vega matches, played once and shared (§9)."""
    return [_play_match(seed, "kaito", "vega") for seed in range(MATCHES_PER_BATCH)]


@pytest.fixture(scope="module")
def mirror_batch() -> list[dict]:
    """A mirror-match batch — Kaito vs Kaito, the §8 same-fighter case."""
    return [
        _play_match(seed, "kaito", "kaito")
        for seed in range(MATCHES_PER_BATCH, MATCHES_PER_BATCH + MIRROR_MATCHES)
    ]


def test_every_match_terminates_within_the_cap(batch):
    """The loop in ``_play_match`` only exits on a terminal status, so reaching
    here at all proves termination; this pins the turn bound as well (§8)."""
    assert len(batch) == MATCHES_PER_BATCH
    for result in batch:
        assert result["status"] in TERMINAL_STATUSES
        assert 1 <= result["turn"] <= TURN_CAP


def test_at_least_95_percent_end_by_ko(batch):
    """The cap is a safety net, not the normal ending (§8)."""
    ko_matches = sum(1 for result in batch if result["ko"])
    assert ko_matches >= 0.95 * MATCHES_PER_BATCH, f"only {ko_matches} of {len(batch)} ended by KO"


def test_a_ko_match_never_reports_draw(batch):
    """``draw`` has exactly one cause: the cap with both fighters alive (§4.6)."""
    for result in batch:
        if result["ko"]:
            assert result["status"] in {STATUS_PLAYER_WON, STATUS_OPPONENT_WON}
        else:
            assert result["turn"] == TURN_CAP


def test_both_sides_win_across_the_batch(batch):
    """Neither fighter is so dominant that the other never wins — a batch that
    only ever ends one way would hide half the KO path from every assertion
    above."""
    statuses = {result["status"] for result in batch}
    assert STATUS_PLAYER_WON in statuses
    assert STATUS_OPPONENT_WON in statuses


def test_mirror_matches_are_playable(mirror_batch):
    """Kaito vs Kaito ties on speed every turn, so this batch is also the one
    that exercises the tie coin flip on essentially every turn (§4.4, §8)."""
    assert len(mirror_batch) == MIRROR_MATCHES
    for result in mirror_batch:
        assert result["status"] in TERMINAL_STATUSES
        assert 1 <= result["turn"] <= TURN_CAP


def test_mirror_batch_also_ends_by_ko(mirror_batch):
    ko_matches = sum(1 for result in mirror_batch if result["ko"])
    assert ko_matches >= 0.95 * MIRROR_MATCHES


def test_fuzz_runs_are_reproducible():
    """The same seed replays identically — the fuzz results above are evidence
    about the rules, not about the run that happened to execute them (§4.8)."""
    assert _play_match(7, "kaito", "vega") == _play_match(7, "kaito", "vega")


def test_driver_matches_play_turn():
    """The driver's three-call composition is ``play_turn``, step for step.

    Without this the fuzz suite would be validating its own reimplementation of
    the turn loop instead of the one the app layer calls (§4.8, A1).
    """
    state = new_match("kaito", "vega")
    driver_rng = random.Random(99)
    composed_rng = random.Random(4)
    play_turn_rng = random.Random(4)
    composed = state
    direct = state

    for _ in range(10):
        if composed["status"] != STATUS_IN_PROGRESS:
            break
        player_action = driver_rng.choice(legal_actions(composed["player"]))

        order = roll_turn_order(composed, composed_rng)
        opponent_action = choose_opponent_action(composed, composed_rng)
        composed, _ = resolve_turn(
            composed, player_action, opponent_action, composed_rng, order=order
        )
        direct, _ = play_turn(direct, player_action, play_turn_rng)
        assert composed == direct
