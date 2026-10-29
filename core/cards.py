"""
Accueil « A faire » : le CC dit quoi faire, et quand.

Une carte est calculee par une FONCTION PURE, `build(state, now)`, a partir d'un etat
collecte ailleurs (`collect()`) : jeu (saison, ranked, boost, modes, versions), evenements
recus du jeu (core/events.py), planificateur, taches manuelles (core/todo.py) et sante du
CC. Testee sans reseau (tests/test_cards.py).

Chaque carte porte une CLE D'IDEMPOTENCE (`fw_result:w7`) :
  * une action faite depuis la carte est journalisee avec cette cle (audit) et la coche ;
    quand toutes ses publications sont faites, la carte se ferme ;
  * « Fait », « Plus tard » et « Ignorer » sont gardes par cle (table cards) ;
  * une carte disparait aussi d'elle-meme quand sa condition n'est plus vraie.

Rien ne part sans clic : une publication passe toujours par un apercu (§4.2 du plan).
Les automatisations (§6.7) viendront avec l'hebergement 24/7 (lot 6).
"""

from __future__ import annotations

import hashlib
import threading
import time
from datetime import datetime

from . import db, discord_api, live, modes, notify, ranked_rewards, roblox_api, store, todo
from . import events as game_events

CACHE_S = 30
RECENT_S = 7 * 86400
RANKED_LATE_S = 30 * 60
PRIO_ORDER = {"crit": 0, "high": 1, "normal": 2, "info": 3}

_lock = threading.Lock()
_cache: dict = {"at": 0.0, "state": None}


def _safe(fn, fallback=None):
    try:
        return fn(), None
    except Exception as exc:                                    # noqa: BLE001
        return fallback, str(exc)


# COLLECTE (impure) -----------------------------------------------------------
def collect(force: bool = False) -> dict:
    with _lock:
        if not force and _cache["state"] and time.time() - _cache["at"] < CACHE_S:
            return _cache["state"]
    errors = {}
    now = int(time.time())
    week = roblox_api.fw_week_index(now)
    start, end = roblox_api.fw_week_bounds(week)

    boost, err = _safe(roblox_api.get_boost)
    if err:
        errors["openCloud"] = err
    discord_ok, err = _safe(lambda: bool(discord_api.get_bot()), False)
    if err:
        errors["discord"] = err
    archive, err = _safe(lambda: roblox_api.faction_war_archive(week - 1))
    if err:
        errors["archive"] = err
    payouts, _ = _safe(ranked_rewards._read_index, [])
    contracts, _ = _safe(lambda: live.contracts().get("issues") or [], [])
    servers, _ = _safe(lambda: live.servers(), {})
    mode_values, _ = _safe(lambda: modes.get().get("values") or {}, {})
    todo_items, _ = _safe(lambda: todo.overview().get("items") or [], [])
    schedule, _ = _safe(store.load_schedule, [])
    templates, _ = _safe(store.load_templates, [])
    recent, _ = _safe(lambda: db.events(tuple(game_events.TYPES), since=now - RECENT_S, limit=300), [])
    notif, _ = _safe(notify.readiness, {"ids": [], "done": [], "lastComeback": 0})

    state = {
        "now": now,
        "season": {"week": week, "startsAt": start, "endsAt": end},
        "openCloudOk": "openCloud" not in errors, "discordOk": bool(discord_ok),
        "errors": errors,
        "boost": boost, "archive": archive, "payouts": payouts or [],
        "contractIssues": contracts or [],
        "placeVersions": (servers or {}).get("summary", {}).get("placeVersions") or [],
        "servers": len([s for s in (servers or {}).get("servers", []) if not s.get("stale")]),
        "operations": (mode_values or {}).get("operations") or {},
        "todo": todo_items or [], "schedule": schedule or [],
        "templates": {t["id"]: t.get("name") or t["id"] for t in templates or []},
        "events": recent or [],
        "notify": notif or {"ids": [], "done": [], "lastComeback": 0},
    }
    with _lock:
        _cache.update(at=time.time(), state=state)
    return state


