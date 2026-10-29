"""
Couche HTTP du Command Center (FastAPI).

Les routes metier sont celles de `core/handlers.py`, a l'identique : memes chemins, memes
corps, meme format d'erreur (`500 {"error": message}`), meme journal d'audit. Les handlers
sont synchrones (Open Cloud et Discord en HTTP bloquant) : FastAPI les execute dans son
pool de threads, la boucle asyncio reste libre pour le bot Discord et les autres requetes.

Autour (lot 6) :
  * garde d'acces (`guard`) : session Discord ou mode local, role par route, CSRF sur
    toute ecriture, controle d'origine, limite de debit, en-tetes de securite ;
  * /login, /auth/discord, /auth/callback, /auth/logout et /api/me (core/auth.py) ;
  * /webhooks/roblox : recepteur signe HMAC (core/webhooks.py) ;
  * /healthz : sonde de disponibilite, publique, sans donnee sensible.
Au demarrage (lifespan) : verification de l'exposition, cloture des campagnes de
notifications interrompues, veilleur live, automatisations et sauvegardes, bot Discord.

Documentation interactive de l'API : /api/docs (OpenAPI genere par FastAPI).
"""

from __future__ import annotations

import asyncio
import contextlib
import html
import json
import logging
import secrets
import time
from collections.abc import AsyncIterator, Callable
from typing import Any
from urllib.parse import parse_qs, urlsplit

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response

from core import auth, automations, config, db, handlers, jobs, watch, webhooks

log = logging.getLogger("cc")
VERSION = "0.7.0"
STARTED = time.time()
PUBLIC_PATHS = {"/login", "/auth/discord", "/auth/callback", "/healthz", "/webhooks/roblox", "/favicon.ico"}
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


def _json(payload, status: int = 200) -> JSONResponse:
    return JSONResponse(payload, status_code=status, headers={"Cache-Control": "no-store"})


def _as(actor: str, fn: Callable, *args: Any):
    """Execute `fn` (dans le pool de threads) avec l'auteur des ecritures pose."""
    token = db.ACTOR.set(actor)
    try:
        return fn(*args)
    finally:
        db.ACTOR.reset(token)


def _user(request: Request) -> dict:
    user = getattr(request.state, "user", None)
    if user:
        return user
    if not auth.enabled():
        return auth.LOCAL_USER
    raise PermissionError("Connexion requise.")        # la garde l'a deja refuse : jamais atteint


def _get_route(fn: Callable[[dict], dict]):
    async def endpoint(request: Request) -> JSONResponse:
        # Meme forme que l'ancien serveur : {cle: [valeurs]} (urllib.parse.parse_qs).
        query = parse_qs(request.url.query, keep_blank_values=True)
        try:
            return _json(await run_in_threadpool(_as, auth.actor(_user(request)), fn, query))
        except Exception as exc:                                # noqa: BLE001
            return _json({"error": str(exc)}, 500)
    return endpoint


def _post_route(path: str, fn: Callable[[dict], dict]):
    action = handlers.AUDITED_POST.get(path)

    async def endpoint(request: Request) -> JSONResponse:
        user = _user(request)
        who = auth.actor(user)
        body: dict = {}
        try:
            raw = await request.body()
            body = json.loads(raw or b"{}")
            if not isinstance(body, dict):
                raise ValueError("Corps JSON attendu : un objet.")
            if path == "/api/cmd":
                refused = auth.check_cmd(user["role"], str(body.get("op") or ""))
                if refused:
                    return _json({"error": refused}, 403)
            result = await run_in_threadpool(_as, who, fn, body)
            if action:
                ok = not (isinstance(result, dict) and result.get("ok") is False)
                await run_in_threadpool(_as, who, handlers._audit_safe, action, handlers._summary(body), ok)
            return _json(result)
        except Exception as exc:                                # noqa: BLE001
            if action:
                await run_in_threadpool(_as, who, handlers._audit_safe, action,
                                        {**handlers._summary(body), "error": str(exc)[:200]}, False)
            return _json({"error": str(exc)}, 500)
    return endpoint


def _summary_of(fn: Callable) -> str:
    doc = (fn.__doc__ or "").strip().splitlines()
    return doc[0] if doc else ""


