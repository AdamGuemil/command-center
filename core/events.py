"""
Lecteur du bus d'evenements du jeu : Queue MemoryStore `CC_Events_V1`.

Le jeu y depose des evenements courts (ServerStorage/Core/CCEvents.luau). A chaque passage
du veilleur (toutes les 20 s), le CC :
  1. lit jusqu'a 100 evenements (items:read) ; Roblox les rend invisibles 60 s,
  2. les enregistre dans data/cc.db (dedoublonnes par id),
  3. les retire de la Queue (items:discard). Si le CC plante entre 2 et 3, les evenements
     reapparaissent apres 60 s et sont ignores comme doublons : rien n'est perdu ni double.
  4. quand la Queue est videe, supprime le carnet `CC_EventsBacklog` : le jeu peut de
     nouveau deposer (il s'arrete de lui-meme au-dela d'une quarantaine d'evenements non lus).

Droits de cle : Memory Store, Queue Read (dequeue) et Discard ; Sorted Map Write (carnet).
"""

from __future__ import annotations

import json
import threading
import time
import urllib.parse

from . import config, db, roblox_api

QUEUE = "CC_Events_V1"
BACKLOG_MAP = "CC_EventsBacklog"
BACKLOG_KEY = "count"
READ_COUNT = 100
INVISIBILITY = "60s"

# Types connus. Un type inconnu est garde (journal) mais ne fait pas de carte.
TYPES = {
    "season_closed": "Saison close",
    "ranked_payout": "Versement ranked",
    "sanction": "Sanction",
    "ac_flag": "Anticheat",
    "honeypot": "Piège anti-triche",
    "feedback": "Avis joueur",
    "cmd_ack": "Commande exécutée",
    "error_spike": "Erreurs de script",   # deduit du battement par le veilleur, pas de la Queue
}

_lock = threading.Lock()
_state: dict = {"lastRead": 0, "lastError": None, "received": 0}


def _base() -> str:
    return f"{roblox_api.OPEN_CLOUD}/cloud/v2/universes/{config.ROBLOX_UNIVERSE_ID}/memory-store"


def parse_item(item: dict) -> dict | None:
    """Element de Queue Open Cloud -> evenement normalise, ou None si illisible."""
    raw = item.get("data")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return None
    if not isinstance(raw, dict) or not raw.get("t"):
        return None
    t = str(raw["t"])
    return {
        "id": str(raw.get("id") or item.get("id") or f"{t}:{raw.get('at')}:{raw.get('job')}"),
        "type": t,
        "at": int(raw.get("at") or time.time()),
        "job": raw.get("job"),
        "place": raw.get("pl"),
        "data": raw.get("d") if isinstance(raw.get("d"), dict) else {},
    }


def poll() -> list[dict]:
    """Une lecture de la Queue. Renvoie les evenements NOUVEAUX. Ne leve pas."""
    if not (config.ROBLOX_OPENCLOUD_KEY and config.ROBLOX_UNIVERSE_ID):
        return []
    with _lock:
        try:
            q = urllib.parse.quote(QUEUE, safe="")
            url = f"{_base()}/queues/{q}/items:read?count={READ_COUNT}&invisibilityWindow={INVISIBILITY}"
            try:
                res = roblox_api._oc_request("GET", url) or {}
            except roblox_api.RobloxError as exc:
                if "404" in str(exc):          # Queue jamais creee : rien a lire
                    res = {}
                else:
                    raise
            # Roblox renvoie queueItems/id ; le schema OpenAPI utilise items/readId.
            # Accepter les deux, sans acquitter une reponse dont on ignore le format.
            items = res.get("queueItems", res.get("items"))
            if items is None:
                if res:
                    raise roblox_api.RobloxError("Format de la file d'accusés inconnu.")
                items = []
            if not isinstance(items, list):
                raise roblox_api.RobloxError("Liste d'événements illisible.")
            read_id = res.get("id") or res.get("readId")
            parsed = [e for e in (parse_item(i) for i in items) if e]
            fresh = db.add_events(parsed) if parsed else []
            if read_id:
                roblox_api._oc_request("POST", f"{_base()}/queues/{q}/items:discard",
                                       json.dumps({"readId": read_id}).encode("utf-8"),
                                       {"Content-Type": "application/json"})
            if len(items) < READ_COUNT:
                _reset_backlog()
            _state.update(lastRead=int(time.time()), lastError=None,
                          received=_state["received"] + len(fresh))
            return fresh
        except Exception as exc:                                # noqa: BLE001
            _state.update(lastRead=int(time.time()), lastError=str(exc))
            return []


def _reset_backlog() -> None:
    m = urllib.parse.quote(BACKLOG_MAP, safe="")
    try:
        roblox_api._oc_request("DELETE", f"{_base()}/sorted-maps/{m}/items/{BACKLOG_KEY}")
    except roblox_api.RobloxError:
        pass   # deja absent (404) ou droit manquant : le jeu repartira a l'expiration


def status() -> dict:
    return dict(_state)
