"""Engine, schema bootstrap and the database-URL override (extension E6 / task 7.1).

No model tables exist yet — those arrive in task 7.2 — so these tests fix the
bootstrap *behaviour*: ``init_db`` is idempotent, a fresh path creates the file
and exactly the registered tables, and the override is honoured so no test ever
writes the real database.
"""

from pathlib import Path

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

import db
import models
from game.fighters import FIGHTERS


def _file_url(path: Path) -> str:
    return f"sqlite+pysqlite:///{path}"


def _session(tmp_path, name="models.db"):
    """A fresh, schema-initialised session over a temp file."""
    engine = db.make_engine(_file_url(tmp_path / name))
    db.init_db(engine)
    return db.make_session_factory(engine)()


def test_init_db_creates_the_file(tmp_path):
    """A fresh temp path has no database until init_db, then the file exists."""
    db_path = tmp_path / "fresh.db"
    assert not db_path.exists()

    engine = db.make_engine(_file_url(db_path))
    db.init_db(engine)

    assert db_path.exists()


def test_init_db_creates_a_missing_parent_directory(tmp_path):
    """init_db makes the parent directory, so a fresh clone needs no mkdir first."""
    db_path = tmp_path / "nested" / "dir" / "fresh.db"
    assert not db_path.parent.exists()

    db.init_db(db.make_engine(_file_url(db_path)))

    assert db_path.exists()


def test_init_db_creates_every_registered_table(tmp_path):
    """Every table on Base.metadata is created on the engine.

    With no models defined yet the registered set is empty, but the assertion is
    written against the metadata rather than a hard-coded list so it keeps
    holding once task 7.2 adds the model tables.
    """
    engine = db.make_engine(_file_url(tmp_path / "schema.db"))
    db.init_db(engine)

    created = set(inspect(engine).get_table_names())
    expected = set(db.Base.metadata.tables)
    assert created == expected


def test_init_db_is_idempotent(tmp_path):
    """Running init_db twice against the same file neither errors nor changes the schema."""
    engine = db.make_engine(_file_url(tmp_path / "twice.db"))

    db.init_db(engine)
    first = set(inspect(engine).get_table_names())
    db.init_db(engine)
    second = set(inspect(engine).get_table_names())

    assert first == second


def test_explicit_url_overrides_the_default_and_the_env(tmp_path, monkeypatch):
    """An explicit url wins over DATABASE_URL, which wins over the on-disk default."""
    monkeypatch.setenv("DATABASE_URL", _file_url(tmp_path / "from_env.db"))

    explicit = _file_url(tmp_path / "explicit.db")
    assert db.resolve_url(explicit) == explicit

    # No argument falls through to the environment override.
    assert db.resolve_url() == _file_url(tmp_path / "from_env.db")


def test_default_url_points_at_the_backend_data_file(monkeypatch):
    """With no arg and no override, the URL is the real backend/data file (E6)."""
    monkeypatch.delenv("DATABASE_URL", raising=False)

    assert db.resolve_url() == f"sqlite+pysqlite:///{db.DEFAULT_DB_PATH}"


def test_the_override_keeps_tests_off_the_real_database(tmp_path, monkeypatch):
    """A temp DATABASE_URL is honoured, so init_db never touches DEFAULT_DB_PATH."""
    override_path = tmp_path / "override.db"
    monkeypatch.setenv("DATABASE_URL", _file_url(override_path))

    engine = db.make_engine()
    db.init_db(engine)

    assert engine.url.database == str(override_path)
    assert override_path.exists()


def test_in_memory_url_needs_no_directory():
    """An in-memory database bootstraps without any filesystem side effect."""
    engine = db.make_engine("sqlite+pysqlite:///:memory:")
    db.init_db(engine)

    # ``:memory:`` databases are per-connection, so a table check must reuse the
    # same connection init_db ran on rather than opening a fresh one.
    assert engine.url.database == ":memory:"


# --- task 7.2: models -------------------------------------------------------


def _column(model, name):
    return inspect(model).columns[name]