# CARTES (pures) --------------------------------------------------------------
def _fmt_when(ts: int) -> str:
    return datetime.fromtimestamp(ts, roblox_api.FW_TIMEZONE).strftime("%d/%m à %H:%M")


def _card(key, prio, category, title, context="", actions=None, at=None, due=None, **extra):
    return {"key": key, "prio": prio, "category": category, "title": title, "context": context,
            "actions": actions or [], "at": at, "due": due, **extra}


def go(label, href):
    return {"id": f"go:{href}", "kind": "go", "label": label, "href": href}


def publish(label, template_id):
    return {"id": f"template:{template_id}", "kind": "publish", "label": label, "template": template_id}


def notify_action(s: dict, key: str, ref: str, params: dict | None = None):
    """Bouton « Notifier les joueurs » : seulement si le texte est cree dans le Creator Hub."""
    n = s.get("notify") or {}
    if key not in (n.get("ids") or []):
        return None
    label = {"RANKED_REWARD": "Notifier le top ranked", "SEASON_RESULT": "Notifier les joueurs",
             "SEASON_ENDING": "Notifier les absents", "EVENT_LIVE": "Notifier les absents",
             "COMEBACK": "Relancer les inactifs"}.get(key, "Notifier les joueurs")
    return {"id": f"notify:{key}", "kind": "notify", "label": label, "notify": key, "ref": ref,
            "params": params or {}, "done": f"{key}|{ref}" in (n.get("done") or [])}


def _acts(*actions):
    return [a for a in actions if a]


