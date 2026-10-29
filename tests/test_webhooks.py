"""Webhooks Roblox : signature, fenetre de 5 min, doublons, lecture tolerante, cartes."""
from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

import app as cc_app
from core import auth, cards, config, db, webhooks

SECRET = "whsec-test"


def body(event_type="RightToErasureRequest", payload=None, nid="n-1", when="2026-10-29T09:00:00.1234567Z"):
    return json.dumps({"NotificationId": nid, "EventType": event_type, "EventTime": when,
                       "EventPayload": payload if payload is not None else {"UserId": 42, "GameIds": [7, 8]}}).encode()


def header(raw: bytes, ts: int | None = None, secret: str = SECRET) -> str:
    ts = int(time.time()) if ts is None else ts
    return f"t={ts},v1={webhooks.sign(secret, ts, raw)}"


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setattr(config, "ROBLOX_WEBHOOK_SECRET", SECRET)
    monkeypatch.setattr(config, "WATCH", False)
    monkeypatch.setattr(config, "JOBS", False)
    auth.limiter._buckets.clear()


def test_signature_follows_the_roblox_recipe():
    # base64(HMAC-SHA256(secret, "<t>.<corps>")), calcule a la main.
    import base64
    import hashlib
    import hmac
    raw = b'{"a":1}'
    expected = base64.b64encode(hmac.new(b"k", b"123." + raw, hashlib.sha256).digest()).decode()
    assert webhooks.sign("k", 123, raw) == expected


@pytest.mark.parametrize("make, reason", [
    (lambda raw: "", "absente"),
    (lambda raw: "t=abc,v1=xyz", "absente"),
    (lambda raw: header(raw, int(time.time()) - 301), "fenêtre"),
    (lambda raw: header(raw, secret="other"), "invalide"),
    (lambda raw: header(raw + b" "), "invalide"),
])
def test_bad_requests_are_rejected(make, reason):
    raw = body()
    with pytest.raises(webhooks.Rejected, match=reason):
        webhooks.verify(SECRET, make(raw), raw)


def test_several_v1_signatures_are_accepted():
    raw, ts = body(), int(time.time())
    webhooks.verify(SECRET, f"t={ts},v1=old,v1={webhooks.sign(SECRET, ts, raw)}", raw)


def test_classification_and_tolerant_fields():
    assert webhooks.classify("SampleNotification") == ("rbx_sample", None)
    assert webhooks.classify("RightToErasureRequest") == ("rbx_erasure", None)
    assert webhooks.classify("SubscriptionCancelled") == ("rbx_subscription", "cancelled")
    assert webhooks.classify("SubscriptionRefunded") == ("rbx_subscription", "refunded")
    assert webhooks.classify("TransactionRefunded") == ("rbx_refund", None)
    e = webhooks.normalize(json.loads(body("TransactionRefunded", {
        "Buyer": {"UserId": "77"}, "productType": "DeveloperProduct", "ProductId": 555, "PriceInRobux": 99,
        "ReceiptId": "r-1"})))
    d = e["data"]
    assert (e["type"], d["userId"], d["productId"], d["robux"], d["receiptId"]) == ("rbx_refund", 77, 555, 99, "r-1")
    assert e["at"] == 1793264400                    # 7 decimales lues
    with pytest.raises(webhooks.Rejected):
        webhooks.normalize({"EventType": "X"})


def test_endpoint_stores_once_and_creates_the_erasure_card():
    raw = body()
    with TestClient(cc_app.create_app(), base_url="http://127.0.0.1:8787") as c:
        r = c.post("/webhooks/roblox", content=raw, headers={"roblox-signature": header(raw)})
        assert r.status_code == 200 and r.json() == {"ok": True, "duplicate": False, "type": "rbx_erasure"}
        r = c.post("/webhooks/roblox", content=raw, headers={"roblox-signature": header(raw)})
        assert r.json()["duplicate"] is True
        assert c.post("/webhooks/roblox", content=raw, headers={"roblox-signature": "t=1,v1=x"}).status_code == 401
    assert len(db.events(webhooks.TYPES)) == 1
    assert db.audit_rows(5, "webhook")[0]["actor"] == "webhook"
    now = int(time.time())
    built = cards._webhook_cards(db.events(webhooks.TYPES), now)
    assert [c["key"] for c in built] == ["rtbf:n-1"]
    assert built[0]["actions"][0]["kind"] == "erase" and built[0]["noDismiss"]
    with pytest.raises(ValueError):
        cards.set_state("rtbf:n-1", "dismissed")


def test_endpoint_is_absent_without_secret(monkeypatch):
    monkeypatch.setattr(config, "ROBLOX_WEBHOOK_SECRET", "")
    with TestClient(cc_app.create_app(), base_url="http://127.0.0.1:8787") as c:
        assert c.post("/webhooks/roblox", content=b"{}").status_code == 404


def test_cards_for_refunds_subscriptions_and_tests():
    now = int(time.time())
    evts = [webhooks.normalize(json.loads(body(t, p, nid=t)))
            for t, p in (("TransactionRefunded", {"UserId": 5, "ProductId": 9}),
                         ("SubscriptionCancelled", {"UserId": 6, "Reason": "<b>trop cher</b>"}),
                         ("SubscriptionRenewed", {"UserId": 7}),
                         ("SampleNotification", {"UserId": 1}))]
    for e in evts:
        e["at"] = now
    keys = {c["key"]: c for c in cards._webhook_cards(evts, now)}
    assert set(keys) == {"refund:TransactionRefunded", "sub_cancelled:SubscriptionCancelled",
                         "rbx_test:SampleNotification"}
    assert keys["refund:TransactionRefunded"]["actions"][0]["href"] == "#players/5"
