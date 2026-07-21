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
    """Play one turn through the API and return the resulting payload."""
    response = app.test_client().post(
        f"/api/match/{match_id}/turn", json={"action": player_action}
    )
    assert response.status_code == 200, response.get_json()
    return response.get_json()


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


# --- Submitting a turn (§5.2) -----------------------------------------------


def seeded(client, seed, player="kaito", opponent="vega"):
    """Create a seeded match and return its id."""
    return create(client, player, opponent, seed=seed).get_json()["match_id"]


def test_a_strike_hurts_the_opponent_and_writes_the_log(client):
    match_id = seeded(client, 12345)
    before = client.get(f"/api/match/{match_id}").get_json()

    response = client.post(f"/api/match/{match_id}/turn", json={"action": "strike"})

    assert response.status_code == 200
    state = response.get_json()
    assert state["opponent"]["hp"] <= before["opponent"]["hp"] - 1
    assert len(state["log"]) >= 1
    assert set(state) == STATE_KEYS


def test_the_turn_counter_advances_by_one_per_request(client):
    match_id = seeded(client, 7)

    for expected in (1, 2, 3):
        state = client.post(
            f"/api/match/{match_id}/turn", json={"action": "guard"}
        ).get_json()
        assert state["turn"] == expected


def test_the_log_is_cumulative_and_oldest_first(client):
    match_id = seeded(client, 21)

    previous: list[dict] = []
    for expected_turn in (1, 2, 3):
        state = client.post(
            f"/api/match/{match_id}/turn", json={"action": "charge"}
        ).get_json()
        log = state["log"]
        # Append-only: every earlier entry survives, unchanged, in its old slot.
        assert log[: len(previous)] == previous
        assert len(log) > len(previous)
        assert [entry["turn"] for entry in log] == sorted(entry["turn"] for entry in log)
        assert all(entry["turn"] == expected_turn for entry in log[len(previous):])
        previous = log


def test_the_stored_match_matches_what_the_turn_returned(client):
    match_id = seeded(client, 99)

    returned = client.post(f"/api/match/{match_id}/turn", json={"action": "ki_blast"})
    fetched = client.get(f"/api/match/{match_id}")

    assert fetched.get_data() == returned.get_data()


def test_ki_blast_costs_exactly_fifteen_ki(client):
    match_id = seeded(client, 31)

    state = client.post(
        f"/api/match/{match_id}/turn", json={"action": "ki_blast"}
    ).get_json()

    assert state["player"]["ki"] == 30 - 15


def test_a_turn_on_an_unknown_match_is_a_404(client):
    response = client.post(f"/api/match/{uuid.uuid4().hex}/turn", json={"action": "strike"})

    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "match_not_found"


# --- Rejected turns (§5.4) --------------------------------------------------


def reject(client, match_id, body, code, status=400):
    """Submit ``body`` as a turn, assert it fails with ``code``, and assert the
    match is byte-identical to what it was before the attempt."""
    before = client.get(f"/api/match/{match_id}")

    response = client.post(f"/api/match/{match_id}/turn", json=body)

    assert response.status_code == status, response.get_json()
    assert response.get_json()["error"]["code"] == code
    assert client.get(f"/api/match/{match_id}").get_data() == before.get_data()
    return response.get_json()["error"]


@pytest.mark.parametrize(
    "body",
    [
        {"action": "punch"},
        {"action": "Strike"},
        {"action": ""},
        {"action": None},
        {"action": 7},
        {},
    ],
    ids=["unknown", "wrong-case", "empty", "null", "non-string", "missing"],
)
def test_an_action_that_is_not_one_of_the_six_is_rejected(client, body):
    match_id = seeded(client, 1)

    reject(client, match_id, body, "unknown_action")


def test_an_empty_body_is_an_unknown_action(client):
    match_id = seeded(client, 1)
    before = client.get(f"/api/match/{match_id}")

    response = client.post(f"/api/match/{match_id}/turn")

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "unknown_action"
    assert client.get(f"/api/match/{match_id}").get_data() == before.get_data()


def test_surge_beam_below_forty_ki_is_rejected(client):
    match_id = seeded(client, 2)
    # A fresh fighter holds 30 ki (§2.1), so the 40-ki beam is unaffordable.
    error = reject(client, match_id, {"action": "surge_beam"}, "insufficient_ki")

    assert "40" in error["message"]
    assert "30" in error["message"]


