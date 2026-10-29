"""
Automatisations (§6.7 du plan) : faire partir seules les publications d'une carte.

Tout est MANUEL par defaut. Pour chaque regle, l'ecran Automatisations regle :
  * le mode : manuel, auto avec delai (annulable depuis l'Accueil), auto immediat ;
  * le delai (0 a 120 min) compte depuis la PREMIERE apparition de la carte, jamais repousse ;
  * les sous-actions autorisees (annonce globale, annonces de faction, notification...).
Reglages communs : heures calmes (rien ne part seul dans la plage ; l'envoi attend la fin)
et l'interrupteur « tout en manuel », qui annule aussi ce qui etait prevu.

Seules les actions de PUBLICATION (modele Discord, annonces de faction) et de
NOTIFICATION des cartes listees ci-dessous sont automatisables. Wipe, ban, redemarrage,
effacement RTBF et retrait d'objet ne le sont jamais : ils ne figurent dans aucune regle.

Une action automatique suit exactement le chemin du clic (core/handlers.py), avec
l'auteur « auto » au journal. Si elle echoue, elle n'est pas retentee : la carte la
repropose en manuel avec l'erreur, et #ops-log est prevenu.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Any

from . import db, discord_api, notify, roblox_api

TICK_S = 60
MAX_DELAY_MIN = 120

RULES: list[dict] = [
    {"id": "season_j1", "prefix": "fw_j1", "label": "Veille de fin de saison",
     "when": "24 h avant la clôture de la saison",
     "actions": {"template:ranked_incoming": "Annonce du versement ranked",
                 "notify:SEASON_ENDING": "Notification aux joueurs absents"}},
    {"id": "season_result", "prefix": "fw_result", "label": "Fin de saison",
     "when": "dès que la saison est close et archivée",
     "actions": {"faction_announce": "Annonces des deux factions",
                 "template:factionwar_result": "Résultat global",
                 "notify:SEASON_RESULT": "Notification aux joueurs"}},
    {"id": "ranked_result", "prefix": "ranked_top", "label": "Versement ranked",
     "when": "dès que le versement de la saison est créé",
     "actions": {"template:ranked": "Top 10 ranked",
                 "notify:RANKED_REWARD": "Notification au top ranked"}},
    {"id": "boost_end", "prefix": "boost_end", "label": "Fin de boost",
     "when": "à la fin d'un boost", "actions": {"template:boost_end": "Annonce de fin"}},
    {"id": "event_live", "prefix": "event_live", "label": "Événement en cours",
     "when": "boost ou OPERATIONS ouvert", "actions": {"notify:EVENT_LIVE": "Notification aux absents"}},
    {"id": "comeback", "prefix": "comeback", "label": "Relance hebdomadaire",
     "when": "une fois par semaine", "actions": {"notify:COMEBACK": "Relance des inactifs"}},
    {"id": "schedule", "prefix": "schedule", "label": "Annonces planifiées",
     "when": "à l'heure prévue dans le Planificateur", "actions": {"template:*": "Annonce prévue"}},
]
RULE_BY_PREFIX = {r["prefix"]: r for r in RULES}
RULE_BY_ID = {r["id"]: r for r in RULES}
MODES = ("manual", "delay", "auto")
GLOBAL = "_global"

_state: dict[str, Any] = {"started": False, "lastTick": 0, "lastError": None}


# REGLAGES ------------------------------------------------------------------------------
def default_rule(rule: dict) -> dict:
    return {"mode": "manual", "delay": 15, "actions": list(rule["actions"])}


def load() -> dict:
    raw = db.automation_configs()
    g = raw.get(GLOBAL) or {}
    out = {GLOBAL: {"allManual": bool(g.get("allManual", False)),
                    "quietStart": str(g.get("quietStart") or ""), "quietEnd": str(g.get("quietEnd") or ""),
                    "opsLog": bool(g.get("opsLog", True))}}
    for r in RULES:
        c = {**default_rule(r), **{k: v for k, v in (raw.get(r["id"]) or {}).items() if not k.startswith("_")}}
        c["actions"] = [a for a in c.get("actions") or [] if a in r["actions"]]
        c["_at"], c["_by"] = (raw.get(r["id"]) or {}).get("_at"), (raw.get(r["id"]) or {}).get("_by")
        out[r["id"]] = c
    return out


def _hhmm(v) -> str:
    s = str(v or "").strip()
    if not s:
        return ""
    try:
        return datetime.strptime(s, "%H:%M").strftime("%H:%M")
    except ValueError as exc:
        raise ValueError(f"Heure invalide : {s} (format HH:MM).") from exc


def save(rule_id: str, cfg: dict) -> dict:
    if rule_id == GLOBAL:
        clean = {"allManual": bool(cfg.get("allManual")), "quietStart": _hhmm(cfg.get("quietStart")),
                 "quietEnd": _hhmm(cfg.get("quietEnd")), "opsLog": bool(cfg.get("opsLog", True))}
        if bool(clean["quietStart"]) != bool(clean["quietEnd"]):
            raise ValueError("Heures calmes : donne le début ET la fin, ou aucun des deux.")
        db.set_automation(GLOBAL, clean)
        cancelled = db.cancel_planned_runs() if clean["allManual"] else 0
        db.audit("automation", GLOBAL, {**clean, "cancelled": cancelled}, True)
        return overview()
    rule = RULE_BY_ID.get(rule_id)
    if not rule:
        raise ValueError("Règle inconnue.")
    mode = str(cfg.get("mode") or "manual")
    if mode not in MODES:
        raise ValueError("Mode inconnu.")
    raw_delay = cfg.get("delay")
    try:
        delay = int(str(raw_delay)) if raw_delay not in (None, "") else 15
    except (TypeError, ValueError) as exc:
        raise ValueError("Délai invalide.") from exc
    if not 0 <= delay <= MAX_DELAY_MIN:
        raise ValueError(f"Délai entre 0 et {MAX_DELAY_MIN} minutes.")
    actions = [a for a in (cfg.get("actions") or []) if a in rule["actions"]]
    if mode != "manual" and not actions:
        raise ValueError("Coche au moins une action, ou laisse la règle en manuel.")
    clean = {"mode": mode, "delay": delay, "actions": actions}
    db.set_automation(rule_id, clean)
    db.audit("automation", rule_id, clean, True)
    return overview()


def overview() -> dict:
    cfg = load()
    runs = sorted(db.auto_runs().values(), key=lambda r: -(r.get("done_at") or r["first_seen"]))[:30]
    return {"global": cfg[GLOBAL], "maxDelay": MAX_DELAY_MIN,
            "rules": [{**{k: r[k] for k in ("id", "label", "when", "actions")}, "config": cfg[r["id"]]} for r in RULES],
            "runs": runs, "engine": {**_state}}


# MOTEUR --------------------------------------------------------------------------------
def rule_for(card_key: str) -> dict | None:
    return RULE_BY_PREFIX.get(card_key.split(":", 1)[0])


def action_key(action: dict) -> str | None:
    if action.get("kind") == "notify":
        return f"notify:{action.get('notify')}"
    if action.get("kind") == "publish":
        return action["id"]
    return None


def _allowed(rule: dict, cfg: dict, action: dict) -> bool:
    k = action_key(action)
    if not k:
        return False
    if rule["id"] == "schedule":
        return k.startswith("template:") and "template:*" in cfg["actions"]
    return k in cfg["actions"]


def in_quiet(now: int, start: str, end: str) -> bool:
    if not start or not end:
        return False
    t = datetime.fromtimestamp(now, roblox_api.FW_TIMEZONE).strftime("%H:%M")
    return start <= t < end if start <= end else (t >= start or t < end)


def annotate(cards: list[dict], now: int | None = None) -> None:
    """Ajoute a chaque action automatisable son etat (prevue a, partie, echec, annulee)."""
    now = int(time.time()) if now is None else now
    cfg = load()
    runs = db.auto_runs()
    for c in cards:
        rule = rule_for(c["key"])
        for a in c["actions"]:
            run = runs.get((c["key"], a["id"]))
            if run:
                a["auto"] = {"state": run["state"], "due": run["due"], "error": run["error"], "by": run["by"]}
            elif rule and not cfg[GLOBAL]["allManual"] and cfg[rule["id"]]["mode"] != "manual" \
                    and _allowed(rule, cfg[rule["id"]], a) and not a.get("done"):
                a["auto"] = {"state": "pending", "due": None}


def _execute(card: dict, action: dict) -> tuple[bool, str | None]:
    from . import handlers  # import tardif : handlers importe ce module
    body = {"key": card["key"], "action": action["id"]}
    if action["kind"] == "notify":
        res = handlers.api_notify_send({"card": card["key"], "action": action["id"]})
        return bool(res.get("campaign")), None
    res = handlers.api_cards_act(body)
    return bool(res.get("ok")), None if res.get("ok") else "Envoi partiel ou refusé (voir le Journal)."


def tick(now: int | None = None, visible: list[dict] | None = None) -> list[dict]:
    """Un passage : planifie les actions nouvelles, execute celles qui sont dues."""
    from . import cards
    now = int(time.time()) if now is None else now
    cfg = load()
    g = cfg[GLOBAL]
    if g["allManual"] or all(cfg[r["id"]]["mode"] == "manual" for r in RULES):
        return []                                # rien d'actif : pas une seule lecture Open Cloud
    if visible is None:
        visible = cards.overview()["cards"]      # cache de 30 s de l'Accueil, partage avec la page
    done: list[dict] = []
    token = db.ACTOR.set("auto")
    try:
        for card in visible:
            rule = rule_for(card["key"])
            if not rule:
                continue
            rc = cfg[rule["id"]]
            if rc["mode"] == "manual":
                continue
            for action in card["actions"]:
                if action.get("done") or not _allowed(rule, rc, action):
                    continue
                delay = rc["delay"] * 60 if rc["mode"] == "delay" else 0
                run = db.plan_auto_run(card["key"], action["id"], rule["id"], now + delay)
                if run["state"] != "planned" or now < run["due"] or in_quiet(now, g["quietStart"], g["quietEnd"]):
                    continue
                if action["kind"] == "notify" and notify._running():
                    continue                     # une campagne a la fois : on reessaie au prochain passage
                try:
                    ok, err = _execute(card, action)
                except Exception as exc:          # noqa: BLE001
                    ok, err = False, str(exc)
                db.set_auto_run(card["key"], action["id"], "done" if ok else "failed", err, "auto")
                done.append({"card": card["key"], "action": action["id"], "ok": ok, "error": err})
                if not ok:
                    db.audit("auto_failed", card["key"], {"action": action["id"], "error": (err or "")[:200]},
                             False, card["key"])
                if g["opsLog"]:
                    discord_api.post_ops_log(
                        "Automatisation" if ok else "Automatisation en échec",
                        f"{card['title']} : {action['label']}" + ("" if ok else f"\n{err}\nÀ refaire à la main "
                                                                   "depuis l'Accueil."),
                        0x4FA874 if ok else 0xD9534A)
    finally:
        db.ACTOR.reset(token)
    return done


def cancel(card: str, action: str) -> dict:
    run = db.auto_runs().get((card, action))
    if not run or run["state"] != "planned":
        raise ValueError("Rien de prévu pour cette action.")
    db.set_auto_run(card, action, "cancelled", None, db.ACTOR.get())
    db.audit("automation_cancel", card, {"action": action}, True, card)
    return {"ok": True}


# FIL DE FOND ---------------------------------------------------------------------------
def _loop() -> None:
    from . import jobs
    while True:
        try:
            tick()
            _state.update(lastTick=int(time.time()), lastError=None)
        except Exception as exc:                  # noqa: BLE001
            _state.update(lastTick=int(time.time()), lastError=str(exc)[:200])
        jobs.daily()
        time.sleep(TICK_S)


def start() -> bool:
    if _state["started"]:
        return False
    _state["started"] = True
    threading.Thread(target=_loop, name="cc-automations", daemon=True).start()
    return True
