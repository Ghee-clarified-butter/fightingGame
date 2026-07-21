"""Tests for AI move selection (extension E1, E2.1).

The rules-level bookkeeping that feeds the cap — ``passive_streak`` incrementing
and resetting — is covered in ``test_rules.py``. This file is about what the
policies do with it.
"""

import random

import pytest

from game.ai import (
    DIFFICULTIES,
    PASSIVE_CAP,
    UnknownDifficultyError,
    attacking_candidates,
    choose_action,
    play_turn,
)
from game.fighters import FIGHTERS
from game.moves import ACTION_ORDER, MOVES
from game.rules import legal_actions, new_match, resolve_turn

ATTACKS = [action for action in ACTION_ORDER if MOVES[action]["is_attack"]]
PASSIVES = [action for action in ACTION_ORDER if not MOVES[action]["is_attack"]]


def _match_with(player: dict | None = None, opponent: dict | None = None, **top) -> dict:
    """A fresh Kaito-vs-Vega match with the given fields overwritten."""
    match = new_match("kaito", "vega")
    match.update(top)
    match["player"].update(player or {})
    match["opponent"].update(opponent or {})
    return match


# --- The cap itself (E2.1) ---------------------------------------------------


def test_the_cap_is_two_consecutive_passives():
    """E2.1 in one number: the *third* consecutive passive turn is forbidden."""
    assert PASSIVE_CAP == 2


def test_below_the_cap_every_legal_move_stays_a_candidate():
    fighter = new_match("kaito", "vega")["opponent"]
    fighter["ki"] = 100
    for streak in range(PASSIVE_CAP):
        fighter["passive_streak"] = streak
        assert attacking_candidates(fighter, legal_actions(fighter)) == ACTION_ORDER


def test_at_the_cap_only_attacks_remain():
    fighter = new_match("kaito", "vega")["opponent"]
    fighter["ki"] = 100
    fighter["passive_streak"] = PASSIVE_CAP
    assert attacking_candidates(fighter, legal_actions(fighter)) == ATTACKS


def test_the_cap_leaves_strike_when_nothing_else_is_affordable():
    """Strike costs 0 ki, so a forced attack always exists — even at 0 ki."""
    fighter = new_match("kaito", "vega")["opponent"]
    fighter["ki"] = 0
    fighter["passive_streak"] = 5
    assert attacking_candidates(fighter, legal_actions(fighter)) == ["strike"]


def test_the_cap_does_not_touch_legal_actions():
    """E2.1: the cap constrains policy selection, never the rules.

    Byte-identical output for a fighter with streak 0 and streak 5 is what makes
    "the player is not bound" true at the source rather than by convention.
    """
    zero = new_match("kaito", "vega")["player"]
    zero["ki"] = 100
    deep = dict(zero, passive_streak=5)
    assert legal_actions(zero) == legal_actions(deep)


# --- The random policy under the cap ----------------------------------------


def test_random_is_forced_to_attack_on_the_third_passive_turn():
    """Over many draws at the cap, a passive move never comes out."""
    match = _match_with(opponent={"ki": 100, "passive_streak": PASSIVE_CAP})
    rng = random.Random(1)
    drawn = {choose_action(match, "opponent", "random", rng) for _ in range(400)}
    assert drawn == set(ATTACKS)


@pytest.mark.parametrize("streak", [0, 1])
def test_random_may_still_go_passive_below_the_cap(streak):
    """Two consecutive passive turns are allowed; only the third is not."""
    match = _match_with(opponent={"ki": 100, "passive_streak": streak})
    rng = random.Random(2)
    drawn = {choose_action(match, "opponent", "random", rng) for _ in range(400)}
    assert drawn == set(ACTION_ORDER)


def test_random_consumes_exactly_one_choice_draw_below_the_cap():
    """B2: the draw is one ``rng.choice`` over the ordered candidate list.

    ``rng.choice`` scales its raw draws to the list length, so replaying the
    pinned call is what fixes both the count *and* the list it was made over.
    """
    match = _match_with(opponent={"ki": 100})
    rng = random.Random(6)
    probe = random.Random(6)
    chosen = choose_action(match, "opponent", "random", rng)
    assert chosen == probe.choice(ACTION_ORDER)
    assert rng.getstate() == probe.getstate()