def build(s: dict, now: int) -> list[dict]:
    cards: list[dict] = []
    week = s["season"]["week"]
    season_label = week + 1

    # Sante du CC
    if not s["openCloudOk"]:
        cards.append(_card("cc:opencloud", "crit", "Système", "Le CC ne peut ni lire ni écrire dans le jeu",
                           s["errors"].get("openCloud", ""), [go("Tester les permissions", "#health")]))
    if not s["discordOk"]:
        cards.append(_card("cc:discord", "high", "Système", "Discord injoignable : aucune annonce ne partira",
                           s["errors"].get("discord", "Bot Discord indisponible."), [go("Voir Santé", "#health")]))
    # Sans Open Cloud, les contrats sont illisibles : la carte Open Cloud suffit.
    for issue in (s["contractIssues"] if s["openCloudOk"] else []):
        digest = hashlib.sha1(str(issue).encode("utf-8")).hexdigest()[:10]
        cards.append(_card(f"contract:{digest}", "crit", "Système",
                           "Contrat du jeu incohérent", str(issue), [go("Voir Live", "#live")]))

    # Saison : J-1
    remaining = s["season"]["endsAt"] - now
    if 0 < remaining <= 86400:
        cards.append(_card(
            f"fw_j1:w{week}", "normal", "Saison", f"Dernière ligne droite, saison {season_label}",
            f"Clôture le {_fmt_when(s['season']['endsAt'])}. Le préavis ranked laisse 24 h aux joueurs "
            f"pour se connecter et toucher leur versement.",
            _acts(publish("Annoncer le versement ranked", "ranked_incoming"),
                  notify_action(s, "SEASON_ENDING", f"w{week}"), go("Voir Faction War", "#factionwar")),
            due=s["season"]["endsAt"]))

    # Saison close, ou cloture en attente
    last = week - 1
    arch = s["archive"]
    if isinstance(arch, dict):
        closed_at = int(arch.get("closedAt") or s["season"]["startsAt"])
        if now - closed_at <= RECENT_S:
            r, u = int(arch.get("Rainor") or 0), int(arch.get("Rusfor") or 0)
            cards.append(_card(
                f"fw_result:w{last}", "high", "Saison",
                f"Saison {last + 1} close : {arch.get('winner') or '?'} gagne",
                f"Rainor {r:,} – Rusfor {u:,}. Les récompenses sont déjà dans les boîtes aux lettres."
                .replace(",", " "),
                _acts({"id": "faction_announce", "kind": "publish", "label": "Annoncer aux 2 factions"},
                      publish("Publier le résultat global", "factionwar_result"),
                      notify_action(s, "SEASON_RESULT", f"w{last}", {"week": last})),
                at=closed_at, closeWhenDone=True))
    elif now - s["season"]["startsAt"] > 600 and s["openCloudOk"]:
        cards.append(_card(
            f"fw_pending:w{last}", "high", "Saison", f"Clôture de la saison {last + 1} en attente",
            "Aucun serveur n'a encore clos la saison. Elle le sera dès qu'un serveur démarre ; "
            "les récompenses partiront à ce moment-là.", [go("Voir Live", "#live")],
            at=s["season"]["startsAt"]))

    # Ranked
    payout = next((p for p in s["payouts"] if isinstance(p, dict) and p.get("week") == last), None)
    if payout:
        cards.append(_card(
            f"ranked_top:w{last}", "normal", "Saison", f"Ranked versé à {int(payout.get('count') or 0)} joueur(s)",
            "Le versement de la saison est créé ; chaque joueur le récupère à sa prochaine connexion.",
            _acts(publish("Publier le Top 10", "ranked"), notify_action(s, "RANKED_REWARD", str(payout.get("id") or "")),
                  go("Voir Ranked", "#ranked")),
            at=int(payout.get("at") or 0) or None, closeWhenDone=True))
    elif isinstance(arch, dict) and now - s["season"]["startsAt"] > RANKED_LATE_S:
        cards.append(_card(
            f"ranked_missing:w{last}", "high", "Saison", "Versement ranked absent",
            "La saison est close depuis plus de 30 min mais aucun versement ranked n'a été créé.",
            [go("Voir l'aperçu ranked", "#ranked")], at=s["season"]["startsAt"] + RANKED_LATE_S))

    # Boost termine
    boost = s["boost"]
    if isinstance(boost, dict) and boost.get("endsAt"):
        ends = int(boost["endsAt"])
        if ends <= now and now - ends <= 3 * 86400:
            cards.append(_card(f"boost_end:{ends}", "normal", "Jeu", f"Boost {boost.get('name') or ''} terminé".strip(),
                               f"Fini le {_fmt_when(ends)}.", [publish("Annoncer la fin", "boost_end")],
                               at=ends, closeWhenDone=True))

    # Evenement en cours : prevenir les absents (EVENT_LIVE)
    if isinstance(boost, dict) and boost.get("endsAt") and int(boost["endsAt"]) > now:
        ends = int(boost["endsAt"])
        hours = max(1, round((ends - now) / 3600))
        act = notify_action(s, "EVENT_LIVE", f"boost:{ends}",
                            {"event": str(boost.get("name") or "BOOST")[:40], "hours": hours})
        if act and not act["done"]:
            cards.append(_card(f"event_live:boost:{ends}", "info", "Diffusion",
                               f"Boost {boost.get('name') or ''} en cours : prévenir les absents".replace("  ", " "),
                               f"Fin le {_fmt_when(ends)}. Les joueurs absents depuis 2 à 14 jours reçoivent "
                               "une notification Roblox (une par jour au plus).", [act],
                               at=int(boost.get("startsAt") or now), closeWhenDone=True))

    # OPERATIONS
    ops = s["operations"]
    if ops.get("up") and ops.get("endsAt"):
        ends = int(ops["endsAt"])
        if ends <= now:
            cards.append(_card(f"ops_close:{ends}", "high", "Jeu", "OPERATIONS à refermer",
                               f"L'événement devait finir le {_fmt_when(ends)} mais la file est encore ouverte.",
                               [go("Ouvrir Modes", "#modes")], at=ends))
        elif ends - now <= 3600:
            cards.append(_card(f"ops_lasthour:{ends}", "normal", "Jeu", "Dernière heure d'OPERATIONS",
                               f"Fin le {_fmt_when(ends)}.", [go("Ouvrir Modes", "#modes")], due=ends))
        else:
            act = notify_action(s, "EVENT_LIVE", f"ops:{ends}",
                                {"event": "Operations", "hours": max(1, round((ends - now) / 3600))})
            if act and not act["done"]:
                cards.append(_card(f"event_live:ops:{ends}", "info", "Diffusion",
                                   "OPERATIONS ouvert : prévenir les absents",
                                   f"Fin le {_fmt_when(ends)}. Les joueurs absents depuis 2 à 14 jours reçoivent "
                                   "une notification Roblox.", [act], closeWhenDone=True))

    # Versions de place melangees
    versions = s["placeVersions"]
    if len(versions) > 1:
        cards.append(_card(f"versions:{'-'.join(map(str, versions))}", "normal", "Jeu",
                           f"Serveurs sur {len(versions)} versions de place",
                           f"Versions {', '.join(map(str, versions))}. Les anciens serveurs se ferment au fil "
                           "des parties ; redémarre-les depuis le Creator Hub pour forcer la mise à jour.",
                           [go("Voir les serveurs", "#live"), publish("Annoncer une maintenance", "maintenance")]))

    # Relance hebdomadaire des inactifs (COMEBACK)
    n = s.get("notify") or {}
    if "COMEBACK" in (n.get("ids") or []) and now - int(n.get("lastComeback") or 0) >= 7 * 86400:
        ref = notify.iso_week(now)
        act = notify_action(s, "COMEBACK", ref)
        if act and not act["done"]:
            cards.append(_card(f"comeback:{ref}", "info", "Diffusion", "Relance hebdomadaire des inactifs",
                               "Joueurs absents depuis 7 à 30 jours. Au plus une relance par semaine et par "
                               "joueur ; les joueurs déjà notifiés aujourd'hui sont sautés.", [act],
                               closeWhenDone=True))

    # Evenements du jeu
    cards += _event_cards(s["events"], now)

    # Planificateur
    for item in s["schedule"]:
        try:
            at = int(datetime.fromisoformat(str(item.get("at"))).timestamp())
        except (TypeError, ValueError):
            continue
        if item.get("done") or at > now:
            continue
        name = s["templates"].get(item.get("templateId"), item.get("templateId") or "modèle")
        cards.append(_card(f"schedule:{item.get('id') or item.get('at')}", "normal", "Diffusion",
                           f"Annonce prévue : {name}", f"Prévue le {_fmt_when(at)}.",
                           [go("Ouvrir le planificateur", "#schedule")], at=at))

    # Taches manuelles (Reste a faire)
    for t in s["todo"]:
        if t.get("state") in ("done",):
            continue
        prio = {"ready": "high", "todo": "normal", "blocked": "waiting"}.get(t["state"], "normal")
        actions = [] if t.get("auto") or t["state"] == "blocked" else [{"id": "todo_done", "kind": "call", "label": "Marquer comme fait"}]
        cards.append(_card(f"todo:{t['id']}", prio, "Configuration", t["title"], t.get("detail") or "",
                           actions, where=t.get("where"), why=t.get("why"), todoState=t["state"],
                           noSnooze=True))
    return cards


