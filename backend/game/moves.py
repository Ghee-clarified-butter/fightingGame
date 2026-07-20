"""The move table (spec §3).

``MOVES`` is data, not behaviour: ki cost, power and whether the move is an
attack. The rules module reads it; nothing here knows about match state.

``ACTION_ORDER`` is the canonical ordering used everywhere a list of actions is
produced (``legal_actions``, the opponent's uniform choice). Fixing it is what
makes a seeded match reproducible — iterating a set would not be.
"""

ACTION_ORDER: list[str] = [
    "strike",
    "ki_blast",
    "surge_beam",
    "charge",
    "guard",
    "ascend",
]

MOVES: dict[str, dict] = {
    "strike": {
        "name": "Strike",
        "cost": 0,
        "power": 14,
        "is_attack": True,
    },
    "ki_blast": {
        "name": "Ki Blast",
        "cost": 15,
        "power": 26,
        "is_attack": True,
    },
    "surge_beam": {
        "name": "Surge Beam",
        "cost": 40,
        "power": 48,
        "is_attack": True,
    },
    "charge": {
        "name": "Charge",
        "cost": 0,
        "power": None,
        "is_attack": False,
    },
    "guard": {
        "name": "Guard",
        "cost": 0,
        "power": None,
        "is_attack": False,
    },
    "ascend": {
        "name": "Ascend",
        "cost": 40,
        "power": None,
        "is_attack": False,
    },
}
