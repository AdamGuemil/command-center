"""
Taches de fond quotidiennes : sauvegarde de la base, menage.

Appele chaque minute par le fil des automatisations (core/automations.py) ; ne fait le
travail qu'une fois par jour (heure de Paris). La sauvegarde utilise l'API de sauvegarde de
SQLite : une copie coherente meme si le CC ecrit au meme moment. Les copies vont dans
CC_BACKUP_DIR (data/backups par defaut), une par jour, les CC_BACKUP_KEEP plus recentes
gardees. Pour une copie hors du serveur, voir docs/OPERATIONS.md (« Sauvegardes »).
"""

from __future__ import annotations

import time
from datetime import datetime

from . import config, db, roblox_api

_state: dict = {"day": None, "lastBackup": None, "lastError": None}


def _today(now: float) -> str:
    return datetime.fromtimestamp(now, roblox_api.FW_TIMEZONE).strftime("%Y-%m-%d")


def backup(now: float | None = None) -> dict:
    now = time.time() if now is None else now
    day = _today(now)
    path = config.BACKUP_DIR / f"cc-{day}.db"
    size = db.backup_to(path)
    copies = sorted(config.BACKUP_DIR.glob("cc-*.db"))
    for old in copies[:-max(1, config.BACKUP_KEEP)]:
        old.unlink(missing_ok=True)
    info = {"at": int(now), "file": path.name, "bytes": size, "kept": min(len(copies), max(1, config.BACKUP_KEEP))}
    _state["lastBackup"] = info
    return info


def daily(now: float | None = None) -> None:
    now = time.time() if now is None else now
    day = _today(now)
    if _state["day"] == day:
        return
    try:
        if not (config.BACKUP_DIR / f"cc-{day}.db").exists():
            backup(now)
        _state.update(day=day, lastError=None)
    except Exception as exc:                                    # noqa: BLE001
        _state["lastError"] = str(exc)[:200]


def status() -> dict:
    return {**_state}
