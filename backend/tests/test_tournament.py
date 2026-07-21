"""Tournament service — creation and advancement (extension E7, plan 8.1 / 8.2).

Exercises ``tournament.create_tournament`` and ``tournament.advance`` against a
temp-file database: the whole bracket is built at creation with byes pre-resolved
and never played, every bad input is rejected without leaving a row behind, and
advancing plays the next ready match AI-vs-AI, replays drawn attempts rather than
awarding them (E7.4), propagates winners and reaches a champion. Serialization
and standings arrive in task 8.3.
"""

import json

import pytest

import db
import models
import tournament
from game import arena, bracket
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


# --- advancement: helpers ----------------------------------------------------


def _play_out(session, tournament_id):
    """Advance a tournament until it is complete (or stalled)."""
    tour = session.get(models.Tournament, tournament_id)
    while tour.status not in (tournament.STATUS_COMPLETE, tournament.STATUS_STALLED):
        tournament.advance(session, tournament_id)
    return tour


def _position_summary(session, tournament_id):
    """The per-position result state used to compare two runs of a bracket."""
    return {
        (m.round, m.slot): (m.status, m.winner_id, m.winner_seed, m.turns,
                            m.attempts_json)
        for m in _matches(session, tournament_id)
    }


def _draw_result(turns=100):
    """An arena result for an undecided match (§4.6 draw, no winner)."""
    return {"winner": None, "winner_side": None, "turns": turns,
            "status": "draw", "log": []}


def _win_result(seed):
    """A decisive arena result that is a pure function of ``seed``.

    Deterministic in the seed so two tournaments at the same root reproduce the
    same winners, turns and logs even under a mocked runner.
    """
    winner = "a" if seed % 2 == 0 else "b"
    side = "player" if winner == "a" else "opponent"
    status = "player_won" if winner == "a" else "opponent_won"
    return {"winner": winner, "winner_side": side, "turns": seed % 40 + 1,
            "status": status, "log": [{"turn": 1, "actor": side}]}


# --- advancement: reaching a champion ---------------------------------------


@pytest.mark.parametrize("n", range(bracket.MIN_ROSTER, bracket.MAX_ROSTER + 1))
def test_advancing_reaches_a_champion(tmp_path, n):
    """For n in 2..16, advancing repeatedly reaches complete with a champion (E10)."""
    session = _session(tmp_path)
    tour = tournament.create_tournament(session, "Cup", _roster(n), "heuristic", 7)

    _play_out(session, tour.id)

    assert tour.status == "complete"
    assert tour.champion_id is not None
    # The champion is the winner of the last-round match.
    last_round = bracket.round_count(bracket.bracket_size(n))
    final = next(m for m in _matches(session, tour.id) if m.round == last_round)
    assert final.slot == 0
    assert final.status == "complete"
    assert tour.champion_id == final.winner_id
    assert final.winner_seed is not None


def test_winner_propagates_to_the_right_parent_slot_and_side(tmp_path):
    """Winner of (r, s) lands at (r+1, s//2) as A for even s, B for odd (E7.2)."""
    session = _session(tmp_path)
    tour = tournament.create_tournament(session, "Cup", _roster(8), "heuristic", 3)

    _play_out(session, tour.id)

    positions = {(m.round, m.slot): m for m in _matches(session, tour.id)}
    last_round = bracket.round_count(bracket.bracket_size(8))
    for (round_, slot), match in positions.items():
        if round_ == last_round:
            continue  # the final has no parent
        parent_round, parent_slot, side = bracket.advance_position(round_, slot)
        parent = positions[(parent_round, parent_slot)]
        seated = parent.fighter_a_seed if side == "a" else parent.fighter_b_seed
        assert seated == match.winner_seed
        assert side == ("a" if slot % 2 == 0 else "b")


def test_advancing_a_complete_tournament_raises(tmp_path):
    """advance on a resolved tournament raises TournamentComplete (E8, 409)."""
    session = _session(tmp_path)
    tour = tournament.create_tournament(session, "Duel", _roster(2), "heuristic", 5)

    _play_out(session, tour.id)
    assert tour.status == "complete"

    with pytest.raises(tournament.TournamentComplete):
        tournament.advance(session, tour.id)


# --- advancement: determinism and order independence ------------------------


def test_two_tournaments_at_the_same_seed_are_identical(tmp_path):
    """Same roster/difficulty/seed ⇒ identical champion, logs and turns (E10)."""
    roster = _roster(4)

    s1 = _session(tmp_path, "a.db")
    t1 = tournament.create_tournament(s1, "Cup", roster, "heuristic", 123)
    _play_out(s1, t1.id)

    s2 = _session(tmp_path, "b.db")
    t2 = tournament.create_tournament(s2, "Cup", roster, "heuristic", 123)
    _play_out(s2, t2.id)

    assert t1.champion_id == t2.champion_id
    assert _position_summary(s1, t1.id) == _position_summary(s2, t2.id)


