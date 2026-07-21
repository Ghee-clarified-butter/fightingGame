"""Tournament service layer (extension E7, plan 8, B12).

The join between the pure bracket arithmetic (``game/bracket.py``), the headless
match runner (``game/arena.py``) and the declarative schema (``models.py``).
Nothing below it knows about SQLAlchemy; nothing here knows about HTTP. The app
layer stays validation → this service → serialize (B12), so a request handler
never builds a bracket or picks a match itself.

Task 8.1 built the whole bracket at creation; task 8.2 (``advance``) plays the
next ready match AI-vs-AI at its derived seed, replays a drawn attempt rather
than awarding it (E7.4), promotes the winner one round forward, and completes the
tournament when the final resolves. Task 8.3 (``serialize_bracket``) renders it as
the E8.1 object with derived, never-stored standings.
"""

import json
import uuid

from game import ai, arena, bracket
from game.fighters import FIGHTERS, UnknownFighterError

import models

#: Tournament lifecycle states (E6.1, E7.4). A freshly created bracket is
#: ``pending``; the first ``advance`` moves it to ``in_progress``; it reaches
#: ``complete`` when the final resolves, or ``stalled`` if a match draws out.
STATUS_PENDING = "pending"
STATUS_IN_PROGRESS = "in_progress"
STATUS_COMPLETE = "complete"
STATUS_STALLED = "stalled"

#: Per-match lifecycle states (E6.1, E7.1, E7.4). ``ready`` = both fighters known
#: and the match can be played; ``pending`` = at least one side still
#: undetermined; ``bye`` = a single-entrant slot, pre-resolved and never played;
#: ``complete`` = a decisive attempt was recorded; ``drawn_out`` = every one of
#: the ``MAX_ATTEMPTS`` attempts drew (E7.4), so no winner was ever awarded.
MATCH_READY = "ready"
MATCH_PENDING = "pending"
MATCH_BYE = "bye"
MATCH_COMPLETE = "complete"
MATCH_DRAWN_OUT = "drawn_out"

#: Hard cap on replayed drawn attempts before a match is abandoned (E7.4, B10).
#: A drawn slot is replayed at ``attempt + 1`` until decisive; ten draws in a row
#: at ten different seeds should be unreachable (E10 requires ≥95% KO), but an
#: unbounded retry loop inside a request handler is not acceptable.
MAX_ATTEMPTS = 10


class TournamentComplete(Exception):
    """Raised by :func:`advance` when the final has already resolved (E8).

    The HTTP layer maps this to ``409 tournament_complete`` (task 9.2). A
    ``stalled`` tournament is *not* complete — it raises :class:`NoReadyMatch`
    instead, because a stall means no more matches can ever be played, not that a
    champion was crowned.
    """


class NoReadyMatch(Exception):
    """Raised by :func:`advance` when no ``ready`` match is available (E8).

    Either every remaining match is still ``pending`` on an undetermined fighter,
    or the tournament has ``stalled`` (E7.4). The HTTP layer maps this to
    ``409 no_ready_match`` (task 9.2).
    """


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


def _propagate(matches: dict, round_: int, slot: int, winner_id, winner_seed):
    """Seat the winner of ``(round_, slot)`` into its parent slot (E7.2).

    Used at creation to carry a **bye** winner one round forward, and by
    ``advance`` to promote a decisive winner. The winner takes side A on an even
    slot and B on an odd one, and the parent flips ``pending`` → ``ready`` once
    both of its sides are known. A match fed by two byes therefore ends up
    ``ready`` (still to be played), never resolved.

    Returns the parent match, or ``None`` when there is no parent — which is
    exactly the final: ``advance_position`` points one round past the last, so a
    missing parent means the winner is the champion. Callers at creation ignore
    the return; ``advance`` uses it to detect that the tournament is complete.
    """
    next_round, next_slot, side = bracket.advance_position(round_, slot)
    parent = matches.get((next_round, next_slot))
    if parent is None:
        return None
    setattr(parent, f"fighter_{side}_id", winner_id)
    setattr(parent, f"fighter_{side}_seed", winner_seed)
    if parent.fighter_a_seed is not None and parent.fighter_b_seed is not None:
        parent.status = MATCH_READY
    return parent


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


def _next_ready_match(tournament: models.Tournament, match_id):
    """Return the match ``advance`` should play, or ``None`` if there is none.

    Without a ``match_id`` this is the **next** match by E8's total order —
    lowest round, then lowest slot — among those that are ``ready``. The
    relationship is already ordered by ``(round, slot)``, so the first ``ready``
    row is the one. With a ``match_id`` (used only to advance a bracket in a
    non-default order, for the order-independence property of E7.3) it is that
    specific match, but still only if it is ``ready``.
    """
    ready = [m for m in tournament.matches if m.status == MATCH_READY]
    if match_id is not None:
        return next((m for m in ready if m.id == match_id), None)
    return ready[0] if ready else None


