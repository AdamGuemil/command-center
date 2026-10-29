"""
Le jeu en direct : contrats publies par les places et registre des serveurs.

Miroir de ServerStorage/Core/CommandCenterBridge.luau (lot 1 du plan).

  * CONTRAT : DataStore NON versionne `CC_Contract`, cle `place_<PlaceId>`. Chaque place
    y decrit ses magasins, sa version de donnees et ses offres. Le CC s'en sert pour viser
    les bons magasins et pour signaler un HUB et un GAME qui divergent.
  * REGISTRE : SortedMap MemoryStore `CC_Servers_V1`, une entree par serveur (cle = JobId),
    rafraichie toutes les 30 s et aux arrivees/departs, expiree apres 300 s (muette apres 75 s). Lu via Open Cloud : aucun endpoint
    public n'est necessaire, le CC tire l'etat quand il en a besoin.

Le veilleur lit le registre toutes les 20 s. Live et Fiches le relisent toutes les 5 s
quand ils sont visibles, avec un cache partage de 3 s.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.parse

from . import config, roblox_api

CONTRACT_STORE = "CC_Contract"
REGISTRY_MAP = "CC_Servers_V1"
KNOWN_CONTRACT_REV = 1
REGISTRY_CACHE_S = 3       # Live et Fiches se rafraichissent toutes les 5 s
CONTRACT_CACHE_S = 300
CONTRACT_RETRY_S = 10      # un contrat absent ou illisible doit etre relu rapidement
STALE_AFTER_S = 75         # deux battements et demi manques : serveur presume mort

_lock = threading.Lock()
_registry_cache: dict = {"at": 0.0, "data": None}
_contract_cache: dict = {"at": 0.0, "data": None}


# CONTRATS
def _place_ids() -> list[tuple[str, str]]:
    return [("hub", config.ROBLOX_PLACE_ID), ("match", config.ROBLOX_GAME_PLACE_ID)]


def contracts(force: bool = False) -> dict:
    """Contrat de chaque place + incoherences detectees. Ne leve pas."""
    with _lock:
        cached = _contract_cache["data"]
        ttl = CONTRACT_RETRY_S if cached and any(
            p["error"] or not p["contract"] for p in cached["places"]
        ) else CONTRACT_CACHE_S
        if cached and not force and time.time() - _contract_cache["at"] < ttl:
            return cached
    places, issues = [], []
    for kind, place_id in _place_ids():
        entry: dict = {"kind": kind, "placeId": place_id, "contract": None, "error": None}
        try:
            rec = roblox_api.datastore_get(CONTRACT_STORE, f"place_{place_id}")
            entry["contract"] = rec if isinstance(rec, dict) else None
        except Exception as exc:                               # noqa: BLE001
            entry["error"] = str(exc)
        places.append(entry)

    for p in places:
        c = p["contract"]
        label = "HUB" if p["kind"] == "hub" else "MATCH"
        if p["error"]:
            issues.append(f"{label} : contrat illisible ({p['error']}).")
        elif not c:
            issues.append(f"{label} : aucun contrat publié pour la place {p['placeId']}. "
                          "Si le serveur est déjà lancé, vérifie les erreurs "
                          "CommandCenterBridge dans sa console. Nouvelle lecture automatique sous 10 s.")
        elif int(c.get("contractRev") or 0) != KNOWN_CONTRACT_REV:
            issues.append(f"{label} : contrat v{c.get('contractRev')} inconnu de ce Command "
                          f"Center (attendu v{KNOWN_CONTRACT_REV}). Mets le CC a jour.")
    versions = {p["kind"]: (p["contract"] or {}).get("dsVersion") for p in places}
    if versions.get("hub") and versions.get("match") and versions["hub"] != versions["match"]:
        issues.append(f"HUB et MATCH visent des données différentes : HUB `{versions['hub']}`, "
                      f"MATCH `{versions['match']}`. Les joueurs n'auraient pas le même "
                      "profil selon la place.")
    for kind, version in versions.items():
        if version and version != config.DATASTORE_VERSION:
            issues.append(f"{'HUB' if kind == 'hub' else 'MATCH'} publie `{version}` mais le "
                          f"Command Center vise `{config.DATASTORE_VERSION}` : ses lectures et "
                          "écritures ne touchent pas les données de cette place.")
    result = {"places": places, "issues": issues, "ccVersion": config.DATASTORE_VERSION}
    with _lock:
        _contract_cache.update(at=time.time(), data=result)
    return result


def store_names() -> dict:
    """Noms des magasins joueurs : ceux du contrat du HUB s'il existe, sinon ceux du CC."""
    fallback = {
        "profile": config.datastore_name("GlobalData"),
        "skills": config.datastore_name("PlayerData_Skills&XP"),
        "inventory": config.datastore_name("PlayerData_Inventory"),
        "stash": config.datastore_name("PlayerData_Stash"),
        "sanctions": config.datastore_name("Sanctions"),
        "exfilClaim": config.datastore_name("ExfilClaim"),
        "blackMarketDebts": config.datastore_name("BlackMarketDebts"),
        "honeypot": config.datastore_name("Honeypot"),
    }
    try:
        hub = next((p["contract"] for p in contracts()["places"]
                    if p["kind"] == "hub" and p["contract"]), None)
    except Exception:                                           # noqa: BLE001
        hub = None
    stores = dict(fallback)
    if hub and int(hub.get("contractRev") or 0) == KNOWN_CONTRACT_REV:
        stores.update({k: v for k, v in (hub.get("stores") or {}).items() if v})
    return stores


