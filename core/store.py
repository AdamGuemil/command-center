"""
Persistance JSON locale : modeles d'annonces et file de planification.

Volontairement en fichiers plats et lisibles : tu peux les editer a la main,
les versionner, ou les copier sur une autre machine. Pas de base de donnees
pour un outil mono-utilisateur.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from . import config

TEMPLATES_FILE = config.DATA_DIR / "templates.json"
SCHEDULE_FILE = config.DATA_DIR / "schedule.json"
HISTORY_FILE = config.DATA_DIR / "history.json"
SETTINGS_FILE = config.DATA_DIR / "settings.json"

# seasonLabelOffset : DECALAGE D'AFFICHAGE UNIQUEMENT.
# L'index de semaine vient du calendrier FactionWarConfig et sert de cle
# DataStore. Ce decalage ne modifie que le libelle de saison, jamais les scores.
DEFAULT_SETTINGS = {
    "seasonLabelOffset": 0,
    "seasonLabelPrefix": "Semaine",
    "rankedTiers": None,   # None = bareme par defaut (voir ranked_rewards)
    "rewardsLast": None,   # derniere surcharge appliquee (repli d'affichage)
}


def load_settings() -> dict:
    data = _read(SETTINGS_FILE, {})
    return {**DEFAULT_SETTINGS, **(data if isinstance(data, dict) else {})}


def save_settings(patch: dict) -> dict:
    current = load_settings()
    if isinstance(patch, dict):
        if "seasonLabelOffset" in patch:
            try:
                current["seasonLabelOffset"] = int(patch["seasonLabelOffset"])
            except (TypeError, ValueError):
                pass
        if "seasonLabelPrefix" in patch:
            current["seasonLabelPrefix"] = str(patch["seasonLabelPrefix"])[:24]
        if "rankedTiers" in patch and isinstance(patch["rankedTiers"], list):
            current["rankedTiers"] = patch["rankedTiers"]
        # Derniere surcharge de recompenses appliquee. Sert de repli d'affichage
        # quand Open Cloud est injoignable : on ne veut jamais laisser croire
        # qu'une saisie est perdue. None = surcharge supprimee.
        if "rewardsLast" in patch:
            current["rewardsLast"] = patch["rewardsLast"]
    _write(SETTINGS_FILE, current)
    return current


def _read(path: Path, fallback):
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        # Un fichier corrompu ne doit pas empecher l'outil de demarrer :
        # on repart du defaut et on conserve l'original pour inspection.
        try:
            path.rename(path.with_suffix(".corrupt.json"))
        except OSError:
            pass
        return fallback


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)          # ecriture atomique : jamais de fichier a moitie ecrit


# MODELES
def load_templates() -> list[dict]:
    return _read(TEMPLATES_FILE, [])


def save_templates(items: list[dict]) -> list[dict]:
    clean = []
    for it in items:
        if not isinstance(it, dict) or not it.get("name"):
            continue
        clean.append({
            "id": it.get("id") or uuid.uuid4().hex[:8],
            "name": it["name"],
            "channel": it.get("channel", ""),
            "title": it.get("title", ""),
            "body": it.get("body", ""),
            "color": int(it.get("color") or config.COLORS["neutral"]),
            "footer": it.get("footer", ""),
            "image": it.get("image", ""),
            "ping": it.get("ping", ""),
        })
    _write(TEMPLATES_FILE, clean)
    return clean


# --------------------------------------------------------- PLANIFICATION ---
def load_schedule() -> list[dict]:
    return _read(SCHEDULE_FILE, [])


def save_schedule(items: list[dict]) -> list[dict]:
    clean = []
    for it in items:
        if not isinstance(it, dict):
            continue
        clean.append({
            "id": it.get("id") or uuid.uuid4().hex[:8],
            "at": it.get("at", ""),               # ISO local, ex "2026-07-25T18:00"
            "templateId": it.get("templateId", ""),
            "channel": it.get("channel", ""),
            "ping": it.get("ping", ""),
            "note": it.get("note", ""),
            "done": bool(it.get("done")),
        })
    clean.sort(key=lambda x: x["at"] or "9999")
    _write(SCHEDULE_FILE, clean)
    return clean


def mark_schedule_done(item_id: str) -> None:
    items = load_schedule()
    for it in items:
        if str(it.get("id")) == str(item_id):
            it["done"] = True
    save_schedule(items)


# -------------------------------------------------------------- HISTORIQUE -
# Les envois vivent dans le journal d'audit (core/db.py, data/cc.db). history.json n'est
# plus ecrit : il est importe une fois au premier demarrage puis laisse tel quel.
def log_send(channel_name: str, title: str, ok: bool, detail: str = "", card: str | None = None) -> None:
    """Trace des envois : savoir ce qui est deja parti evite les doublons."""
    from . import db
    db.audit("discord_send", channel_name, {"title": title, "error": detail[:300]}, ok, card)


def load_history(limit: int = 100) -> list[dict]:
    """Les derniers envois Discord, au format historique (ecran Historique, announce.py)."""
    from . import db
    out = []
    for r in db.audit_rows(limit, "discord_send"):
        d = r["detail"] if isinstance(r["detail"], dict) else {}
        out.append({"at": r["at"], "channel": r["target"], "title": d.get("title", ""),
                    "ok": r["ok"], "detail": d.get("error", "")})
    return out