def test_random_consumes_exactly_one_choice_draw_at_the_cap():
    """Still one draw when the cap shortened the list — just over a shorter one.

    That the *result* differs from the unfiltered draw at the same seed is B3:
    E2.1 binds the random policy, so a fixed seed can now yield a different
    match than it did in Step 1.
    """
    match = _match_with(opponent={"ki": 100, "passive_streak": PASSIVE_CAP})
    rng = random.Random(6)
    probe = random.Random(6)
    chosen = choose_action(match, "opponent", "random", rng)
    assert chosen == probe.choice(ATTACKS)
    assert rng.getstate() == probe.getstate()


def test_the_cap_reads_the_chooser_not_its_foe():
    """A passive player must not force the *opponent* to attack."""
    match = _match_with(
        player={"ki": 100, "passive_streak": 9},
        opponent={"ki": 100, "passive_streak": 0},
    )
    rng = random.Random(3)
    drawn = {choose_action(match, "opponent", "random", rng) for _ in range(400)}
    assert drawn == set(ACTION_ORDER)


def test_either_side_can_be_the_chooser():
    """Tournaments run AI against AI (E8), so the AI is not always ``opponent``."""
    match = _match_with(player={"ki": 0, "passive_streak": PASSIVE_CAP})
    rng = random.Random(4)
    drawn = {choose_action(match, "player", "random", rng) for _ in range(50)}
    assert drawn == {"strike"}


# --- Dispatch ----------------------------------------------------------------


def test_random_is_a_difficulty():
    assert "random" in DIFFICULTIES


@pytest.mark.parametrize("difficulty", ["", "hard", "Random", "RANDOM", None, 3])
def test_an_unknown_difficulty_raises(difficulty):
    match = new_match("kaito", "vega")
    with pytest.raises(UnknownDifficultyError) as excinfo:
        choose_action(match, "opponent", difficulty, random.Random(1))
    assert excinfo.value.args[0] == difficulty


# --- ``play_turn`` -----------------------------------------------------------


def test_play_turn_reads_the_difficulty_off_the_state():
    """B5: the policy comes from the match, not from the caller."""
    match = _match_with(difficulty="nonsense")
    with pytest.raises(UnknownDifficultyError):
        play_turn(match, "strike", random.Random(1))


def test_a_new_match_plays_under_the_random_policy():
    """The default is ``random``, so Step 1 matches keep their behaviour (E1)."""
    match = new_match("kaito", "vega")
    assert match["difficulty"] == "random"
    state, entries = play_turn(match, "strike", random.Random(5))
    assert state["turn"] == 1
    assert {entry["actor"] for entry in entries} <= {"player", "opponent"}


def test_the_opponent_never_goes_passive_three_turns_running():
    """E10: no AI takes a non-attacking action three turns in a row.

    Played through ``play_turn`` over many seeds, so this exercises the cap in
    the composition the server actually uses rather than on a crafted state. The
    ``forced`` counter keeps the assertion from passing vacuously: it counts the
    turns the opponent entered already at the cap, which are exactly the turns on
    which the filter did the work.
    """
    forced = 0
    for seed in range(60):
        state = new_match("kaito", "vega")
        rng = random.Random(seed)
        streak = 0
        while state["status"] == "in_progress":
            forced += streak == PASSIVE_CAP
            state, entries = play_turn(state, "charge", rng)
            action = next(e["action"] for e in entries if e["actor"] == "opponent")
            streak = 0 if MOVES[action]["is_attack"] else streak + 1
            assert streak <= PASSIVE_CAP, f"seed {seed}: opponent went passive {streak} times"
    assert forced > 0, "the cap never bound, so this proves nothing about it"


def test_the_player_is_not_bound_by_the_cap():
    """E10: charging four turns running is accepted, and stays accepted."""
    state = new_match("kaito", "vega")
    rng = random.Random(7)
    for turn in range(1, 5):
        assert "charge" in legal_actions(state["player"])
        state, _ = play_turn(state, "charge", rng)
        assert state["turn"] == turn
        assert state["player"]["passive_streak"] == turn


