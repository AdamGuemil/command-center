"""Bot Discord : regles pures, liaisons en base, demarrage sans risque pour le CC."""
from __future__ import annotations

import asyncio
import json

from core import bot, config, db


def test_rank_and_level_roles():
    assert bot.lp_to_rank(None) is None
    assert bot.lp_to_rank(2500) == "🔥 Elite"
    assert bot.lp_to_rank(1000) == "🥇 Gold"
    assert bot.lp_to_rank(-5) == "🥉 Bronze"
    assert bot.lp_to_rank("abc") is None
    assert bot.level_to_role(9) is None
    assert bot.level_to_role(30) == "Lvl 25+"
    assert bot.level_to_role(None) is None


def test_link_code_uses_the_game_prefix():
    code = bot.new_link_code()
    assert code.startswith("SW-") and len(code) == 9


def test_links_live_in_the_database_and_legacy_file_is_imported(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "ROOT", tmp_path / "root")
    (tmp_path / "roblox_links.json").write_text(json.dumps({"111": 999, "222": 888, "bad": "x"}))
    assert bot.import_legacy_links() == 2
    assert bot.import_legacy_links() == 0           # une seule fois
    db.set_link(222, 777)
    assert db.get_link(111) == 999 and db.get_link(222) == 777 and db.get_link(333) is None
    assert sorted(db.links()) == [(111, 999), (222, 777)]


def test_bot_data_prefers_the_data_folder(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "ROOT", root)
    (root / "bot_data.json").write_text(json.dumps({"guild_id": 1}))
    assert bot.load_data() == {"guild_id": 1}        # ancien emplacement, encore lu
    (tmp_path / "bot_data.json").write_text(json.dumps({"guild_id": 2}))
    assert bot.load_data() == {"guild_id": 2}


def test_run_without_token_returns_without_raising(monkeypatch, capsys):
    monkeypatch.setattr(config, "DISCORD_BOT_TOKEN", "")
    asyncio.run(bot.run())
    assert "DISCORD_BOT_TOKEN" in capsys.readouterr().out
