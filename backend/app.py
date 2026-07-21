"""HTTP layer (spec §5, §6).

Validation → call into ``game.rules`` → serialize. No rule ever lives here: the
routes decide what a request is allowed to do, and the rules module decides what
happens when it does.

Step 1 keeps matches in memory (§6). The store is created per app instance
rather than at module scope so two ``create_app()`` calls — one per test — never
see each other's matches.
"""

import random
import uuid

from flask import Flask, jsonify, request
from sqlalchemy import select

import db
import models
import tournament
from game import ai, rules
from game.bracket import InvalidRosterError
from game.fighters import UnknownFighterError
from game.moves import MOVES


def _error(code: str, message: str, status: int):
    """Return the §5.4 error envelope with its HTTP status."""
    return jsonify({"error": {"code": code, "message": message}}), status


def serialize(match_id: str, state: dict) -> dict:
    """Render a match as the §5.5 state object.

    ``legal_actions`` is computed for the **player** only, so the UI can disable
    buttons without reimplementing any rule — it consumes the answer as data.
    It is empty once the match is over, so a finished match can never present a
    playable button (§5.5).
    """
    playable = state["status"] == rules.STATUS_IN_PROGRESS
    return {
        "match_id": match_id,
        "status": state["status"],
        "turn": state["turn"],
        "difficulty": state["difficulty"],
        "player": dict(state["player"]),
        "opponent": dict(state["opponent"]),
        "legal_actions": rules.legal_actions(state["player"]) if playable else [],
        "log": [dict(entry) for entry in state["log"]],
    }


def _parse_seed(payload: dict):
    """Return ``(seed, error)`` for the optional ``seed`` field (§5.1).

    ``bool`` is rejected explicitly: ``isinstance(True, int)`` is true in Python,
    so ``{"seed": true}`` would otherwise seed a match with 1.
    """
    if "seed" not in payload:
        return None, None
    seed = payload["seed"]
    if isinstance(seed, bool) or not isinstance(seed, int):
        return None, _error(
            "invalid_seed",
            f"seed must be an integer; got {seed!r}.",
            400,
        )
    return seed, None


def _parse_difficulty(payload: dict):
    """Return ``(difficulty, error)`` for the optional ``difficulty`` field (E4).

    Absent ⇒ ``"random"`` (E4: every Step 1 request stays valid). Any value
    outside :data:`ai.DIFFICULTIES` — including a non-string — is a 400
    ``unknown_difficulty``. Validation lives here, not in the rules (§6): the
    routes decide what a request may ask for, the rules decide what happens.
    """
    if "difficulty" not in payload:
        return "random", None
    difficulty = payload["difficulty"]
    if difficulty not in ai.DIFFICULTIES:
        return None, _error(
            "unknown_difficulty",
            f"difficulty must be one of {list(ai.DIFFICULTIES)}; got {difficulty!r}.",
            400,
        )
    return difficulty, None


def _validate_action(state: dict, action):
    """Return an error response for ``action``, or ``None`` if it is playable.

    The checks run in a fixed precedence so a request that is wrong in more than
    one way always reports the same code: ``match_over`` → ``unknown_action`` →
    ``already_ascended`` → ``insufficient_ki``. Status comes first because a
    finished match accepts nothing at all; ``already_ascended`` comes before the
    ki check because being out of Ascends is the more specific reason, and it
    stays true no matter how much ki the fighter later charges up.
    """
    if state["status"] != rules.STATUS_IN_PROGRESS:
        return _error(
            "match_over",
            f"This match is already over ({state['status']}).",
            409,
        )

    if action not in MOVES:
        # A missing ``action`` lands here too, by §5.4.
        return _error("unknown_action", f"Unknown action: {action!r}.", 400)

    move = MOVES[action]
    player = state["player"]

    if action == "ascend" and player["ascend_used"]:
        return _error(
            "already_ascended",
            f"{player['name']} has already ascended this match.",
            400,
        )

    if player["ki"] < move["cost"]:
        return _error(
            "insufficient_ki",
            f"{move['name']} costs {move['cost']} ki; "
            f"{player['name']} has {player['ki']}.",
            400,
        )

    return None


