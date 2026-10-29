"""Identifiants fictifs pour les tests : le depot ne porte aucun identifiant reel par defaut."""
import os
import sys
from pathlib import Path

os.environ.setdefault("ROBLOX_UNIVERSE_ID", "1000000001")
os.environ.setdefault("ROBLOX_PLACE_ID", "2000000001")
os.environ.setdefault("ROBLOX_GAME_PLACE_ID", "2000000002")
os.environ.pop("CC_DEMO", None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """Aucun test n'ecrit dans la vraie base data/cc.db."""
    from core import db
    monkeypatch.setattr(db, "DB_FILE", tmp_path / "cc.db")
