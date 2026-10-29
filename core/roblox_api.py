"""
Pont Roblox Open Cloud — pilotage du jeu depuis le dashboard.

COMMENT CA MARCHE (et pourquoi c'est fiable) :
EventService.luau ecoute exactement DEUX canaux pour les boosts :
  1. DataStore SharedConfig.dsName("FactionWar"), cle "event_override"
     -> lu au demarrage serveur
  2. MessagingService topic "FW_Event"                -> pousse aux serveurs live
Open Cloud expose ces deux canaux en HTTP. En ecrivant dans le premier puis en
publiant sur le second, on reproduit a l'identique ce que fait la commande
/boost en jeu — meme donnee, meme effet, sans etre connecte.

Tout passe par EventConfig.sanitize() cote Luau a la lecture : meme si on
ecrivait une valeur aberrante, le jeu la clamperait. On clampe quand meme ici
pour echouer tot et clairement.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import config

OPEN_CLOUD = "https://apis.roblox.com"
GAMES_API = "https://games.roblox.com/v1"


class RobloxError(Exception):
    """Erreur Open Cloud, message deja lisible."""


def _oc_request(method: str, url: str, body: bytes | None = None,
                headers: dict | None = None):
    if not config.ROBLOX_OPENCLOUD_KEY:
        raise RobloxError("ROBLOX_OPENCLOUD_KEY absent (voir .env)")
    if not config.ROBLOX_UNIVERSE_ID:
        raise RobloxError("ROBLOX_UNIVERSE_ID absent (voir .env)")

    hdrs = {"x-api-key": config.ROBLOX_OPENCLOUD_KEY,
            "Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)

    req = urllib.request.Request(url, data=body, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        if exc.code == 401:
            raise RobloxError("Cle Open Cloud invalide (401).") from exc
        if exc.code == 403:
            raise RobloxError(
                "Cle Open Cloud refusee (403) : scope manquant sur CET univers, ou "
                "adresse IP non autorisee par la cle. Onglet Sante > « Tester les "
                "permissions » indique precisement lequel."
            ) from exc
        if exc.code == 404:
            return None          # cle absente du DataStore = cas normal
        if exc.code == 429:
            raise RobloxError("Rate limit Open Cloud (429).") from exc
        raise RobloxError(f"HTTP {exc.code} : {detail}") from exc
    except urllib.error.URLError as exc:
        raise RobloxError(f"Reseau indisponible : {exc.reason}") from exc


# DATASTORE
def _entry_url(datastore: str, key: str) -> str:
    q = urllib.parse.urlencode({"datastoreName": datastore, "entryKey": key})
    return (f"{OPEN_CLOUD}/datastores/v1/universes/"
            f"{config.ROBLOX_UNIVERSE_ID}/standard-datastores/datastore/entries/entry?{q}")


def datastore_get(datastore: str, key: str):
    return _oc_request("GET", _entry_url(datastore, key))


def datastore_set(datastore: str, key: str, value) -> None:
    body = json.dumps(value).encode("utf-8")
    # L'API DataStore exige content-md5 (base64 du MD5 binaire du corps).
    md5 = base64.b64encode(hashlib.md5(body).digest()).decode("ascii")
    _oc_request("POST", _entry_url(datastore, key), body, {"content-md5": md5})


def datastore_delete(datastore: str, key: str) -> None:
    _oc_request("DELETE", _entry_url(datastore, key))


def datastore_list_keys(datastore: str, cursor: str | None = None,
                        limit: int = 100, prefix: str | None = None) -> dict:
    """Liste UNE page de cles d'un DataStore standard. -> { keys: [str], cursor: str|None }.
    Utilise pour la maintenance (purge des stash inactifs). Suivre `cursor` pour paginer."""
    params = {"datastoreName": datastore, "limit": max(1, min(limit, 100))}
    if cursor:
        params["cursor"] = cursor
    if prefix:
        params["prefix"] = prefix
    url = (f"{OPEN_CLOUD}/datastores/v1/universes/{config.ROBLOX_UNIVERSE_ID}"
           f"/standard-datastores/datastore/entries?{urllib.parse.urlencode(params)}")
    data = _oc_request("GET", url) or {}
    keys = [k.get("key") for k in (data.get("keys") or []) if k.get("key")]
    return {"keys": keys, "cursor": data.get("nextPageCursor") or None}


# MESSAGING
def publish_url() -> str:
    # Endpoint Cloud v2. L'ancien `messaging-service/v1/.../topics/{topic}` est classe
    # « Not Recommended » par Roblox ; meme scope de cle (Messaging Service : publish).
    return f"{OPEN_CLOUD}/cloud/v2/universes/{config.ROBLOX_UNIVERSE_ID}:publishMessage"


def publish_body(topic: str, message: dict) -> bytes:
    """MessagingService transporte une CHAINE (1 Ko max). EventService fait un
    JSONDecode cote Luau, donc on serialise le dict avant de l'envoyer."""
    return json.dumps({"topic": topic, "message": json.dumps(message)}).encode("utf-8")


