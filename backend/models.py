"""Declarative SQLAlchemy models for the persistent tournament (extension E6.1).

Declarative only (plan B12): no engine, no session lifecycle, no bracket logic
here. The service layer (``backend/tournament.py``) joins these tables to the
pure bracket arithmetic (``game/bracket.py``) and the match runner
(``game/arena.py``); these classes just describe the schema and the one bit of
reference data — the fighter registry — that the rest keys its foreign keys to.

**Only tournaments persist** (E6). Step 1's single-match store stays in memory,
so nothing in ``game/`` or the single-match endpoints imports this module.

**The ``Fighter`` table stores only an id** (E6.1). ``hp_max``, ``atk`` and the
rest live in ``game/fighters.py`` and are read from there at match time. Copying
them into the database would create a second source of truth that drifts the
moment a stat is tuned — old rows would keep the old numbers and a replayed
tournament would silently disagree with a fresh one at the same seed. The table
exists only to give ``TournamentMatch`` a foreign key to point at.

**Entrants are identified by seed, not fighter id** (E7.2). Duplicate fighter
ids are legal — a ``["kaito", "kaito"]`` bracket is two distinct entrants — so
every match carries ``fighter_a_seed`` / ``fighter_b_seed`` / ``winner_seed``
integers alongside the (non-unique) fighter ids. Keying on fighter id instead
would merge the two Kaito entrants into one row that is at once eliminated and
still playing.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    select,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db import Base
from game.fighters import FIGHTERS


def _utcnow() -> datetime:
    """Timezone-aware UTC now, so ``created_at`` sorts correctly across a restart."""
    return datetime.now(timezone.utc)


class Fighter(Base):
    """Registry of which fighter ids exist (E6.1).

    Seeded from :data:`game.fighters.FIGHTERS` on first run by
    :func:`seed_fighters`. Id only — never a stat column (see the module
    docstring); a later "helpful" addition of ``hp_max`` here is exactly the
    drift E6.1 forbids, and ``test_fighter_table_stores_only_an_id`` fails if one
    appears.
    """

    __tablename__ = "fighter"

    id: Mapped[str] = mapped_column(String, primary_key=True)


class Tournament(Base):
    """A single-elimination tournament and its run state (E6.1).

    ``size`` is the bracket size — a power of two at least the roster size — and
    ``seed`` is the root seed every match's per-match seed derives from (E7.3),
    which is what makes a whole tournament reproducible and its result
    order-independent. ``champion_id`` is set only when the final resolves.
    """

    __tablename__ = "tournament"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    difficulty: Mapped[str] = mapped_column(String, nullable=False)
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    champion_id: Mapped[str | None] = mapped_column(
        ForeignKey("fighter.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow
    )

    matches: Mapped[list["TournamentMatch"]] = relationship(
        back_populates="tournament",
        cascade="all, delete-orphan",
        order_by="TournamentMatch.round, TournamentMatch.slot",
    )


class TournamentMatch(Base):
    """One bracket position and every attempt played at it (E6.1, E7.2, E7.4).

    ``(tournament_id, round, slot)`` is unique — the bracket coordinate *is* the
    match's identity. ``round`` is 1-based, ``slot`` 0-based within the round.

    Both a fighter id and a seed are stored for each side. ``fighter_*_id`` is
    ``NULL`` before an entrant is determined or in the B position of a bye;
    ``fighter_*_seed`` is the entrant number (the identity that must not merge).
    ``winner_id`` / ``winner_seed`` are ``NULL`` until the match resolves.

    ``attempts_json`` holds every attempt as ``[{attempt, result, turns, log}]``
    — usually one entry, more when a draw was replayed (E7.4); a drawn attempt
    has ``result: "draw"`` and no winner. ``turns`` is the decisive attempt's
    turn count.
    """

    __tablename__ = "tournament_match"
    __table_args__ = (
        UniqueConstraint(
            "tournament_id", "round", "slot", name="uq_match_position"
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tournament_id: Mapped[str] = mapped_column(
        ForeignKey("tournament.id"), nullable=False, index=True
    )
    round: Mapped[int] = mapped_column(Integer, nullable=False)
    slot: Mapped[int] = mapped_column(Integer, nullable=False)
    fighter_a_id: Mapped[str | None] = mapped_column(
        ForeignKey("fighter.id"), nullable=True
    )
    fighter_b_id: Mapped[str | None] = mapped_column(
        ForeignKey("fighter.id"), nullable=True
    )
    fighter_a_seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fighter_b_seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    winner_id: Mapped[str | None] = mapped_column(
        ForeignKey("fighter.id"), nullable=True
    )
    winner_seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    turns: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attempts_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    tournament: Mapped[Tournament] = relationship(back_populates="matches")


def seed_fighters(session) -> None:
    """Populate the ``Fighter`` registry from :data:`FIGHTERS`, idempotently (E6.1).

    Inserts exactly the ids in ``FIGHTERS`` that are not already present, so a
    second call on the same session (or a later run against the same file) adds
    nothing and never raises on the primary key. ``flush`` makes the new rows
    visible to a query in the same transaction without committing — the caller
    owns the commit.
    """
    existing = set(session.scalars(select(Fighter.id)).all())
    for fighter_id in FIGHTERS:
        if fighter_id not in existing:
            session.add(Fighter(id=fighter_id))
    session.flush()
