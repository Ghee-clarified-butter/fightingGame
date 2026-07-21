"""Depth-limited expectimax search (extension E3).

This module is pure: it reads a match state, never mutates the caller's copy,
and — critically — **consumes no RNG** (E3.4). The live match generator is never
handed to anything here; hypothetical turns are resolved with the fixed spreads
of E3.2 through ``rules.resolve_turn``'s ``spread`` keyword (B6).

It knows nothing about HTTP and nothing about difficulty dispatch; ``game.ai``
wires the ``search`` policy to it, which keeps E2.1's streak cap in the one place
that owns policy.
"""

from game.moves import MOVES
from game.rules import deterministic_order, resolve_turn

#: The value of a decided position, from the AI's perspective. Two orders of
#: magnitude above anything the material terms below can produce (100 is a whole
#: health bar), so the search always prefers a win to any accumulation of
#: advantage and always prefers survival to any amount of it (E3.3).
TERMINAL_VALUE = 1000.0

#: E3.3's weights. HP dominates; ki is latent damage and worth about a tenth of
#: a health bar per full pool; tempo is the part of having ascended that neither
#: hp nor ki captures.
HP_WEIGHT = 100.0
KI_WEIGHT = 10.0
TEMPO_WEIGHT = 8.0

#: Ki is scaled by this rather than by either fighter's ``ki_max`` so the term
#: stays a plain difference of pools — both fighters have a 100 ki pool (§2.1)
#: and E3.3 writes the divisor as the literal 100.
KI_SCALE = 100.0

#: The side each side faces.
_FOE = {"player": "opponent", "opponent": "player"}

#: E3.2's chance node. The spread is uniform on [0.90, 1.10] (§4.1) and cannot be
#: enumerated, so it is sampled at the *midpoints of three equal-probability
#: intervals* — 0.90 + 0.2/6, the mean, and 1.10 - 0.2/6. Sampling the endpoints
#: 0.90/1.00/1.10 instead would put a third of the mass on each end of a flat
#: distribution, inflating the variance the search believes it faces and biasing
#: it toward defensive play. The endpoints still belong in E2 rules 1 and 2,
#: where the worst and best case is the actual question.
SPREAD_SAMPLES = (0.9333, 1.0, 1.0667)

#: Equal weights, one per sample (E3.2).
SPREAD_WEIGHT = 1.0 / len(SPREAD_SAMPLES)

#: The single sample used below the root ply, and for turns with no attack in
#: them at all. It is ``SPREAD_SAMPLES``' middle entry, so the mean-only ply is
#: literally one of the three branches rather than a fourth number.
MEAN_SPREAD = SPREAD_SAMPLES[1]


def spread_samples(player_action: str, opponent_action: str, *, root: bool) -> tuple[float, ...]:
    """Return the spreads to branch over for this action pair (E3.2).

    Three equally likely samples when either side attacks **at the root ply**,
    and exactly one otherwise, for two separate reasons:

    * A turn in which neither side attacks draws no spread at all, so three
      children would be three identical states — wrong as probability and
      wasteful as cost. Mixed charge/guard lines are therefore cheap.
    * Below the root ply the spread's contribution is dominated by the choice of
      moves, and paying a 3× branching factor per ply is what pushes the search
      past its time budget (E3.5). So deeper plies take the mean alone.
    """
    if root and (MOVES[player_action]["is_attack"] or MOVES[opponent_action]["is_attack"]):
        return SPREAD_SAMPLES
    return (MEAN_SPREAD,)


def chance_children(
    state: dict, player_action: str, opponent_action: str, *, root: bool
) -> list[tuple[float, dict]]:
    """Expand one turn into its ``(weight, child_state)`` pairs (E3.1, E3.2).

    The weights are the sample probabilities and always sum to 1: ``1/3`` each
    for a three-way root branch, ``1.0`` for a single child.

    Every call passes an explicit ``spread`` **and** an explicit ``order``, so
    ``rules.resolve_turn`` reaches neither of its two draw sites and ``rng=None``
    is safe. That is E3.4's "the search must never be handed the live match RNG"
    made structural rather than promised: there is no generator here to touch.
    The order comes from ``rules.deterministic_order``, which breaks a speed tie
    without a coin flip (B6).
    """
    order = deterministic_order(state)
    samples = spread_samples(player_action, opponent_action, root=root)
    weight = 1.0 / len(samples)
    return [
        (
            weight,
            resolve_turn(
                state, player_action, opponent_action, None, order=order, spread=spread
            )[0],
        )
        for spread in samples
    ]


def evaluate(state: dict, side: str) -> float:
    """Score ``state`` from ``side``'s point of view (E3.3).

    Positive is good for ``side``. A knocked-out fighter short-circuits to
    ±:data:`TERMINAL_VALUE` before any material term is computed — a dead
    fighter's leftover ki is not worth points, and letting it contribute would
    let the search prefer a rich corpse to a poor survivor.

    ``side``'s own death is checked first. Both fighters can be at 0 hp only if
    a caller hand-built that position; §4.4 stops resolution at the first KO, so
    it cannot arise from play. Scoring it as a loss is the conservative reading
    and matches E3.3's literal order.

    HP is compared as a *fraction* of each pool, so Kaito at 50/100 and Vega at
    65/130 are level rather than Vega being 15 points ahead for having the
    bigger bar (§2.1).
    """
    me = state[side]
    foe = state[_FOE[side]]

    if me["hp"] == 0:
        return -TERMINAL_VALUE
    if foe["hp"] == 0:
        return TERMINAL_VALUE

    hp_term = HP_WEIGHT * (me["hp"] / me["hp_max"] - foe["hp"] / foe["hp_max"])
    ki_term = KI_WEIGHT * (me["ki"] - foe["ki"]) / KI_SCALE
    tempo_term = TEMPO_WEIGHT * (int(me["ascended"]) - int(foe["ascended"]))
    return hp_term + ki_term + tempo_term