def publish(topic: str, message: dict) -> None:
    _oc_request("POST", publish_url(), publish_body(topic, message))


# BOOSTS
def _clamp(value, low, high, default):
    try:
        return max(low, min(high, float(value)))
    except (TypeError, ValueError):
        return default


def get_boost() -> dict | None:
    """Boost live actuel, ou None. Un boost expire est signale comme tel
    plutot que masque : savoir qu'il vient de finir est une information."""
    rec = datastore_get(config.FW_DATASTORE, config.FW_OVERRIDE_KEY)
    if not isinstance(rec, dict):
        return None
    rec["expired"] = int(rec.get("endsAt", 0)) <= int(time.time())
    rec["remaining"] = max(0, int(rec.get("endsAt", 0)) - int(time.time()))
    return rec


def set_boost(xp: float, gold: float, war: float, minutes: int,
              name: str = "BOOST", desc: str = "") -> dict:
    """Reproduit EventService.SetOverride(). Meme record, memes bornes."""
    xp = _clamp(xp, 1, config.EVENT_MAX_MULT, 1.0)
    gold = _clamp(gold, 1, config.EVENT_MAX_MULT, 1.0)
    war = _clamp(war, 1, config.EVENT_MAX_MULT, 1.0)
    minutes = int(_clamp(minutes, 1, config.EVENT_MAX_MINUTES, 60))

    # Meme garde que EventConfig.isNeutral : un boost tout a 1 ne fait rien et
    # masquerait un event planifie. On refuse tot, avec la bonne consigne.
    if xp == 1 and gold == 1 and war == 1:
        raise RobloxError(
            "Tous les multiplicateurs valent 1 : ce boost n'aurait aucun effet. "
            "Utilise 'Couper le boost' pour desactiver."
        )

    now = int(time.time())
    record = {
        "id": "admin",
        "name": (name or "BOOST").upper(),
        "desc": desc or "Active depuis le Command Center",
        "startsAt": now,
        "endsAt": now + minutes * 60,
        "xpMult": xp,
        "goldMult": gold,
        "factionPointMult": war,
        "setAt": now,
    }
    datastore_set(config.FW_DATASTORE, config.FW_OVERRIDE_KEY, record)
    # Les serveurs deja demarres ne relisent le DataStore que toutes les 300 s :
    # sans ce publish, le boost mettrait jusqu'a 5 min a apparaitre.
    publish(config.FW_TOPIC, {"kind": "event"})
    return record


def clear_boost() -> None:
    datastore_delete(config.FW_DATASTORE, config.FW_OVERRIDE_KEY)
    publish(config.FW_TOPIC, {"kind": "event"})


# ----------------------------------------------------------- FACTION WAR ---
# Miroir exact de FactionWarConfig.luau / FactionWarService.luau.
# Les bornes sont calculees en heure civile Europe/Paris afin que chaque saison
# commence et finisse le samedi a 18h00, aussi bien en CEST qu'en CET.
FW_TIMEZONE = ZoneInfo("Europe/Paris")
FW_EPOCH_LOCAL = datetime(2026, 9, 5, 18, 0, tzinfo=FW_TIMEZONE)
FW_EPOCH = int(FW_EPOCH_LOCAL.timestamp())
FW_WEEK_SECONDS = 604800       # meme calendrier en production et en Studio
FW_SHARD_COUNT = 4


