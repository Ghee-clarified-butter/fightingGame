"""Fighter templates and instantiation (spec §2, §2.1).

Templates are plain dicts so that a match state serializes with no conversion
step. ``new_fighter`` hands back a fresh, independent copy every time, which is
what makes a mirror match (kaito vs kaito) two separate fighters rather than two
references to one.
"""


class UnknownFighterError(KeyError):
    """Raised when a fighter id is not in ``FIGHTERS``."""


FIGHTERS: dict[str, dict] = {
    "kaito": {
        "id": "kaito",
        "name": "Kaito",
        "hp_max": 100,
        "ki_max": 100,
        "atk": 22,
        "def": 8,
        "spd": 14,
    },
    "vega": {
        "id": "vega",
        "name": "Vega",
        "hp_max": 130,
        "ki_max": 100,
        "atk": 16,
        "def": 14,
        "spd": 9,
    },
}

STARTING_KI = 30


def new_fighter(fighter_id: str) -> dict:
    """Return a fresh fighter at full hp and 30 ki (§2.1).

    ``passive_streak`` starts at 0: it counts this fighter's consecutive
    non-attacking actions so an AI policy can be stopped from stalling a match
    (extension E2.1). It is bookkeeping only — it never enters ``legal_actions``.

    Raises ``UnknownFighterError`` for an id that is not a known template.
    """
    try:
        template = FIGHTERS[fighter_id]
    except KeyError:
        raise UnknownFighterError(fighter_id) from None

    return {
        "id": template["id"],
        "name": template["name"],
        "hp": template["hp_max"],
        "hp_max": template["hp_max"],
        "ki": STARTING_KI,
        "ki_max": template["ki_max"],
        "atk": template["atk"],
        "def": template["def"],
        "spd": template["spd"],
        "guarding": False,
        "ascended": False,
        "ascend_used": False,
        "passive_streak": 0,
    }