def test_play_turn_does_not_mutate_its_input():
    match = new_match("kaito", "vega")
    before = {"turn": match["turn"], "log": list(match["log"])}
    play_turn(match, "strike", random.Random(41))
    assert match["turn"] == before["turn"]
    assert match["log"] == before["log"]


def test_every_passive_move_is_filtered_by_the_cap():
    """All three of charge, guard and ascend are non-attacking (E2.1)."""
    assert PASSIVES == ["charge", "guard", "ascend"]


# --- The heuristic policy (E2 rules 1-7) -------------------------------------
#
# Every rule gets a state where exactly that rule fires, paired with one where
# its guard is *just* unmet so the next rule fires instead. The pairs are what
# make the boundaries real: a test that only ever satisfies a condition cannot
# tell a ``>=`` from a ``>``.
#
# All the numbers below are Kaito (atk 22) against Vega (def 14) and back, at the
# spread the rule names — see the derivations inline.


def _heuristic(player=None, opponent=None, side="player") -> str:
    """``side``'s heuristic move on a Kaito-vs-Vega state with those overrides."""
    match = _match_with(player=player, opponent=opponent)
    return choose_action(match, side, "heuristic")


def test_heuristic_is_a_difficulty():
    assert "heuristic" in DIFFICULTIES


@pytest.mark.parametrize(
    ("foe_hp", "expected"),
    [
        # Kaito's minimum damage (spread 0.90): Strike 8, Ki Blast 14, Beam 26.
        (8, "strike"),
        (14, "ki_blast"),
        (26, "surge_beam"),
    ],
)
def test_rule_1_finishes_with_the_cheapest_lethal_attack(foe_hp, expected):
    """Rule 1: cheapest, and sized by the *minimum* roll, not the expected one."""
    assert _heuristic(player={"ki": 100}, opponent={"hp": foe_hp, "ki": 0}) == expected


def test_rule_1_falls_through_when_the_foe_survives_the_minimum_by_one():
    """27 hp against a 26-damage worst case is not a finish — rule 3 fires instead."""
    assert _heuristic(player={"ki": 100}, opponent={"hp": 27, "ki": 0}) == "ascend"


def test_rule_1_skips_a_lethal_attack_it_cannot_afford():
    """The Beam would kill, but at 0 ki it is illegal, so the rule is skipped."""
    assert _heuristic(player={"ki": 0}, opponent={"hp": 26, "ki": 0}) == "charge"


def test_rule_2_guards_against_a_lethal_incoming_beam():
    """Vega's Surge Beam at spread 1.10 deals 35 to an unguarded Kaito."""
    assert _heuristic(player={"hp": 35, "ki": 0}, opponent={"ki": 40}) == "guard"


def test_rule_2_falls_through_when_the_beam_leaves_one_hp():
    assert _heuristic(player={"hp": 36, "ki": 0}, opponent={"ki": 40}) == "charge"


def test_rule_2_falls_through_when_the_foe_cannot_afford_the_beam():
    """One ki short of the 40 it costs: the threat is not real yet."""
    assert _heuristic(player={"hp": 35, "ki": 0}, opponent={"ki": 39}) == "charge"


@pytest.mark.parametrize(
    ("hp", "ki", "expected"),
    [
        (50, 65, "ascend"),  # both boundaries met exactly
        (49, 65, "ki_blast"),  # one hp under half
        (50, 64, "ki_blast"),  # one ki under the floor
    ],
)
def test_rule_3_ascends_only_at_half_health_and_65_ki(hp, ki, expected):
    assert _heuristic(player={"hp": hp, "ki": ki}, opponent={"ki": 0}) == expected


def test_rule_3_is_skipped_once_ascend_has_been_used():
    """Once-per-match (§3): the rule holds, the move is illegal, rule 4 fires."""
    chosen = _heuristic(
        player={"ki": 100, "ascended": True, "ascend_used": True},
        opponent={"ki": 0},
    )
    assert chosen == "surge_beam"


@pytest.mark.parametrize(("ki", "expected"), [(80, "surge_beam"), (79, "ki_blast")])
def test_rule_4_beams_only_at_80_ki(ki, expected):
    """Below half health so rule 3 cannot pre-empt it."""
    assert _heuristic(player={"hp": 40, "ki": ki}, opponent={"ki": 0}) == expected


