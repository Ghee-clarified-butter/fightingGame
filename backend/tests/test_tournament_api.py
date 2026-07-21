"""Tournament HTTP layer — creation, read, advance and list (extension E8).

Driven through Flask's test client over a **per-test** temp database, so each
test owns an isolated bracket store and can assert that a rejected request left
zero tournament rows behind. ``POST /api/tournament`` builds the whole bracket
and returns the E8.1 object; ``GET /api/tournament/<id>`` returns the same object
read-only (task 9.1); ``POST /api/tournament/<id>/advance`` plays the next match
and ``GET /api/tournaments`` lists every tournament newest first (task 9.2);
every documented error maps to its §5.4 envelope.
"""

import pytest
from sqlalchemy import func, select

from app import create_app
from game import arena
import models

# The E8.1 bracket object, key for key — written out literally so a field that
# quietly appears or disappears fails a test.
BRACKET_KEYS = {
    "tournament_id",
    "name",
    "difficulty",
    "seed",
    "size",
    "status",
    "champion",
    "rounds",
    "standings",
}


@pytest.fixture()
def app(tmp_path):
    """A Flask app over a fresh per-test database file.

    A per-test URL keeps one test's tournaments out of another's — the shared
    conftest ``DATABASE_URL`` would otherwise let rows leak across tests and make
    the "no row created" assertions meaningless.
    """
    return create_app(f"sqlite+pysqlite:///{tmp_path / 'api.db'}")


@pytest.fixture()
def client(app):
    return app.test_client()


def _tournament_count(app) -> int:
    """How many tournament rows the app's database holds."""
    session = app.extensions["db_session_factory"]()
    try:
        return session.scalar(select(func.count()).select_from(models.Tournament))
    finally:
        session.close()


def _create(client, **overrides):
    """POST /api/tournament with a sensible default body, returning the response."""
    body = {
        "name": "Spring Cup",
        "roster": ["kaito", "vega", "kaito", "vega"],
        "difficulty": "heuristic",
        "seed": 99,
    }
    body.update(overrides)
    return client.post("/api/tournament", json=body)


def _assert_envelope(response, code, status):
    """Assert the §5.4 error envelope: a code and a non-empty message, nothing else."""
    assert response.status_code == status
    payload = response.get_json()
    assert set(payload) == {"error"}
    error = payload["error"]
    assert set(error) == {"code", "message"}
    assert error["code"] == code
    assert isinstance(error["message"], str) and error["message"]


# --- happy path -------------------------------------------------------------


def test_create_returns_201_and_the_e8_bracket(client):
    response = _create(client)

    assert response.status_code == 201
    body = response.get_json()
    assert set(body) == BRACKET_KEYS
    assert body["name"] == "Spring Cup"
    assert body["difficulty"] == "heuristic"
    assert body["seed"] == 99
    assert body["size"] == 4
    assert body["status"] == "pending"
    assert body["champion"] is None
    # Four fighters ⇒ two first-round matches and a final, no byes.
    assert [r["round"] for r in body["rounds"]] == [1, 2]
    assert len(body["rounds"][0]["matches"]) == 2
    assert len(body["rounds"][1]["matches"]) == 1
    assert all(m["status"] == "ready" for m in body["rounds"][0]["matches"])
    # Four entrants, each its own standings row keyed by seed.
    assert len(body["standings"]) == 4


def test_get_returns_the_same_object_and_is_read_only(client, app):
    created = _create(client).get_json()
    tid = created["tournament_id"]

    fetched = client.get(f"/api/tournament/{tid}").get_json()
    assert fetched == created
    # A read never advances the bracket: every match is still unplayed.
    assert all(
        m["status"] in ("ready", "pending", "bye")
        for r in fetched["rounds"]
        for m in r["matches"]
    )
    # And no extra tournament materialised from the two reads.
    assert _tournament_count(app) == 1


@pytest.mark.parametrize("difficulty", ["random", "heuristic", "search"])
def test_each_difficulty_is_accepted_and_echoed(client, difficulty):
    response = _create(client, difficulty=difficulty)

    assert response.status_code == 201
    assert response.get_json()["difficulty"] == difficulty


