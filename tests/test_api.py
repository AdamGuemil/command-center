"""Couche HTTP (FastAPI) : memes routes, memes erreurs, meme journal que l'ancien serveur."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app as cc_app
from core import auth, config, db, handlers, notify

LOCAL = "http://127.0.0.1:8787"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WATCH", False)
    monkeypatch.setattr(config, "BOT", False)
    monkeypatch.setattr(config, "JOBS", False)
    monkeypatch.setattr(notify, "CONFIG_FILE", tmp_path / "notifications.json")
    # Mode local : Host 127.0.0.1 et jeton CSRF du processus, comme la vraie page.
    with TestClient(cc_app.create_app(), base_url=LOCAL, headers={"x-cc-csrf": auth.LOCAL_CSRF}) as c:
        yield c


def test_every_handler_has_its_route(client):
    routes = {(r.path, m) for r in client.app.routes for m in getattr(r, "methods", ())}
    for path in handlers.ROUTES_GET:
        assert (path, "GET") in routes, path
    for path in handlers.ROUTES_POST:
        assert (path, "POST") in routes, path


def test_interface_files_are_served_without_cache(client):
    r = client.get("/")
    assert r.status_code == 200 and "<html" in r.text.lower()
    assert r.headers["cache-control"] == "no-store"
    assert client.get("/js/app.js").status_code == 200
    assert client.get("/favicon.ico").status_code == 204


@pytest.mark.parametrize("path", ["/../.env", "/%2e%2e/.env", "/..%2fcore/config.py", "/core/config.py"])
def test_nothing_outside_web_is_served(client, path):
    r = client.get(path)
    assert r.status_code == 404
    assert "ROBLOX_OPENCLOUD_KEY" not in r.text


def test_unknown_api_route_is_json_404(client):
    r = client.get("/api/nope")
    assert r.status_code == 404 and r.json() == {"error": "Route inconnue."}


def test_handler_error_becomes_500_with_readable_message(client):
    r = client.get("/api/player")
    assert r.status_code == 500
    assert "userId" in r.json()["error"]


def test_query_string_keeps_the_old_shape(client):
    db.audit("probe", "x", {}, True)
    r = client.get("/api/journal?limit=1")
    assert r.status_code == 200 and len(r.json()["rows"]) == 1


def test_invalid_bodies_are_refused(client):
    assert client.post("/api/notify/preview", content=b"{oops").status_code == 500
    r = client.post("/api/notify/preview", json=[1, 2])
    assert r.status_code == 500 and "objet" in r.json()["error"]


def test_writes_are_audited_success_and_failure(client):
    r = client.post("/api/notify/config", json={"ids": {"COMEBACK": "12345"}, "testUserId": "7"})
    assert r.status_code == 200 and r.json()["ok"] is True
    r = client.post("/api/unban", json={})
    assert r.status_code == 500
    rows = {row["action"]: row for row in db.audit_rows(10)}
    assert rows["notify_config"]["ok"] is True
    assert rows["notify_config"]["detail"]["ids"] == "1 champ(s)"
    assert rows["unban"]["ok"] is False and "userId" in rows["unban"]["detail"]["error"]


def test_openapi_lists_the_api(client):
    spec = client.get("/api/openapi.json").json()
    assert "/api/live" in spec["paths"] and "post" in spec["paths"]["/api/cmd"]
    assert client.get("/api/docs").status_code == 200