def _play_to_a_decision(tournament: models.Tournament,
                        match: models.TournamentMatch):
    """Play a ready match, replaying drawn attempts, per E7.4 / B10.

    Runs the pairing through :func:`arena.run_ai_match` at ``match_seed(attempt)``
    for ``attempt`` = 0, 1, … . A drawn attempt is recorded and the pairing is
    replayed at the next attempt — never awarded — until an attempt is decisive
    or :data:`MAX_ATTEMPTS` is reached. Because ``attempt`` feeds the seed, the
    whole sequence is deterministic, so a replayed tournament reproduces the same
    draws and the same eventual winner.

    Returns ``(attempts, decisive)`` where ``attempts`` is the E6.1 attempt list
    (``[{attempt, result, turns, log}]``) and ``decisive`` is the winning
    attempt's arena result, or ``None`` if all attempts drew.
    """
    attempts = []
    decisive = None
    for attempt in range(MAX_ATTEMPTS):
        seed = bracket.match_seed(tournament.seed, match.round, match.slot, attempt)
        result = arena.run_ai_match(
            match.fighter_a_id, match.fighter_b_id, tournament.difficulty, seed
        )
        attempts.append({
            "attempt": attempt,
            "result": result["status"],
            "turns": result["turns"],
            "log": result["log"],
        })
        if result["winner"] is not None:
            decisive = result
            break
    return attempts, decisive


def advance(session, tournament_id: str, *, match_id: str | None = None):
    """Play the next ready match and propagate the result (E7.2, E7.4, task 8.2).

    Picks the next ``ready`` match by lowest round then lowest slot (E8), plays
    it AI-vs-AI at the tournament's difficulty and the derived per-match seed,
    and records every attempt in ``attempts_json``. A drawn attempt is replayed
    at ``attempt + 1`` rather than awarded (E7.4); ``winner_*`` and ``turns`` come
    only from the decisive attempt. The winner is promoted into ``round+1,
    slot//2`` as A on an even slot and B on an odd one, flipping that parent
    ``pending`` → ``ready`` once both of its sides are known.

    When the final resolves, the tournament becomes ``complete`` and its winner
    is ``champion_id``. If a match draws out all :data:`MAX_ATTEMPTS` attempts it
    is left ``drawn_out`` and the tournament ``stalled`` (B10) — no winner is
    invented and no further round is fed from it.

    The ``match_id`` keyword plays a *specific* ready match instead of the
    auto-picked one; it exists so a test can advance a bracket in a non-default
    order and confirm each position's result is order-independent (E7.3). The
    HTTP layer never passes it.

    Raises :class:`TournamentComplete` if the final has already resolved and
    :class:`NoReadyMatch` if no ``ready`` match is available (a ``pending`` wait
    or a ``stalled`` bracket). On success the mutations are flushed and the
    :class:`models.Tournament` is returned; the caller owns the commit.
    """
    tournament = session.get(models.Tournament, tournament_id)
    if tournament.status == STATUS_COMPLETE:
        raise TournamentComplete(tournament_id)

    match = _next_ready_match(tournament, match_id)
    if match is None:
        raise NoReadyMatch(tournament_id)

    attempts, decisive = _play_to_a_decision(tournament, match)
    match.attempts_json = json.dumps(attempts)

    if decisive is None:
        # Ten straight draws (E7.4): abandon the match, stall the tournament.
        # Nothing propagates, so the parent slot stays undetermined by design.
        match.status = MATCH_DRAWN_OUT
        tournament.status = STATUS_STALLED
        session.flush()
        return tournament

    winner_side = decisive["winner"]  # "a" or "b" — the arena's bracket side.
    match.winner_id = getattr(match, f"fighter_{winner_side}_id")
    match.winner_seed = getattr(match, f"fighter_{winner_side}_seed")
    match.turns = decisive["turns"]
    match.status = MATCH_COMPLETE

    positions = {(m.round, m.slot): m for m in tournament.matches}
    parent = _propagate(
        positions, match.round, match.slot, match.winner_id, match.winner_seed
    )
    if parent is None:
        # No parent means this was the final: crown the champion.
        tournament.status = STATUS_COMPLETE
        tournament.champion_id = match.winner_id
    elif tournament.status not in (STATUS_COMPLETE, STATUS_STALLED):
        tournament.status = STATUS_IN_PROGRESS

    session.flush()
    return tournament