def _event_cards(evts: list[dict], now: int) -> list[dict]:
    out = []
    by_player: dict = {}
    for e in evts:
        d = e.get("data") or {}
        t = e["type"]
        uid = d.get("u")
        if t in ("ac_flag", "sanction") and uid:
            day = datetime.fromtimestamp(e["at"], roblox_api.FW_TIMEZONE).strftime("%Y-%m-%d")
            g = by_player.setdefault((uid, day), {"events": [], "uid": uid, "day": day})
            g["events"].append(e)
        elif t == "honeypot" and uid:
            who = d.get("n") or f"userId {uid}"
            out.append(_card(f"honeypot:{uid}", "high", "Sécurité", f"Piège anti-triche déclenché : {who}",
                             d.get("text") or f"Piège {d.get('trap') or '?'}.",
                             [go("Ouvrir la fiche", f"#players/{uid}"), go("Voir Sécurité", "#security")], at=e["at"],
                             userId=uid))
        elif t == "feedback":
            out.append(_card(f"feedback:{e['id']}", "info", "Joueurs", d.get("title") or "Avis négatif",
                             d.get("text") or "", [go("Ouvrir la fiche", f"#players/{uid}")] if uid else [],
                             at=e["at"], userId=uid))
        elif t == "error_spike":
            out.append(_card(f"errors:{e['id']}", "normal", "Jeu",
                             f"{d.get('n')} erreurs en 1 min dans {d.get('script') or '?'}",
                             f"{d.get('server') or 'Serveur'}. Dernier message : {d.get('message') or '?'}",
                             [go("Voir Live", "#live")], at=e["at"]))
    for g in by_player.values():
        evs = sorted(g["events"], key=lambda e: e["at"])
        flags = [e for e in evs if e["type"] == "ac_flag"]
        sanctions = [e for e in evs if e["type"] == "sanction"]
        last = evs[-1]["data"]
        title = last.get("title") or ("Sanction" if sanctions else "Anticheat")
        parts = []
        if flags:
            parts.append(f"{len(flags)} signalement(s) anticheat")
        if sanctions:
            parts.append(f"{len(sanctions)} sanction(s)")
        summary = f"Aujourd'hui : {', '.join(parts)}. Dernier : " if len(evs) > 1 else ""
        out.append(_card(f"mod:{g['uid']}:{g['day']}", "high" if sanctions else "normal", "Modération",
                         title, summary + (last.get("text") or ""),
                         [go("Ouvrir la fiche", f"#players/{g['uid']}")], at=evs[-1]["at"], userId=g["uid"],
                         count=len(evs)))
    return out


