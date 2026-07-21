"""Strength criteria for the AI policies (extension E10, plan 4.2).

These tests answer one question the per-rule and per-node tests cannot: *does the
smarter policy actually win more?* The answer is only meaningful in a **mirror
match**. The two starters are deliberately asymmetric (Kaito: 100 hp / 22 atk /
14 spd; Vega: 130 hp / 16 atk / 9 spd, §2.1), and with them the fighter decides
the game — every policy, heuristic or search, beats random only ~52% under fair
side-alternation, because being handed Kaito matters more than how you play.
Neutralising the fighter (Kaito vs Kaito) exposes the policy signal: search and
heuristic both crush random ~82-91%. So every measurement here is Kaito-vs-Kaito,
with the two policies swapped between the ``player`` and ``opponent`` sides across
seeds so that acting first on a speed tie is not an edge one policy keeps.

See E13 for why the original non-mirror 70%/55% criteria were unsatisfiable and
how the opponent-model change (E3.1) fixed the search losing to the heuristic.

Deterministic: every match is seeded, so the rates below are reproducible facts
about the implementation, not samples. After the E3.1 opponent-model change each
search selection is ~2 ms, so the whole file runs in a few seconds; B9's
escalation was never needed.
"""

import random

from game import ai, rules

#: Fixed sample size (E10). Sides are alternated within it, so it is also an even
#: split of who plays the ``player`` (first-on-a-tie) seat.
SEEDS = 200

#: Both starters are the same fighter, so the matchup is symmetric and any win
#: rate above 50% is pure policy skill (E10 note).
MIRROR = "kaito"


def _play_mirror(player_policy: str, opponent_policy: str, seed: int) -> str:
    """Play one Kaito-vs-Kaito match, each side on its own policy, and return the
    §4.6 terminal status.

    This drives the policies directly rather than through ``arena.run_ai_match``,
    which takes a single difficulty for both sides — a strength test needs the two
    sides on *different* policies. The draw order still follows §4.8: turn-order
    flip, then each side's choice (only ``random`` actually draws, E3.4), then the
    spreads inside ``resolve_turn``.
    """
    rng = random.Random(seed)
    state = rules.new_match(MIRROR, MIRROR, "random")
    while state["status"] == rules.STATUS_IN_PROGRESS:
        order = rules.roll_turn_order(state, rng)
        a = ai.choose_action(state, "player", player_policy, rng)
        b = ai.choose_action(state, "opponent", opponent_policy, rng)
        state, _ = rules.resolve_turn(state, a, b, rng, order=order)
    return state["status"]


def _win_rate(strong: str, weak: str, seeds: int = SEEDS) -> float:
    """Fraction of ``seeds`` mirror matches ``strong`` wins against ``weak``.

    On even seeds ``strong`` plays the ``player`` side, on odd seeds the
    ``opponent`` side, so the first-move-on-a-tie seat is split evenly between the
    two policies and cannot flatter either.
    """
    wins = 0
    for seed in range(seeds):
        if seed % 2 == 0:
            wins += _play_mirror(strong, weak, seed) == rules.STATUS_PLAYER_WON
        else:
            wins += _play_mirror(weak, strong, seed) == rules.STATUS_OPPONENT_WON
    return wins / seeds


def _ko_rate(a: str, b: str, seeds: int = SEEDS) -> float:
    """Fraction of ``seeds`` mirror matches that end by KO rather than the cap."""
    decided = sum(
        _play_mirror(a, b, seed) != rules.STATUS_DRAW for seed in range(seeds)
    )
    return decided / seeds


def test_search_beats_random_by_a_wide_margin():
    """E10: ≥70% over 200 mirror seeds. Measured: 82.0% on the reference machine
    (CPython 3.13.5). This is the search's real value — exploiting an opponent that
    is *not* playing the heuristic it models."""
    assert _win_rate("search", "random") >= 0.70


def test_search_is_not_a_regression_on_the_heuristic():
    """E10: ≥45% over 200 mirror seeds — parity, not dominance. Measured: 48.0%.

    A depth-2 search that models the opponent as the heuristic (E3.1) reconfirms
    the heuristic's own choices more often than it overturns them, so parity is the
    correct outcome; demanding >50% would drive eval over-fitting to two fighters
    (E13). What matters is that the search is *not worse* than the policy it
    extends — the adversarial version was, at 31%, which is the bug E3.1 fixed."""
    assert _win_rate("search", "heuristic") >= 0.45


def test_heuristic_mirror_matches_end_by_ko_not_the_cap():
    """E10 / E2.1: ≥95% of 200 heuristic-vs-heuristic matches end by KO. Measured:
    100.0% — the streak cap makes a stalemate to the turn cap essentially
    impossible, which is what keeps tournament results meaningful."""
    assert _ko_rate("heuristic", "heuristic") >= 0.95
