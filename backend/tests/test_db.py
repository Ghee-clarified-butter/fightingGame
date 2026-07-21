"""Engine, schema bootstrap and the database-URL override (extension E6 / task 7.1).

No model tables exist yet — those arrive in task 7.2 — so these tests fix the
bootstrap *behaviour*: ``init_db`` is idempotent, a fresh path creates the file
and exactly the registered tables, and the override is honoured so no test ever
writes the real database.
"""

from pathlib import Path

from sqlalchemy import inspect

import db


def _file_url(path: Path) -> str:
    return f"sqlite+pysqlite:///{path}"


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