# VUE (etat des cartes applique) ---------------------------------------------
def overview(force: bool = False) -> dict:
    s = collect(force)
    now = int(time.time())
    cards = build(s, now)
    states = db.card_states()
    done_actions: dict[str, set] = {}
    for r in db.audit_rows(1000, "card_action"):
        if r["ok"] and r["card"]:
            done_actions.setdefault(r["card"], set()).add((r["detail"] or {}).get("action"))
    visible, snoozed = [], 0
    for c in cards:
        st = states.get(c["key"])
        for a in c["actions"]:
            a["done"] = bool(a.get("done")) or a["id"] in done_actions.get(c["key"], set())
        pubs = [a for a in c["actions"] if a["kind"] in ("publish", "notify")]
        if c.get("closeWhenDone") and pubs and all(a["done"] for a in pubs):
            continue
        if st and st["state"] in ("done", "dismissed"):
            continue
        if st and st["state"] == "snoozed" and (st.get("until") or 0) > now:
            snoozed += 1
            continue
        visible.append(c)
    visible.sort(key=lambda c: (PRIO_ORDER.get(c["prio"], 9), -(c.get("at") or c.get("due") or 0)))
    waiting = [c for c in visible if c["prio"] == "waiting"]
    active = [c for c in visible if c["prio"] != "waiting"]
    return {"cards": active, "waiting": waiting, "snoozed": snoozed, "at": now,
            "season": {**s["season"], "label": s["season"]["week"] + 1},
            "servers": s["servers"], "errors": s["errors"]}


def set_state(key: str, state: str, until: int | None = None) -> dict:
    db.set_card(key, state, until)
    title = next((c["title"] for c in build(collect(), int(time.time())) if c["key"] == key), key)
    db.audit("card_state", key, {"state": state, "until": until, "title": title}, True, key)
    return overview()


def find(key: str) -> dict:
    s = collect()
    for c in build(s, int(time.time())):
        if c["key"] == key:
            return c
    raise ValueError("Cette carte n'existe plus : la situation a changé. Actualise l'Accueil.")


def invalidate() -> None:
    with _lock:
        _cache.update(at=0.0, state=None)
