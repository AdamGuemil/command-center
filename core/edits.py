"""
Modifications d'un joueur depuis le Command Center, sans jamais etre ecrasees (lot 3).

LE PROBLEME. Le serveur qui heberge un joueur garde son inventaire, son stash et son
profil en memoire et les reecrit a sa prochaine sauvegarde. Une ecriture directe du CC
pendant que le joueur joue serait effacee en silence.

LA REGLE. Le CC n'ecrit jamais une donnee qu'un serveur tient en memoire :
  * joueur EN LIGNE (present dans le registre CC_Servers_V1) : la modification part en
    commande `cc_cmd` vers son serveur (core/commands.py), qui l'applique et sauvegarde ;
  * joueur HORS LIGNE : protocole a verrou, ici.
      1. verrou `edit:<userId>` dans la SortedMap MemoryStore `CC_EditLocks` (60 s). Un
         serveur ou le joueur arrive attend sa levee avant de charger (CCEditLock.luau) ;
      2. le joueur doit etre absent du registre, avant ET 5 s apres la pose du verrou
         (un serveur qui l'aurait charge juste avant le verrou se serait annonce) ;
      3. relecture de l'entree et de son etag : il doit etre celui de l'apercu, sinon le
         jeu a ecrit entre-temps et on refait l'apercu ;
      4. ecriture conditionnee par l'etag (Open Cloud DataStore v2, PATCH) ;
      5. copie de l'entree d'origine dans data/cc.db (annulation possible), journal d'audit,
         levee du verrou.

Chaque modification passe d'abord par un APERCU (avant -> apres) ; rien n'est ecrit sans
confirmation. L'annulation suit le meme protocole et exige que l'entree n'ait pas change
depuis la modification.
"""

from __future__ import annotations

import copy
import json
import threading
import time
import urllib.parse
import uuid
from typing import Any

from . import config, db, live, roblox_api

LOCK_MAP = "CC_EditLocks"
LOCK_TTL = "60s"
SETTLE_S = 5
PLAN_TTL_S = 300
MONEY_MAX = 100_000_000

_plans: dict[str, dict] = {}
_lock = threading.Lock()


class EditError(Exception):
    """Refus lisible (joueur en ligne, verrou pris, donnee modifiee entre-temps...)."""


# OPEN CLOUD : entrees v2 avec etag, et verrou MemoryStore -------------------------
def _entry_url(store: str, key: str) -> str:
    return (f"{roblox_api.OPEN_CLOUD}/cloud/v2/universes/{config.ROBLOX_UNIVERSE_ID}/data-stores/"
            f"{urllib.parse.quote(store, safe='')}/entries/{urllib.parse.quote(key, safe='')}")


def read_entry(store: str, key: str) -> dict:
    res = roblox_api._oc_request("GET", _entry_url(store, key))
    if not isinstance(res, dict):
        raise EditError(f"Entree {store}/{key} introuvable : rien a modifier.")
    return res


def write_entry(store: str, key: str, entry: dict, value) -> dict:
    body = {"value": value, "etag": entry.get("etag")}
    for field in ("users", "attributes"):
        if entry.get(field) is not None:
            body[field] = entry[field]
    try:
        res = roblox_api._oc_request("PATCH", _entry_url(store, key), json.dumps(body).encode("utf-8"))
    except roblox_api.RobloxError as exc:
        if any(code in str(exc) for code in ("409", "412", "ABORTED", "FAILED_PRECONDITION")):
            raise EditError("Le jeu a modifié cette donnée entre-temps : refais l'aperçu.") from exc
        raise
    return res or {}


def _lock_base() -> str:
    return (f"{roblox_api.OPEN_CLOUD}/cloud/v2/universes/{config.ROBLOX_UNIVERSE_ID}"
            f"/memory-store/sorted-maps/{LOCK_MAP}/items")


def acquire_lock(user_id: int) -> None:
    item = f"edit:{int(user_id)}"
    try:
        roblox_api._oc_request("POST", f"{_lock_base()}?id={urllib.parse.quote(item)}",
                               json.dumps({"value": "command-center", "ttl": LOCK_TTL}).encode("utf-8"))
    except roblox_api.RobloxError as exc:
        if "409" in str(exc) or "ALREADY_EXISTS" in str(exc):
            raise EditError("Une autre modification de ce joueur est en cours (verrou pris). "
                            "Réessaie dans une minute.") from exc
        raise


def release_lock(user_id: int) -> None:
    try:
        roblox_api._oc_request("DELETE", f"{_lock_base()}/{urllib.parse.quote(f'edit:{int(user_id)}')}")
    except roblox_api.RobloxError:
        pass   # il expirera seul dans 60 s


def online(user_id: int, force: bool = True) -> dict | None:
    if force:
        live.servers(force=True)
    return live.find_player(user_id)


# MODIFICATIONS (pures, testees) ----------------------------------------------------
def _remove_from_list(items, uid):
    """Retire l'objet `uid` d'une liste, y compris dans le contenu d'un sac (`b`)."""
    if not isinstance(items, list):
        return None
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            continue
        if str(it.get("u")) == str(uid):
            return items.pop(i)
        found = _remove_from_list(it.get("b"), uid)
        if found is not None:
            return found
    return None


