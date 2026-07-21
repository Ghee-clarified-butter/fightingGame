"""Tournament service layer (extension E7, plan 8, B12).

The join between the pure bracket arithmetic (``game/bracket.py``), the headless
match runner (``game/arena.py``) and the declarative schema (``models.py``).
Nothing below it knows about SQLAlchemy; nothing here knows about HTTP. The app
layer stays validation → this service → serialize (B12), so a request handler
never builds a bracket or picks a match itself.

Task 8.1 is creation only: build the **entire** bracket up front — every round,
later ones ``pending`` — pre-resolve byes to a winner without playing them, and
reject a roster, fighter, difficulty or seed the bracket cannot be built from.
Advancing matches and serializing the bracket land in the following tasks.
"""

import uuid

from game import ai, bracket
from game.fighters import FIGHTERS, UnknownFighterError

import models

#: Tournament lifecycle states (E6.1). A freshly created bracket is ``pending``
#: until its first match is advanced; ``advance`` (task 8.2) drives the rest.
STATUS_PENDING = "pending"

#: Per-match lifecycle states (E6.1, E7.1). ``ready`` = both fighters known and
#: the match can be played; ``pending`` = at least one side still undetermined;
#: ``bye`` = a single-entrant slot, pre-resolved and never played.
MATCH_READY = "ready"
MATCH_PENDING = "pending"
MATCH_BYE = "bye"


class InvalidSeedError(ValueError):
    """Raised for a tournament seed that is not a plain integer (E8).

    The root seed drives every per-match seed (E7.3), so it must be an ``int``.
    ``bool`` is rejected explicitly — ``isinstance(True, int)`` is true in
    Python, so ``seed=True`` would otherwise silently seed the tournament with
    1. The offending value is carried in ``args[0]`` so the HTTP layer can quote
    it back in the §5.4 envelope without re-deriving it, mirroring the single
    match's ``invalid_seed`` (``app._parse_seed``).
    """


def _validate(roster, difficulty, seed) -> int:
    """Validate the creation inputs and return the bracket size.

    Runs **before** anything is added to the session, so a rejected request
    leaves zero rows behind (E8: every error asserts no tournament was created).
    The checks raise the vocabulary's own error type — ``InvalidSeedError``,
    ``UnknownDifficultyError`` (``ai``), ``InvalidRosterError`` (via
    ``bracket.bracket_size``) and ``UnknownFighterError`` (``fighters``) — so the
    service adds no error taxonomy of its own and the HTTP layer maps each to its
    §5.4 code (task 9.1).
    """
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise InvalidSeedError(seed)
    if difficulty not in ai.DIFFICULTIES:
        raise ai.UnknownDifficultyError(difficulty)
    # ``bracket_size`` is the single place roster size is validated: it raises
    # ``InvalidRosterError`` for a size outside ``[MIN_ROSTER, MAX_ROSTER]``.
    size = bracket.bracket_size(len(roster))
    for fighter_id in roster:
        if fighter_id not in FIGHTERS:
            raise UnknownFighterError(fighter_id)
    return size


def _new_match(tournament_id: str, round_: int, slot: int) -> models.TournamentMatch:
    """A blank bracket position with a fresh id, sides and winner unset.

    Callers fill in whichever of the fighter/seed/winner fields the position
    already knows; the round and slot are the coordinate the
    ``(tournament_id, round, slot)`` unique constraint keys on (E6.1).
    """
    return models.TournamentMatch(
        id=uuid.uuid4().hex,
        tournament_id=tournament_id,
        round=round_,
        slot=slot,
        status=MATCH_PENDING,
    )


