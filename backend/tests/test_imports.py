"""Guard the import layout that every later test depends on (plan A10)."""

import sys
from pathlib import Path

from conftest import BACKEND_DIR


def test_backend_dir_is_on_sys_path():
    assert str(BACKEND_DIR) in sys.path


def test_backend_dir_is_the_directory_holding_the_game_package():
    assert BACKEND_DIR.name == "backend"
    assert (BACKEND_DIR / "game" / "__init__.py").is_file()


def test_game_package_imports_from_the_server_module_path():
    import game

    assert Path(game.__file__).resolve() == (BACKEND_DIR / "game" / "__init__.py").resolve()


def test_requirements_file_exists():
    assert (BACKEND_DIR / "requirements.txt").is_file()