def fw_week_index(now: int | None = None) -> int:
    timestamp = int(time.time() if now is None else now)
    local_now = datetime.fromtimestamp(timestamp, FW_TIMEZONE).replace(tzinfo=None)
    local_epoch = FW_EPOCH_LOCAL.replace(tzinfo=None)
    return int((local_now - local_epoch).total_seconds()) // FW_WEEK_SECONDS


def fw_week_bounds(week: int) -> tuple[int, int]:
    starts = FW_EPOCH_LOCAL + timedelta(weeks=week)
    ends = FW_EPOCH_LOCAL + timedelta(weeks=week + 1)
    return int(starts.timestamp()), int(ends.timestamp())


def faction_war_state(week: int | None = None) -> dict:
    """Totaux par faction pour la semaine. Les scores sont ecrits en 4 shards
    par faction (pour eviter la contention d'ecriture entre serveurs) : on
    additionne les 8 cles, exactement comme readShardTotals() cote Luau."""
    week = fw_week_index() if week is None else week
    starts, ends = fw_week_bounds(week)
    totals: dict[str, int] = {}
    for faction in ("Rainor", "Rusfor"):
        total = 0
        for shard in range(FW_SHARD_COUNT):
            val = datastore_get(config.FW_DATASTORE, f"s_{week}_{faction}_{shard}")
            try:
                total += int(val or 0)
            except (TypeError, ValueError):
                pass
        totals[faction] = total

    lead = max(totals, key=lambda f: totals[f])
    spread = abs(totals["Rainor"] - totals["Rusfor"])
    return {
        "week": week,
        # Numero AFFICHE : l'index technique commence a 0, le libelle joueur a 1.
        "season": week + 1,
        "startsAt": starts,
        "endsAt": ends,
        "remaining": max(0, ends - int(time.time())),
        "totals": totals,
        "leader": lead if spread else None,
        "spread": spread,
    }


def faction_war_archive(week: int | None = None) -> dict | None:
    """Archive d'une semaine CLOSE : scores finaux + vainqueur.

    INDISPENSABLE pour annoncer un resultat : apres la bascule, les totaux de
    la semaine COURANTE sont repartis a zero. Publier "les scores" sans lire
    l'archive annoncerait 0-0.
    """
    if week is None:
        week = fw_week_index() - 1        # la derniere semaine close
    rec = datastore_get(config.FW_DATASTORE, f"archive_{week}")
    if not isinstance(rec, dict):
        return None
    rec.setdefault("week", week)
    rec["season"] = week + 1
    return rec


def faction_war_top(faction: str, week: int | None = None, limit: int = 10) -> dict:
    """Top contributeurs d'une faction. -> { rows, error }"""
    week = fw_week_index() if week is None else week
    rows, err = _ordered_top(config.datastore_name(f"FWLB_w{week}_{faction}"), limit)
    # L'id de l'entree est l'userId ; le nom se resout par l'appelant.
    for r in rows:
        r["points"] = r.pop("value")
    return {"rows": rows, "error": err}


# ------------------------------------------------------- RANKED (LADDER) ---
# Miroir de RankedLadderService.luau : store unique, permanent, sans saison.
RANKED_STORE = config.datastore_name("RankedLB")
RANKED_META_STORE = config.datastore_name("RankedMeta")
RANKED_META_SHARDS = 8


