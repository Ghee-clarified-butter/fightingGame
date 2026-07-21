"""Tournament HTTP layer — creation and read (extension E8, plan 9.1).

Driven through Flask's test client over a **per-test** temp database, so each
test owns an isolated bracket store and can assert that a rejected request left
zero tournament rows behind. ``POST /api/tournament`` builds the whole bracket
and returns the E8.1 object; ``GET /api/tournament/<id>`` returns the same object
read-only; every documented error maps to its §5.4 envelope. The advance and list
endpoints are task 9.2.
"""

import pytest
from sqlalchemy import func, select

from app import create_app
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