def test_ascend_below_forty_ki_is_rejected(client):
    match_id = seeded(client, 3)

    reject(client, match_id, {"action": "ascend"}, "insufficient_ki")


def test_a_second_ascend_is_rejected_and_changes_nothing(client):
    app = create_app()
    api = app.test_client()
    match_id = api.post(
        "/api/match",
        json={"player_fighter": "kaito", "opponent_fighter": "vega", "seed": 4},
    ).get_json()["match_id"]

    # Charge to 40+ ki, ascend for real, then charge back above the cost so the
    # only thing standing in the way of a second Ascend is ``ascend_used``.
    app.extensions["matches"][match_id]["state"]["player"]["ki"] = 40
    ascended = advance(app, match_id, "ascend")
    assert ascended["player"]["ascended"] is True
    assert ascended["player"]["ascend_used"] is True

    # ``resolve_turn`` hands back a new state object, so re-read the store.
    stored = app.extensions["matches"][match_id]["state"]
    stored["player"]["ki"] = 100

    reject(api, match_id, {"action": "ascend"}, "already_ascended")

    assert stored["player"]["ki"] == 100
    assert stored["player"]["ascended"] is True


def test_already_ascended_outranks_insufficient_ki(client):
    """A6: an Ascend that is both used up *and* unaffordable reports the former."""
    app = create_app()
    api = app.test_client()
    match_id = api.post(
        "/api/match", json={"player_fighter": "kaito", "opponent_fighter": "vega"}
    ).get_json()["match_id"]

    player = app.extensions["matches"][match_id]["state"]["player"]
    player["ascend_used"] = True
    player["ki"] = 0

    reject(api, match_id, {"action": "ascend"}, "already_ascended")


@pytest.mark.parametrize("status", ["player_won", "opponent_won", "draw"])
def test_a_turn_on_a_finished_match_is_a_409(client, status):
    app = create_app()
    api = app.test_client()
    match_id = api.post(
        "/api/match", json={"player_fighter": "kaito", "opponent_fighter": "vega"}
    ).get_json()["match_id"]
    app.extensions["matches"][match_id]["state"]["status"] = status

    reject(api, match_id, {"action": "strike"}, "match_over", status=409)


def test_match_over_outranks_a_bad_action(client):
    """A6: status is checked before the action is even looked at."""
    app = create_app()
    api = app.test_client()
    match_id = api.post(
        "/api/match", json={"player_fighter": "kaito", "opponent_fighter": "vega"}
    ).get_json()["match_id"]
    app.extensions["matches"][match_id]["state"]["status"] = "player_won"

    reject(api, match_id, {"action": "not_a_move"}, "match_over", status=409)
    reject(api, match_id, {}, "match_over", status=409)


def test_match_not_found_outranks_everything(client):
    """A6: an unknown match id is a 404 even with a garbage action."""
    response = client.post(f"/api/match/{uuid.uuid4().hex}/turn", json={"action": "nope"})

    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "match_not_found"


def test_a_rejected_turn_leaves_the_match_playable(client):
    """The UI must not be wedged by a bad request: the next legal turn works."""
    match_id = seeded(client, 5)
    reject(client, match_id, {"action": "surge_beam"}, "insufficient_ki")

    state = client.post(
        f"/api/match/{match_id}/turn", json={"action": "strike"}
    ).get_json()

    assert state["turn"] == 1


def test_the_route_resolves_the_turn_the_rules_would(client):
    """The route adds no rule of its own: same seed, same actions, same result."""
    app = create_app()
    api = app.test_client()
    match_id = api.post(
        "/api/match",
        json={"player_fighter": "kaito", "opponent_fighter": "vega", "seed": 808},
    ).get_json()["match_id"]

    expected = rules.new_match("kaito", "vega")
    rng = random.Random(808)
    for action in ("strike", "charge", "ki_blast", "guard"):
        expected, _ = rules.play_turn(expected, action, rng)
        state = api.post(f"/api/match/{match_id}/turn", json={"action": action}).get_json()
        assert state["player"] == expected["player"]
        assert state["opponent"] == expected["opponent"]
        assert state["log"] == expected["log"]
        assert state["status"] == expected["status"]
