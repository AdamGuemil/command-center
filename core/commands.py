"""
Commandes du Command Center vers les serveurs du jeu (lot 3, §3.4 du plan).

Transport : publication Open Cloud sur le topic MessagingService `FW_Event`, deja ecoute
par EventService dans chaque serveur ; CCCommands.luau execute. Le serveur concerne
repond par un evenement `cmd_ack` sur le bus CC_Events_V1 (lu par core/events.py).

Aussi ici, parce que ce sont des actions sur les joueurs et les serveurs :
  * bans d'univers : Open Cloud `user-restrictions` (motif public et prive, duree,
    comptes alternatifs), suivis d'un kick si le joueur est en ligne ;
  * redemarrage des serveurs : Open Cloud `:restartServers` (avec delai d'evacuation).
"""

from __future__ import annotations

import json
import threading
import time
import uuid

from . import config, db, events, live, roblox_api

OPS = {"toast", "kick", "drain", "remove_item", "set_money"}
MAX_BYTES = 950
EXPIRES_S = 120
TEXT_MAX = 240

_poll_lock = threading.Lock()
_last_poll = [0.0]


class CommandError(Exception):
    """Refus lisible."""


def send(op: str, **fields) -> dict:
    if op not in OPS:
        raise CommandError("Commande inconnue.")
    now = int(time.time())
    msg: dict = {"kind": "cc_cmd", "id": uuid.uuid4().hex[:12], "op": op, "at": now, "exp": now + EXPIRES_S}
    for k, v in fields.items():
        if v is None or v == "":
            continue
        msg[k] = v[:TEXT_MAX] if isinstance(v, str) else v
    if len(json.dumps(msg, ensure_ascii=False).encode("utf-8")) > MAX_BYTES:
        raise CommandError("Message trop long (1 Ko au plus) : raccourcis le texte.")
    roblox_api.publish(config.FW_TOPIC, msg)
    target = f"u:{fields['u']}" if fields.get("u") else f"job:{fields.get('job') or '*'}"
    db.add_command(msg["id"], op, target, {k: v for k, v in msg.items() if k not in ("kind",)})
    return {"id": msg["id"], "op": op, "target": target}


def status(cmd_id: str) -> dict:
    """Etat d'une commande et ses accuses. Relit le bus au plus toutes les 2 s."""
    with _poll_lock:
        if time.time() - _last_poll[0] >= 2:
            _last_poll[0] = time.time()
            events.poll()
    cmd = db.get_command(cmd_id)
    if not cmd:
        raise CommandError("Commande inconnue.")
    age = int(time.time()) - cmd["at"]
    cmd["age"] = age
    # Une diffusion globale collecte plusieurs reponses pendant 45 s.
    broadcast = cmd["op"] == "toast" and cmd["target"] == "job:*"
    cmd["done"] = bool(cmd["acks"]) and (not broadcast or age >= 45)
    cmd["expired"] = age >= 45 and not cmd["acks"]
    cmd["ackError"] = events.status().get("lastError")
    return cmd


# BANS (Open Cloud user-restrictions) --------------------------------------------
def _restriction_url(user_id: int) -> str:
    return (f"{roblox_api.OPEN_CLOUD}/cloud/v2/universes/{config.ROBLOX_UNIVERSE_ID}"
            f"/user-restrictions/{int(user_id)}")


def ban(user_id: int, days: float | None, display_reason: str, private_reason: str = "",
        include_alts: bool = True) -> dict:
    display_reason = (display_reason or "").strip()
    if not display_reason:
        raise CommandError("Le motif affiché au joueur est obligatoire.")
    restriction = {"active": True, "displayReason": display_reason[:400],
                   "privateReason": (private_reason or "")[:1000],
                   "excludeAltAccounts": not include_alts}
    if days:
        restriction["duration"] = f"{int(float(days) * 86400)}s"
    body = json.dumps({"gameJoinRestriction": restriction}).encode("utf-8")
    res = roblox_api._oc_request("PATCH", _restriction_url(user_id) + "?updateMask=gameJoinRestriction", body)
    kicked = None
    if live.find_player(user_id):
        kicked = send("kick", u=int(user_id), reason=f"Banned: {display_reason}")
    return {"ok": True, "restriction": (res or {}).get("gameJoinRestriction"), "kick": kicked}


def unban(user_id: int) -> dict:
    body = json.dumps({"gameJoinRestriction": {"active": False}}).encode("utf-8")
    res = roblox_api._oc_request("PATCH", _restriction_url(user_id) + "?updateMask=gameJoinRestriction", body)
    return {"ok": True, "restriction": (res or {}).get("gameJoinRestriction")}


def bans(limit: int = 100) -> dict:
    """Joueurs actuellement bannis de l'univers (restriction active)."""
    url = (f"{roblox_api.OPEN_CLOUD}/cloud/v2/universes/{config.ROBLOX_UNIVERSE_ID}"
           f"/user-restrictions?maxPageSize={min(100, limit)}")
    res = roblox_api._oc_request("GET", url) or {}
    rows = []
    for r in res.get("userRestrictions") or []:
        g = r.get("gameJoinRestriction") or {}
        if not g.get("active"):
            continue
        uid = str(r.get("user") or r.get("path") or "").rsplit("/", 1)[-1]
        rows.append({"userId": int(uid) if uid.isdigit() else uid, "start": g.get("startTime"),
                     "duration": g.get("duration"), "displayReason": g.get("displayReason"),
                     "privateReason": g.get("privateReason"), "alts": not g.get("excludeAltAccounts")})
    names = roblox_api.resolve_usernames([r["userId"] for r in rows if isinstance(r["userId"], int)][:100])
    for r in rows:
        r["name"] = names.get(str(r["userId"]))
    return {"bans": rows, "more": bool(res.get("nextPageToken"))}


# REDEMARRAGE DES SERVEURS -----------------------------------------------------------
def restart_servers(all_versions: bool = False, bleed_minutes: int = 0) -> dict:
    body: dict = {"closeAllVersions": bool(all_versions)}
    if bleed_minutes:
        body.update(bleedOffServers=True, bleedOffDurationMinutes=max(1, min(60, int(bleed_minutes))))
    url = f"{roblox_api.OPEN_CLOUD}/cloud/v2/universes/{config.ROBLOX_UNIVERSE_ID}:restartServers"
    roblox_api._oc_request("POST", url, json.dumps(body).encode("utf-8"))
    return {"ok": True, **body}
