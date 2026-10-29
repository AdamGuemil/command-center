"""
Reste a faire : les actions MANUELLES qui attendent le developpeur (Creator Hub, Cloudflare...),
avec, quand c'est possible, une verification automatique qui dit si l'action est faisable
MAINTENANT. Le CC previent au lieu de laisser y penser.

Etats :
  todo     a faire, rien ne bloque
  blocked  pas encore possible ; `detail` dit pourquoi et ce qui debloquera
  ready    debloque depuis peu : c'est le moment
  done     fait (coche a la main, ou constate automatiquement)

Les coches manuelles sont gardees dans data/todo_state.json (local, non versionne).
Les verifications sont cachees 30 min : la plus couteuse est UNE requete Analytics.
Ces taches s'affichent comme cartes « Configuration » de l'Accueil (core/cards.py), a cote
des cartes venues du jeu.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta, timezone

from . import analytics, config, db, notify, roblox_api, watch

STATE_FILE = config.DATA_DIR / "todo_state.json"
CHECK_CACHE_S = 1800
DAU_REQUIRED = 100
VISITS_REQUIRED = 100      # seuil Roblox pour les notifications d'experience

_lock = threading.Lock()
_cache: dict = {"at": 0.0, "checks": {}}


def _dau_check() -> dict:
    """Joueurs actifs par jour sur 7 jours : sert au droit Analytics ET au seuil des alertes."""
    end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    try:
        series = analytics.query("DailyActiveUsers", "OneDay", end - timedelta(days=7), end)
    except analytics.AnalyticsError as exc:
        # permission : True lue, False refusee, None inconnue (cle absente, reseau, quota).
        denied = "Analytics → Read" in str(exc)
        return {"permission": False if denied else None, "error": str(exc), "dauMax": None}
    values = [v for s in series for _, v in s["points"]]
    return {"permission": True, "error": None, "dauMax": int(max(values)) if values else 0}


ITEMS: list[dict] = [
    {
        "id": "analytics_permission",
        "title": "Ajouter « Analytics → Read » à la clé Open Cloud",
        "where": "Creator Hub, Open Cloud, API Keys, ta clé, Edit, Add API System : Analytics, Read.",
        "why": "Ce droit laisse le CC lire ce que Roblox mesure (écran Tendances, crashs serveur "
               "avec leur cause dans le journal Live). La clé ne change pas : rien à toucher dans .env.",
        "auto": True,
    },
    {
        "id": "roblox_alerts",
        "title": "Créer les alertes de performance Roblox",
        "where": "Creator Hub, Shroud War, Configure, Alerts. Destination : le webhook « Custom alerts » "
                 "(salon #roblox-alerts).",
        "why": "Roblox surveille alors les tendances globales et prévient Discord même quand le CC "
               "est éteint. Alertes à créer : pic de joueurs en baisse de plus de 80 % en une heure "
               "(jeu tombé) ; FPS serveur sous 30 pendant 5 min ; mémoire serveur au-dessus de "
               "2 500 Mo (seuil à ajuster d'après Tendances) ; taux de crash client en hausse de "
               "50 % d'un jour à l'autre (mise à jour qui casse le jeu).",
        "auto": False,
    },
    {
        "id": "notif_strings",
        "title": "Créer les 6 textes de notification joueurs",
        "where": "Creator Hub, Shroud War, Engagement, Notifications, « Create a Notification String ». "
                 "Puis, dans la colonne Actions, « Copy Asset ID » et colle-le dans le CC : Diffusion, "
                 "Notifications. Les textes à recopier sont affichés sur cet écran.",
        "why": "Roblox n'a pas d'API pour créer ces textes : sans eux, le CC ne peut prévenir personne hors "
               "du jeu (résultat de saison, récompense ranked, événement, mise à jour, retour des inactifs).",
        "auto": True,
    },
    {
        "id": "notif_permission",
        "title": "Ajouter « User Notifications → Write » à la clé Open Cloud",
        "where": "Creator Hub, Open Cloud, API Keys, ta clé, Edit. Ce droit est dans la partie des droits "
                 "utilisateur, séparée des droits de l'expérience.",
        "why": "C'est le droit qui envoie une notification à un joueur. Le CC ne peut pas le tester sans "
               "envoyer une vraie notification : utilise « Tester sur mon compte » dans Notifications, "
               "la tâche se coche seule au premier envoi réussi.",
        "auto": False,
    },
    {
        "id": "old_webhooks",
        "title": "Retirer les anciens webhooks du Worker Cloudflare",
        "where": "Cloudflare, Workers, hf-webhook-proxy, Settings, Variables : ALLOWED_WEBHOOK_IDS.",
        "why": "Les anciens serveurs (avant le Secrets Store) envoient encore avec les anciens "
               "identifiants. Une fois qu'aucun ne tourne, ne garder que les 4 identifiants des "
               "secrets actuels ferme le proxy aux anciens tokens, qui étaient visibles dans le code.",
        "auto": False,
    },
]


def _load_state() -> dict:
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_FILE)


def _checks(force: bool) -> dict:
    with _lock:
        if not force and time.time() - _cache["at"] < CHECK_CACHE_S and _cache["checks"]:
            return _cache["checks"]
    health = roblox_api.game_health()
    checks = {"dau": _dau_check(), "unbridged": len(watch._state.get("unbridged") or ()),
              "watching": bool(watch._state.get("seeded")),
              "visits": health.get("visits") if health.get("ok") else None}
    with _lock:
        _cache.update(at=time.time(), checks=checks)
    return checks


def _evaluate(item: dict, checks: dict, manual: dict) -> tuple[str, str]:
    dau = checks["dau"]
    iid = item["id"]
    if iid == "analytics_permission":
        if dau["permission"]:
            return "done", "Constaté : la clé lit les Analytics."
        if dau["permission"] is None:
            return "todo", f"Vérification impossible pour l'instant : {dau['error']}"
        return "todo", dau["error"] or ""
    if iid == "notif_strings":
        have = len(notify.configured())
        total = len(notify.CATALOGUE)
        if have >= total:
            return "done", f"Constaté : les {total} Asset IDs sont enregistrés."
        visits = checks.get("visits")
        if visits is not None and visits < VISITS_REQUIRED:
            return "blocked", (f"Roblox n'ouvre les notifications qu'à partir de {VISITS_REQUIRED} visites. "
                               f"Visites actuelles : {visits}. Le CC revérifie toutes les 30 min.")
        return "todo", f"{have}/{total} textes enregistrés dans le CC."
    if iid == "notif_permission" and _notification_delivered():
        return "done", "Constaté : une notification est partie avec cette clé."
    if manual.get(iid):
        return "done", f"Coché le {manual[iid]}."
    if iid == "roblox_alerts":
        if dau["permission"] is False:
            return "blocked", "Il faut d'abord le droit Analytics : sans lui, le CC ne peut pas " \
                              "vérifier le nombre de joueurs."
        if dau["error"]:
            return "todo", f"Joueurs actifs illisibles ({dau['error']}). Roblox exige environ " \
                           f"{DAU_REQUIRED} joueurs actifs par jour pour créer ces alertes."
        if dau["dauMax"] < DAU_REQUIRED:
            return "blocked", (f"Roblox refuse ces alertes sous environ {DAU_REQUIRED} joueurs actifs "
                               f"par jour. Maximum sur 7 jours : {dau['dauMax']}. Le CC revérifie "
                               f"toutes les 30 min et passera cette tâche à « C'est le moment ».")
        return "ready", f"Seuil atteint : {dau['dauMax']} joueurs actifs par jour au maximum sur 7 jours."
    if iid == "old_webhooks":
        if not checks["watching"]:
            return "todo", "Le veilleur Live n'a pas encore lu les serveurs : vérifier avant de retirer."
        if checks["unbridged"]:
            return "blocked", (f"{checks['unbridged']} Hub(s) public(s) tournent encore une version sans "
                               f"pont CC, donc probablement les anciens webhooks. Attendre leur fermeture "
                               f"(ou redémarrer les serveurs).")
        return "ready", "Aucun Hub d'ancienne version vu par le veilleur : possible maintenant. " \
                        "Les serveurs de match privés ne sont pas visibles : attendre une heure après " \
                        "la dernière publication par prudence."
    return "todo", ""


def _notification_delivered() -> bool:
    try:
        with db.connect() as con:
            return con.execute("SELECT 1 FROM notified WHERE status IN ('sent', 'test') LIMIT 1").fetchone() is not None
    except Exception:                                         # noqa: BLE001
        return False


def overview(force: bool = False) -> dict:
    checks = _checks(force)
    manual = _load_state()
    items = []
    for item in ITEMS:
        state, detail = _evaluate(item, checks, manual)
        items.append({**{k: item[k] for k in ("id", "title", "where", "why", "auto")},
                      "state": state, "detail": detail})
    order = {"ready": 0, "todo": 1, "blocked": 2, "done": 3}
    items.sort(key=lambda i: order[i["state"]])
    return {"items": items, "at": int(_cache["at"]),
            "open": sum(i["state"] in ("ready", "todo") for i in items)}


def mark(item_id: str, done: bool) -> dict:
    known = {i["id"]: i for i in ITEMS}
    if item_id not in known or known[item_id]["auto"]:
        raise ValueError("Tâche inconnue ou vérifiée automatiquement.")
    with _lock:
        state = _load_state()
        if done:
            state[item_id] = datetime.now().strftime("%d/%m/%Y")
        else:
            state.pop(item_id, None)
        _save_state(state)
    return overview()
