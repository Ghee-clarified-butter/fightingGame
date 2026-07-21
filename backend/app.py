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

from game import rules
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


def create_app() -> Flask:
    """Build the Flask app and its in-memory match store (§6)."""
    app = Flask(__name__)

    # match_id (UUID4 hex) -> {"state": <rules state>, "rng": <match RNG>}.
    # The RNG lives beside the state because determinism is a property of the
    # match, not of a request: every draw for a match comes from this one
    # generator, in the §4.8 order.
    matches: dict[str, dict] = {}
    app.extensions["matches"] = matches

    @app.post("/api/match")
    def create_match():
        payload = request.get_json(silent=True) or {}

        seed, error = _parse_seed(payload)
        if error is not None:
            return error

        try:
            state = rules.new_match(
                payload.get("player_fighter"), payload.get("opponent_fighter")
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

        # ``play_turn`` draws the opponent's move itself, and only after this
        # point — so a turn rejected above never advances the match RNG (§4.7).
        state, _ = rules.play_turn(match["state"], action, match["rng"])
        # The state is replaced rather than mutated in place: ``resolve_turn``
        # works on a copy (§6), so the store only adopts the new one once the
        # whole turn resolved without raising.
        match["state"] = state
        return jsonify(serialize(match_id, state)), 200

    return app


app = create_app()
