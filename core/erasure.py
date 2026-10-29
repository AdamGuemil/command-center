"""
Droit a l'effacement (RTBF) : effacer les donnees d'un joueur, sur demande de Roblox.

Roblox envoie `RightToErasureRequest` (webhook, core/webhooks.py) ; la carte de l'Accueil
ouvre ce module. JAMAIS automatique (§6.7 du plan) : apercu, puis confirmation en tapant
l'identifiant du joueur.

Ce qui est efface :
  * DataStores standard, une entree par magasin joueur (noms lus dans le contrat du HUB) ;
  * OrderedDataStores qui indexent le joueur : classement ranked, index des pieges,
    activite (notifications), classements Faction War de chaque semaine depuis l'ouverture ;
  * dans la base du CC : liaisons Discord, copies d'edition, registre des notifications,
    evenements du jeu le concernant ; les lignes du journal qui le visent sont anonymisees.
La trace de l'effacement lui-meme reste au journal, sans l'identifiant du joueur.

Non couvert : les annonces du marche noir (cle = identifiant d'annonce, introuvable sans
parcourir tout le magasin) ; l'apercu le dit.
"""

from __future__ import annotations

import secrets
import threading
import time
import urllib.parse

from . import config, db, live, roblox_api

PLAN_TTL_S = 600
STANDARD_KEYS = (("profile", "p_{u}"), ("skills", "p_{u}"), ("inventory", "{u}"), ("stash", "{u}"),
                 ("sanctions", "{u}"), ("exfilClaim", "{u}"), ("blackMarketDebts", "d_{u}"),
                 ("honeypot", "u_{u}"))
NOT_COVERED = "Annonces du marché noir (indexées par annonce, pas par joueur) : à vérifier dans le jeu si besoin."

_lock = threading.Lock()
_plans: dict[str, dict] = {}


def ordered_stores(now: int | None = None) -> list[str]:
    week = roblox_api.fw_week_index(now)
    stores = [config.datastore_name("RankedLB"), config.datastore_name("HoneypotIndex"),
              config.datastore_name("CC_LastSeen")]
    for w in range(0, max(0, week) + 1):
        stores += [config.datastore_name(f"FWLB_w{w}_{f}") for f in config.FACTIONS]
    return stores


def _ods_url(store: str, uid: int) -> str:
    return (f"{roblox_api.OPEN_CLOUD}/ordered-data-stores/v1/universes/{config.ROBLOX_UNIVERSE_ID}"
            f"/orderedDataStores/{urllib.parse.quote(store, safe='')}/scopes/global/entries/{uid}")


def targets(user_id: int) -> list[dict]:
    uid = int(user_id)
    names = live.store_names()
    out = [{"kind": "datastore", "store": names[k], "key": fmt.format(u=uid)}
           for k, fmt in STANDARD_KEYS if names.get(k)]
    out += [{"kind": "ordered", "store": s, "key": str(uid)} for s in ordered_stores()]
    return out


def _exists(t: dict, uid: int) -> bool:
    if t["kind"] == "datastore":
        return roblox_api.datastore_get(t["store"], t["key"]) is not None
    return roblox_api._oc_request("GET", _ods_url(t["store"], uid)) is not None


def _delete(t: dict, uid: int) -> None:
    if t["kind"] == "datastore":
        roblox_api.datastore_delete(t["store"], t["key"])
    else:
        roblox_api._oc_request("DELETE", _ods_url(t["store"], uid))


def plan(user_id: int, card: str | None = None) -> dict:
    """Ce qui serait efface : chaque entree, presente ou non. Lecture seule."""
    uid = int(user_id)
    if uid <= 0:
        raise ValueError("Identifiant de joueur invalide.")
    rows = []
    for t in targets(uid):
        try:
            rows.append({**t, "exists": _exists(t, uid), "error": None})
        except Exception as exc:                                # noqa: BLE001
            rows.append({**t, "exists": None, "error": str(exc)[:160]})
    token = secrets.token_urlsafe(16)
    with _lock:
        now = time.time()
        for k in [k for k, p in _plans.items() if now - p["at"] > PLAN_TTL_S]:
            _plans.pop(k, None)
        _plans[token] = {"at": now, "userId": uid, "card": card, "rows": rows}
    return {"token": token, "userId": uid, "card": card, "rows": rows,
            "found": sum(1 for r in rows if r["exists"]), "unreadable": sum(1 for r in rows if r["error"]),
            "local": "liaisons Discord, copies d'édition, registre des notifications, événements du jeu ; "
                     "journal anonymisé", "notCovered": NOT_COVERED, "expiresIn": PLAN_TTL_S}


def apply(token: str, confirm: str) -> dict:
    with _lock:
        p = _plans.get(str(token or ""))
    if not p or time.time() - p["at"] > PLAN_TTL_S:
        raise ValueError("Aperçu expiré : relance l'aperçu avant d'effacer.")
    uid = p["userId"]
    if str(confirm or "").strip() != str(uid):
        raise ValueError("Pour confirmer, tape l'identifiant exact du joueur.")
    results = []
    for row in p["rows"]:
        t = {"kind": row["kind"], "store": row["store"], "key": row["key"]}
        if row["exists"] is False:
            results.append({**t, "ok": True, "skipped": True})
            continue
        try:
            _delete(t, uid)
            results.append({**t, "ok": True})
        except Exception as exc:                                # noqa: BLE001
            results.append({**t, "ok": False, "error": str(exc)[:160]})
    local = db.erase_local(uid)
    ok = all(r["ok"] for r in results)
    card = p.get("card")
    if card:
        db.scrub_rbx_event(card.split(":", 1)[1] if ":" in card else card, ok)
    db.audit("erasure", card or "rtbf:manuel", {"ok": ok, "deleted": sum(1 for r in results if r["ok"] and not r.get("skipped")),
                                         "failed": sum(1 for r in results if not r["ok"]), "local": local}, ok, card)
    if card and ok:
        db.audit("card_action", card, {"action": "erase", "label": "Effacement", "ok": True}, True, card)
    with _lock:
        _plans.pop(str(token), None)
    return {"ok": ok, "results": results, "local": local}