def test_advance_order_does_not_change_results(tmp_path):
    """Advancing a bracket in a different order gives identical results (E7.3)."""
    roster = _roster(4)

    # Default order: lowest round, lowest slot first.
    s1 = _session(tmp_path, "a.db")
    t1 = tournament.create_tournament(s1, "Cup", roster, "heuristic", 55)
    _play_out(s1, t1.id)

    # Reversed: play round-1 slot 1 before slot 0, then finish the final.
    s2 = _session(tmp_path, "b.db")
    t2 = tournament.create_tournament(s2, "Cup", roster, "heuristic", 55)
    r1 = {m.slot: m for m in _matches(s2, t2.id) if m.round == 1}
    tournament.advance(s2, t2.id, match_id=r1[1].id)
    _play_out(s2, t2.id)

    assert t1.champion_id == t2.champion_id
    assert _position_summary(s1, t1.id) == _position_summary(s2, t2.id)


# --- advancement: a drawn attempt is replayed, never awarded (E7.4) ----------


def test_a_drawn_attempt_is_replayed_not_awarded(tmp_path, monkeypatch):
    """A draw records result 'draw' with no winner and replays at attempt+1."""
    session = _session(tmp_path)
    tour = tournament.create_tournament(session, "Duel", _roster(2), "heuristic", 5)

    calls = {"n": 0}

    def fake(a_id, b_id, difficulty, seed):
        calls["n"] += 1
        # First attempt draws; the replay at attempt 1 is decisive.
        return _draw_result() if calls["n"] == 1 else {
            "winner": "b", "winner_side": "opponent", "turns": 12,
            "status": "opponent_won", "log": [{"turn": 1}]}

    monkeypatch.setattr(arena, "run_ai_match", fake)

    tournament.advance(session, tour.id)
    match = _matches(session, tour.id)[0]

    attempts = json.loads(match.attempts_json)
    assert [a["attempt"] for a in attempts] == [0, 1]
    assert attempts[0]["result"] == "draw"
    assert "winner" not in attempts[0]
    assert attempts[1]["result"] == "opponent_won"
    # winner_seed comes only from the decisive attempt.
    assert match.winner_seed == match.fighter_b_seed
    assert match.winner_id == match.fighter_b_id
    assert match.turns == 12
    assert match.status == "complete"
    assert tour.status == "complete"  # a 2-fighter bracket is a single final


def test_ten_consecutive_draws_stall_the_tournament(tmp_path, monkeypatch):
    """Ten draws leave the match drawn_out and the tournament stalled (B10)."""
    session = _session(tmp_path)
    tour = tournament.create_tournament(session, "Duel", _roster(2), "heuristic", 5)

    monkeypatch.setattr(arena, "run_ai_match",
                        lambda a, b, d, s: _draw_result())

    tournament.advance(session, tour.id)
    match = _matches(session, tour.id)[0]

    attempts = json.loads(match.attempts_json)
    assert len(attempts) == tournament.MAX_ATTEMPTS == 10
    assert all(a["result"] == "draw" for a in attempts)
    assert match.status == "drawn_out"
    assert match.winner_id is None and match.winner_seed is None
    assert tour.status == "stalled"
    assert tour.champion_id is None
    # A stalled bracket has no ready match left to advance.
    with pytest.raises(tournament.NoReadyMatch):
        tournament.advance(session, tour.id)


def test_a_replayed_draw_reproduces_at_the_same_root_seed(tmp_path, monkeypatch):
    """A bracket containing a replayed draw still reproduces exactly (E7.4)."""
    roster = _roster(4)
    root = 21
    # Force the first round-1 match's first attempt to draw, keyed on its
    # position-derived seed — a pure function of the root, so it reproduces.
    draw_seed = bracket.match_seed(root, 1, 0, 0)

    def fake(a_id, b_id, difficulty, seed):
        return _draw_result() if seed == draw_seed else _win_result(seed)

    monkeypatch.setattr(arena, "run_ai_match", fake)

    s1 = _session(tmp_path, "a.db")
    t1 = tournament.create_tournament(s1, "Cup", roster, "heuristic", root)
    _play_out(s1, t1.id)

    s2 = _session(tmp_path, "b.db")
    t2 = tournament.create_tournament(s2, "Cup", roster, "heuristic", root)
    _play_out(s2, t2.id)

    replayed = next(m for m in _matches(s1, t1.id) if m.round == 1 and m.slot == 0)
    assert len(json.loads(replayed.attempts_json)) == 2  # one draw, one decisive
    assert t1.status == "complete"
    assert t1.champion_id == t2.champion_id
    assert _position_summary(s1, t1.id) == _position_summary(s2, t2.id)


# --- advancement: persistence across a restart ------------------------------


def test_results_survive_a_restart(tmp_path):
    """Create, advance, dispose, reopen the same file: bracket compares equal (E10)."""
    url = f"sqlite+pysqlite:///{tmp_path / 'persist.db'}"

    engine = db.make_engine(url)
    db.init_db(engine)
    session = db.make_session_factory(engine)()
    tour = tournament.create_tournament(session, "Cup", _roster(4), "heuristic", 7)
    tournament_id = tour.id
    tournament.advance(session, tournament_id)
    session.commit()
    before_status = tour.status
    before = _position_summary(session, tournament_id)
    session.close()
    engine.dispose()

    # Rebuild against the same file, outside any prior session.
    engine2 = db.make_engine(url)
    session2 = db.make_session_factory(engine2)()
    reopened = session2.get(models.Tournament, tournament_id)
    assert reopened is not None
    assert reopened.status == before_status
    assert _position_summary(session2, tournament_id) == before
    session2.close()
    engine2.dispose()
