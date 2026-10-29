"""
Fiche joueur : lecture a la demande (lot 1 du plan, lecture seule).

Rien n'est lu tant que la fiche n'est pas ouverte. Le resume lit en parallele une
douzaine de sources ; l'inventaire et le stash ne sont lus qu'a l'ouverture de leur
onglet. Chaque section echoue seule : un droit Open Cloud manquant n'empeche pas
d'afficher le reste.

Formats lus (sources du jeu) :
  * profil      GlobalData_<v>            p_<userId>   (PlayerDataService : faction, money, lp...)
  * competences PlayerData_Skills&XP_<v>  p_<userId>   (XPService)
  * inventaire  PlayerData_Inventory_<v>  <userId>     { _v=2, equipped={slot=item}, pockets={item}, active }
  * stash       PlayerData_Stash_<v>      <userId>     { _v=2, tabs={ {name, items={item}} }, unlockedTabs }
  * item        ItemSerializer v2 : { u=uid, i=id, t=template?, x, y, r?, a={attributs},
                c={Config}, m={ {s=slot, i=id, ...} }, b={contenu de sac} }
Aucune ecriture ici : les modifications arrivent au lot 3 (protocole sans ecrasement).
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from . import config, live, roblox_api

CACHE_S = 60
_cache: dict = {}


class PlayerError(Exception):
    """Erreur destinee a l'utilisateur."""


def _cached(key: str, fn, force: bool = False):
    hit = _cache.get(key)
    if hit and not force and time.time() - hit[0] < CACHE_S:
        return hit[1]
    value = fn()
    _cache[key] = (time.time(), value)
    return value


def _section(fn):
    """Execute une lecture et rend {ok, data} ou {ok: False, error} sans jamais lever."""
    try:
        return {"ok": True, "data": fn()}
    except Exception as exc:                                    # noqa: BLE001
        return {"ok": False, "error": str(exc)[:300]}


# RECHERCHE
def resolve(query: str) -> dict:
    """Pseudo (nom d'utilisateur) ou userId -> {userId, name}."""
    q = str(query or "").strip().lstrip("@")
    if not q:
        raise PlayerError("Saisis un nom d'utilisateur ou un userId.")
    if q.isdigit():
        uid = int(q)
    else:
        found = roblox_api.resolve_user_ids([q]).get(q.lower())
        uid = int(found) if found else 0
        if not uid:
            raise PlayerError(f"« {q} » introuvable. Mets le NOM D'UTILISATEUR (@pseudo), "
                              "pas le nom affiché, ou colle l'userId.")
    name = roblox_api.resolve_usernames([uid]).get(str(uid), f"#{uid}")
    return {"userId": int(uid), "name": name}


