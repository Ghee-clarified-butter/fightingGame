"""Single-elimination bracket arithmetic (extension E7, plan 6.1, B12).

Pure combinatorics over integers: how big a bracket a roster needs, where each
seed sits, who gets a bye, where a winner advances to, and what seed drives each
match's RNG. Nothing here touches SQLAlchemy, a match runner or a request — the
tournament service layer (``backend/tournament.py``) joins this to the database,
so this module is unit-testable without one (B12).

Entrants are numbered by roster order: index 0 is seed 1. Seeds, not fighter
ids, identify entrants everywhere, because duplicate fighter ids are legal and
two ``kaito`` entrants must not merge (E7.2).
"""

#: A roster must field at least a final's worth of fighters and no more than the
#: bracket cap. ``n`` outside ``[MIN_ROSTER, MAX_ROSTER]`` is ``invalid_roster``.
MIN_ROSTER = 2
MAX_ROSTER = 16

#: E7.3's per-match seed mixer. Large, coprime-ish multipliers keep adjacent
#: bracket positions far apart in the generator's output so sibling matches do
#: not share a draw sequence.
_SEED_MULT = 1_000_003
_ROUND_MULT = 1_009
_SEED_MODULUS = 2 ** 32


class InvalidRosterError(ValueError):
    """Raised for a roster the bracket cannot be built from (E7.2).

    Fewer than :data:`MIN_ROSTER` or more than :data:`MAX_ROSTER` entrants. The
    offending size is carried in ``args[0]`` so the HTTP layer can quote it back
    in the §5.4 envelope without re-deriving it.
    """


def bracket_size(n: int) -> int:
    """Return the bracket size for ``n`` entrants: ``2**ceil(log2(n))`` (E7.1).

    The smallest power of two that is at least ``n`` — so 4 fills a bracket of
    4, 5 needs 8, and 9 needs 16. Raises :class:`InvalidRosterError` for a size
    outside ``[MIN_ROSTER, MAX_ROSTER]``, which is the single place roster size
    is validated (``first_round_pairs`` and the service layer go through here).
    """
    if not MIN_ROSTER <= n <= MAX_ROSTER:
        raise InvalidRosterError(n)
    return 1 << (n - 1).bit_length()


def round_count(size: int) -> int:
    """Return the number of rounds in a bracket of ``size``: ``log2(size)``.

    Size 2 is one round (the final), 4 is two, 8 is three, 16 is four.
    """
    return size.bit_length() - 1


def seed_order(size: int) -> list[int]:
    """Return the standard bracket seed placement for a power-of-two ``size``.

    E7.1's recursive interleave::

        order(1)  = [1]
        order(2k) = interleave(order(k), [2k+1 - s for s in order(k)])

    giving ``[1, 2]``, ``[1, 4, 2, 3]``, ``[1, 8, 4, 5, 2, 7, 3, 6]`` for sizes
    2, 4, 8. Round-1 slot ``i`` pairs ``order[2i]`` against ``order[2i+1]``, so
    every first-round pair sums to ``size + 1`` (1 plays ``size``, 2 plays
    ``size - 1``, …) and the top two seeds land in opposite halves — they can
    only meet in the final. Placing seeds by slot order instead would let seeds
    1 and 2 meet in round 2, which is what E7.1 exists to prevent.
    """
    order = [1]
    half = 1
    while half < size:
        full = half * 2
        mirror = [full + 1 - s for s in order]
        order = [s for pair in zip(order, mirror) for s in pair]
        half = full
    return order


def first_round_pairs(roster: list[str]) -> list[tuple[int, int, int | None]]:
    """Return the round-1 pairings as ``(slot, seed_a, seed_b)`` (E7.1).

    ``seed_b`` is ``None`` for a bye. Byes fall on the top ``size - n`` seeds:
    the absent entrants are the numerically largest seeds (``n+1 .. size``), and
    standard seeding always pairs a better seed against a worse one, so every
    absent seed lands in the B position and ``seed_a`` is always a real entrant.

    A five-fighter roster (``size = 8``, placement ``[1,8,4,5,2,7,3,6]``) yields
    slot 0 ``(1, None)``, slot 1 ``(4, 5)``, slot 2 ``(2, None)``, slot 3
    ``(3, None)`` — three byes on seeds 1, 2, 3 in opposite halves, exactly
    E7.1's worked table.

    Raises :class:`InvalidRosterError` (via :func:`bracket_size`) for a roster
    size outside ``[MIN_ROSTER, MAX_ROSTER]``.
    """
    n = len(roster)
    size = bracket_size(n)
    order = seed_order(size)
    pairs: list[tuple[int, int, int | None]] = []
    for slot in range(size // 2):
        seed_a = order[2 * slot]
        seed_b = order[2 * slot + 1]
        # A seed is a real entrant iff it is within the roster; larger seeds are
        # the phantom opponents that a bye advances past.
        pairs.append((slot, seed_a, seed_b if seed_b <= n else None))
    return pairs


def advance_position(round_: int, slot: int) -> tuple[int, int, str]:
    """Return where the winner of ``(round_, slot)`` goes: ``(round, slot, side)``.

    The winner of round ``r`` slot ``s`` occupies round ``r+1`` slot ``s // 2``,
    as fighter **A** when ``s`` is even and **B** when ``s`` is odd (E7.2). So
    slots 0 and 1 feed the two sides of one next-round slot, 2 and 3 the next,
    and so on — a total, unambiguous mapping the service layer uses to promote a
    winner and flip the parent ``pending`` → ``ready``.
    """
    return round_ + 1, slot // 2, "a" if slot % 2 == 0 else "b"


def match_seed(root: int, round_: int, slot: int, attempt: int = 0) -> int:
    """Return the RNG seed for a bracket position (E7.3).

    ``(root * 1_000_003 + round * 1_009 + slot + attempt) % 2**32``. Deriving
    every match's seed from the tournament's root seed and its fixed bracket
    coordinates is what makes a match's result independent of the order matches
    are played in, and makes a whole tournament reproducible from one root seed.

    ``attempt`` starts at 0 and is bumped only when a drawn match is replayed
    (E7.4), so each replay draws a fresh but still-deterministic sequence.
    """
    mixed = root * _SEED_MULT + round_ * _ROUND_MULT + slot + attempt
    return mixed % _SEED_MODULUS
