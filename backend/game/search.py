"""Depth-limited expectimax search (extension E3).

This module is pure: it reads a match state, never mutates the caller's copy,
and — critically — **consumes no RNG** (E3.4). The live match generator is never
handed to anything here; hypothetical turns are resolved with the fixed spreads
of E3.2 through ``rules.resolve_turn``'s ``spread`` keyword (B6).

It knows nothing about HTTP and nothing about difficulty dispatch; ``game.ai``
wires the ``search`` policy to it, which keeps E2.1's streak cap in the one place
that owns policy.
"""

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
