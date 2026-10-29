"""
Analytics Roblox (Open Cloud, Analytics Query API) : ce que ROBLOX mesure, sans rien
couter aux serveurs du jeu.

Le registre live (core/live.py) dit ce que fait CHAQUE serveur, en direct, mais seulement
pour les serveurs qui battent. Les Analytics disent ce que Roblox a mesure sur TOUTE
l'experience, par place : pic de joueurs, crashs serveur avec leur cause (CrashType),
FPS, memoire et CPU serveur, crashs client, erreurs DataStore, joueurs actifs, revenus.
Les deux se completent : un crash vu ici a une cause, un crash vu dans le registre a un
serveur et des joueurs.

Fonctionnement de l'API : POST d'une requete, puis attente de son resultat (operation).
Limite : 30 requetes par minute et par cle. Le CC regroupe ses requetes (vue Tendances,
cache 5 min) et le veilleur n'interroge que les crashs serveur, toutes les 5 min.

Droit de cle : « Analytics → Read » (universe.analytics:read) sur l'experience.
Les metriques de performance demandent environ 100 joueurs actifs par jour : en dessous,
Roblox renvoie des series vides ou une erreur, affichee telle quelle.
Reference : create.roblox.com/docs/cloud/guides/analytics/metrics
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from . import config

BASE = "https://apis.roblox.com/analytics-query-api"
CACHE_S = 300
POLL_MAX = 20
POLL_STEP_S = 0.6

_lock = threading.Lock()
_cache: dict = {}


class AnalyticsError(Exception):
    """Erreur lisible (droit manquant, eligibilite, quota)."""


def _request(method: str, url: str, body: dict | None = None) -> tuple[int, dict]:
    if not config.ROBLOX_OPENCLOUD_KEY:
        raise AnalyticsError("ROBLOX_OPENCLOUD_KEY absent (voir .env).")
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "x-api-key": config.ROBLOX_OPENCLOUD_KEY, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        if exc.code in (401, 403):
            raise AnalyticsError("Droit « Analytics → Read » absent de la clé Open Cloud "
                                 f"(HTTP {exc.code}).") from exc
        if exc.code == 429:
            raise AnalyticsError("Quota Analytics atteint (30 requêtes par minute).") from exc
        raise AnalyticsError(f"HTTP {exc.code} : {detail}") from exc
    except urllib.error.URLError as exc:
        raise AnalyticsError(f"Réseau indisponible : {exc.reason}") from exc


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def query(metric: str, granularity: str, start: datetime, end: datetime,
          breakdown: list[str] | None = None) -> list[dict]:
    """Une metrique, en series. -> [{ "key": {dimension: valeur}, "points": [(ts, v)] }]"""
    body: dict = {"metric": metric, "granularity": granularity,
            "startTime": _iso(start), "endTime": _iso(end)}
    if breakdown:
        body["breakdown"] = breakdown
    _, res = _request("POST", f"{BASE}/v1/universes/{config.ROBLOX_UNIVERSE_ID}/metrics", body)
    polls = 0
    while not res.get("done"):
        polls += 1
        if polls > POLL_MAX or not res.get("path"):
            raise AnalyticsError(f"{metric} : résultat toujours en préparation chez Roblox.")
        time.sleep(POLL_STEP_S)
        _, res = _request("GET", f"{BASE}/{res['path'].lstrip('/')}")
    if res.get("error"):
        err = res["error"]
        raise AnalyticsError(f"{metric} : {err.get('message') or err.get('code') or err}")
    series = []
    for value in (res.get("response") or {}).get("values") or []:
        key = {}
        for b in value.get("breakdowns") or []:
            if isinstance(b, dict):
                key[str(b.get("dimension") or b.get("name") or "?")] = str(b.get("value"))
        points = []
        for p in value.get("dataPoints") or []:
            try:
                ts = int(datetime.fromisoformat(str(p["time"]).replace("Z", "+00:00")).timestamp())
                points.append((ts, float(p.get("value") or 0)))
            except (KeyError, ValueError, TypeError):
                continue
        series.append({"key": key, "points": sorted(points)})
    return series


def _place_label(value: str) -> str:
    if value == str(config.ROBLOX_PLACE_ID):
        return "Hub"
    if value == str(config.ROBLOX_GAME_PLACE_ID):
        return "Matchs"
    return value


def _labelled(series: list[dict], dim: str = "Place") -> list[dict]:
    out = []
    for s in series:
        raw = s["key"].get(dim)
        out.append({"label": _place_label(raw) if dim == "Place" and raw else (raw or "Total"),
                    "key": s["key"], "points": s["points"]})
    return out


# Ce que l'ecran Tendances affiche : (identifiant, metrique, granularite, decoupage, titre, unite)
PANELS = [
    ("players", "PeakConcurrentPlayers", "HalfHour", ["Place"], "Pic de joueurs connectés", ""),
    ("serverCrashes", "ServerCrashCount", "HalfHour", ["CrashType"], "Crashs serveur, par cause", ""),
    ("serverFps", "ServerFrameRateP10", "HalfHour", ["Place"], "FPS serveur (10 % les plus lents)", "FPS"),
    ("serverMemory", "MemoryUsageP90", "HalfHour", ["Place"], "Mémoire serveur (90e centile)", "Mo"),
    ("serverCpu", "CpuTimeP90", "HalfHour", ["Place"], "CPU serveur (90e centile)", "ms"),
    ("clientCrashes", "ClientCrashRate15m", "HalfHour", ["Place"], "Taux de crash client (15 min)", "%"),
    ("dataStore", "DataStoreRequestsByStatus", "HalfHour", ["DataStoreStatus"], "Requêtes DataStore par statut", ""),
    ("dau", "DailyActiveUsers", "OneDay", None, "Joueurs actifs par jour", ""),
    ("revenue", "DailyRevenue", "OneDay", None, "Revenus par jour", "Robux"),
]


def overview(hours: int = 24, force: bool = False) -> dict:
    """Tous les panneaux, en parallele, caches 5 min. Chaque panneau echoue seul."""
    hours = max(1, min(int(hours or 24), 24 * 28))
    cache_key = f"overview:{hours}"
    with _lock:
        hit = _cache.get(cache_key)
        if hit and not force and time.time() - hit[0] < CACHE_S:
            return hit[1]
    end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start = end - timedelta(hours=hours)
    day_start = (end - timedelta(days=max(14, hours // 24))).replace(hour=0, minute=0)

    def one(panel):
        pid, metric, gran, breakdown, title, unit = panel
        daily = gran == "OneDay"
        g = gran if daily else ("OneHour" if hours > 48 else gran)
        try:
            series = query(metric, g, day_start if daily else start, end, breakdown)
            dim = breakdown[0] if breakdown else "Total"
            return {"id": pid, "title": title, "unit": unit, "metric": metric,
                    "series": _labelled(series, dim), "error": None}
        except Exception as exc:                                # noqa: BLE001
            return {"id": pid, "title": title, "unit": unit, "metric": metric,
                    "series": [], "error": str(exc)}

    # 9 requetes, 3 a la fois : bien sous le quota de 30 par minute.
    with ThreadPoolExecutor(max_workers=3) as pool:
        panels = list(pool.map(one, PANELS))
    result = {"hours": hours, "at": int(time.time()), "panels": panels}
    with _lock:
        _cache[cache_key] = (time.time(), result)
    return result


def recent_server_crashes(minutes: int = 30) -> list[dict]:
    """Crashs serveur des `minutes` dernieres minutes, par place et par cause, a la minute.
    -> [{ "at", "place", "cause", "count" }] (seulement les minutes ou count > 0)"""
    end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start = end - timedelta(minutes=minutes)
    out = []
    for s in query("ServerCrashCount", "OneMinute", start, end, ["Place", "CrashType"]):
        place = _place_label(s["key"].get("Place", "?"))
        cause = s["key"].get("CrashType", "inconnue")
        for ts, value in s["points"]:
            if value > 0:
                out.append({"at": ts, "place": place, "cause": cause, "count": int(value)})
    return out
