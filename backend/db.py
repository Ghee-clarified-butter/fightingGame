"""Database engine, session factory and schema bootstrap (extension E6).

SQLAlchemy 2.0 over SQLite. The database file lives at
``backend/data/fightinggame.db`` and is gitignored (``*.db``). Only tournaments
persist here; Step 1's single-match store stays in memory (E6), so nothing in
this module is imported by ``game.rules`` or the single-match endpoints.

**Flask-SQLAlchemy is deliberately not used** (plan B13): it binds a session to
an app context, and E10 requires a persistence test that disposes the session
and rebuilds it against the same file *outside* any request. Plain SQLAlchemy
lets a test own an engine and a session factory directly.

A ``DATABASE_URL`` environment override lets tests point at a temp file or
``sqlite+pysqlite:///:memory:`` so no test ever writes the real database; an
explicit ``url`` argument to :func:`make_engine` overrides even that.
"""

import importlib
import importlib.util
import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

BACKEND_DIR = Path(__file__).resolve().parent
DATA_DIR = BACKEND_DIR / "data"
DEFAULT_DB_PATH = DATA_DIR / "fightinggame.db"


class Base(DeclarativeBase):
    """Declarative base every model inherits.

    The model classes themselves land in a later task (7.2); until then this
    base carries no tables, so :func:`init_db` bootstraps an empty schema. Once
    ``backend/models.py`` exists and defines classes on this base, importing it
    registers those tables on ``Base.metadata`` and :func:`init_db` creates
    them.
    """


def resolve_url(url: str | None = None) -> str:
    """Resolve the database URL: explicit arg → ``DATABASE_URL`` → default file.

    An explicit ``url`` wins so a test can be unambiguous; otherwise the
    ``DATABASE_URL`` environment override applies (the protection tests rely on
    to avoid the real database); otherwise the on-disk default at
    :data:`DEFAULT_DB_PATH`.
    """
    if url is not None:
        return url
    override = os.environ.get("DATABASE_URL")
    if override:
        return override
    return f"sqlite+pysqlite:///{DEFAULT_DB_PATH}"


def make_engine(url: str | None = None):
    """Create a SQLAlchemy engine for :func:`resolve_url`.

    Engine creation is lazy — no file is touched until the first connection —
    so the parent directory is created by :func:`init_db` at ``create_all``
    time rather than here.
    """
    return create_engine(resolve_url(url), future=True)


def make_session_factory(engine):
    """Return a :class:`sessionmaker` bound to ``engine``.

    ``expire_on_commit=False`` so a serialized bracket can still be read after
    the commit that produced it without a fresh round-trip, which matters for
    the create/advance-then-serialize flow the service layer uses (task 8).
    """
    return sessionmaker(bind=engine, future=True, expire_on_commit=False)


def _register_models() -> None:
    """Import ``backend/models.py`` if it exists so its tables register.

    Uses ``find_spec`` rather than a ``try/except ImportError`` so that a
    *missing* module is tolerated (it arrives in task 7.2) while a genuine
    import error *inside* an existing ``models.py`` still propagates instead of
    being silently swallowed.
    """
    if importlib.util.find_spec("models") is not None:
        importlib.import_module("models")


def init_db(engine) -> None:
    """Create every registered table on ``engine`` if it is not already there.

    Idempotent: SQLAlchemy issues ``CREATE TABLE IF NOT EXISTS``, so calling
    this on an already-initialised database is a no-op — which is what lets the
    app bootstrap the schema on every startup "if it is absent" (E6) without a
    migration step.
    """
    _register_models()
    db_path = engine.url.database
    if db_path and db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)