def test_models_register_the_three_tables(tmp_path):
    """Importing models registers fighter, tournament and tournament_match."""
    engine = db.make_engine(_file_url(tmp_path / "tables.db"))
    db.init_db(engine)

    created = set(inspect(engine).get_table_names())
    assert {"fighter", "tournament", "tournament_match"} <= created


def test_fighter_table_stores_only_an_id():
    """E6.1: Fighter is id-only; no stat column may creep in and split the truth."""
    columns = {c.name for c in inspect(models.Fighter).columns}
    assert columns == {"id"}
    # Named explicitly so a later "helpful" addition of any stat fails loudly.
    for stat in ("hp_max", "ki_max", "atk", "def", "spd", "name"):
        assert stat not in columns


def test_tournament_columns_and_nullability():
    """Every E6.1 Tournament column exists with the right nullability."""
    not_null = {"id", "name", "difficulty", "seed", "size", "status", "created_at"}
    nullable = {"champion_id"}
    columns = {c.name: c for c in inspect(models.Tournament).columns}

    assert set(columns) == not_null | nullable
    for name in not_null:
        assert not columns[name].nullable, name
    for name in nullable:
        assert columns[name].nullable, name
    assert columns["id"].primary_key


def test_tournament_match_columns_and_nullability():
    """Every E6.1 / E7.2 TournamentMatch column exists with the right nullability."""
    not_null = {"id", "tournament_id", "round", "slot", "status"}
    nullable = {
        "fighter_a_id",
        "fighter_b_id",
        "fighter_a_seed",
        "fighter_b_seed",
        "winner_id",
        "winner_seed",
        "turns",
        "attempts_json",
    }
    columns = {c.name: c for c in inspect(models.TournamentMatch).columns}

    assert set(columns) == not_null | nullable
    for name in not_null:
        assert not columns[name].nullable, name
    for name in nullable:
        assert columns[name].nullable, name
    assert columns["id"].primary_key
    assert columns["tournament_id"].index


def test_match_position_is_unique(tmp_path):
    """(tournament_id, round, slot) is unique — the bracket coordinate is identity."""
    session = _session(tmp_path)
    models.seed_fighters(session)
    session.add(models.Tournament(
        id="t1", name="Cup", difficulty="heuristic", seed=1, size=4, status="pending",
    ))
    session.flush()

    session.add(models.TournamentMatch(
        id="m1", tournament_id="t1", round=1, slot=0, status="ready",
    ))
    session.add(models.TournamentMatch(
        id="m2", tournament_id="t1", round=1, slot=0, status="ready",
    ))
    with pytest.raises(IntegrityError):
        session.flush()


def test_two_matches_may_share_a_slot_across_tournaments(tmp_path):
    """The uniqueness is scoped to a tournament, not global (round, slot)."""
    session = _session(tmp_path)
    for tid in ("ta", "tb"):
        session.add(models.Tournament(
            id=tid, name="Cup", difficulty="heuristic", seed=1, size=4,
            status="pending",
        ))
    session.flush()

    session.add(models.TournamentMatch(
        id="ma", tournament_id="ta", round=1, slot=0, status="ready",
    ))
    session.add(models.TournamentMatch(
        id="mb", tournament_id="tb", round=1, slot=0, status="ready",
    ))
    session.flush()  # no IntegrityError

    assert session.get(models.TournamentMatch, "ma").slot == 0
    assert session.get(models.TournamentMatch, "mb").slot == 0


def test_seed_fighters_inserts_exactly_the_registry(tmp_path):
    """seed_fighters inserts exactly the ids in FIGHTERS."""
    session = _session(tmp_path)
    models.seed_fighters(session)

    ids = set(session.scalars(select(models.Fighter.id)))
    assert ids == set(FIGHTERS)


def test_seed_fighters_is_idempotent(tmp_path):
    """A second seed_fighters call adds nothing and never trips the primary key."""
    session = _session(tmp_path)
    models.seed_fighters(session)
    models.seed_fighters(session)  # must not raise on the duplicate ids

    ids = list(session.scalars(select(models.Fighter.id)))
    assert set(ids) == set(FIGHTERS)
    assert len(ids) == len(FIGHTERS)
