"""
Couche HTTP du Command Center (FastAPI).

Les routes sont celles de `core/handlers.py`, a l'identique : memes chemins, memes corps,
meme format d'erreur (`500 {"error": message}`), meme journal d'audit. Les handlers sont
synchrones (Open Cloud et Discord en HTTP bloquant) : FastAPI les execute dans son pool de
threads, la boucle asyncio reste libre pour le bot Discord et les autres requetes.

Au demarrage (lifespan) : cloture des campagnes de notifications
interrompues, veilleur live, et bot Discord dans le meme processus si CC_BOT=1.

Documentation interactive de l'API : /api/docs (OpenAPI genere par FastAPI).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator, Callable
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, Response

from core import config, db, handlers, watch

log = logging.getLogger("cc")


def _json(payload, status: int = 200) -> JSONResponse:
    return JSONResponse(payload, status_code=status, headers={"Cache-Control": "no-store"})


def _get_route(fn: Callable[[dict], dict]):
    async def endpoint(request: Request) -> JSONResponse:
        # Meme forme que l'ancien serveur : {cle: [valeurs]} (urllib.parse.parse_qs).
        query = parse_qs(request.url.query, keep_blank_values=True)
        try:
            return _json(await run_in_threadpool(fn, query))
        except Exception as exc:                                # noqa: BLE001
            return _json({"error": str(exc)}, 500)
    return endpoint


def _post_route(path: str, fn: Callable[[dict], dict]):
    action = handlers.AUDITED_POST.get(path)

    async def endpoint(request: Request) -> JSONResponse:
        body: dict = {}
        try:
            raw = await request.body()
            body = json.loads(raw or b"{}")
            if not isinstance(body, dict):
                raise ValueError("Corps JSON attendu : un objet.")
            result = await run_in_threadpool(fn, body)
            if action:
                ok = not (isinstance(result, dict) and result.get("ok") is False)
                await run_in_threadpool(handlers._audit_safe, action, handlers._summary(body), ok)
            return _json(result)
        except Exception as exc:                                # noqa: BLE001
            if action:
                await run_in_threadpool(handlers._audit_safe, action,
                                        {**handlers._summary(body), "error": str(exc)[:200]}, False)
            return _json({"error": str(exc)}, 500)
    return endpoint


def _summary_of(fn: Callable) -> str:
    doc = (fn.__doc__ or "").strip().splitlines()
    return doc[0] if doc else ""


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    try:
        db.close_stale_campaigns()
    except Exception:                                           # noqa: BLE001
        pass
    if config.WATCH and watch.start():
        log.info("Veilleur live actif.")
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
    app = FastAPI(title="Shroud War Command Center", version="0.6.0", lifespan=lifespan,
                  docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json")
    for path, fn in handlers.ROUTES_GET.items():
        app.add_api_route(path, _get_route(fn), methods=["GET"], summary=_summary_of(fn) or path,
                          name=f"GET {path}")
    for path, fn in handlers.ROUTES_POST.items():
        app.add_api_route(path, _post_route(path, fn), methods=["POST"],
                          summary=_summary_of(fn) or path, name=f"POST {path}")

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