# PAGES DE CONNEXION ------------------------------------------------------------------
_PAGE_CSS = """
:root{--bg:#171b20;--panel:#1e232a;--border:#2c333c;--text:#e3e6ea;--dim:#8c95a1;--accent:#c9a24b;
--down:#d9534a}
*{box-sizing:border-box}html,body{margin:0;height:100%;background:var(--bg);color:var(--text);
font:15px/1.5 "Barlow",system-ui,-apple-system,"Segoe UI",sans-serif}
main{min-height:100%;display:flex;align-items:center;justify-content:center;padding:24px}
.box{width:100%;max-width:380px;background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:28px}
.brand{display:flex;align-items:center;gap:10px;font-weight:600;font-size:16px;margin-bottom:22px}
.brand span{color:var(--dim);font-weight:500}
h1{font-size:20px;margin:0 0 6px}p{color:var(--dim);margin:0 0 20px}
a.btn{display:flex;align-items:center;justify-content:center;gap:10px;width:100%;padding:11px 14px;border-radius:6px;
background:var(--accent);color:#1b1608;font-weight:600;text-decoration:none}
a.btn:focus-visible{outline:2px solid var(--text);outline-offset:2px}
.err{border-left:3px solid var(--down);background:rgba(217,83,74,.12);color:#f0c4bf;padding:10px 12px;
border-radius:4px;margin:0 0 18px;font-size:14px}
code{background:#252b33;padding:1px 6px;border-radius:4px;color:var(--text)}
small{display:block;color:var(--dim);margin-top:16px;font-size:12.5px}
"""
_MARK = ('<svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2.5 20 6v6.2c0 4.6-3.3 '
         '8.4-8 9.3-4.7-.9-8-4.7-8-9.3V6z" fill="none" stroke="#c9a24b" stroke-width="1.6"/><path d="M8 12.5 11 15l5-6" '
         'fill="none" stroke="#c9a24b" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>')
LOGIN_ERRORS = {
    "expired": "La connexion a expiré ou a été ouverte dans un autre onglet. Recommence.",
    "cancelled": "Connexion annulée sur Discord.",
    "failed": "Discord n'a pas pu confirmer ton identité. Réessaie dans un instant.",
    "busy": "Trop de tentatives. Attends une minute.",
}


def _page(title: str, inner: str, status: int = 200, script: str = "") -> HTMLResponse:
    doc = (f'<!doctype html><html lang="fr"><head><meta charset="utf-8">'
           f'<meta name="viewport" content="width=device-width,initial-scale=1">'
           f'<title>{html.escape(title)} · Command Center</title><style>{_PAGE_CSS}</style></head>'
           f'<body><main><div class="box"><div class="brand">{_MARK} Shroud War <span>Command Center</span></div>'
           f'{inner}</div></main>{script}</body></html>')
    return HTMLResponse(doc, status_code=status, headers={"Cache-Control": "no-store"})


def login_page(error: str = "", denied_id: int | None = None, status: int = 200) -> HTMLResponse:
    msg = ""
    if denied_id is not None:
        msg = (f'<div class="err">Ton compte Discord n\'a pas accès à cette console. Donne cet identifiant à un '
               f'administrateur pour qu\'il l\'ajoute : <code>{int(denied_id)}</code></div>')
    elif error in LOGIN_ERRORS:
        msg = f'<div class="err">{html.escape(LOGIN_ERRORS[error])}</div>'
    # Un lien venu d'un autre site (Discord...) n'emporte pas le cookie SameSite=Strict : la page
    # verifie la session par une requete de meme origine et repart vers la console si elle existe.
    script = ('<script>fetch("/api/me",{credentials:"same-origin"}).then(r=>{if(r.ok)location.replace("/")})'
              '.catch(()=>{})</script>') if denied_id is None and not error else ""
    return _page("Connexion", f"<h1>Connexion</h1><p>Accès réservé à l'équipe Shroud War.</p>{msg}"
                 '<a class="btn" href="/auth/discord">Se connecter avec Discord</a>'
                 "<small>Seul ton identifiant et ton nom Discord sont lus. Aucune autorisation sur ton compte "
                 "n'est demandée.</small>", status, script)


def _bounce(target: str = "/") -> HTMLResponse:
    # Pas de 302 : apres un aller-retour par discord.com, le navigateur n'enverrait pas le cookie
    # SameSite=Strict sur la redirection. Une navigation lancee par cette page est, elle, de meme site.
    return _page("Connexion", '<h1>Connecté</h1><p>Ouverture de la console…</p>'
                 f'<a class="btn" href="{html.escape(target)}">Continuer</a>', 200,
                 f'<script>location.replace({json.dumps(target)})</script>')