def _ordered_top(store: str, limit: int) -> tuple[list[dict], str | None]:
    """Lit un OrderedDataStore via l'API dediee (scope Open Cloud SEPARE de
    celui des DataStores standard).

    Renvoie (lignes, erreur). On ne confond PAS "classement vide" et "appel en
    echec" : sans cette distinction, une permission manquante s'affichait comme
    un classement vide, indefiniment et sans explication.
    """
    url = (f"{OPEN_CLOUD}/ordered-data-stores/v1/universes/"
           f"{config.ROBLOX_UNIVERSE_ID}/orderedDataStores/{store}/scopes/global/entries"
           f"?max_page_size={limit}&order_by=desc")
    try:
        data = _oc_request("GET", url) or {}
    except RobloxError as exc:
        return [], str(exc)
    rows = [{"rank": i, "userId": e.get("id"), "value": int(e.get("value") or 0)}
            for i, e in enumerate(data.get("entries") or [], start=1)]
    return rows, None


def ordered_all_ids(store: str, max_total: int = 5000) -> tuple[list[int], str | None]:
    """Parcourt TOUTES les pages d'un OrderedDataStore et renvoie la liste des userIds
    (les ids d'entree). Utilise pour resoudre l'audience "active" (union des joueurs
    presents aux classements de guerre de la semaine). `_ordered_top` ne lit qu'UNE
    page : ici on suit nextPageToken jusqu'au bout (borne par max_total, garde-fou).
    Renvoie (ids, erreur)."""
    ids: list[int] = []
    token = None
    base = (f"{OPEN_CLOUD}/ordered-data-stores/v1/universes/"
            f"{config.ROBLOX_UNIVERSE_ID}/orderedDataStores/{store}/scopes/global/entries")
    for _ in range(200):                       # plafond de pages (garde-fou anti-boucle)
        params = {"max_page_size": 100, "order_by": "desc"}
        if token:
            params["page_token"] = token
        try:
            data = _oc_request("GET", f"{base}?{urllib.parse.urlencode(params)}") or {}
        except RobloxError as exc:
            return ids, str(exc)
        for e in data.get("entries") or []:
            uid = e.get("id")
            if uid and str(uid).isdigit():
                ids.append(int(uid))
                if len(ids) >= max_total:
                    return ids, None
        token = data.get("nextPageToken")
        if not token:
            break
    return ids, None


def ranked_top(limit: int = 20) -> dict:
    """Top LP global des DUALS. -> { rows, error }"""
    rows, err = _ordered_top(RANKED_STORE, max(1, min(int(limit or 20), 100)))
    names = resolve_usernames([r["userId"] for r in rows])
    meta: dict[str, str] = {}
    shards = {int(r["userId"]) % RANKED_META_SHARDS for r in rows
              if str(r.get("userId", "")).isdigit()}
    for shard in shards:
        try:
            stored = datastore_get(RANKED_META_STORE, f"s_{shard}")
            if isinstance(stored, dict):
                meta.update({str(uid): faction for uid, faction in stored.items()
                             if faction in ("Rainor", "Rusfor")})
        except Exception:                                       # noqa: BLE001
            # La faction est informative : son index ne doit jamais masquer le LP.
            pass
    for r in rows:
        r["name"] = names.get(str(r["userId"]), f"#{r['userId']}")
        r["faction"] = meta.get(str(r["userId"]))
        r["lp"] = r.pop("value")
    return {"rows": rows, "error": err}


