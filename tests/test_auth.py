"""Acces : mode local verrouille, connexion Discord, roles, CSRF, origine, limite de debit."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app as cc_app
from core import auth, config, db

LOCAL = "http://127.0.0.1:8787"
PUBLIC = "https://cc.example.test"
ADMIN, MOD, VIEWER, STRANGER = 1001, 1002, 1003, 1999


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.setattr(config, "WATCH", False)
    monkeypatch.setattr(config, "BOT", False)
    monkeypatch.setattr(config, "JOBS", False)
    auth.limiter._buckets.clear()


@pytest.fixture()
def hosted(monkeypatch):
    monkeypatch.setattr(config, "DISCORD_CLIENT_ID", "123")
    monkeypatch.setattr(config, "DISCORD_CLIENT_SECRET", "s3cret")
    monkeypatch.setattr(config, "PUBLIC_URL", PUBLIC)
    monkeypatch.setattr(config, "ADMINS", frozenset({ADMIN}))
    monkeypatch.setattr(config, "MODS", frozenset({MOD}))
    monkeypatch.setattr(config, "VIEWERS", frozenset({VIEWER}))
    with TestClient(cc_app.create_app(), base_url=PUBLIC) as c:
        yield c


def login(client, monkeypatch, uid: int) -> str:
    """Parcours complet : /auth/discord pose l'etat, Discord renvoie sur /auth/callback."""
    monkeypatch.setattr(auth, "exchange", lambda code: {"id": uid, "name": f"user{uid}", "avatar": None})
    r = client.get("/auth/discord", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith(auth.AUTHORIZE_URL)
    state = client.cookies.get(auth.STATE_COOKIE)
    r = client.get(f"/auth/callback?code=abc&state={state}", follow_redirects=False)
    return r


def csrf(client) -> dict:
    return {"x-cc-csrf": client.get("/api/me").json()["csrf"]}


# MODE LOCAL ----------------------------------------------------------------------------
def test_local_mode_refuses_foreign_host_headers():
    with TestClient(cc_app.create_app(), base_url="http://evil.example") as c:
        assert c.get("/").status_code == 403
        assert c.get("/api/me").status_code == 403
    with TestClient(cc_app.create_app(), base_url=LOCAL) as c:
        assert c.get("/api/me").json()["role"] == "admin"


def test_local_writes_need_the_csrf_header_and_same_origin():
    with TestClient(cc_app.create_app(), base_url=LOCAL) as c:
        assert c.post("/api/todo", json={"id": "x"}).status_code == 403
        token = c.get("/api/me").json()["csrf"]
        r = c.post("/api/cards/state", json={"key": "k", "state": "open"},
                   headers={"x-cc-csrf": token, "origin": "https://evil.example"})
        assert r.status_code == 403 and "Origine" in r.json()["error"]
        r = c.post("/api/cards/state", json={"key": "k", "state": "nope"},
                   headers={"x-cc-csrf": token, "origin": LOCAL})
        assert r.status_code == 500                 # passe la garde, refuse par le handler


def test_exposing_without_login_is_refused():
    assert auth.startup_problems("127.0.0.1") == []
    assert auth.startup_problems("0.0.0.0")


def test_hosted_mode_needs_public_https_url_and_an_admin(monkeypatch):
    monkeypatch.setattr(config, "DISCORD_CLIENT_ID", "1")
    monkeypatch.setattr(config, "DISCORD_CLIENT_SECRET", "2")
    monkeypatch.setattr(config, "PUBLIC_URL", "http://cc.example.test")
    monkeypatch.setattr(config, "ADMINS", frozenset())
    problems = " ".join(auth.startup_problems("0.0.0.0"))
    assert "https" in problems and "CC_ADMINS" in problems
    monkeypatch.setattr(config, "PUBLIC_URL", PUBLIC)
    monkeypatch.setattr(config, "ADMINS", frozenset({ADMIN}))
    assert auth.startup_problems("0.0.0.0") == []


# MODE HEBERGE --------------------------------------------------------------------------
def test_anonymous_visitors_see_only_the_login_page(hosted):
    r = hosted.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert hosted.get("/js/app.js", follow_redirects=False).status_code == 303
    assert hosted.get("/api/live").status_code == 401
    assert hosted.get("/api/openapi.json").status_code == 401
    page = hosted.get("/login")
    assert page.status_code == 200 and "Se connecter avec Discord" in page.text
    assert page.headers["x-frame-options"] == "DENY"
    assert hosted.get("/healthz").json()["ok"] is True


def test_login_sets_a_strict_host_only_cookie_and_stores_only_a_hash(hosted, monkeypatch):
    r = login(hosted, monkeypatch, ADMIN)
    assert r.status_code == 200 and "location.replace" in r.text
    cookie = r.headers["set-cookie"]
    assert cookie.startswith("__Host-cc=") and "HttpOnly" in cookie and "Secure" in cookie
    assert "samesite=strict" in cookie.lower()
    token = hosted.cookies.get("__Host-cc")
    with db.connect() as con:
        ids = [row["id"] for row in con.execute("SELECT id FROM sessions")]
    assert ids and token not in ids
    me = hosted.get("/api/me").json()
    assert me["role"] == "admin" and me["user"]["name"] == f"user{ADMIN}"
    assert db.audit_rows(5, "login")[0]["actor"] == f"user{ADMIN} ({ADMIN})"


def test_callback_rejects_a_forged_state(hosted, monkeypatch):
    monkeypatch.setattr(auth, "exchange", lambda code: pytest.fail("ne doit pas appeler Discord"))
    hosted.cookies.set(auth.STATE_COOKIE, "abc", path="/auth")
    r = hosted.get("/auth/callback?code=x&state=other")
    assert r.status_code == 400 and "expiré" in r.text


def test_unknown_discord_account_is_told_its_id(hosted, monkeypatch):
    r = login(hosted, monkeypatch, STRANGER)
    assert r.status_code == 403 and str(STRANGER) in r.text
    assert hosted.get("/api/me").status_code == 401
    assert db.audit_rows(5, "login_denied")[0]["ok"] is False


def test_roles_limit_writes(hosted, monkeypatch):
    login(hosted, monkeypatch, VIEWER)
    h = csrf(hosted)
    assert hosted.get("/api/journal").status_code == 200
    r = hosted.post("/api/cards/state", json={"key": "k", "state": "open"}, headers=h)
    assert r.status_code == 403 and "lecture seule" in r.json()["error"]

    hosted.cookies.clear()
    login(hosted, monkeypatch, MOD)
    h = csrf(hosted)
    assert hosted.post("/api/cards/state", json={"key": "k", "state": "open"}, headers=h).status_code == 200
    assert hosted.post("/api/wipe", json={}, headers=h).status_code == 403
    assert hosted.post("/api/erasure/plan", json={"userId": 1}, headers=h).status_code == 403
    r = hosted.post("/api/cmd", json={"op": "set_money", "userId": 5}, headers=h)
    assert r.status_code == 403 and "modérateur" in r.json()["error"]
    r = hosted.post("/api/cmd", json={"op": "kick", "userId": 5}, headers=h)
    assert r.status_code == 500                     # autorise ; refuse ensuite : joueur hors ligne


def test_removing_an_id_revokes_open_sessions(hosted, monkeypatch):
    login(hosted, monkeypatch, MOD)
    assert hosted.get("/api/me").status_code == 200
    monkeypatch.setattr(config, "MODS", frozenset())
    assert hosted.get("/api/me").status_code == 401


def test_writes_are_attributed_and_logout_ends_the_session(hosted, monkeypatch):
    login(hosted, monkeypatch, ADMIN)
    h = csrf(hosted)
    hosted.post("/api/notify/stop", json={}, headers=h)
    assert db.audit_rows(5, "notify_stop")[0]["actor"] == f"user{ADMIN} ({ADMIN})"
    assert hosted.post("/auth/logout", json={}).status_code == 403          # sans jeton CSRF
    assert hosted.post("/auth/logout", json={}, headers=h).status_code == 200
    assert hosted.get("/api/me").status_code == 401


def test_rate_limit_on_writes(hosted, monkeypatch):
    login(hosted, monkeypatch, ADMIN)
    h = csrf(hosted)
    codes = [hosted.post("/api/cards/state", json={"key": "k", "state": "open"}, headers=h).status_code
             for _ in range(25)]
    assert 429 in codes and codes[0] == 200


def test_rate_limiter_refills():
    rl = auth.RateLimiter()
    assert all(rl.allow("k", 60, 2, now=0.0) for _ in range(2))
    assert not rl.allow("k", 60, 2, now=0.0)
    assert rl.allow("k", 60, 2, now=1.5)