def remove_item(value: dict, where: str, uid: str):
    """-> (nouvelle valeur, objet retire, emplacement lisible)."""
    new = copy.deepcopy(value)
    if where == "inventory":
        for slot, it in list((new.get("equipped") or {}).items()):
            if isinstance(it, dict) and str(it.get("u")) == str(uid):
                del new["equipped"][slot]
                return new, it, f"équipé ({slot})"
            if isinstance(it, dict):
                found = _remove_from_list(it.get("b"), uid)
                if found is not None:
                    return new, found, f"sac porté ({slot})"
        found = _remove_from_list(new.get("pockets"), uid)
        if found is not None:
            return new, found, "poches"
    elif where == "stash":
        for i, tab in enumerate(new.get("tabs") or [], start=1):
            if isinstance(tab, dict):
                found = _remove_from_list(tab.get("items"), uid)
                if found is not None:
                    return new, found, f"stash, onglet {tab.get('name') or i}"
    else:
        raise EditError("Emplacement inconnu.")
    raise EditError("Objet introuvable : l'inventaire a peut-être changé. Relis la fiche.")


def _label(item: dict) -> str:
    a = item.get("a")
    attrs = a if isinstance(a, dict) else {}
    return str(attrs.get("ItemName") or item.get("t") or item.get("i") or item.get("u"))


# APERCU, APPLICATION, ANNULATION ---------------------------------------------------
def _store_for(kind: str) -> str:
    stores = live.store_names()
    return {"inventory": stores["inventory"], "stash": stores["stash"], "money": stores["profile"]}[kind]


def plan(user_id: int, op: str, params: dict) -> dict:
    uid = int(user_id)
    where = online(uid, force=False)
    if op == "remove_item":
        kind: Any = params.get("where")
        store, key = _store_for(kind), str(uid)
        entry = read_entry(store, key)
        new, removed, place = remove_item(entry.get("value") or {}, kind, str(params.get("uid")))
        before, after = f"{_label(removed)} ({place})", "retiré"
        inside = len(removed.get("b") or [])
        if inside:
            after += f", avec les {inside} objet(s) de son sac"
    elif op == "set_money":
        raw: Any = params.get("amount")
        amount = int(raw)
        if not 0 <= amount <= MONEY_MAX:
            raise EditError("Montant hors limites.")
        store, key = _store_for("money"), f"p_{uid}"
        entry = read_entry(store, key)
        new = copy.deepcopy(entry.get("value") or {})
        old = new.get("money")
        new["money"] = amount
        before, after = f"{old if old is not None else 0} or", f"{amount} or"
    else:
        raise EditError("Modification inconnue.")
    token = uuid.uuid4().hex
    with _lock:
        now = time.time()
        for t in [t for t, p in _plans.items() if now - p["at"] > PLAN_TTL_S]:
            del _plans[t]
        _plans[token] = {"at": now, "userId": uid, "op": op, "params": params, "store": store, "key": key,
                         "etag": entry.get("etag"), "before": entry.get("value"), "after": new}
    return {"token": token, "userId": uid, "op": op, "online": where,
            "change": {"before": before, "after": after}, "store": store, "key": key,
            "path": "online" if where else "offline"}


def apply(token: str) -> dict:
    with _lock:
        p = _plans.pop(token, None)
    if not p or time.time() - p["at"] > PLAN_TTL_S:
        raise EditError("Aperçu expiré : refais-le.")
    uid = p["userId"]
    if online(uid):
        raise EditError("Le joueur vient de se connecter : la modification doit passer par son serveur. Refais-la.")
    acquire_lock(uid)
    try:
        time.sleep(SETTLE_S)
        if online(uid):
            raise EditError("Le joueur s'est connecté pendant la modification : rien n'a été écrit.")
        entry = read_entry(p["store"], p["key"])
        if entry.get("etag") != p["etag"]:
            raise EditError("Le jeu a modifié cette donnée depuis l'aperçu : refais-le.")
        written = write_entry(p["store"], p["key"], entry, p["after"])
    finally:
        release_lock(uid)
    backup = db.add_backup(uid, p["op"], p["store"], p["key"], p["before"], p["after"],
                           written.get("etag"), p["params"])
    db.audit(f"edit_{p['op']}", str(uid), {**p["params"], "backup": backup, "store": p["store"]}, True)
    return {"ok": True, "backup": backup, "userId": uid}


def undo(backup_id: int) -> dict:
    b = db.get_backup(backup_id)
    if not b:
        raise EditError("Copie introuvable.")
    if b.get("undoneAt"):
        raise EditError("Cette modification a déjà été annulée.")
    uid = int(b["userId"])
    if online(uid):
        raise EditError("Le joueur est en ligne : annule quand il sera déconnecté.")
    acquire_lock(uid)
    try:
        time.sleep(SETTLE_S)
        if online(uid):
            raise EditError("Le joueur s'est connecté : rien n'a été écrit.")
        entry = read_entry(b["store"], b["key"])
        if b.get("etagAfter") and entry.get("etag") != b["etagAfter"]:
            raise EditError("Le joueur a joué depuis : annuler écraserait sa progression. Corrige à la main.")
        write_entry(b["store"], b["key"], entry, b["before"])
    finally:
        release_lock(uid)
    db.mark_backup_undone(backup_id)
    db.audit("edit_undo", str(uid), {"backup": backup_id, "op": b["op"]}, True)
    return {"ok": True, "backup": backup_id}
