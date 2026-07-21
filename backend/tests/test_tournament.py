"""Tournament service — creation (extension E7, plan 8.1).

Exercises ``tournament.create_tournament`` against a temp-file database: the
whole bracket is built at creation with byes pre-resolved and never played, and
every bad input is rejected without leaving a row behind. Advancement,
serialization and standings arrive in tasks 8.2 / 8.3.
"""

import pytest

import db
import models
import tournament
from game import bracket
from game.ai import UnknownDifficultyError
from game.bracket import InvalidRosterError
from game.fighters import FIGHTERS, UnknownFighterError


def _session(tmp_path, name="tournament.db"):
    """A fresh, schema-initialised session over a temp file."""
    engine = db.make_engine(f"sqlite+pysqlite:///{tmp_path / name}")
    db.init_db(engine)
    return db.make_session_factory(engine)()


def _matches(session, tournament_id):
    """Every match row of a tournament, ordered by (round, slot)."""
    tour = session.get(models.Tournament, tournament_id)
    return sorted(tour.matches, key=lambda m: (m.round, m.slot))


def _roster(n):
    """An ``n``-fighter roster, cycling the known fighter ids."""
    ids = list(FIGHTERS)
    return [ids[i % len(ids)] for i in range(n)]


# --- shape: rows, rounds, byes for every legal roster size ------------------


@pytest.mark.parametrize("n", range(bracket.MIN_ROSTER, bracket.MAX_ROSTER + 1))
def test_bracket_shape_for_every_roster_size(tmp_path, n):
    """For n in 2..16 the row count, round count and bye count are exact."""
    session = _session(tmp_path)
    tour = tournament.create_tournament(session, "Cup", _roster(n), "heuristic", 7)

    size = bracket.bracket_size(n)
    rows = _matches(session, tour.id)

    assert tour.size == size
    # A single-elimination bracket of ``size`` has exactly ``size - 1`` matches.
    assert len(rows) == size - 1
    # Every round 1..round_count is present with the right slot count.
    for round_ in range(1, bracket.round_count(size) + 1):
        in_round = [m for m in rows if m.round == round_]
        assert len(in_round) == size >> round_
    # Byes number ``size - n`` and are all in round 1.
    byes = [m for m in rows if m.status == "bye"]
    assert len(byes) == size - n
    assert all(m.round == 1 for m in byes)


@pytest.mark.parametrize("n", range(bracket.MIN_ROSTER, bracket.MAX_ROSTER + 1))
def test_byes_fall_on_the_top_seeds(tmp_path, n):
    """Byes sit on seeds 1..(size - n) — the top seeds, in opposite halves (E7.1)."""
    session = _session(tmp_path)
    tour = tournament.create_tournament(session, "Cup", _roster(n), "search", 3)

    size = bracket.bracket_size(n)
    byes = [m for m in _matches(session, tour.id) if m.status == "bye"]
    bye_seeds = {m.fighter_a_seed for m in byes}

    assert bye_seeds == set(range(1, size - n + 1))


def test_four_fighter_bracket_has_no_byes(tmp_path):
    """A 4-fighter roster: 2 first-round matches, 1 final, no byes (E10)."""
    session = _session(tmp_path)
    tour = tournament.create_tournament(session, "Cup", _roster(4), "heuristic", 1)

    rows = _matches(session, tour.id)
    round1 = [m for m in rows if m.round == 1]
    final = [m for m in rows if m.round == 2]

    assert len(round1) == 2
    assert all(m.status == "ready" for m in round1)
    assert len(final) == 1
    assert final[0].status == "pending"
    assert not [m for m in rows if m.status == "bye"]


def test_five_fighter_bracket_matches_the_worked_table(tmp_path):
    """n=5 → size 8, 3 byes on seeds 1/2/3, one ready pairing 4v5 (E7.1 table)."""
    session = _session(tmp_path)
    roster = _roster(5)
    tour = tournament.create_tournament(session, "Cup", roster, "heuristic", 42)

    assert tour.size == 8
    round1 = {m.slot: m for m in _matches(session, tour.id) if m.round == 1}

    # Placement [1,8,4,5,2,7,3,6]: slot 0 bye(1), slot 1 ready(4v5),
    # slot 2 bye(2), slot 3 bye(3).
    assert round1[0].status == "bye" and round1[0].fighter_a_seed == 1
    assert round1[1].status == "ready"
    assert (round1[1].fighter_a_seed, round1[1].fighter_b_seed) == (4, 5)
    assert round1[2].status == "bye" and round1[2].fighter_a_seed == 2
    assert round1[3].status == "bye" and round1[3].fighter_a_seed == 3


def test_two_fighter_bracket_is_a_single_final(tmp_path):
    """A 2-fighter roster produces exactly one match, which is the final (E10)."""
    session = _session(tmp_path)
    tour = tournament.create_tournament(session, "Duel", _roster(2), "random", 5)

    rows = _matches(session, tour.id)
    assert len(rows) == 1
    assert rows[0].round == 1  # round 1 == the final when size is 2
    assert rows[0].status == "ready"
    assert (rows[0].fighter_a_seed, rows[0].fighter_b_seed) == (1, 2)


