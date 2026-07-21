"""HTTP layer tests (spec §5, §8, §9), driven through Flask's test client."""

import uuid

import pytest

from app import create_app


@pytest.fixture()
def client():
    """A test client over a fresh app, so each test gets an empty match store."""
    return create_app().test_client()


def create(client, player="kaito", opponent="vega", **extra):
    """POST /api/match with the given fighters, returning the raw response."""
    body = {"player_fighter": player, "opponent_fighter": opponent}
    body.update(extra)
    return client.post("/api/match", json=body)


def test_create_match_returns_201_and_a_fresh_state(client):
    response = create(client)
    assert response.status_code == 201

    state = response.get_json()
    assert state["status"] == "in_progress"
    assert state["turn"] == 0
    assert state["log"] == []

    assert state["player"]["hp"] == state["player"]["hp_max"] == 100
    assert state["opponent"]["hp"] == state["opponent"]["hp_max"] == 130
    assert state["player"]["ki"] == 30
    assert state["opponent"]["ki"] == 30


def test_match_id_is_a_uuid4_hex_string(client):
    match_id = create(client).get_json()["match_id"]

    assert isinstance(match_id, str)
    assert len(match_id) == 32
    parsed = uuid.UUID(hex=match_id)
    assert parsed.version == 4
    assert parsed.hex == match_id


def test_two_matches_get_distinct_ids(client):
    first = create(client).get_json()["match_id"]
    second = create(client).get_json()["match_id"]
    assert first != second


def test_a_fresh_match_offers_the_moves_the_rules_allow(client):
    state = create(client).get_json()
    # 30 ki: everything but the two 40-ki moves.
    assert state["legal_actions"] == ["strike", "ki_blast", "charge", "guard"]


@pytest.mark.parametrize(
    ("player", "opponent"),
    [("nobody", "vega"), ("kaito", "nobody")],
)
def test_unknown_fighter_on_either_side_is_rejected(client, player, opponent):
    response = create(client, player, opponent)

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "unknown_fighter"


def test_a_missing_fighter_field_is_an_unknown_fighter(client):
    response = client.post("/api/match", json={})

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "unknown_fighter"


def test_an_integer_seed_is_accepted(client):
    assert create(client, seed=12345).status_code == 201
    assert create(client, seed=0).status_code == 201
    assert create(client, seed=-7).status_code == 201


@pytest.mark.parametrize("seed", ["12345", 1.5, True, False, None, [1]])
def test_a_non_integer_seed_is_rejected(client, seed):
    response = create(client, seed=seed)

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "invalid_seed"


def test_a_rejected_seed_creates_no_match(client):
    app = create_app()
    rejected = app.test_client().post(
        "/api/match",
        json={"player_fighter": "kaito", "opponent_fighter": "vega", "seed": "12345"},
    )

    assert rejected.status_code == 400
    assert app.extensions["matches"] == {}


def test_the_error_envelope_carries_a_code_and_a_message(client):
    body = create(client, "nobody", "vega").get_json()

    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message"}
    assert isinstance(body["error"]["message"], str)
    assert body["error"]["message"]


def test_a_mirror_match_is_accepted(client):
    response = create(client, "kaito", "kaito")

    assert response.status_code == 201
    state = response.get_json()
    assert state["player"]["id"] == state["opponent"]["id"] == "kaito"


def test_mirror_fighters_are_independent_copies(client):
    app = create_app()
    match_id = (
        app.test_client()
        .post("/api/match", json={"player_fighter": "kaito", "opponent_fighter": "kaito"})
        .get_json()["match_id"]
    )

    state = app.extensions["matches"][match_id]["state"]
    state["player"]["hp"] = 1
    assert state["opponent"]["hp"] == 100


def test_get_returns_the_same_payload_the_create_returned(client):
    created = create(client)
    match_id = created.get_json()["match_id"]

    fetched = client.get(f"/api/match/{match_id}")

    assert fetched.status_code == 200
    assert fetched.get_data() == created.get_data()


def test_two_consecutive_gets_are_identical(client):
    match_id = create(client).get_json()["match_id"]

    first = client.get(f"/api/match/{match_id}")
    second = client.get(f"/api/match/{match_id}")

    assert first.get_data() == second.get_data()


def test_get_never_creates_a_match_on_demand(client):
    app = create_app()
    response = app.test_client().get(f"/api/match/{uuid.uuid4().hex}")

    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "match_not_found"
    assert app.extensions["matches"] == {}


@pytest.mark.parametrize("match_id", ["not-a-uuid", "0" * 32, uuid.uuid4().hex])
def test_an_unknown_match_id_is_a_404(client, match_id):
    response = client.get(f"/api/match/{match_id}")

    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "match_not_found"


def test_get_isolates_matches_from_one_another(client):
    mirror = create(client, "kaito", "kaito").get_json()["match_id"]
    standard = create(client).get_json()["match_id"]

    assert client.get(f"/api/match/{mirror}").get_json()["opponent"]["id"] == "kaito"
    assert client.get(f"/api/match/{standard}").get_json()["opponent"]["id"] == "vega"


def test_a_seeded_match_stores_a_reproducible_rng(client):
    app = create_app()
    ids = [
        app.test_client()
        .post(
            "/api/match",
            json={"player_fighter": "kaito", "opponent_fighter": "vega", "seed": 4242},
        )
        .get_json()["match_id"]
        for _ in range(2)
    ]

    first, second = (app.extensions["matches"][i]["rng"] for i in ids)
    assert [first.random() for _ in range(5)] == [second.random() for _ in range(5)]