def create_app(database_url: str | None = None) -> Flask:
    """Build the Flask app and its in-memory match store (§6).

    A tournament database engine is bootstrapped alongside the in-memory match
    store: the schema is created on startup if it is absent (E6), so a fresh
    clone works with no migration step. ``database_url`` overrides the location
    (the default resolves through :func:`db.resolve_url`), which is what lets a
    test point the app at a temp file instead of the real database. Single
    matches stay ephemeral in ``matches``; only tournaments persist (E6).
    """
    app = Flask(__name__)

    # match_id (UUID4 hex) -> {"state": <rules state>, "rng": <match RNG>}.
    # The RNG lives beside the state because determinism is a property of the
    # match, not of a request: every draw for a match comes from this one
    # generator, in the §4.8 order.
    matches: dict[str, dict] = {}
    app.extensions["matches"] = matches

    # The engine and session factory live on the app so later tournament
    # endpoints (task 9) open a request-scoped session without a global.
    engine = db.make_engine(database_url)
    db.init_db(engine)
    app.extensions["db_engine"] = engine
    app.extensions["db_session_factory"] = db.make_session_factory(engine)

    @app.post("/api/match")
    def create_match():
        payload = request.get_json(silent=True) or {}

        seed, error = _parse_seed(payload)
        if error is not None:
            return error

        difficulty, error = _parse_difficulty(payload)
        if error is not None:
            return error

        try:
            state = rules.new_match(
                payload.get("player_fighter"),
                payload.get("opponent_fighter"),
                difficulty=difficulty,
            )
        except UnknownFighterError as exc:
            return _error("unknown_fighter", f"Unknown fighter id: {exc.args[0]!r}.", 400)

        match_id = uuid.uuid4().hex
        # Seedless matches get a fresh Random() — seeded from the OS — rather
        # than the module-level generator, so unrelated matches cannot interleave
        # draws with one another (§4.8).
        matches[match_id] = {
            "state": state,
            "rng": random.Random(seed) if seed is not None else random.Random(),
        }
        return jsonify(serialize(match_id, state)), 201

    @app.get("/api/match/<match_id>")
    def get_match(match_id: str):
        # Read-only (§5.3): an unknown id is a 404, never a match created on
        # demand — otherwise a typo'd id would silently start a new fight.
        match = matches.get(match_id)
        if match is None:
            return _error("match_not_found", f"No match with id {match_id!r}.", 404)
        return jsonify(serialize(match_id, match["state"])), 200

    @app.post("/api/match/<match_id>/turn")
    def submit_turn(match_id: str):
        match = matches.get(match_id)
        if match is None:
            return _error("match_not_found", f"No match with id {match_id!r}.", 404)

        payload = request.get_json(silent=True) or {}
        action = payload.get("action")

        error = _validate_action(match["state"], action)
        if error is not None:
            return error

        # ``ai.play_turn`` picks the opponent's move itself, from the difficulty
        # stored on the state, and only after this point — so a turn rejected
        # above never advances the match RNG (§4.7, E3.4).
        state, _ = ai.play_turn(match["state"], action, match["rng"])
        # The state is replaced rather than mutated in place: ``resolve_turn``
        # works on a copy (§6), so the store only adopts the new one once the
        # whole turn resolved without raising.
        match["state"] = state
        return jsonify(serialize(match_id, state)), 200

    @app.post("/api/tournament")
    def create_tournament_route():
        """Create a tournament and its whole bracket (E8, task 9.1).

        Validation → ``tournament.create_tournament`` → ``serialize_bracket``
        (B12). Shape checks the service does not own live here: ``roster`` must be
        a list and ``difficulty`` is defaulted/validated by :func:`_parse_difficulty`
        exactly as a single match's is. Everything the service validates —
        ``invalid_seed``, ``unknown_fighter``, and the roster *size* half of
        ``invalid_roster`` — is caught below and mapped to its §5.4 code. The
        service raises **before** adding any row (see ``tournament._validate``), so
        a rejected request leaves the database untouched; the ``rollback`` is belt
        and braces for the fighter-registry rows ``create_tournament`` flushes
        first.
        """
        payload = request.get_json(silent=True) or {}

        name = payload.get("name", "")
        if not isinstance(name, str):
            return _error(
                "invalid_name", f"name must be a string; got {name!r}.", 400
            )

        roster = payload.get("roster")
        if not isinstance(roster, list):
            return _error(
                "invalid_roster",
                f"roster must be a list of fighter ids; got {roster!r}.",
                400,
            )

        difficulty, error = _parse_difficulty(payload)
        if error is not None:
            return error

        session = app.extensions["db_session_factory"]()
        try:
            tour = tournament.create_tournament(
                session, name, roster, difficulty, payload.get("seed")
            )
            body = tournament.serialize_bracket(tour)
            session.commit()
        except tournament.InvalidSeedError as exc:
            session.rollback()
            return _error(
                "invalid_seed", f"seed must be an integer; got {exc.args[0]!r}.", 400
            )
        except InvalidRosterError as exc:
            session.rollback()
            return _error(
                "invalid_roster",
                f"a roster of {exc.args[0]} is not a legal size (2..16).",
                400,
            )
        except UnknownFighterError as exc:
            session.rollback()
            return _error(
                "unknown_fighter", f"Unknown fighter id: {exc.args[0]!r}.", 400
            )
        except ai.UnknownDifficultyError as exc:
            session.rollback()
            return _error(
                "unknown_difficulty",
                f"difficulty must be one of {list(ai.DIFFICULTIES)}; "
                f"got {exc.args[0]!r}.",
                400,
            )
        finally:
            session.close()
        return jsonify(body), 201

    @app.get("/api/tournament/<tournament_id>")
    def get_tournament_route(tournament_id: str):
        """Return a tournament's bracket, read-only (E8, task 9.1).

        An unknown id is a 404, never a tournament created on demand — the same
        stance the single-match GET takes (§5.3). The session is opened only to
        read and is always closed.
        """
        session = app.extensions["db_session_factory"]()
        try:
            tour = session.get(models.Tournament, tournament_id)
            if tour is None:
                return _error(
                    "tournament_not_found",
                    f"No tournament with id {tournament_id!r}.",
                    404,
                )
            body = tournament.serialize_bracket(tour)
        finally:
            session.close()
        return jsonify(body), 200

    @app.post("/api/tournament/<tournament_id>/advance")
    def advance_tournament_route(tournament_id: str):
        """Play the next ready match and return the updated bracket (E8, task 9.2).

        Validation → ``tournament.advance`` → ``serialize_bracket`` (B12). The id
        is checked first so an unknown tournament is a 404 rather than an
        ``AttributeError`` inside the service. ``advance`` plays exactly one match
        (E8's "next" = lowest round then lowest slot), so repeated POSTs walk the
        bracket to a champion one match at a time. A completed tournament raises
        :class:`tournament.TournamentComplete` → 409 ``tournament_complete``, and a
        bracket with nothing ``ready`` (a ``pending`` wait or a ``stalled`` slot)
        raises :class:`tournament.NoReadyMatch` → 409 ``no_ready_match``; on either
        the transaction is rolled back so the bracket is unchanged afterwards.
        """
        session = app.extensions["db_session_factory"]()
        try:
            tour = session.get(models.Tournament, tournament_id)
            if tour is None:
                return _error(
                    "tournament_not_found",
                    f"No tournament with id {tournament_id!r}.",
                    404,
                )
            tour = tournament.advance(session, tournament_id)
            body = tournament.serialize_bracket(tour)
            session.commit()
        except tournament.TournamentComplete:
            session.rollback()
            return _error(
                "tournament_complete",
                f"Tournament {tournament_id!r} is already complete.",
                409,
            )
        except tournament.NoReadyMatch:
            session.rollback()
            return _error(
                "no_ready_match",
                f"Tournament {tournament_id!r} has no match ready to play.",
                409,
            )
        finally:
            session.close()
        return jsonify(body), 200

    @app.get("/api/tournaments")
    def list_tournaments_route():
        """List every tournament, newest first (E8, task 9.2).

        The persistence-visible endpoint: each row is the
        :func:`tournament.serialize_summary` shape (``id``, ``name``, ``status``,
        ``champion``, ``created_at``), ordered by ``created_at`` descending so the
        most recent tournament is first. A second app instance built over the same
        database file still lists everything here, which is the restart criterion
        at the HTTP layer (E8). Read-only; the session is opened only to read and
        always closed.
        """
        session = app.extensions["db_session_factory"]()
        try:
            tours = session.scalars(
                select(models.Tournament).order_by(
                    models.Tournament.created_at.desc()
                )
            ).all()
            body = [tournament.serialize_summary(tour) for tour in tours]
        finally:
            session.close()
        return jsonify(body), 200

    return app


app = create_app()
