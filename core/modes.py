"""
Disponibilite des modes de jeu, pilotee depuis le dashboard.

MEME mecanisme que les boosts/recompenses (pas de scope ConfigService requis) : une
cle DataStore "modes_config" dans SharedConfig.dsName("FactionWar") fait foi, un message MessagingService
previent les serveurs deja lances. Cote jeu, ServerStorage/Match/ModeConfig lit cette cle.

Pour chaque mode : up (jouable ? sinon "Soon"), minLevel (niveau requis pour la file).
Operations est un evenement temporaire et porte aussi une date `endsAt` Unix UTC.
"""

from __future__ import annotations

from . import config, roblox_api, store

MODES_KEY = "modes_config"

# Doit correspondre a ModeConfig.MODE_IDS / DEFAULT cote Luau.
MODE_IDS = ("duals", "domination", "exfil", "operations", "wargames")
MODE_LABELS = {
    "duals": "Duels (DUALS)",
    "domination": "Domination",
    "exfil": "Extraction (EXFIL)",
    "operations": "Operations (evenement)",
    "wargames": "War Games",
}
DEFAULT = {
    "duals": {"up": True, "minLevel": 0},
    "domination": {"up": True, "minLevel": 0},
    "exfil": {"up": True, "minLevel": 5},
    "operations": {"up": False, "minLevel": 10, "endsAt": 0},
    "wargames": {"up": True, "minLevel": 0},
}


class ModeError(Exception):
    """Erreur de validation, message destine a l'utilisateur."""


def _sanitize(raw: dict) -> dict:
    out = {}
    for mid in MODE_IDS:
        d = DEFAULT[mid]
        r = (raw or {}).get(mid) or {}
        try:
            lvl = int(r.get("minLevel", d["minLevel"]))
        except (TypeError, ValueError):
            lvl = d["minLevel"]
        out[mid] = {
            "up": bool(r.get("up", d["up"])),
            "minLevel": max(0, min(lvl, 1000)),
        }
        if mid == "operations":
            try:
                ends_at = int(r.get("endsAt", d.get("endsAt", 0)))
            except (TypeError, ValueError):
                ends_at = 0
            out[mid]["endsAt"] = max(0, ends_at)
    return out


def get() -> dict:
    """Etat courant (ou defauts). -> { values, source, error, labels }"""
    try:
        stored = roblox_api.datastore_get(config.FW_DATASTORE, MODES_KEY)
    except Exception as exc:                                    # noqa: BLE001
        local = store.load_settings().get("modesLast")
        if isinstance(local, dict):
            return {"values": _sanitize(local), "source": "local",
                    "error": f"{exc} — derniere saisie locale.",
                    "labels": MODE_LABELS, "modeIds": list(MODE_IDS)}
        return {"values": DEFAULT, "source": "defaults", "error": str(exc),
                "labels": MODE_LABELS, "modeIds": list(MODE_IDS)}
    if isinstance(stored, dict):
        return {"values": _sanitize(stored), "source": "remote", "error": None,
                "labels": MODE_LABELS, "modeIds": list(MODE_IDS)}
    return {"values": DEFAULT, "source": "defaults", "error": None,
            "labels": MODE_LABELS, "modeIds": list(MODE_IDS)}


def save(values: dict) -> dict:
    clean = _sanitize(values or {})
    store.save_settings({"modesLast": clean})   # copie locale avant l'ecriture distante
    roblox_api.datastore_set(config.FW_DATASTORE, MODES_KEY, clean)
    roblox_api.publish(config.FW_TOPIC, {"kind": "modes"})
    return clean


def reset() -> dict:
    """Revient aux defauts (supprime la surcharge)."""
    store.save_settings({"modesLast": None})
    roblox_api.datastore_delete(config.FW_DATASTORE, MODES_KEY)
    roblox_api.publish(config.FW_TOPIC, {"kind": "modes"})
    return DEFAULT