# SOURCES
def _headshot(uid: int) -> str | None:
    url = ("https://thumbnails.roblox.com/v1/users/avatar-headshot?"
           + urllib.parse.urlencode({"userIds": uid, "size": "150x150", "format": "Png"}))
    req = urllib.request.Request(url, headers={"User-Agent": "CommandCenter"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    rows = data.get("data") or []
    return rows[0].get("imageUrl") if rows else None


def _ban(uid: int) -> dict | None:
    url = (f"{roblox_api.OPEN_CLOUD}/cloud/v2/universes/{config.ROBLOX_UNIVERSE_ID}"
           f"/user-restrictions/{uid}")
    rec = roblox_api._oc_request("GET", url) or {}
    return rec.get("gameJoinRestriction") or None


def _subscriptions(uid: int) -> list[dict]:
    out = []
    for offer in live.offers():
        sub_id = offer.get("subscriptionId")
        if offer.get("kind") != "subscription" or not sub_id:
            continue
        url = (f"{roblox_api.OPEN_CLOUD}/cloud/v2/universes/{config.ROBLOX_UNIVERSE_ID}"
               f"/subscription-products/{sub_id}/subscriptions/{uid}?view=FULL")
        try:
            rec = roblox_api._oc_request("GET", url)
            out.append({"id": offer.get("id"), "label": offer.get("label"),
                        "subscriptionId": sub_id, "record": rec, "error": None})
        except Exception as exc:                                # noqa: BLE001
            out.append({"id": offer.get("id"), "label": offer.get("label"),
                        "subscriptionId": sub_id, "record": None, "error": str(exc)[:200]})
    return out


PROFILE_FIELDS = ("faction", "money", "lp", "placementsPlayed", "specialization",
                  "factionLockedAt", "lastSeenAt", "hasFinishedTutorial", "defection")


def _profile(stores: dict, uid: int) -> dict | None:
    rec = roblox_api.datastore_get(stores["profile"], f"p_{uid}")
    if not isinstance(rec, dict):
        return None
    m = rec.get("market")
    market = m if isinstance(m, dict) else {}
    return {
        **{k: rec.get(k) for k in PROFILE_FIELDS if k in rec},
        "market": {k: len(v) for k, v in market.items() if isinstance(v, (list, dict))},
        "raw": rec,
    }


def summary(user_id: int, force: bool = False) -> dict:
    """En-tete de la fiche : tout sauf l'inventaire et le stash."""
    uid = int(user_id)

    def build():
        stores = live.store_names()
        jobs = {
            "identity": lambda: {
                "name": roblox_api.resolve_usernames([uid]).get(str(uid), f"#{uid}"),
                "headshot": _headshot(uid),
                "profileUrl": f"https://www.roblox.com/users/{uid}/profile",
            },
            "profile": lambda: _profile(stores, uid),
            "skills": lambda: roblox_api.datastore_get(stores["skills"], f"p_{uid}"),
            "sanctions": lambda: roblox_api.datastore_get(stores["sanctions"], str(uid)),
            "exfilClaim": lambda: roblox_api.datastore_get(stores["exfilClaim"], str(uid)),
            "debt": lambda: roblox_api.datastore_get(stores["blackMarketDebts"], f"d_{uid}"),
            "honeypot": lambda: roblox_api.datastore_get(stores["honeypot"], f"u_{uid}"),
            "ban": lambda: _ban(uid),
            "subscriptions": lambda: _subscriptions(uid),
            "presence": lambda: live.find_player(uid),
        }
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {k: pool.submit(_section, fn) for k, fn in jobs.items()}
            sections = {k: f.result() for k, f in futures.items()}
        return {"userId": uid, "stores": stores, "sections": sections, "at": int(time.time())}

    return _cached(f"summary:{uid}", build, force)


# DECODAGE ItemSerializer v2
def _scalar(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict) and value.get("_t"):
        return f"<{value['_t']}>"
    return json.dumps(value, ensure_ascii=False)[:80]


def decode_item(item) -> dict | None:
    if not isinstance(item, dict):
        return None
    a = item.get("a")
    attrs = a if isinstance(a, dict) else {}
    mods = [{"slot": m.get("s"), "id": m.get("i"), "template": m.get("t")}
            for m in (item.get("m") or []) if isinstance(m, dict)]
    contents = [d for d in (decode_item(b) for b in (item.get("b") or [])) if d]
    return {
        "uid": item.get("u"),
        "id": item.get("i"),
        "template": item.get("t"),
        "label": attrs.get("ItemName") or item.get("t") or item.get("i"),
        "x": item.get("x"), "y": item.get("y"), "rotated": bool(item.get("r")),
        "quantity": attrs.get("Quantity"),
        "attrs": {k: _scalar(v) for k, v in attrs.items()},
        "config": {k: _scalar(v) for k, v in (item.get("c") or {}).items()}
                  if isinstance(item.get("c"), dict) else {},
        "mods": mods,
        "contents": contents,
    }


def inventory(user_id: int, force: bool = False) -> dict:
    uid = int(user_id)

    def build():
        stores = live.store_names()
        rec = roblox_api.datastore_get(stores["inventory"], str(uid))
        if not isinstance(rec, dict):
            return {"userId": uid, "store": stores["inventory"], "empty": True}
        equipped = rec.get("equipped") if isinstance(rec.get("equipped"), dict) else {}
        return {
            "userId": uid, "store": stores["inventory"], "empty": False,
            "version": rec.get("_v"), "active": rec.get("active"),
            "equipped": {slot: decode_item(it) for slot, it in equipped.items()},
            "pockets": [d for d in (decode_item(it) for it in (rec.get("pockets") or [])) if d],
        }

    return _cached(f"inventory:{uid}", build, force)


def stash(user_id: int, force: bool = False) -> dict:
    uid = int(user_id)

    def build():
        stores = live.store_names()
        rec = roblox_api.datastore_get(stores["stash"], str(uid))
        if not isinstance(rec, dict):
            return {"userId": uid, "store": stores["stash"], "empty": True}
        tabs = []
        for i, tab in enumerate(rec.get("tabs") or [], start=1):
            if not isinstance(tab, dict):
                continue
            tabs.append({"index": i, "name": tab.get("name") or f"Onglet {i}",
                         "items": [d for d in (decode_item(it) for it in (tab.get("items") or [])) if d]})
        return {"userId": uid, "store": stores["stash"], "empty": False,
                "version": rec.get("_v"), "unlockedTabs": rec.get("unlockedTabs"),
                "permanentTabs": rec.get("permanentTabs"), "tabs": tabs}

    return _cached(f"stash:{uid}", build, force)
