"""Make the backend importable the same way the server imports it.

``./script/server`` runs ``cd backend && flask run``, so ``app.py`` says
``from game.rules import ...``. ``./script/test`` runs ``pytest backend/tests``
from the repo root, where ``backend/`` is not on ``sys.path``. Inserting it here
means the tests exercise the exact module paths the server uses.
"""

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