def _ip(request: Request) -> str:
    return request.client.host if request.client else ""


def _expected_origin(request: Request) -> str:
    if auth.enabled() and config.PUBLIC_URL:
        u = urlsplit(config.PUBLIC_URL)
        return f"{u.scheme}://{u.netloc}"
    return f"{request.url.scheme}://{request.headers.get('host', '')}"


def _harden(resp: Response) -> Response:
    h = resp.headers
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("X-Frame-Options", "DENY")
    h.setdefault("Referrer-Policy", "same-origin")
    h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    h.setdefault("Content-Security-Policy", "frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
    if auth.secure_cookies():
        h.setdefault("Strict-Transport-Security", "max-age=31536000")
    return resp


# DEMARRAGE ---------------------------------------------------------------------------
@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    problems = auth.startup_problems(config.HOST)
    if problems:
        raise RuntimeError("Démarrage refusé : " + " ".join(problems))
    try:
        db.close_stale_campaigns()
    except Exception:                                           # noqa: BLE001
        pass
    if config.WATCH and watch.start():
        log.info("Veilleur live actif.")
    if config.JOBS:
        automations.start()
    bot_task = None
    if config.BOT:
        from core import bot
        bot_task = asyncio.create_task(bot.run(), name="discord-bot")
    try:
        yield
    finally:
        if bot_task:
            bot_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await bot_task


def create_app() -> FastAPI:
    app = FastAPI(title="Shroud War Command Center", version=VERSION, lifespan=lifespan,
                  docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json")

    @app.middleware("http")
    async def guard(request: Request, call_next):
        path = request.url.path
        if auth.enabled():
            token = request.cookies.get(auth.session_cookie())
            user = await run_in_threadpool(auth.resolve, token) if token else None
        else:
            # Mode local : seul un en-tete Host local est servi (parade au DNS rebinding).
            if not auth.is_loopback(request.url.hostname or ""):
                return _harden(Response("Hôte refusé : en mode local, ouvre http://127.0.0.1.", 403))
            user = auth.LOCAL_USER
        request.state.user = user
        if path in PUBLIC_PATHS:
            return _harden(await call_next(request))
        if user is None:
            if path.startswith("/api/") or request.method not in SAFE_METHODS:
                return _harden(_json({"error": "Connexion requise.", "login": "/login"}, 401))
            return _harden(RedirectResponse("/login", 303))
        if request.method not in SAFE_METHODS:
            origin = request.headers.get("origin")
            if origin and origin != _expected_origin(request):
                return _harden(_json({"error": "Origine refusée."}, 403))
            if not auth.csrf_ok(user, request.headers.get(auth.CSRF_HEADER)):
                return _harden(_json({"error": "Jeton de sécurité absent ou périmé : recharge la page.",
                                      "csrf": True}, 403))
            if not auth.rate_ok("write", str(user["id"]) if not user.get("local") else _ip(request)):
                return _harden(_json({"error": "Trop d'actions d'affilée : attends quelques secondes."}, 429))
            if path.startswith("/api/"):
                refused = auth.check(user["role"], request.method, path)
                if refused:
                    return _harden(_json({"error": refused}, 403))
        return _harden(await call_next(request))

    for path, fn in handlers.ROUTES_GET.items():
        app.add_api_route(path, _get_route(fn), methods=["GET"], summary=_summary_of(fn) or path,
                          name=f"GET {path}")
    for path, fn in handlers.ROUTES_POST.items():
        app.add_api_route(path, _post_route(path, fn), methods=["POST"],
                          summary=_summary_of(fn) or path, name=f"POST {path}")

    @app.get("/api/me", summary="Utilisateur connecte, role, jeton CSRF")
    async def me(request: Request) -> JSONResponse:
        u = _user(request)
        return _json({"user": {"id": str(u["id"]), "name": u["name"], "avatar": u.get("avatar")},
                      "role": u["role"], "roleLabel": auth.ROLE_LABEL[u["role"]], "csrf": u["csrf"],
                      "auth": auth.enabled(), "local": bool(u.get("local")),
                      "permissions": auth.permissions(u["role"])})

    # CONNEXION DISCORD
    @app.get("/login", include_in_schema=False)
    async def login(request: Request, error: str = "") -> Response:
        if not auth.enabled() or request.state.user:
            return RedirectResponse("/", 303)
        return login_page(error)

    @app.get("/auth/discord", include_in_schema=False)
    async def auth_start(request: Request) -> Response:
        if not auth.enabled():
            return RedirectResponse("/", 303)
        if not auth.rate_ok("auth", _ip(request)):
            return login_page("busy", status=429)
        state = auth.new_state()
        resp = RedirectResponse(auth.authorize_url(state), 303)
        # Lax : ce cookie doit revenir avec la redirection depuis discord.com (navigation de premier niveau).
        resp.set_cookie(auth.STATE_COOKIE, state, max_age=600, path="/auth", httponly=True,
                        secure=auth.secure_cookies(), samesite="lax")
        return resp

    @app.get("/auth/callback", include_in_schema=False)
    async def auth_callback(request: Request, code: str = "", state: str = "", error: str = "") -> Response:
        if not auth.enabled():
            return RedirectResponse("/", 303)
        if not auth.rate_ok("auth", _ip(request)):
            return login_page("busy", status=429)
        if error:
            return login_page("cancelled")
        expected = request.cookies.get(auth.STATE_COOKIE) or ""
        if not state or not expected or not secrets.compare_digest(state, expected):
            return login_page("expired", status=400)
        try:
            profile = await run_in_threadpool(auth.exchange, code)
        except auth.AuthError:
            return login_page("failed", status=502)
        role = auth.role_for(profile["id"])
        if role is None:
            await run_in_threadpool(_as, f"{profile['name']} ({profile['id']})", db.audit, "login_denied",
                                    str(profile["id"]), {"ip": _ip(request)}, False)
            return login_page(denied_id=profile["id"], status=403)
        token = await run_in_threadpool(auth.create_session, profile, _ip(request),
                                        request.headers.get("user-agent", ""))
        await run_in_threadpool(_as, auth.actor(profile), db.audit, "login", str(profile["id"]),
                                {"role": role, "ip": _ip(request)}, True)
        resp = _bounce("/")
        resp.set_cookie(auth.session_cookie(), token, max_age=auth.ttl_s(), path="/", httponly=True,
                        secure=auth.secure_cookies(), samesite="strict")
        resp.delete_cookie(auth.STATE_COOKIE, path="/auth")
        return resp

    @app.post("/auth/logout", include_in_schema=False)
    async def logout(request: Request) -> Response:
        resp = _json({"ok": True, "login": "/login" if auth.enabled() else None})
        if auth.enabled():
            await run_in_threadpool(auth.end_session, request.cookies.get(auth.session_cookie()))
            resp.delete_cookie(auth.session_cookie(), path="/", secure=auth.secure_cookies(),
                               httponly=True, samesite="strict")
        return resp

    # SONDE ET WEBHOOKS
    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> JSONResponse:
        try:
            db_ok = await run_in_threadpool(db.ping)
        except Exception:                                       # noqa: BLE001
            db_ok = False
        backup = jobs.status().get("lastBackup") or {}
        return _json({"ok": db_ok, "version": VERSION, "uptime": int(time.time() - STARTED),
                      "lastBackup": backup.get("at"), "automations": automations._state.get("lastTick")},
                     200 if db_ok else 503)

    @app.post("/webhooks/roblox", include_in_schema=False)
    async def roblox_webhook(request: Request) -> JSONResponse:
        if not config.ROBLOX_WEBHOOK_SECRET:
            return _json({"error": "Not found"}, 404)
        if not auth.rate_ok("webhook", "roblox"):
            return _json({"error": "Too many requests"}, 429)
        length = request.headers.get("content-length", "")
        if length.isdigit() and int(length) > webhooks.MAX_BODY:
            return _json({"error": "Payload too large"}, 413)
        raw = await request.body()
        try:
            res = await run_in_threadpool(_as, "webhook", webhooks.receive, raw,
                                          request.headers.get("roblox-signature", ""))
        except webhooks.Rejected as exc:
            return _json({"error": str(exc)}, 401)
        return _json(res)

    # INTERFACE
    web = config.WEB_DIR.resolve()

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon() -> Response:
        return Response(status_code=204)

    @app.get("/{path:path}", include_in_schema=False)
    async def static(path: str) -> Response:
        # Interface : fichiers de web/ seulement, jamais au-dela (garde anti-traversee).
        if path.startswith("api/"):
            return _json({"error": "Route inconnue."}, 404)
        target = (web / (path or "index.html")).resolve()
        if not target.is_relative_to(web) or not target.is_file():
            return Response("Not found", status_code=404)
        return FileResponse(target, headers={"Cache-Control": "no-store"})

    return app


app = create_app()