def test_a_five_fighter_roster_reports_size_8_with_three_byes(client):
    """E7.1: byes on the top three seeds, pre-resolved and never played."""
    roster = ["kaito", "vega", "kaito", "vega", "kaito"]
    body = _create(client, roster=roster).get_json()

    assert body["size"] == 8
    byes = [m for m in body["rounds"][0]["matches"] if m["status"] == "bye"]
    assert len(byes) == 3
    for bye in byes:
        assert bye["fighter_b"] is None
        assert bye["winner"] is not None
        assert bye["turns"] is None


def test_duplicate_ids_yield_distinct_entrants_with_distinct_display(client):
    """E7.2: a ["kaito","kaito"] pairing is two rows, not one merged one."""
    body = _create(client, roster=["kaito", "kaito"]).get_json()

    assert body["size"] == 2
    match = body["rounds"][0]["matches"][0]
    assert match["fighter_a"]["display"] == "Kaito (1)"
    assert match["fighter_b"]["display"] == "Kaito (2)"
    displays = {row["fighter"]["display"] for row in body["standings"]}
    assert displays == {"Kaito (1)", "Kaito (2)"}


# --- errors, each leaving the database untouched ----------------------------


@pytest.mark.parametrize("n", [0, 1, 17])
def test_an_invalid_roster_size_is_rejected_and_creates_nothing(client, app, n):
    roster = ["kaito"] * n
    response = _create(client, roster=roster)

    _assert_envelope(response, "invalid_roster", 400)
    assert _tournament_count(app) == 0


@pytest.mark.parametrize("roster", [None, "kaito", 3, {"a": 1}])
def test_a_non_list_roster_is_rejected_and_creates_nothing(client, app, roster):
    response = _create(client, roster=roster)

    _assert_envelope(response, "invalid_roster", 400)
    assert _tournament_count(app) == 0


def test_an_unknown_fighter_is_rejected_and_creates_nothing(client, app):
    response = _create(client, roster=["kaito", "nobody"])

    _assert_envelope(response, "unknown_fighter", 400)
    assert _tournament_count(app) == 0


@pytest.mark.parametrize("difficulty", ["easy", "SEARCH", "", "expectimax"])
def test_an_unknown_difficulty_is_rejected_and_creates_nothing(client, app, difficulty):
    response = _create(client, difficulty=difficulty)

    _assert_envelope(response, "unknown_difficulty", 400)
    assert _tournament_count(app) == 0


@pytest.mark.parametrize("seed", ["99", 1.5, True, None, ["x"]])
def test_an_invalid_seed_is_rejected_and_creates_nothing(client, app, seed):
    """A non-int seed (bool and null included) cannot drive the per-match RNG (E7.3)."""
    body = {
        "name": "Spring Cup",
        "roster": ["kaito", "vega"],
        "difficulty": "heuristic",
        "seed": seed,
    }
    response = client.post("/api/tournament", json=body)

    _assert_envelope(response, "invalid_seed", 400)
    assert _tournament_count(app) == 0


def test_a_missing_seed_is_rejected_and_creates_nothing(client, app):
    """Absent ⇒ no root seed, so no reproducible tournament: invalid_seed."""
    response = client.post(
        "/api/tournament",
        json={"name": "Cup", "roster": ["kaito", "vega"], "difficulty": "heuristic"},
    )

    _assert_envelope(response, "invalid_seed", 400)
    assert _tournament_count(app) == 0


def test_an_unknown_tournament_id_is_a_404(client):
    _assert_envelope(client.get("/api/tournament/deadbeef"), "tournament_not_found", 404)


# --- advance (task 9.2) -----------------------------------------------------


def _advance_to_champion(client, tid, limit=64):
    """POST advance until the tournament reports ``complete``, returning the body.

    Bounded so a bug that never completes fails loudly instead of looping — a
    real bracket of ≤16 fighters resolves in well under ``limit`` matches.
    """
    for _ in range(limit):
        body = client.post(f"/api/tournament/{tid}/advance").get_json()
        if body["status"] == "complete":
            return body
    raise AssertionError("tournament never reached 'complete'")


def test_advance_plays_one_match_and_returns_the_updated_bracket(client):
    created = _create(client).get_json()
    tid = created["tournament_id"]

    response = client.post(f"/api/tournament/{tid}/advance")

    assert response.status_code == 200
    body = response.get_json()
    assert set(body) == BRACKET_KEYS
    # Exactly one round-1 match resolved; the bracket is now under way.
    completed = [
        m for r in body["rounds"] for m in r["matches"] if m["status"] == "complete"
    ]
    assert len(completed) == 1
    assert completed[0]["turns"] is not None
    assert completed[0]["winner"] is not None
    assert body["status"] == "in_progress"