@pytest.mark.parametrize(("ki", "expected"), [(15, "ki_blast"), (14, "charge")])
def test_rule_5_pokes_while_a_ki_blast_is_affordable(ki, expected):
    """15 ki is exactly a Ki Blast; 14 is rule 6's recover threshold."""
    assert _heuristic(player={"hp": 40, "ki": ki}, opponent={"ki": 0}) == expected


def test_rule_7_strikes_when_the_cap_removes_the_charge():
    """The only route to rule 7: Charge is illegal to *pick*, not illegal (E2.1).

    At 0 ki rule 6 would recover, but a third consecutive passive turn is
    forbidden, so the scan falls all the way to Strike — which costs 0 ki and is
    an attack, and so always survives both filters.
    """
    player = {"hp": 40, "ki": 0, "passive_streak": PASSIVE_CAP}
    assert _heuristic(player=player, opponent={"ki": 0}) == "strike"


def test_the_heuristic_reads_the_chooser_not_always_the_player():
    """Vega choosing: Vega's Strike at spread 0.90 deals 8 to Kaito."""
    chosen = _heuristic(player={"hp": 8}, opponent={"ki": 0}, side="opponent")
    assert chosen == "strike"


def test_a_heuristic_match_plays_out_through_play_turn():
    """The policy composes with §4.8's order exactly as ``random`` does."""
    state = _match_with(difficulty="heuristic")
    rng = random.Random(11)
    while state["status"] == "in_progress":
        state, entries = play_turn(state, "strike", rng)
        for entry in entries:
            assert entry["action"] in ACTION_ORDER
    assert state["status"] in {"player_won", "opponent_won", "draw"}


# --- Cap precedence over the heuristic's own rules (E2.1) --------------------
#
# E2.1 states the cap "outranks every rule that would otherwise fire". The pair
# below is that sentence made falsifiable: one position, one difference — the
# streak — and the AI trades a survivable turn for a lethal one because of it.
# Kaito on 35 hp against a Vega holding 80 ki with Ascend spent:
#   * rule 2 sees Vega's best-case Surge Beam at 48 * 16/(16+8) * 1.10 = 35,
#     exactly lethal, and wants to Guard;
#   * guarded, that same beam deals round(35.2 * 0.5) = 18, so Guard survives.

_LETHAL_BEAM_PLAYER = {"hp": 35, "ki": 0}
_BEAM_READY_OPPONENT = {"ki": 80, "ascend_used": True}


def test_rule_2_would_guard_against_this_beam():
    """The control: below the cap the panic guard fires on this exact position."""
    chosen = _heuristic(player=_LETHAL_BEAM_PLAYER, opponent=_BEAM_READY_OPPONENT)
    assert chosen == "guard"


def test_the_cap_overrides_the_panic_guard():
    """E10: at the cap the same position attacks instead — the cap outranks rule 2."""
    player = dict(_LETHAL_BEAM_PLAYER, passive_streak=PASSIVE_CAP)
    chosen = _heuristic(player=player, opponent=_BEAM_READY_OPPONENT)
    assert MOVES[chosen]["is_attack"]
    assert chosen == "strike"


@pytest.mark.parametrize(
    ("streak", "status"),
    [(0, "in_progress"), (PASSIVE_CAP, "opponent_won")],
)
def test_the_cap_may_cost_the_ai_the_match(streak, status):
    """E2.1's stated price: forced out of Guard, the AI eats the beam and dies.

    Resolved at a fixed ``spread`` of 1.10 (B6) so the outcome is the rule's
    consequence rather than a roll: no RNG is consumed by either the selection or
    the resolution. Kaito is the faster fighter, so it swings first and is still
    alive to be killed by the reply.
    """
    match = _match_with(
        player=dict(_LETHAL_BEAM_PLAYER, passive_streak=streak),
        opponent=_BEAM_READY_OPPONENT,
    )
    player_action = choose_action(match, "player", "heuristic")
    opponent_action = choose_action(match, "opponent", "heuristic")
    assert opponent_action == "surge_beam"
    state, _ = resolve_turn(
        match,
        player_action,
        opponent_action,
        None,
        order=("player", "opponent"),
        spread=1.10,
    )
    assert state["status"] == status


