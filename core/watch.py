"""
Veilleur live : transforme les lectures successives du registre en EVENEMENTS.

Tant que le Command Center tourne, un fil relit le registre `CC_Servers_V1` toutes les
20 s (3 appels Open Cloud par minute) et compare avec la lecture precedente :

  start      un serveur apparait
  stop       un serveur disparait alors qu'il battait encore : fermeture propre
             (CommandCenterBridge retire son entree dans BindToClose)
  crash      un serveur est toujours liste mais ne bat plus depuis 75 s : crash ou gel.
             Une fermeture propre ne passe JAMAIS par cet etat, c'est ce qui les distingue.
  recovered  un serveur signale « crash » rebat : c'etait un gel
  lag        FPS serveur sous 30 sur deux lectures de suite
  versions   des serveurs tournent sur des versions de place differentes
  unbridged  la liste publique Roblox montre un Hub absent du registre : ce serveur
             tourne une version sans CommandCenterBridge

  discord    le limiteur DiscordFeed d'un serveur a abandonne des messages (rafale d'un
             joueur ou d'un type), ou Discord en a refuse : au plus un evenement par
             serveur toutes les 10 min, avec le detail
  errors     un serveur a produit beaucoup d'erreurs de script en une minute (champ `err`
             du battement) ; aussi enregistre comme evenement `error_spike` pour l'Accueil
  game       evenement recu du jeu par le bus CC_Events_V1 (core/events.py) : fin de
             saison, versement ranked, sanction, anticheat, piege, avis negatif
  roblox_crash  Roblox (Analytics) a compte des crashs serveur, avec leur CAUSE
                (CrashType), par place et a la minute. Lu toutes les 5 min.

QUI PREVIENT DISCORD. Le veilleur elu DANS LE JEU (CommandCenterBridge) signale les serveurs
muets dans #ops-log et marque l'entree `crashReportedAt`, meme CC eteint. Le CC ne poste
lui-meme que si, 150 s apres le dernier signal, aucun veilleur du jeu ne l'a fait (cas d'un
serveur seul qui tombe : il n'y a plus personne pour veiller). Les tendances globales
(FPS, memoire, crash client) partent dans Discord via les alertes Roblox, configurees dans
le Creator Hub. Aucune source n'alerte deux fois pour le meme crash.

Le journal (300 derniers evenements) et la courbe des joueurs (24 h, un point par minute)
sont gardes dans data/ pour survivre a un redemarrage du CC.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from datetime import datetime

from . import analytics, config, db, discord_api, events, live, roblox_api

INTERVAL_S = 20
CC_ALERT_AFTER_S = 150          # le CC ne poste dans Discord qu'en dernier recours
ANALYTICS_EVERY_TICKS = 15      # 15 x 20 s = 5 min entre deux lectures Analytics
LOW_FPS = 30
MAX_EVENTS = 300
MAX_POINTS = 1440                    # 24 h a un point par minute
EVENTS_FILE = config.DATA_DIR / "live_events.json"
TIMELINE_FILE = config.DATA_DIR / "live_timeline.json"

_lock = threading.Lock()
_state: dict = {"known": {}, "events": [], "timeline": [], "seeded": False,
                "lastTick": 0, "lastError": None, "running": False, "nextId": 1,
                "versionsSig": "", "unbridged": set(), "robloxSeen": set(),
                "analyticsError": None, "analyticsAt": 0, "ticks": 0}


def _load(path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return fallback


def _save(path, data) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass                         # journal de confort : jamais bloquant


def _restore() -> None:
    events = _load(EVENTS_FILE, [])
    _state["events"] = events if isinstance(events, list) else []
    _state["nextId"] = max([int(e.get("id", 0)) for e in _state["events"]] + [0]) + 1
    timeline = _load(TIMELINE_FILE, [])
    _state["timeline"] = timeline if isinstance(timeline, list) else []
    # Les crashs Roblox deja journalises ne sont pas reemis apres un redemarrage du CC.
    _state["robloxSeen"] = {e["key"] for e in _state["events"] if e.get("key")}


def _label(srv: dict) -> str:
    if srv.get("kind") == "hub":
        return "Hub"
    mode = srv.get("mode") or "Match"
    return f"{mode} sur {srv['map']}" if srv.get("map") else str(mode)


def _emit(kind: str, level: str, text: str, srv: dict | None = None, notify: bool = False):
    event = {"id": _state["nextId"], "at": int(time.time()), "kind": kind, "level": level,
             "text": text}
    _state["nextId"] += 1
    if srv:
        event.update(jobId=srv.get("jobId"), server=_label(srv),
                     players=len(srv.get("players") or []))
    _state["events"].append(event)
    del _state["events"][:-MAX_EVENTS]
    if notify:
        threading.Thread(target=discord_api.post_ops_log,
                         args=(f"Serveur : {kind}", text, 0xD9534A), daemon=True).start()
    return event


def public_hub_servers() -> list[dict]:
    """Serveurs publics du Hub selon Roblox (sans cle). Les matchs, prives, n'y sont pas."""
    url = (f"https://games.roblox.com/v1/games/{config.ROBLOX_PLACE_ID}/servers/Public"
           "?limit=100&excludeFullGames=false")
    req = urllib.request.Request(url, headers={"User-Agent": "CommandCenter"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return [s for s in data.get("data") or [] if isinstance(s, dict)]


DISCORD_EVENT_EVERY_S = 600
ERROR_SPIKE_N = 20               # erreurs de script en une minute sur un serveur
ERROR_EVENT_EVERY_S = 600


def _error_spike(srv: dict, prev: dict, label: str, now: int) -> None:
    """Le battement porte les erreurs de la derniere minute complete (`err`)."""
    err = srv.get("err")
    if not isinstance(err, dict) or int(err.get("n") or 0) < ERROR_SPIKE_N:
        return
    if err.get("at") == prev.get("errAt") or now - prev.get("errEventAt", 0) < ERROR_EVENT_EVERY_S:
        return
    prev["errAt"], prev["errEventAt"] = err.get("at"), now
    where = err.get("s") or "?"
    _emit("errors", "warn", f"{label} : {err.get('n')} erreurs de script en une minute, surtout "
          f"dans {where}. Dernier message : {err.get('m') or '?'}", srv)
    db.add_events([{"id": f"error_spike:{srv.get('jobId')}:{err.get('at')}", "type": "error_spike",
                    "at": int(err.get("at") or now), "job": str(srv.get("jobId") or "")[:8],
                    "place": srv.get("kind"),
                    "data": {"n": err.get("n"), "script": where, "message": err.get("m"),
                             "server": label}}])


def _discord_losses(srv: dict, prev: dict, label: str, now: int) -> None:
    """Pertes du limiteur DiscordFeed (compteurs cumules du serveur : d abandonnes,
    f refuses par Discord). On signale la HAUSSE, au plus une fois par 10 min et par serveur."""
    d = srv.get("discord")
    if not isinstance(d, dict):
        return
    lost = int(d.get("d") or 0) + int(d.get("f") or 0)
    seen = prev.get("discordLost")
    prev.setdefault("discordLost", lost)
    if seen is None or lost <= seen or now - prev.get("discordAt", 0) < DISCORD_EVENT_EVERY_S:
        return
    prev["discordLost"], prev["discordAt"] = lost, now
    _emit("discord", "warn",
          f"{label} : {lost - seen} message(s) Discord perdu(s) depuis la dernière alerte "
          f"({int(d.get('d') or 0)} abandonnés par le limiteur, {int(d.get('f') or 0)} refusés "
          f"par Discord depuis le démarrage). Une rafale d'un joueur ou d'un type de message : "
          f"voir la sortie du serveur.", srv)


def tick(now: int | None = None, public: list[dict] | None = None) -> None:
    """Une lecture du registre et ses evenements. Testable : `now` et `public` injectables."""
    data = live.servers(force=True)
    now = int(time.time() if now is None else now)
    with _lock:
        _state["lastTick"] = now
        _state["lastError"] = data.get("error")
        if data.get("error"):
            return
        servers = {s["jobId"]: s for s in data["servers"] if s.get("jobId")}
        known = _state["known"]
        seeded = _state["seeded"]

        for job_id, srv in servers.items():
            prev = known.get(job_id)
            label = _label(srv)
            if prev is None:
                if seeded and not srv["stale"]:
                    _emit("start", "info", f"{label} démarré", srv)
                known[job_id] = {"stale": srv["stale"], "lowFps": 0, "lagging": False}
                prev = known[job_id]
            elif srv["stale"] and not prev["stale"]:
                silent = now - int(srv.get("hb") or now)
                by_game = " Signalé dans #ops-log par le veilleur du jeu." if srv.get("crashReportedAt") else ""
                _emit("crash", "crit",
                      f"{label} ne répond plus depuis {silent} s, avec "
                      f"{len(srv['players'])} joueur(s) au dernier signal. Crash ou gel du serveur.{by_game}",
                      srv)
                prev["discordDone"] = bool(srv.get("crashReportedAt"))
            elif prev["stale"] and not srv["stale"]:
                _emit("recovered", "warn", f"{label} répond de nouveau : c'était un gel.", srv)
            prev["stale"] = srv["stale"]

            # Dernier recours Discord : aucun veilleur du jeu n'a marque ce serveur.
            if srv["stale"] and not prev.get("discordDone"):
                silent = now - int(srv.get("hb") or now)
                if srv.get("crashReportedAt"):
                    prev["discordDone"] = True
                elif silent >= CC_ALERT_AFTER_S:
                    prev["discordDone"] = True
                    threading.Thread(target=discord_api.post_ops_log, daemon=True, args=(
                        f"Serveur muet : {label}",
                        f"Plus de signal depuis {silent} s, {len(srv['players'])} joueur(s) au "
                        f"dernier battement. Aucun veilleur du jeu actif : signalé par le Command "
                        f"Center.\nServeur `{job_id}`.", 0xD9534A)).start()

            fps = srv.get("fps")
            low = isinstance(fps, (int, float)) and fps < LOW_FPS and not srv["stale"]
            prev["lowFps"] = prev["lowFps"] + 1 if low else 0
            if prev["lowFps"] >= 2 and not prev["lagging"]:
                prev["lagging"] = True
                _emit("lag", "warn", f"{label} rame : {fps} FPS serveur.", srv)
            elif not low and prev["lagging"]:
                prev["lagging"] = False

            _discord_losses(srv, prev, label, now)
            _error_spike(srv, prev, label, now)

        for job_id in [j for j in known if j not in servers]:
            prev = known.pop(job_id)
            if seeded and not prev["stale"]:
                _emit("stop", "info", "Serveur fermé proprement.", {"jobId": job_id})

        versions = data["summary"].get("placeVersions") or []
        sig = ",".join(map(str, versions))
        if len(versions) > 1 and sig != _state["versionsSig"]:
            _emit("versions", "warn",
                  f"Versions de place mélangées ({sig}) : des serveurs tournent sur l'ancienne "
                  "version. Redémarre-les pour que tout le monde ait la mise à jour.")
        _state["versionsSig"] = sig

        if public is not None:
            for s in public:
                sid = s.get("id")
                if sid and sid not in servers and sid not in _state["unbridged"]:
                    _state["unbridged"].add(sid)
                    _emit("unbridged", "warn",
                          f"Hub sans pont : Roblox liste un serveur ({s.get('playing', 0)} "
                          "joueur(s)) absent du registre. Il tourne une version sans "
                          "CommandCenterBridge.", {"jobId": sid, "kind": "hub",
                                                   "players": [None] * int(s.get("playing") or 0)})

        _state["seeded"] = True

        # Courbe : un point par minute (le dernier point de la minute fait foi).
        point = {"at": now - now % 60, "hub": data["summary"].get("hubPlayers", 0),
                 "match": data["summary"].get("matchPlayers", 0),
                 "servers": data["summary"].get("hubs", 0) + data["summary"].get("matches", 0)}
        timeline = _state["timeline"]
        if timeline and timeline[-1].get("at") == point["at"]:
            timeline[-1] = point
        else:
            timeline.append(point)
        del timeline[:-MAX_POINTS]
        events_copy = list(_state["events"])
        timeline_copy = list(timeline)
    _save(EVENTS_FILE, events_copy)
    _save(TIMELINE_FILE, timeline_copy)


def analytics_tick(crashes: list[dict] | None = None) -> None:
    """Journalise les crashs serveur comptes par Roblox (une fois chacun)."""
    if crashes is None:
        try:
            crashes = analytics.recent_server_crashes(30)
            error = None
        except Exception as exc:                                # noqa: BLE001
            crashes, error = [], str(exc)
    else:
        error = None
    with _lock:
        _state["analyticsError"] = error
        _state["analyticsAt"] = int(time.time())
        for c in sorted(crashes, key=lambda c: c["at"]):
            key = f"rc:{c['at']}:{c['place']}:{c['cause']}"
            if key in _state["robloxSeen"]:
                continue
            _state["robloxSeen"].add(key)
            event = _emit("roblox_crash", "crit",
                          f"Roblox a compté {c['count']} crash(s) serveur sur {c['place']} à "
                          f"{datetime.fromtimestamp(c['at'], roblox_api.FW_TIMEZONE).strftime('%H:%M')}. Cause : {c['cause']}.")
            event["key"] = key
            event["at"] = c["at"]
        events_copy = list(_state["events"])
    _save(EVENTS_FILE, events_copy)


GAME_EVENT_LEVEL = {"honeypot": "crit", "ac_flag": "warn", "sanction": "warn",
                    "feedback": "info", "season_closed": "info", "ranked_payout": "info",
                    "cmd_ack": "info"}


def _game_event_text(e: dict) -> str:
    d = e.get("data") or {}
    t = e["type"]
    if t == "season_closed":
        return f"Saison {int(d.get('week') or 0) + 1} close : {d.get('winner') or '?'} gagne. Carte sur l'Accueil."
    if t == "ranked_payout":
        return f"Versement ranked de la saison {int(d.get('week') or 0) + 1} créé dans le jeu."
    if t == "cmd_ack":
        state = "faite" if d.get("ok") else "refusée"
        return f"Commande {d.get('op') or '?'} {state} par un serveur : {d.get('msg') or ''}".strip()
    title = d.get("title") or events.TYPES.get(t, t)
    return f"{title}. {d.get('text') or ''}".strip()


def game_events_tick() -> list[dict]:
    """Lit le bus d'evenements du jeu et journalise les nouveaux."""
    fresh = events.poll()
    if not fresh:
        return []
    with _lock:
        for e in sorted(fresh, key=lambda e: e["at"]):
            ev = _emit("game", GAME_EVENT_LEVEL.get(e["type"], "info"), _game_event_text(e))
            ev.update(gameType=e["type"], userId=(e.get("data") or {}).get("u"))
        events_copy = list(_state["events"])
    _save(EVENTS_FILE, events_copy)
    return fresh


def _loop() -> None:
    while True:
        with _lock:
            _state["ticks"] += 1
            due = _state["ticks"] % ANALYTICS_EVERY_TICKS == 1
        if due:
            analytics_tick()
        try:
            game_events_tick()
        except Exception as exc:                                # noqa: BLE001
            with _lock:
                _state["lastError"] = str(exc)
        public = None
        try:
            public = public_hub_servers()
        except Exception:                                       # noqa: BLE001
            public = None            # liste publique indisponible : on n'en deduit rien
        try:
            tick(public=public)
        except Exception as exc:                                # noqa: BLE001
            with _lock:
                _state["lastError"] = str(exc)
        time.sleep(INTERVAL_S)


def start() -> bool:
    """Demarre le veilleur une seule fois. Sans cle Open Cloud, il ne demarre pas."""
    with _lock:
        if _state["running"] or not config.ROBLOX_OPENCLOUD_KEY:
            return _state["running"]
        _state["running"] = True
    _restore()
    threading.Thread(target=_loop, name="live-watch", daemon=True).start()
    return True


def snapshot(since: int = 0) -> dict:
    """Evenements posterieurs a `since`, courbe et etat du veilleur."""
    with _lock:
        return {
            "events": [e for e in _state["events"] if int(e["id"]) > since],
            "timeline": list(_state["timeline"]),
            "watcher": {"running": _state["running"], "lastTick": _state["lastTick"],
                        "interval": INTERVAL_S, "lastError": _state["lastError"],
                        "analyticsError": _state["analyticsError"],
                        "analyticsAt": _state["analyticsAt"],
                        "gameEvents": events.status()},
        }