def test_advancing_repeatedly_reaches_a_champion(client):
    created = _create(client).get_json()
    tid = created["tournament_id"]

    body = _advance_to_champion(client, tid)

    assert body["status"] == "complete"
    assert body["champion"] is not None
    # The champion also shows up as the winner of the final.
    final = body["rounds"][-1]["matches"][0]
    assert final["winner"] == body["champion"]


def test_advance_on_a_complete_tournament_is_409_and_leaves_it_unchanged(client):
    created = _create(client).get_json()
    tid = created["tournament_id"]
    _advance_to_champion(client, tid)

    before = client.get(f"/api/tournament/{tid}").get_json()
    response = client.post(f"/api/tournament/{tid}/advance")

    _assert_envelope(response, "tournament_complete", 409)
    after = client.get(f"/api/tournament/{tid}").get_json()
    assert after == before


def test_advance_with_no_ready_match_is_409(client, monkeypatch):
    """A stalled bracket (ten straight draws) has nothing ready → no_ready_match."""
    created = _create(client, roster=["kaito", "vega"]).get_json()
    tid = created["tournament_id"]

    # Every attempt draws, so the lone final draws out and the tournament stalls.
    monkeypatch.setattr(
        arena,
        "run_ai_match",
        lambda a, b, d, s: {
            "winner": None, "winner_side": None, "turns": 100,
            "status": "draw", "log": [{"turn": 1}],
        },
    )
    stalled = client.post(f"/api/tournament/{tid}/advance").get_json()
    assert stalled["status"] == "stalled"

    # A stalled tournament is not complete, but has no ready match to play.
    _assert_envelope(
        client.post(f"/api/tournament/{tid}/advance"), "no_ready_match", 409
    )


def test_advance_on_an_unknown_tournament_is_a_404(client):
    _assert_envelope(
        client.post("/api/tournament/deadbeef/advance"), "tournament_not_found", 404
    )


# --- list (task 9.2) --------------------------------------------------------

SUMMARY_KEYS = {"id", "name", "status", "champion", "created_at"}


def test_the_list_is_empty_before_any_tournament(client):
    response = client.get("/api/tournaments")

    assert response.status_code == 200
    assert response.get_json() == []


def test_the_list_returns_summaries_newest_first(client):
    first = _create(client, name="First").get_json()
    second = _create(client, name="Second").get_json()

    body = client.get("/api/tournaments").get_json()

    assert [row["name"] for row in body] == ["Second", "First"]
    assert set(body[0]) == SUMMARY_KEYS
    assert [row["id"] for row in body] == [
        second["tournament_id"], first["tournament_id"]
    ]
    # created_at is emitted, ISO-8601, and in descending order.
    assert body[0]["created_at"] >= body[1]["created_at"]


def test_the_list_shows_a_champion_once_a_tournament_completes(client):
    created = _create(client, roster=["kaito", "kaito"]).get_json()
    tid = created["tournament_id"]

    # Pending tournament: no champion in the summary.
    pending = client.get("/api/tournaments").get_json()[0]
    assert pending["status"] == "pending"
    assert pending["champion"] is None

    _advance_to_champion(client, tid)
    done = client.get("/api/tournaments").get_json()[0]
    assert done["status"] == "complete"
    # The seed-disambiguated display survives into the summary (B11).
    assert done["champion"]["display"] in {"Kaito (1)", "Kaito (2)"}


def test_a_second_app_over_the_same_file_still_lists_the_tournament(tmp_path):
    """The restart criterion at the HTTP layer: a fresh app sees persisted rows (E8)."""
    url = f"sqlite+pysqlite:///{tmp_path / 'restart.db'}"

    first_app = create_app(url)
    created = first_app.test_client().post(
        "/api/tournament",
        json={"name": "Enduring", "roster": ["kaito", "vega"],
              "difficulty": "heuristic", "seed": 7},
    ).get_json()

    # A brand-new app instance over the same file — the "restart".
    second = create_app(url).test_client()
    listed = second.get("/api/tournaments").get_json()

    assert [row["id"] for row in listed] == [created["tournament_id"]]
    assert listed[0]["name"] == "Enduring"