def resolve_user_ids(usernames: list[str]) -> dict:
    """pseudo (minuscules) -> userId, via l'API publique (pas de cle requise).
    Utilise pour l'audience "users" du give (on saisit des pseudos, pas des ids)."""
    names = [str(n).strip().lstrip("@") for n in usernames if str(n).strip()]
    if not names:
        return {}
    try:
        body = json.dumps({"usernames": names, "excludeBannedUsers": False}).encode()
        req = urllib.request.Request(
            "https://users.roblox.com/v1/usernames/users", data=body, method="POST",
            headers={"Content-Type": "application/json", "User-Agent": "CommandCenter"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        # requestedUsername conserve la casse saisie ; on indexe en minuscules.
        return {str(u.get("requestedUsername") or u.get("name")).lower(): u["id"]
                for u in data.get("data", [])}
    except Exception:                                          # noqa: BLE001
        return {}


def resolve_usernames(user_ids: list[int]) -> dict:
    """userId -> nom d'affichage, via l'API publique (pas de cle requise)."""
    ids = [int(u) for u in user_ids if str(u).isdigit()]
    if not ids:
        return {}
    try:
        body = json.dumps({"userIds": ids, "excludeBannedUsers": False}).encode()
        req = urllib.request.Request(
            "https://users.roblox.com/v1/users", data=body, method="POST",
            headers={"Content-Type": "application/json", "User-Agent": "CommandCenter"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return {str(u["id"]): u.get("displayName") or u.get("name")
                for u in data.get("data", [])}
    except Exception:                                          # noqa: BLE001
        return {}


# SECURITE : PIEGES ANTI-TRICHE
# Miroir de HoneypotService.luau (claude_works/guides/GUIDE_PIEGES.md). Lecture seule et a
# la demande : la liste n'est lue qu'a l'ouverture de l'espace Securite, le detail d'un
# joueur qu'au clic sur sa ligne.
HONEYPOT_STORE = config.datastore_name("Honeypot")
HONEYPOT_INDEX = config.datastore_name("HoneypotIndex")


def honeypot_list(limit: int = 50) -> dict:
    """Joueurs pieges, du dernier appel au plus ancien. -> { rows, error }"""
    rows, err = _ordered_top(HONEYPOT_INDEX, max(1, min(int(limit or 50), 100)))
    names = resolve_usernames([r["userId"] for r in rows])
    for r in rows:
        r["lastAt"] = r.pop("value")
        r["name"] = names.get(str(r["userId"]), f"#{r['userId']}")
    return {"rows": rows, "error": err}


def honeypot_detail(user_id: int) -> dict:
    """Enregistrement complet d'un joueur (compteurs, pieges, echantillons)."""
    uid = int(user_id)
    rec = datastore_get(HONEYPOT_STORE, f"u_{uid}")
    name = resolve_usernames([uid]).get(str(uid), f"#{uid}")
    return {"userId": uid, "name": name, "record": rec if isinstance(rec, dict) else None}


# PERMISSIONS DE LA CLE
# Une sonde par scope : un 403 generique ne dit pas QUEL droit manque, et la page de
# creation de cle les presente systeme par systeme. Chaque sonde est inoffensive :
# lectures, ecriture puis suppression d'une cle `cc_probe` dediee, publication sur un
# topic sans abonne, lecture d'une Queue dediee. Deux droits ne sont PAS sondes parce
# que leur seul test serait l'action elle-meme : envoyer une notification a un joueur
# et redemarrer tous les serveurs.
PROBE_KEY = "cc_probe"
PROBE_TOPIC = "CC_Probe"
PROBE_QUEUE = "CC_Probe"
PROBE_SORTED_MAP = "MM_ActiveMatches_V1"   # index des matchs vivants (TeleportManager)
PROBE_SORTED_MAP_WRITE = "CC_Probe"         # item ecrit avec un TTL de 30 s, jamais lu par le jeu


def _subscription_probe(universe_id: str) -> dict:
    """Lit l'abonnement de l'userId 1 a la premiere offre du contrat : 404 = droit accorde."""
    from . import live  # import tardif : live depend deja de ce module
    sub = next((o.get("subscriptionId") for o in live.offers()
                if o.get("kind") == "subscription" and o.get("subscriptionId")), None)
    row = {"id": "subscriptions", "system": "Subscriptions", "operation": "Read",
           "use": "abonnement d'un joueur dans sa fiche"}
    if not sub:
        return {**row, "call": None,
                "skip": "aucune offre d'abonnement connue (contrat du HUB pas encore publié)"}
    return {**row, "ok": (200, 404),
            "call": ("GET", f"{OPEN_CLOUD}/cloud/v2/universes/{universe_id}/subscription-products/"
                            f"{sub}/subscriptions/1", None, None)}


def _probe_call(method: str, url: str, body: bytes | None = None,
                headers: dict | None = None) -> tuple[int, str]:
    """Appel brut : rend (code HTTP, debut du corps). 0 = reseau injoignable."""
    hdrs = {"x-api-key": config.ROBLOX_OPENCLOUD_KEY, "Content-Type": "application/json"}
    hdrs.update(headers or {})
    req = urllib.request.Request(url, data=body, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, ""
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")[:200]
    except urllib.error.URLError as exc:
        return 0, str(exc.reason)[:200]


def _probe_plan() -> list[dict]:
    """Les sondes, dans l'ordre de la page de creation de cle.
    `ok` = codes qui prouvent que le droit est accorde (404 = droit OK, cible absente)."""
    u = config.ROBLOX_UNIVERSE_ID
    entry = _entry_url(config.FW_DATASTORE, PROBE_KEY)
    probe_body = json.dumps({"at": int(time.time())}).encode("utf-8")
    md5 = base64.b64encode(hashlib.md5(probe_body).digest()).decode("ascii")
    keys_url = (f"{OPEN_CLOUD}/datastores/v1/universes/{u}/standard-datastores/datastore/"
                f"entries?{urllib.parse.urlencode({'datastoreName': config.FW_DATASTORE, 'limit': 1})}")
    ordered = (f"{OPEN_CLOUD}/ordered-data-stores/v1/universes/{u}/orderedDataStores/"
               f"{config.datastore_name('RankedLB')}/scopes/global/entries?max_page_size=1")
    mem = f"{OPEN_CLOUD}/cloud/v2/universes/{u}/memory-store"
    return [
        {"id": "ds_read", "system": "Data Stores", "operation": "Read Entry",
         "use": "boosts, scores Faction War, barèmes", "call": ("GET", entry, None, None),
         "ok": (200, 404)},
        {"id": "ds_list", "system": "Data Stores", "operation": "List Entry Keys",
         "use": "maintenance des stash", "call": ("GET", keys_url, None, None), "ok": (200,)},
        {"id": "ds_write", "system": "Data Stores", "operation": "Create Entry + Update Entry",
         "use": "boosts, modes, give, barèmes",
         "call": ("POST", entry, probe_body, {"content-md5": md5}), "ok": (200,)},
        {"id": "ds_delete", "system": "Data Stores", "operation": "Delete Entry",
         "use": "couper un boost, purge stash", "call": ("DELETE", entry, None, None),
         "ok": (200, 204, 404)},
        {"id": "ordered_read", "system": "Ordered Data Stores", "operation": "Read",
         "use": "classements Faction War et ranked", "call": ("GET", ordered, None, None),
         "ok": (200, 404)},
        {"id": "messaging", "system": "Messaging Service", "operation": "Publish",
         "use": "pousser boosts, modes et give aux serveurs ouverts",
         "call": ("POST", publish_url(), publish_body(PROBE_TOPIC, {"kind": "probe"}), None),
         "ok": (200,)},
        {"id": "memory_sorted_read", "system": "Memory Store", "operation": "Sorted Map : Read",
         "use": "lot 1 : serveurs et matchs en direct",
         "call": ("GET", f"{mem}/sorted-maps/{PROBE_SORTED_MAP}/items?maxPageSize=1", None, None),
         "ok": (200, 404)},
        {"id": "memory_sorted_write", "system": "Memory Store", "operation": "Sorted Map : Write",
         "use": "lot 3 : verrou d'édition d'un joueur hors ligne",
         "call": ("POST", f"{mem}/sorted-maps/{PROBE_SORTED_MAP_WRITE}/items?id=probe",
                  json.dumps({"value": 1, "ttl": "30s"}).encode("utf-8"), None),
         "ok": (200, 409)},
        {"id": "memory_queue_read", "system": "Memory Store", "operation": "Queue : Read (+ Discard)",
         "use": "lot 2 : événements du jeu",
         "call": ("GET", f"{mem}/queues/{PROBE_QUEUE}/items:read?count=1", None, None),
         "ok": (200, 404)},
        {"id": "bans_read", "system": "User Restrictions", "operation": "Read (+ Write)",
         "use": "lot 3 : bans depuis le CC",
         "call": ("GET", f"{OPEN_CLOUD}/cloud/v2/universes/{u}/user-restrictions?maxPageSize=1",
                  None, None),
         "ok": (200,)},
        _subscription_probe(u),
        {"id": "analytics", "system": "Analytics", "operation": "Read",
         "use": "Tendances : crashs serveur avec leur cause, FPS, mémoire, joueurs",
         "call": ("POST", f"https://apis.roblox.com/analytics-query-api/v1/universes/{u}/metrics",
                  json.dumps({"metric": "DailyActiveUsers", "granularity": "OneDay",
                              "startTime": time.strftime("%Y-%m-%dT00:00:00Z", time.gmtime(time.time() - 3 * 86400)),
                              "endTime": time.strftime("%Y-%m-%dT00:00:00Z", time.gmtime())}).encode("utf-8"),
                  None),
         "ok": (200, 202)},
        {"id": "notifications", "system": "User Notifications", "operation": "Write",
         "use": "notifications joueurs (Diffusion > Notifications)", "call": None,
         "skip": "non testable sans envoyer une notification : utilise « Tester sur mon compte »"},
        {"id": "restart", "system": "Universes", "operation": "Write (restart servers)",
         "use": "lot 3 : redémarrage après mise à jour", "call": None,
         "skip": "non testable sans redémarrer tous les serveurs"},
    ]


def _probe_hint(status: int, system: str, operation: str) -> str:
    if status == 401:
        return "Clé invalide, expirée ou révoquée : régénère-la et remplace ROBLOX_OPENCLOUD_KEY."
    if status == 403:
        return (f"Ajoute « {system} → {operation} » sur l'expérience Shroud War dans la clé. "
                "Si toutes les sondes sont en 403 : l'IP de ce PC n'est pas autorisée "
                "(champ Accepted IP Addresses) ou la clé n'appartient pas au groupe.")
    if status == 429:
        return "Limite de débit atteinte : réessaie dans une minute."
    if status == 0:
        return "Réseau injoignable."
    return "Réponse inattendue : voir le détail."


def probe_permissions() -> dict:
    """Teste chaque droit de la cle. Ne leve jamais : rend une ligne par droit."""
    if not config.ROBLOX_OPENCLOUD_KEY or not config.ROBLOX_UNIVERSE_ID:
        return {"ok": False, "error": "ROBLOX_OPENCLOUD_KEY ou ROBLOX_UNIVERSE_ID absent (voir .env).",
                "rows": []}
    rows = []
    for p in _probe_plan():
        row = {k: p[k] for k in ("id", "system", "operation", "use")}
        if p.get("call") is None:
            row.update(state="skip", detail=p["skip"])
        else:
            method, url, body, headers = p["call"]
            status, detail = _probe_call(method, url, body, headers)
            granted = status in p["ok"]
            row.update(state="ok" if granted else "bad", status=status,
                       detail="" if granted else detail,
                       hint="" if granted else _probe_hint(status, p["system"], p["operation"]))
        rows.append(row)
    return {"ok": all(r["state"] != "bad" for r in rows), "universeId": config.ROBLOX_UNIVERSE_ID,
            "rows": rows}


# SANTE DU JEU
def game_health() -> dict:
    """Etat public de l'experience. N'exige PAS de cle Open Cloud : utile meme
    avant d'avoir tout branche."""
    if not config.ROBLOX_UNIVERSE_ID:
        return {"ok": False, "reason": "ROBLOX_UNIVERSE_ID absent"}
    try:
        url = f"{GAMES_API}/games?universeIds={config.ROBLOX_UNIVERSE_ID}"
        req = urllib.request.Request(url, headers={"User-Agent": "CommandCenter"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        items = data.get("data") or []
        if not items:
            return {"ok": False, "reason": "Universe introuvable"}
        g = items[0]
        return {
            "ok": True,
            "name": g.get("name"),
            "playing": g.get("playing", 0),
            "visits": g.get("visits", 0),
            "favorites": g.get("favoritedCount", 0),
            "maxPlayers": g.get("maxPlayers", 0),
            "playable": g.get("isGenreEnforced") is not None,
        }
    except Exception as exc:                                  # noqa: BLE001
        return {"ok": False, "reason": str(exc)[:200]}
