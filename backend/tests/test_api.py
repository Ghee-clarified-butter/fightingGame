"""HTTP layer tests (spec §5, §8, §9), driven through Flask's test client."""

import random
import uuid

import pytest

from app import create_app, serialize
from game import rules

# The §5.5 payload, key for key. Written out literally rather than derived from
# the code so a field that quietly appears or disappears fails a test.
STATE_KEYS = {"match_id", "status", "turn", "player", "opponent", "legal_actions", "log"}
FIGHTER_KEYS = {
    "id",
    "name",
    "hp",
    "hp_max",
    "ki",
    "ki_max",
    "atk",
    "def",
    "spd",
    "guarding",
    "ascended",
    "ascend_used",
}
LOG_ENTRY_KEYS = {"turn", "actor", "action", "damage", "target_hp", "text"}


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


# --- Serialization (§5.5) ---------------------------------------------------


def advance(app, match_id, player_action):
    """Play one turn straight through the rules, bypassing the HTTP layer.

    `POST .../turn` does not exist yet (plan 2.4), but serialization has to be
    provable against a match that is mid-fight and against one that is over, so
    these tests drive the stored match the same way the route will.
    """
    match = app.extensions["matches"][match_id]
    state, _ = rules.play_turn(match["state"], player_action, match["rng"])
    state["status"] = rules.check_status(state)
    match["state"] = state
    return state


def test_the_payload_has_exactly_the_spec_keys(client):
    state = create(client).get_json()

    assert set(state) == STATE_KEYS
    assert set(state["player"]) == FIGHTER_KEYS
    assert set(state["opponent"]) == FIGHTER_KEYS


def test_log_entries_have_exactly_the_spec_keys(client):
    app = create_app()
    match_id = (
        app.test_client()
        .post(
            "/api/match",
            json={"player_fighter": "kaito", "opponent_fighter": "vega", "seed": 11},
        )
        .get_json()["match_id"]
    )
    advance(app, match_id, "strike")

    log = app.test_client().get(f"/api/match/{match_id}").get_json()["log"]

    assert log
    for entry in log:
        assert set(entry) == LOG_ENTRY_KEYS


def test_guarding_is_always_false_in_a_returned_state(client):
    app = create_app()
    match_id = (
        app.test_client()
        .post(
            "/api/match",
            json={"player_fighter": "kaito", "opponent_fighter": "vega", "seed": 5},
        )
        .get_json()["match_id"]
    )
    api = app.test_client()

    for _ in range(12):
        advance(app, match_id, "guard")
        state = api.get(f"/api/match/{match_id}").get_json()
        assert state["player"]["guarding"] is False
        assert state["opponent"]["guarding"] is False
        if state["status"] != "in_progress":
            break


def test_legal_actions_agrees_with_the_rules_at_every_turn(client):
    app = create_app()
    api = app.test_client()
    match_id = api.post(
        "/api/match",
        json={"player_fighter": "kaito", "opponent_fighter": "vega", "seed": 1234},
    ).get_json()["match_id"]

    # A separate RNG picks the player's actions, so the match RNG keeps its §4.8
    # draw order.
    picker = random.Random(99)
    while True:
        state = api.get(f"/api/match/{match_id}").get_json()
        stored = app.extensions["matches"][match_id]["state"]
        if state["status"] != "in_progress":
            break
        assert state["legal_actions"] == rules.legal_actions(stored["player"])
        advance(app, match_id, picker.choice(state["legal_actions"]))

    assert state["legal_actions"] == []


def test_legal_actions_is_empty_once_the_match_is_over(client):
    app = create_app()
    api = app.test_client()
    match_id = api.post(
        "/api/match", json={"player_fighter": "kaito", "opponent_fighter": "vega"}
    ).get_json()["match_id"]

    # The player still has moves left; only the status decides the answer.
    stored = app.extensions["matches"][match_id]["state"]
    stored["status"] = "player_won"

    state = api.get(f"/api/match/{match_id}").get_json()
    assert state["status"] == "player_won"
    assert state["legal_actions"] == []
    assert rules.legal_actions(stored["player"]) != []


@pytest.mark.parametrize("status", ["player_won", "opponent_won", "draw"])
def test_every_terminal_status_suppresses_legal_actions(client, status):
    app = create_app()
    api = app.test_client()
    match_id = api.post(
        "/api/match", json={"player_fighter": "kaito", "opponent_fighter": "vega"}
    ).get_json()["match_id"]
    app.extensions["matches"][match_id]["state"]["status"] = status

    assert api.get(f"/api/match/{match_id}").get_json()["legal_actions"] == []


def test_serialize_hands_back_copies_not_the_stored_dicts():
    app = create_app()
    match_id = (
        app.test_client()
        .post(
            "/api/match",
            json={"player_fighter": "kaito", "opponent_fighter": "vega", "seed": 3},
        )
        .get_json()["match_id"]
    )
    advance(app, match_id, "strike")
    stored = app.extensions["matches"][match_id]["state"]
    hp_before = stored["player"]["hp"]
    damage_before = stored["log"][0]["damage"]

    payload = serialize(match_id, stored)
    payload["player"]["hp"] = 1
    payload["log"][0]["damage"] = 999

    assert stored["player"]["hp"] == hp_before
    assert stored["log"][0]["damage"] == damage_before
