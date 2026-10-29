"""
Recepteur des webhooks Roblox (remboursements, abonnements, droit a l'effacement).

Reference : https://create.roblox.com/docs/cloud/webhooks/webhook-notifications

Verification, dans cet ordre :
  1. en-tete `roblox-signature: t=<horodatage>,v1=<signature>` present et bien forme ;
  2. horodatage a moins de 5 minutes de l'heure du CC (rejeu d'une requete capturee) ;
  3. signature = base64(HMAC-SHA256(secret, "<t>.<corps brut>")), comparee en temps constant ;
  4. corps JSON avec NotificationId, EventType, EventPayload.
Roblox peut livrer deux fois la meme notification : elle est stockee sous l'id
`rbx:<NotificationId>` dans la table des evenements (INSERT OR IGNORE), un doublon ne cree
donc ni carte ni message.

Roblox exige une reponse 2xx en moins de 5 s et invalide l'URL apres 5 echecs : le
recepteur ne fait QUE verifier et stocker. Les cartes de l'Accueil (core/cards.py) et les
actions (retrait, effacement) viennent ensuite, au clic.

Les noms de champs des remboursements et abonnements ne sont pas tous publies : la lecture
est tolerante (plusieurs noms essayes, sans casse) et le contenu brut est garde pour
l'affichage. Le test du Creator Hub (SampleNotification) produit une carte d'information.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from datetime import datetime

from . import config, db

MAX_SKEW_S = 300
MAX_BODY = 64 * 1024
TYPES = ("rbx_refund", "rbx_subscription", "rbx_erasure", "rbx_sample", "rbx_other")


class Rejected(Exception):
    """Requete refusee (401) : signature, horodatage ou corps invalide."""


def sign(secret: str, timestamp: int | str, body: bytes) -> str:
    msg = f"{timestamp}.".encode() + body
    return base64.b64encode(hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).digest()).decode("ascii")


def _parse_header(header: str) -> tuple[str, list[str]]:
    ts, sigs = "", []
    for part in (header or "").split(","):
        k, _, v = part.strip().partition("=")
        if k == "t":
            ts = v.strip()
        elif k == "v1" and v:
            sigs.append(v.strip())
    return ts, sigs


def verify(secret: str, header: str, body: bytes, now: float | None = None) -> None:
    if not secret:
        raise Rejected("Webhooks non configurés.")
    ts, sigs = _parse_header(header)
    if not ts.isdigit() or not sigs:
        raise Rejected("Signature absente ou mal formée.")
    now = time.time() if now is None else now
    if abs(now - int(ts)) > MAX_SKEW_S:
        raise Rejected("Horodatage hors fenêtre (5 min).")
    expected = sign(secret, ts, body)
    if not any(hmac.compare_digest(expected, s) for s in sigs):
        raise Rejected("Signature invalide.")


# LECTURE DU CONTENU ------------------------------------------------------------------
def _flat(payload: dict) -> dict[str, object]:
    """Champs du payload a plat, cles en minuscules (un niveau d'imbrication suffit)."""
    out: dict[str, object] = {}
    for k, v in payload.items():
        if isinstance(v, dict):
            for k2, v2 in v.items():
                out.setdefault(f"{k}.{k2}".lower(), v2)
                out.setdefault(str(k2).lower(), v2)
        out[str(k).lower()] = v
    return out


def _pick(flat: dict, *names: str):
    for n in names:
        v = flat.get(n.lower())
        if v not in (None, ""):
            return v
    return None


def _int(v) -> int | None:
    s = str(v or "")
    return int(s) if s.isdigit() else None


def classify(event_type: str) -> tuple[str, str | None]:
    t = (event_type or "").lower()
    if "sample" in t:
        return "rbx_sample", None
    if "erasure" in t:
        return "rbx_erasure", None
    if "subscription" in t:
        for word, state in (("refund", "refunded"), ("cancel", "cancelled"), ("resub", "resubscribed"),
                            ("renew", "renewed"), ("purchas", "purchased")):
            if word in t:
                return "rbx_subscription", state
        return "rbx_subscription", "other"
    if "refund" in t or "transaction" in t:
        return "rbx_refund", None
    return "rbx_other", None


def _event_time(raw) -> int:
    try:
        text = str(raw or "")
        if "." in text:                       # 7 decimales chez Roblox : fromisoformat en veut 6 au plus
            head, _, frac = text.partition(".")
            text = f"{head}.{frac.rstrip('Z')[:6]}Z"
        return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return int(time.time())


def normalize(doc: dict) -> dict:
    """Corps Roblox -> evenement du CC {id, type, at, data}."""
    nid = str(doc.get("NotificationId") or "")
    etype = str(doc.get("EventType") or "")
    payload = doc.get("EventPayload")
    if not nid or not etype or not isinstance(payload, dict):
        raise Rejected("Corps inattendu : NotificationId, EventType et EventPayload sont requis.")
    kind, state = classify(etype)
    flat = _flat(payload)
    data: dict = {
        "notificationId": nid[:120], "eventType": etype[:80], "state": state,
        "userId": _int(_pick(flat, "UserId", "BuyerUserId", "BuyerId", "SubscriberId", "Subscriber.UserId",
                             "PurchaserId", "user.id")),
        "payload": payload,
    }
    if kind == "rbx_erasure":
        games = payload.get("GameIds") or payload.get("gameIds") or []
        data["gameIds"] = [int(g) for g in games if str(g).isdigit()] if isinstance(games, list) else []
    if kind == "rbx_refund":
        data.update(
            productType=_pick(flat, "ProductType", "ItemType", "AssetType", "PurchaseType"),
            productId=_pick(flat, "ProductId", "DeveloperProductId", "GamePassId", "AssetId", "ItemId", "TargetId"),
            robux=_int(_pick(flat, "Robux", "RobuxAmount", "Price", "PriceInRobux", "Amount")),
            receiptId=_pick(flat, "ReceiptId", "PurchaseId", "TransactionId", "PurchaseReceiptId"),
            placeId=_int(_pick(flat, "PlaceId", "RootPlaceId")),
        )
    if kind == "rbx_subscription":
        data.update(
            productId=_pick(flat, "SubscriptionProductId", "ProductId", "SubscriptionId", "Subscription.Id"),
            reason=_pick(flat, "CancellationReason", "Reason", "CancelReason"),
        )
    return {"id": f"rbx:{nid[:120]}", "type": kind, "at": _event_time(doc.get("EventTime")), "data": data}


def receive(body: bytes, signature: str, now: float | None = None) -> dict:
    """Point d'entree du recepteur : verifie, stocke, dit si c'etait un doublon."""
    if len(body) > MAX_BODY:
        raise Rejected("Corps trop volumineux.")
    verify(config.ROBLOX_WEBHOOK_SECRET, signature, body, now)
    try:
        doc = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise Rejected("Corps JSON illisible.") from exc
    if not isinstance(doc, dict):
        raise Rejected("Corps JSON attendu : un objet.")
    event = normalize(doc)
    fresh = db.add_events([event])
    if fresh:
        d = event["data"]
        db.audit("webhook", event["type"], {"eventType": d["eventType"], "userId": d.get("userId"),
                                            "notificationId": d["notificationId"]}, True, actor="webhook")
    return {"ok": True, "duplicate": not fresh, "type": event["type"]}


def recent(limit: int = 50) -> list[dict]:
    return db.events(TYPES, since=0, limit=limit)