# --- byes carry a winner and are seated forward, never played ---------------


def test_byes_carry_a_winner_and_are_never_played(tmp_path):
    """A bye's winner is its lone entrant and it has no attempts recorded."""
    session = _session(tmp_path)
    tour = tournament.create_tournament(session, "Cup", _roster(5), "heuristic", 9)

    for match in _matches(session, tour.id):
        if match.status == "bye":
            assert match.winner_seed == match.fighter_a_seed
            assert match.winner_id == match.fighter_a_id
            assert match.fighter_b_id is None
            assert match.fighter_b_seed is None
            # Never played: no turns, no attempt log.
            assert match.turns is None
            assert match.attempts_json is None


def test_bye_winner_is_seated_in_the_next_round(tmp_path):
    """A bye advances its entrant one round forward so no slot is stranded (E7.2)."""
    session = _session(tmp_path)
    tour = tournament.create_tournament(session, "Cup", _roster(5), "heuristic", 9)

    round2 = {m.slot: m for m in _matches(session, tour.id) if m.round == 2}

    # Byes on slots 0, 2, 3. Slot 0 → round2 slot0 side A; slots 2,3 →
    # round2 slot1 sides A,B. So round2 slot1 is fed by two byes (seeds 2, 3)
    # and is now ready; round2 slot0 has only its A side (seed 1) and waits.
    assert round2[0].fighter_a_seed == 1
    assert round2[0].fighter_b_seed is None
    assert round2[0].status == "pending"

    assert (round2[1].fighter_a_seed, round2[1].fighter_b_seed) == (2, 3)
    assert round2[1].status == "ready"


# --- duplicate ids stay distinct entrants -----------------------------------


def test_duplicate_fighter_ids_are_distinct_entrants(tmp_path):
    """A ["kaito","kaito"] roster is two rows keyed by seed, not one (E7.2)."""
    session = _session(tmp_path)
    tour = tournament.create_tournament(session, "Mirror", ["kaito", "kaito"],
                                        "heuristic", 1)

    rows = _matches(session, tour.id)
    assert len(rows) == 1
    final = rows[0]
    assert final.fighter_a_id == "kaito"
    assert final.fighter_b_id == "kaito"
    # Distinct entrants: same fighter id, different seed.
    assert final.fighter_a_seed == 1
    assert final.fighter_b_seed == 2
    assert final.fighter_a_seed != final.fighter_b_seed


# --- rejections leave nothing behind ----------------------------------------


def _no_rows(session):
    return (session.query(models.Tournament).count() == 0
            and session.query(models.TournamentMatch).count() == 0)


@pytest.mark.parametrize("n", [0, 1, 17])
def test_invalid_roster_size_is_rejected(tmp_path, n):
    """Rosters of size 0, 1 and 17 raise InvalidRosterError and add no rows."""
    session = _session(tmp_path)
    with pytest.raises(InvalidRosterError):
        tournament.create_tournament(session, "Cup", _roster(n), "heuristic", 1)
    assert _no_rows(session)


def test_unknown_fighter_is_rejected(tmp_path):
    """A roster with an unknown id raises UnknownFighterError and adds no rows."""
    session = _session(tmp_path)
    with pytest.raises(UnknownFighterError):
        tournament.create_tournament(session, "Cup", ["kaito", "nobody"],
                                     "heuristic", 1)
    assert _no_rows(session)


def test_unknown_difficulty_is_rejected(tmp_path):
    """An unknown difficulty raises UnknownDifficultyError and adds no rows."""
    session = _session(tmp_path)
    with pytest.raises(UnknownDifficultyError):
        tournament.create_tournament(session, "Cup", _roster(4), "nightmare", 1)
    assert _no_rows(session)


@pytest.mark.parametrize("seed", [True, 1.5, "5", None])
def test_invalid_seed_is_rejected(tmp_path, seed):
    """A non-integer seed (including bool) raises InvalidSeedError and adds no rows."""
    session = _session(tmp_path)
    with pytest.raises(tournament.InvalidSeedError):
        tournament.create_tournament(session, "Cup", _roster(4), "heuristic", seed)
    assert _no_rows(session)


# --- persisted fields the later tasks and the API rely on -------------------


def test_created_tournament_persists_its_metadata(tmp_path):
    """The tournament row carries name, difficulty, seed, size and a pending status."""
    session = _session(tmp_path)
    tour = tournament.create_tournament(session, "Spring Cup", _roster(4),
                                        "search", 99)

    stored = session.get(models.Tournament, tour.id)
    assert stored.name == "Spring Cup"
    assert stored.difficulty == "search"
    assert stored.seed == 99
    assert stored.size == 4
    assert stored.status == "pending"
    assert stored.champion_id is None


def test_creation_seeds_the_fighter_registry(tmp_path):
    """Creation seeds the Fighter registry so every fighter foreign key resolves."""
    session = _session(tmp_path)
    tournament.create_tournament(session, "Cup", _roster(4), "heuristic", 1)

    ids = {f.id for f in session.query(models.Fighter).all()}
    assert set(FIGHTERS) <= ids