# --- Legality fuzz across every difficulty (E10) -----------------------------


def _random_fighter(rng: random.Random) -> dict:
    """A fighter at an arbitrary reachable point in a match.

    ``hp`` never reaches 0 — a KO'd fighter is never asked to choose — and
    ``ascended`` implies ``ascend_used`` because ``_apply_ascend`` sets both.
    """
    fighter = new_match(rng.choice(list(FIGHTERS)), "vega")["player"]
    fighter["hp"] = rng.randint(1, fighter["hp_max"])
    fighter["ki"] = rng.randint(0, fighter["ki_max"])
    fighter["ascended"] = rng.random() < 0.4
    fighter["ascend_used"] = fighter["ascended"] or rng.random() < 0.3
    fighter["passive_streak"] = rng.randint(0, PASSIVE_CAP + 3)
    return fighter


def _random_state(rng: random.Random) -> dict:
    state = new_match("kaito", "vega")
    state["turn"] = rng.randint(0, 99)
    state["player"] = _random_fighter(rng)
    state["opponent"] = _random_fighter(rng)
    return state


@pytest.mark.parametrize("difficulty", DIFFICULTIES)
def test_every_difficulty_only_ever_picks_a_legal_move(difficulty):
    """1000 generated states per policy: the cap filters, it never invents.

    ``attacking_candidates`` falls back to the unfiltered list when it would
    otherwise empty one, so this is the assertion that catches a policy returning
    a move the fighter cannot pay for — at any streak, including well past the
    cap.
    """
    rng = random.Random(2024)
    for index in range(1000):
        for side in ("player", "opponent"):
            state = _random_state(rng)
            action = choose_action(state, side, difficulty, rng)
            allowed = legal_actions(state[side])
            assert action in allowed, f"{difficulty} #{index} {side}: {action} not in {allowed}"


@pytest.mark.parametrize("difficulty", DIFFICULTIES)
def test_the_cap_forces_an_attack_at_every_streak_above_it(difficulty):
    """The other half of the fuzz: past the cap, only attacks come out."""
    rng = random.Random(99)
    for _ in range(500):
        state = _random_state(rng)
        state["opponent"]["passive_streak"] = rng.randint(PASSIVE_CAP, PASSIVE_CAP + 3)
        action = choose_action(state, "opponent", difficulty, rng)
        assert MOVES[action]["is_attack"], f"{difficulty}: {action} at the cap"


def test_the_heuristic_consumes_no_randomness():
    """E3.4's principle, one policy early: a pure policy leaves the RNG alone.

    Checked over generated states rather than one, because a stray draw on a
    single branch is exactly the bug a single position would miss.
    """
    rng = random.Random(31)
    for _ in range(200):
        state = _random_state(rng)
        probe = random.Random(77)
        before = probe.getstate()
        choose_action(state, "player", "heuristic", probe)
        assert probe.getstate() == before


def test_legal_actions_ignores_the_streak_over_generated_states():
    """The player-not-bound criterion at the source (E2.1).

    ``legal_actions`` is what the HTTP layer validates a player's move against,
    so if it were byte-identical only on the positions a hand-written test
    happens to pick, the cap could still leak into the player's options.
    """
    rng = random.Random(505)
    for _ in range(500):
        fighter = _random_fighter(rng)
        baseline = legal_actions(dict(fighter, passive_streak=0))
        for streak in range(1, PASSIVE_CAP + 4):
            assert legal_actions(dict(fighter, passive_streak=streak)) == baseline


@pytest.mark.parametrize("difficulty", DIFFICULTIES)
def test_the_player_may_charge_four_turns_running_at_every_difficulty(difficulty):
    """E10: the cap binds AI policy only, whichever policy the match was made with."""
    state = _match_with(difficulty=difficulty)
    rng = random.Random(13)
    for turn in range(1, 5):
        assert "charge" in legal_actions(state["player"])
        state, entries = play_turn(state, "charge", rng)
        assert any(e["actor"] == "player" and e["action"] == "charge" for e in entries)
        assert state["player"]["passive_streak"] == turn