def _propagate(matches: dict, round_: int, slot: int, winner_id, winner_seed) -> None:
    """Seat the winner of ``(round_, slot)`` into its parent slot (E7.2).

    Used at creation to carry a **bye** winner one round forward, since a bye is
    never played and so ``advance`` (task 8.2) never touches it — a round-2 slot
    fed entirely by byes would otherwise never learn its fighters and never
    become ready. The winner takes side A on an even slot and B on an odd one,
    and the parent flips ``pending`` → ``ready`` once both of its sides are
    known. A match fed by two byes therefore ends up ``ready`` (still to be
    played), never resolved: only round 1 has byes, so propagation is one level
    deep and never chains.

    The final has no parent (``advance_position`` points past the last round),
    so a missing parent is simply the tournament's top and is ignored.
    """
    next_round, next_slot, side = bracket.advance_position(round_, slot)
    parent = matches.get((next_round, next_slot))
    if parent is None:
        return
    setattr(parent, f"fighter_{side}_id", winner_id)
    setattr(parent, f"fighter_{side}_seed", winner_seed)
    if parent.fighter_a_seed is not None and parent.fighter_b_seed is not None:
        parent.status = MATCH_READY


def create_tournament(session, name: str, roster: list[str], difficulty: str,
                      seed: int) -> models.Tournament:
    """Create a tournament and its entire bracket, byes pre-resolved (E7, task 8.1).

    Builds every round up front — round 1 ``ready``/``bye``, every later slot
    ``pending`` — so the bracket's shape is fixed at creation and ``advance`` only
    ever fills in results (task 8.2). Byes fall on the top ``size - n`` seeds
    (E7.1); each is created ``bye`` with its lone entrant already the winner and
    that winner seated one round forward, so a bye is recorded but never played.

    Entrants are numbered by roster order (index 0 = seed 1) and identified by
    **seed**, not fighter id: a ``["kaito", "kaito"]`` roster is two distinct
    entrants in two rows, never one merged one (E7.2). The registry is seeded
    first so every fighter foreign key has a target.

    Raises :class:`InvalidSeedError`, ``ai.UnknownDifficultyError``,
    ``bracket.InvalidRosterError`` or ``UnknownFighterError`` for a bad input,
    each **before** any row is added, so a rejected creation leaves nothing
    behind. On success the tournament and all ``size - 1`` match rows are flushed
    and the :class:`models.Tournament` is returned; the caller owns the commit.
    """
    size = _validate(roster, difficulty, seed)
    models.seed_fighters(session)

    tournament_id = uuid.uuid4().hex
    tournament = models.Tournament(
        id=tournament_id,
        name=name,
        difficulty=difficulty,
        seed=seed,
        size=size,
        status=STATUS_PENDING,
    )
    session.add(tournament)

    matches: dict[tuple[int, int], models.TournamentMatch] = {}

    # Round 1: real pairings become ``ready``; a bye is resolved to its lone
    # entrant. ``first_round_pairs`` guarantees ``seed_a`` is always a real
    # entrant and only ``seed_b`` is ever absent (E7.1).
    for slot, seed_a, seed_b in bracket.first_round_pairs(roster):
        match = _new_match(tournament_id, 1, slot)
        match.fighter_a_id = roster[seed_a - 1]
        match.fighter_a_seed = seed_a
        if seed_b is None:
            match.status = MATCH_BYE
            match.winner_id = roster[seed_a - 1]
            match.winner_seed = seed_a
        else:
            match.fighter_b_id = roster[seed_b - 1]
            match.fighter_b_seed = seed_b
            match.status = MATCH_READY
        matches[(1, slot)] = match

    # Later rounds: one match per pair of slots below, all ``pending`` until
    # ``advance`` (or a bye, below) seats both fighters.
    for round_ in range(2, bracket.round_count(size) + 1):
        for slot in range(size >> round_):
            matches[(round_, slot)] = _new_match(tournament_id, round_, slot)

    for match in matches.values():
        session.add(match)

    # Carry each bye's winner one round forward, so a slot fed by byes is not
    # stranded ``pending`` with no match ever scheduled to fill it.
    for slot, seed_a, seed_b in bracket.first_round_pairs(roster):
        if seed_b is None:
            _propagate(matches, 1, slot, roster[seed_a - 1], seed_a)

    session.flush()
    return tournament
