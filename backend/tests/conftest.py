"""Make the backend importable the same way the server imports it.

``./script/server`` runs ``cd backend && flask run``, so ``app.py`` says
``from game.rules import ...``. ``./script/test`` runs ``pytest backend/tests``
from the repo root, where ``backend/`` is not on ``sys.path``. Inserting it here
means the tests exercise the exact module paths the server uses.
"""

import os
import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Point every test's default database at a throwaway temp file, never the real
# ``backend/data/fightinggame.db`` (extension E6 / task 7.1: "no test ever
# writes the real database"). ``create_app`` bootstraps a schema on startup, and
# the many single-match API tests do not set a URL of their own, so without this
# they would each create the real database file. Tests that exercise the DB pass
# their own per-test ``url`` to ``db.make_engine`` and never rely on this value.
os.environ.setdefault(
    "DATABASE_URL",
    f"sqlite+pysqlite:///{Path(tempfile.gettempdir()) / 'fightinggame_conftest.db'}",
)
