"""
Maintenance de stockage : purge du STASH des joueurs inactifs depuis N mois.

POURQUOI : le stash de chaque joueur vit sous sa propre cle DataStore. Un joueur qui
ne revient jamais garde son stash indefiniment -> stockage qui ne fait que croitre.
On propose de supprimer le stash des joueurs dont la DERNIERE connexion (lastSeenAt du
profil) remonte a plus de N mois.

SUR PAR CONCEPTION :
  * scan borne (une page de cles a la fois, curseur) -> jamais un balayage geant bloquant ;
  * DRY-RUN par defaut (liste QUI serait purge, sans rien supprimer) ;
  * la suppression prend une LISTE EXPLICITE d'userIds (revus par l'operateur), pas un
    "supprime tout ce qui matche" a l'aveugle.

Cout : 1 lecture de profil par cle de stash scannee (pour lire lastSeenAt). On plafonne
donc le nombre de cles par scan.
"""

from __future__ import annotations

import time
from typing import Any

from . import config, roblox_api

STASH_DATASTORE = config.datastore_name("PlayerData_Stash")
PROFILE_DATASTORE = config.datastore_name("GlobalData")

DAY = 86400


def _last_seen(user_id: int) -> int | None:
    """lastSeenAt (epoch) du profil, ou None si illisible / absent."""
    try:
        prof = roblox_api.datastore_get(PROFILE_DATASTORE, f"p_{user_id}")
    except Exception:                                          # noqa: BLE001
        return None
    if isinstance(prof, dict):
        ts: Any = prof.get("lastSeenAt")
        try:
            return int(ts)
        except (TypeError, ValueError):
            return None
    return None


def scan_inactive_stashes(months: int = 3, cursor: str | None = None,
                          max_keys: int = 100) -> dict:
    """Scanne UNE page de cles de stash. Renvoie les candidats a la purge (inactifs
    depuis >= `months` mois) + le curseur pour la page suivante. Ne supprime RIEN.

    -> { candidates: [{userId, lastSeen, daysInactive}], scanned, cursor, error? }
    """
    months = max(1, min(int(months or 3), 60))
    cutoff = int(time.time()) - months * 30 * DAY

    try:
        page = roblox_api.datastore_list_keys(STASH_DATASTORE, cursor=cursor,
                                              limit=max(1, min(max_keys, 100)))
    except Exception as exc:                                    # noqa: BLE001
        return {"candidates": [], "scanned": 0, "cursor": None, "error": str(exc)}

    candidates = []
    scanned = 0
    for key in page["keys"]:
        # Les cles de stash SONT l'userId (StashServer : SetAsync(tostring(userId), ...)).
        if not str(key).isdigit():
            continue
        scanned += 1
        uid = int(key)
        seen = _last_seen(uid)
        # Pas de profil / pas de lastSeen : on NE purge PAS (prudence -- on ne sait pas).
        if seen is None:
            continue
        if seen <= cutoff:
            candidates.append({
                "userId": uid,
                "lastSeen": seen,
                "daysInactive": (int(time.time()) - seen) // DAY,
            })

    return {"candidates": candidates, "scanned": scanned,
            "cursor": page["cursor"], "error": None, "months": months}


def purge_stashes(user_ids: list[int]) -> dict:
    """Supprime le stash des userIds fournis (liste EXPLICITE, issue d'un scan).
    -> { deleted, failed: [{userId, error}] }"""
    deleted = 0
    failed = []
    for raw in user_ids or []:
        if not str(raw).isdigit():
            continue
        uid = int(raw)
        try:
            roblox_api.datastore_delete(STASH_DATASTORE, str(uid))
            deleted += 1
        except Exception as exc:                                # noqa: BLE001
            failed.append({"userId": uid, "error": str(exc)})
    return {"ok": True, "deleted": deleted, "failed": failed}
