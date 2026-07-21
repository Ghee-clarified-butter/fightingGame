"""Tests for the single-elimination bracket arithmetic (extension E7, plan 6.1).

Pure combinatorics, no database and no match runner: these assert the shape of
the bracket (size, byes, seed placement, advancement, per-match seeds) that the
tournament service later builds rows from. The E10 structural criteria — a
4-roster has no byes, a 5-roster byes the top 3, seeds 1 and 2 only meet in the
final — are proven here where they are cheapest to check.
"""

import pytest

from game.bracket import (
    InvalidRosterError,
    MAX_ROSTER,
    MIN_ROSTER,
    advance_position,
    bracket_size,
    first_round_pairs,
    match_seed,
    round_count,
    seed_order,
)


def _roster(n: int) -> list[str]:
    """A roster of ``n`` entrants; ids are irrelevant to bracket arithmetic."""
    return ["kaito"] * n


# --- bracket_size -----------------------------------------------------------

@pytest.mark.parametrize(
    "n, expected",
    [
        (2, 2), (3, 4), (4, 4), (5, 8), (7, 8), (8, 8),
        (9, 16), (15, 16), (16, 16),
    ],
)
def test_bracket_size_is_the_next_power_of_two(n, expected):
    assert bracket_size(n) == expected


@pytest.mark.parametrize("n", range(MIN_ROSTER, MAX_ROSTER + 1))
def test_bracket_size_is_a_power_of_two_at_least_n(n):
    size = bracket_size(n)
    assert size >= n
    assert size & (size - 1) == 0  # power of two
    assert size // 2 < n  # smallest such power: halving drops below n


@pytest.mark.parametrize("n", [0, 1, 17, 100, -1])
def test_bracket_size_rejects_out_of_range_rosters(n):
    with pytest.raises(InvalidRosterError) as excinfo:
        bracket_size(n)
    assert excinfo.value.args[0] == n


# --- round_count ------------------------------------------------------------

@pytest.mark.parametrize("size, rounds", [(2, 1), (4, 2), (8, 3), (16, 4)])
def test_round_count_is_log2_size(size, rounds):
    assert round_count(size) == rounds


# --- seed_order -------------------------------------------------------------

@pytest.mark.parametrize(
    "size, order",
    [
        (2, [1, 2]),
        (4, [1, 4, 2, 3]),
        (8, [1, 8, 4, 5, 2, 7, 3, 6]),
    ],
)
def test_seed_order_matches_the_spec_examples(size, order):
    assert seed_order(size) == order


def test_seed_order_is_a_permutation_of_one_to_size():
    for size in (2, 4, 8, 16):
        assert sorted(seed_order(size)) == list(range(1, size + 1))


def test_size_sixteen_round_one_pairs_each_sum_to_size_plus_one():
    order = seed_order(16)
    for i in range(8):
        assert order[2 * i] + order[2 * i + 1] == 17


@pytest.mark.parametrize("size", [4, 8, 16])
def test_top_two_seeds_land_in_opposite_halves(size):
    order = seed_order(size)
    half = size // 2
    top_half = set(order[:half])
    assert 1 in top_half
    assert 2 not in top_half  # seed 2 sits in the bottom half


# --- first_round_pairs ------------------------------------------------------

def test_four_fighter_bracket_has_two_matches_a_final_and_no_byes():
    pairs = first_round_pairs(_roster(4))
    assert len(pairs) == 2  # two first-round matches
    assert all(seed_b is not None for _, _, seed_b in pairs)  # no byes
    assert round_count(bracket_size(4)) == 2  # first round + final


def test_two_fighter_bracket_is_a_single_match_which_is_the_final():
    pairs = first_round_pairs(_roster(2))
    assert pairs == [(0, 1, 2)]
    assert round_count(bracket_size(2)) == 1  # the one match is the final


def test_five_fighter_bracket_matches_the_spec_worked_table():
    # E7.1: size 8, 3 byes, placement [1,8,4,5,2,7,3,6].
    pairs = first_round_pairs(_roster(5))
    assert pairs == [
        (0, 1, None),  # bye, seed 1 advances
        (1, 4, 5),     # ready
        (2, 2, None),  # bye, seed 2 advances
        (3, 3, None),  # bye, seed 3 advances
    ]
    byes = [seed_a for _, seed_a, seed_b in pairs if seed_b is None]
    assert sorted(byes) == [1, 2, 3]  # byes on the top three seeds


@pytest.mark.parametrize("n", range(MIN_ROSTER, MAX_ROSTER + 1))
def test_bye_count_and_placement_for_every_roster_size(n):
    size = bracket_size(n)
    pairs = first_round_pairs(_roster(n))
    assert len(pairs) == size // 2

    byes = sorted(seed_a for _, seed_a, seed_b in pairs if seed_b is None)
    assert len(byes) == size - n  # byes = size - n
    assert byes == list(range(1, size - n + 1))  # on the top (size - n) seeds

    # Every present seed 1..n appears exactly once across both positions.
    present = []
    for _, seed_a, seed_b in pairs:
        present.append(seed_a)
        if seed_b is not None:
            present.append(seed_b)
    assert sorted(present) == list(range(1, n + 1))


@pytest.mark.parametrize("n", [0, 1, 17])
def test_first_round_pairs_rejects_out_of_range_rosters(n):
    with pytest.raises(InvalidRosterError):
        first_round_pairs(_roster(n))


# --- advance_position -------------------------------------------------------

@pytest.mark.parametrize(
    "slot, expected",
    [
        (0, (2, 0, "a")),
        (1, (2, 0, "b")),
        (2, (2, 1, "a")),
        (3, (2, 1, "b")),
        (6, (2, 3, "a")),
        (7, (2, 3, "b")),
    ],
)
def test_advance_position_maps_slot_to_half_as_a_for_even_b_for_odd(slot, expected):
    assert advance_position(1, slot) == expected


def test_advance_position_increments_the_round():
    assert advance_position(3, 0)[0] == 4


# --- match_seed -------------------------------------------------------------

def test_match_seed_matches_the_e7_3_formula():
    root, round_, slot, attempt = 99, 2, 3, 0
    expected = (root * 1_000_003 + round_ * 1_009 + slot + attempt) % 2 ** 32
    assert match_seed(root, round_, slot, attempt) == expected


def test_match_seed_attempt_defaults_to_zero():
    assert match_seed(99, 2, 3) == match_seed(99, 2, 3, 0)


def test_match_seed_is_distinct_across_bracket_positions():
    seeds = {
        match_seed(99, r, s)
        for r in range(1, 5)
        for s in range(8)
    }
    # 4 rounds x 8 slots = 32 positions, all with distinct seeds.
    assert len(seeds) == 32


def test_match_seed_replay_differs_from_the_first_attempt():
    assert match_seed(99, 1, 0, 1) != match_seed(99, 1, 0, 0)


def test_match_seed_stays_within_thirty_two_bits():
    big = match_seed(2 ** 32 - 1, 4, 7, 9)
    assert 0 <= big < 2 ** 32