def offers() -> list[dict]:
    """Abonnements et passes declares par le contrat du HUB (vide sans contrat)."""
    try:
        for p in contracts()["places"]:
            if p["kind"] == "hub" and p["contract"]:
                return list(p["contract"].get("offers") or [])
    except Exception:                                           # noqa: BLE001
        pass
    return []


# REGISTRE
def _list_registry() -> list[dict]:
    base = (f"{roblox_api.OPEN_CLOUD}/cloud/v2/universes/{config.ROBLOX_UNIVERSE_ID}"
            f"/memory-store/sorted-maps/{REGISTRY_MAP}/items")
    out, token = [], None
    for _ in range(20):                         # 20 pages de 100 serveurs : garde-fou
        params = {"maxPageSize": 100}
        if token:
            params["pageToken"] = token
        data = roblox_api._oc_request("GET", f"{base}?{urllib.parse.urlencode(params)}") or {}
        items = data.get("memoryStoreSortedMapItems") or data.get("items") or []
        for item in items:
            value = item.get("value")
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except ValueError:
                    value = None
            if isinstance(value, dict):
                value.setdefault("jobId", item.get("id") or str(item.get("path", "")).rsplit("/", 1)[-1])
                out.append(value)
        token = data.get("nextPageToken")
        if not token:
            break
    return out


def servers(force: bool = False) -> dict:
    """Etat live : serveurs, joueurs connectes et resume. -> { servers, summary, error }"""
    with _lock:
        cached = _registry_cache["data"]
        if cached and not force and time.time() - _registry_cache["at"] < REGISTRY_CACHE_S:
            return cached
    now = int(time.time())
    try:
        rows = _list_registry()
        error = None
    except Exception as exc:                                    # noqa: BLE001
        rows, error = [], str(exc)

    by_mode: dict[str, int] = {}
    players_by_mode: dict[str, int] = {}
    hubs = matches = players = hub_players = match_players = 0
    for s in rows:
        s["players"] = [p for p in (s.get("players") or []) if isinstance(p, dict)]
        s["stale"] = now - int(s.get("hb") or 0) > STALE_AFTER_S
        s["uptime"] = max(0, now - int(s.get("startedAt") or now))
        if s["stale"]:
            continue
        count = len(s["players"])
        players += count
        if s.get("kind") == "hub":
            hubs += 1
            hub_players += count
        else:
            matches += 1
            match_players += count
            mode = str(s.get("mode") or "?")
            by_mode[mode] = by_mode.get(mode, 0) + 1
            players_by_mode[mode] = players_by_mode.get(mode, 0) + count
    rows.sort(key=lambda s: (s.get("kind") != "hub", str(s.get("mode") or ""), -len(s["players"])))

    ids = sorted({p.get("u") for s in rows for p in s["players"] if p.get("u") and not p.get("n")})
    if ids:
        names = roblox_api.resolve_usernames(ids[:200])
        for s in rows:
            for p in s["players"]:
                p.setdefault("n", names.get(str(p.get("u"))))

    versions = sorted({int(s.get("placeVersion") or 0) for s in rows if not s["stale"]})
    result = {
        "servers": rows,
        "summary": {"players": players, "hubs": hubs, "matches": matches, "byMode": by_mode,
                    "hubPlayers": hub_players, "matchPlayers": match_players,
                    "playersByMode": players_by_mode, "placeVersions": versions},
        "error": error,
        "at": now,
    }
    with _lock:
        _registry_cache.update(at=time.time(), data=result)
    return result


def find_player(user_id: int) -> dict | None:
    """Serveur ou se trouve le joueur, d'apres le registre (cache 10 s)."""
    uid = int(user_id)
    for s in servers().get("servers", []):
        if s.get("stale"):
            continue
        for p in s["players"]:
            if int(p.get("u") or 0) == uid:
                return {"jobId": s.get("jobId"), "kind": s.get("kind"), "mode": s.get("mode"),
                        "map": s.get("map"), "phase": s.get("phase"), "team": p.get("t"),
                        "placeId": s.get("placeId")}
    return None