def _entrant(fighter_id, seed) -> dict | None:
    """The E8.1 fighter object for a bracket side, or ``None`` if undetermined.

    ``id`` and ``name`` come from ``fighters.py`` (never the database, E6.1);
    ``display`` is ``"Kaito (2)"`` — the name plus the **seed** (B11), built here
    so the client never assembles it and two entrants of the same fighter stay
    distinguishable. A side is present iff it has a seed (``_propagate`` always
    sets id and seed together), so ``seed is None`` — an unresolved slot or the B
    side of a bye — serializes to ``None``.
    """
    if seed is None or fighter_id is None:
        return None
    name = FIGHTERS[fighter_id]["name"]
    return {"id": fighter_id, "name": name, "display": f"{name} ({seed})"}


def _standings(tournament: models.Tournament) -> list[dict]:
    """Derive the standings table (E8.1) — never stored, always recomputed (B11).

    Every entrant is one row keyed by **seed**, so a ``["kaito", "kaito"]``
    bracket is two rows, never one merged one (E7.2). Wins and losses are counted
    over ``complete`` matches only — a **bye is neither** (E8.1). Each entrant
    loses at most once in single elimination, so ``eliminated_in`` is the round of
    that single loss, or ``None`` for the (still-unbeaten) champion.

    Sorted wins descending, then fighter name, then seed ascending — the seed
    tie-break makes the order total even when two rows share a name (B11).
    """
    entrants: dict[int, str] = {}
    for match in tournament.matches:
        if match.round != 1:
            continue
        if match.fighter_a_seed is not None:
            entrants[match.fighter_a_seed] = match.fighter_a_id
        if match.fighter_b_seed is not None:
            entrants[match.fighter_b_seed] = match.fighter_b_id

    rows = {seed: {"wins": 0, "losses": 0, "eliminated_in": None}
            for seed in entrants}
    for match in tournament.matches:
        if match.status != MATCH_COMPLETE or match.winner_seed is None:
            continue
        rows[match.winner_seed]["wins"] += 1
        for seed in (match.fighter_a_seed, match.fighter_b_seed):
            if seed is not None and seed != match.winner_seed:
                rows[seed]["losses"] += 1
                rows[seed]["eliminated_in"] = match.round

    ordered = sorted(
        entrants,
        key=lambda seed: (-rows[seed]["wins"],
                          FIGHTERS[entrants[seed]]["name"], seed),
    )
    return [{
        "fighter": _entrant(entrants[seed], seed),
        "wins": rows[seed]["wins"],
        "losses": rows[seed]["losses"],
        "eliminated_in": rows[seed]["eliminated_in"],
    } for seed in ordered]


def serialize_bracket(tournament: models.Tournament) -> dict:
    """Render a tournament as the E8.1 bracket object (task 8.3).

    Rounds in order, each match carrying ``fighter_a`` / ``fighter_b`` / ``winner``
    entrant objects (``None`` where a side is a bye or still undetermined),
    ``turns`` and ``status``. ``champion`` is the final's winner once the
    tournament is ``complete`` and ``None`` before that. ``standings`` is derived
    fresh here (:func:`_standings`) and never persisted.

    Pure and read-only: it reads the already-loaded relationship and touches no
    session, so the HTTP layer can serialize inside or outside a transaction.
    """
    rounds = []
    by_round: dict[int, list[models.TournamentMatch]] = {}
    for match in tournament.matches:
        by_round.setdefault(match.round, []).append(match)

    for round_ in sorted(by_round):
        matches = []
        for match in sorted(by_round[round_], key=lambda m: m.slot):
            matches.append({
                "match_id": match.id,
                "slot": match.slot,
                "status": match.status,
                "fighter_a": _entrant(match.fighter_a_id, match.fighter_a_seed),
                "fighter_b": _entrant(match.fighter_b_id, match.fighter_b_seed),
                "winner": _entrant(match.winner_id, match.winner_seed),
                "turns": match.turns,
            })
        rounds.append({"round": round_, "matches": matches})

    champion = None
    if tournament.status == STATUS_COMPLETE and by_round:
        final = min(by_round[max(by_round)], key=lambda m: m.slot)
        champion = _entrant(final.winner_id, final.winner_seed)

    return {
        "tournament_id": tournament.id,
        "name": tournament.name,
        "difficulty": tournament.difficulty,
        "seed": tournament.seed,
        "size": tournament.size,
        "status": tournament.status,
        "champion": champion,
        "rounds": rounds,
        "standings": _standings(tournament),
    }
