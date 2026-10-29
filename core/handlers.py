"""
Handlers de l'API JSON du Command Center.

Chaque route est une fonction synchrone `query -> dict` (GET) ou `body -> dict` (POST),
rangee dans ROUTES_GET / ROUTES_POST. La couche HTTP (app.py, FastAPI) les expose telles
quelles, les execute dans un pool de threads (les appels Open Cloud et Discord sont
bloquants) et journalise les ecritures listees dans AUDITED_POST. Une exception devient
une reponse 500 `{"error": message}` : les messages sont ecrits pour etre lus tels quels.
"""

from __future__ import annotations

from typing import Any

from . import (
    analytics,
    arsenal,
    automations,
    cards,
    commands,
    config,
    configs_api,
    db,
    discord_api,
    docs,
    edits,
    erasure,
    grants,
    live,
    maintenance,
    modes,
    notify,
    players,
    ranked_rewards,
    rewards,
    roblox_api,
    store,
    todo,
    watch,
    webhooks,
)
from . import vars as tvars


# HANDLERS
def api_status() -> dict:
    """Etat de TOUTES les connexions. Chaque bloc echoue independamment :
    un Discord casse ne doit pas cacher l'etat de Roblox."""
    out: dict = {
        "config": {
            "game": config.GAME_NAME,
            "gameUrl": config.GAME_URL,
            "guildId": config.DISCORD_GUILD_ID,
            "universeId": config.ROBLOX_UNIVERSE_ID,
            "placeId": config.ROBLOX_PLACE_ID,
            "dataStoreVersion": config.DATASTORE_VERSION,
            "factionWarStore": config.FW_DATASTORE,
        },
        "missing": config.missing_secrets(),
    }

    try:
        bot = discord_api.get_bot()
        guild = discord_api.get_guild()
        out["discord"] = {
            "ok": True,
            "bot": f"{bot.get('username')}",
            "guild": guild.get("name"),
            "members": guild.get("approximate_member_count"),
            "online": guild.get("approximate_presence_count"),
        }
    except Exception as exc:                                   # noqa: BLE001
        out["discord"] = {"ok": False, "error": str(exc)}

    out["roblox"] = roblox_api.game_health()

    try:
        out["boost"] = roblox_api.get_boost()
        out["boostOk"] = True
    except Exception as exc:                                   # noqa: BLE001
        out["boost"], out["boostOk"] = None, False
        out["boostError"] = str(exc)

    return out


def api_factionwar(query: dict) -> dict:
    week = query.get("week", [None])[0]
    week = int(week) if week and week.lstrip("-").isdigit() else None
    state = roblox_api.faction_war_state(week)

    tops, top_error = {}, None
    for faction in ("Rainor", "Rusfor"):
        res = roblox_api.faction_war_top(faction, state["week"])
        rows = res["rows"]
        top_error = top_error or res["error"]
        names = roblox_api.resolve_usernames([r["userId"] for r in rows])
        for r in rows:
            r["name"] = names.get(str(r["userId"]), f"#{r['userId']}")
        tops[faction] = rows
    state["tops"] = tops
    # Remonte l'erreur : un classement vide et un classement inaccessible ne
    # doivent pas s'afficher pareil.
    state["topsError"] = top_error
    return state


def api_rewards(body: dict) -> dict:
    """action = "save" | "reset". Toute ecriture passe par rewards.validate()."""
    if body.get("action") == "reset":
        rewards.clear_override()
        return {"ok": True, "reset": True, **rewards.get()}
    clean = rewards.set_override(body.get("values") or {})
    return {"ok": True, "saved": clean, **rewards.get()}


def api_faction_announce(body: dict) -> dict:
    """Poste un message ADAPTE dans le salon de CHAQUE faction.

    Le vainqueur recoit le modele "faction_win", le perdant "faction_loss",
    chacun avec le top de SA propre faction. Sans ca, on ne pourrait envoyer
    qu'un message neutre identique aux deux camps -- ce qui rate tout l'interet
    d'une guerre de factions.
    """
    arch = roblox_api.faction_war_archive()
    if not arch:
        raise ValueError("Aucune saison close a annoncer (archive introuvable). "
                         "La cloture n'a peut-etre pas encore eu lieu.")

    winner = arch.get("winner")
    templates = {t["id"]: t for t in store.load_templates()}
    channels = discord_api.get_channels()
    results = []

    for faction in config.FACTIONS:
        tpl = templates.get("faction_win" if faction == winner else "faction_loss")
        if not tpl:
            results.append({"faction": faction, "sent": False,
                            "reason": "modele introuvable"})
            continue

        # Salon QUALIFIE par la categorie : les deux factions ont un salon
        # portant le meme nom.
        target = discord_api.find_channel_ref(f"{faction}/{tpl['channel']}", channels)
        if not target:
            results.append({"faction": faction, "sent": False,
                            "reason": f"salon {faction}/{tpl['channel']} introuvable"})
            continue

        # Top de CETTE faction, deja mis en forme.
        rows = (arch.get("top") or {}).get(faction) or []
        names = roblox_api.resolve_usernames([int(r["userId"]) for r in rows[:5]
                                              if isinstance(r, dict) and str(r.get("userId", "")).isdigit()])
        lines = []
        for i, r in enumerate(rows[:5], start=1):
            if not isinstance(r, dict):
                continue
            who = names.get(str(r.get("userId")), f"#{r.get('userId')}")
            lines.append(f"**#{i}** {who} — {r.get('points', 0)} pts")
        extra = {"{FACTION}": faction,
                 "{FACTION_TOP}": "\n".join(lines) or "*(aucun contributeur)*"}

        try:
            text = tvars.resolve(tpl["body"], extra)
            text = discord_api.resolve_channel_mentions(text, channels)
            embed = discord_api.build_embed(
                title=tvars.resolve(tpl["title"], extra), body=text,
                color=int(tpl.get("color") or config.COLORS["neutral"]),
                footer=tvars.resolve(tpl.get("footer", ""), extra),
                image=tpl.get("image", ""))
            discord_api.send_message(target["id"], embed, ping=tpl.get("ping", ""))
            store.log_send(f"{faction}/{target['name']}", tpl["title"], True)
            results.append({"faction": faction, "sent": True,
                            "channel": target["name"],
                            "outcome": "win" if faction == winner else "loss"})
        except Exception as exc:                               # noqa: BLE001
            store.log_send(f"{faction}/{tpl['channel']}", tpl["title"], False, str(exc))
            results.append({"faction": faction, "sent": False, "reason": str(exc)})

    return {"ok": True, "winner": winner, "results": results}


def api_give_preview(body: dict) -> dict:
    """Ce qui SERAIT donne (audience resolue, plafonds), sans rien ecrire."""
    try:
        return {"ok": True, **grants.preview(body)}
    except grants.GrantError as exc:
        return {"ok": False, "error": str(exc)}


def api_give(body: dict) -> dict:
    """Ecrit le bordereau de cadeau + publie. dry_run=true -> preview seulement."""
    if body.get("dry_run"):
        return api_give_preview(body)
    try:
        res = grants.give(body)
    except grants.GrantError as exc:
        return {"ok": False, "error": str(exc)}
    # Audit Discord (best-effort). On resume le cadeau pour la trace #ops-log.
    who = (f"{res.get('targetCount')} joueur(s)" if res.get("targetCount") is not None
           else f"connectés ({res['grant']['audience']})")
    parts = []
    for k in ("gold", "xp"):
        if body.get(k):
            parts.append(f"{body[k]} {k}")
    for k in ("kits", "items", "badges", "title"):
        if body.get(k):
            parts.append(f"{k}: {body[k]}")
    res["discord"] = discord_api.post_ops_log(
        "🎒 Give", f"→ {who} : {', '.join(parts) or '—'}", color=0x2ECC71)
    return res


def api_wipe(body: dict) -> dict:
    """Wipe DESTRUCTIF (inventaire + stash + equipe) d'un/plusieurs joueur(s)."""
    try:
        res = grants.wipe(body)
    except grants.GrantError as exc:
        return {"ok": False, "error": str(exc)}
    who = (f"{res.get('targetCount')} joueur(s)" if res.get("targetCount") is not None
           else f"connectés ({res['wipe']['audience']})")
    res["discord"] = discord_api.post_ops_log(
        "🧹 WIPE", f"→ {who} : inventaire + stash + équipé", color=0xE74C3C)
    return res


def api_maint_scan(body: dict) -> dict:
    """Scanne une page de stash inactifs (dry-run). Ajoute les pseudos pour l'affichage."""
    res = maintenance.scan_inactive_stashes(
        months=body.get("months", 3), cursor=body.get("cursor"),
        max_keys=body.get("maxKeys", 100))
    ids = [c["userId"] for c in res.get("candidates", [])]
    names = roblox_api.resolve_usernames(ids) if ids else {}
    for c in res.get("candidates", []):
        c["name"] = names.get(str(c["userId"]), f"#{c['userId']}")
    return {"ok": res.get("error") is None, **res}


def api_maint_purge(body: dict) -> dict:
    """Supprime le stash des userIds fournis (liste explicite issue d'un scan)."""
    ids = body.get("userIds") or []
    res = maintenance.purge_stashes(ids)
    if res.get("deleted"):
        res["discord"] = discord_api.post_ops_log(
            "🧽 Purge stash", f"{res['deleted']} stash inactif(s) supprimé(s).", color=0x95A5A6)
    return res


def api_configs_audit(action: str) -> dict:
    return discord_api.post_ops_log("🎚️ Config", f"Action : **{action}**", color=0xF1C40F)


def api_configs(body: dict) -> dict:
    """action = overwrite | publish | restore. Toute ecriture remonte l'erreur
    Roblox telle quelle (l'API Configs est recente, schema a confirmer)."""
    action = body.get("action")
    try:
        if action == "overwrite":
            configs_api.overwrite_draft(body.get("values") or {})
            return {"ok": True, "saved": True, **configs_api.overview()}
        if action == "publish":
            configs_api.publish()
            api_configs_audit("publication de config")   # trace #ops-log
            return {"ok": True, "published": True, **configs_api.overview()}
        if action == "restore":
            rev = str(body.get("revisionId") or "")
            if not rev:
                return {"ok": False, "error": "revisionId manquant."}
            configs_api.restore_revision(rev)
            return {"ok": True, "restored": rev, **configs_api.overview()}
        return {"ok": False, "error": f"Action inconnue : {action}"}
    except configs_api.ConfigError as exc:
        return {"ok": False, "error": str(exc)}


def api_modes(body: dict) -> dict:
    """action = save | reset. Ecrit modes_config + publie FW_Event kind=modes."""
    action = body.get("action")
    try:
        if action == "reset":
            modes.reset()
            return {"ok": True, "reset": True, **modes.get()}
        clean = modes.save(body.get("values") or {})
        return {"ok": True, "saved": clean, **modes.get()}
    except modes.ModeError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:                                    # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def api_ranked_pay(body: dict) -> dict:
    """Le dashboard ne verse plus : le jeu cloture exactement-once. Le
    fallback explicite reste disponible pour une intervention technique."""
    if body.get("action") == "tiers":
        return {"ok": True, "tiers": ranked_rewards.save_tiers(body.get("tiers") or [])}
    if body.get("action") != "manual_fallback":
        raise ranked_rewards.PayoutError(
            "Versement automatique actif : aucun paiement manuel n'a ete lance.")
    return ranked_rewards.pay(int(body.get("limit") or 25),
                              bool(body.get("notifyRoblox", True)))


def api_ranked(query: dict) -> dict:
    limit = query.get("limit", ["20"])[0]
    limit = int(limit) if str(limit).isdigit() else 20
    return roblox_api.ranked_top(limit)


def api_announce(body: dict) -> dict:
    channel_id = body.get("channelId", "")
    if not channel_id:
        raise ValueError("Aucun salon selectionne.")

    channels = discord_api.get_channels()
    # Ordre important : variables d'abord (elles peuvent contenir des <#salon>),
    # puis resolution des mentions de salon en IDs cliquables.
    text = tvars.resolve(body.get("body", ""))
    text = discord_api.resolve_channel_mentions(text, channels)
    embed = discord_api.build_embed(
        title=tvars.resolve(body.get("title", "")),
        body=text,
        color=int(body.get("color") or config.COLORS["neutral"]),
        footer=body.get("footer", ""),
        image=body.get("image", ""),
    )

    name = next((c["name"] for c in channels if c["id"] == channel_id), channel_id)
    try:
        msg = discord_api.send_message(channel_id, embed,
                                       ping=body.get("ping", ""),
                                       publish=bool(body.get("publish")))
        store.log_send(name, body.get("title", ""), True)
        return {"ok": True, "channel": name, "messageId": msg.get("id"),
                "published": msg.get("published")}
    except Exception as exc:                                   # noqa: BLE001
        store.log_send(name, body.get("title", ""), False, str(exc))
        raise


def _announce_from_template(template_id: str, extra: dict | None = None, card: str | None = None) -> dict:
    """Poste le modele `template_id`. Utilise par les annonces AUTOMATIQUES
    (boost). Ne leve jamais : l'action principale (activer le boost) a deja
    reussi, un Discord indisponible ne doit pas la faire passer pour un echec.
    Renvoie {sent: bool, ...} pour que l'UI puisse le dire honnetement."""
    tpl = next((t for t in store.load_templates() if t["id"] == template_id), None)
    if not tpl:
        return {"sent": False, "reason": f"modele '{template_id}' introuvable"}
    try:
        channels = discord_api.get_channels()
        target = next((c for c in channels
                       if c["name"].lower() == tpl["channel"].lower()), None)
        if not target:
            return {"sent": False, "reason": f"salon #{tpl['channel']} introuvable"}

        text = tvars.resolve(tpl["body"], extra)
        text = discord_api.resolve_channel_mentions(text, channels)
        embed = discord_api.build_embed(
            title=tvars.resolve(tpl["title"], extra), body=text,
            color=int(tpl.get("color") or config.COLORS["neutral"]),
            footer=tvars.resolve(tpl.get("footer", ""), extra),
            image=tpl.get("image", ""))
        discord_api.send_message(target["id"], embed, ping=tpl.get("ping", ""))
        store.log_send(target["name"], tpl["title"], True, card=card)
        return {"sent": True, "channel": target["name"]}
    except Exception as exc:                                   # noqa: BLE001
        store.log_send(tpl.get("channel", "?"), tpl.get("title", ""), False, str(exc), card=card)
        return {"sent": False, "reason": str(exc)}


# ACCUEIL : cartes « A faire ». Une publication passe toujours par un apercu.
def _card_action(body: dict) -> tuple[dict, dict]:
    card = cards.find(str(body.get("key") or ""))
    action = next((a for a in card["actions"] if a["id"] == body.get("action")), None)
    if not action:
        raise ValueError("Action inconnue pour cette carte.")
    return card, action


# ACTIONS SUR LES JOUEURS ET LES SERVEURS (lot 3)
def _int(body: dict, key: str) -> int:
    raw = str(body.get(key) or "")
    if not raw.isdigit():
        raise ValueError(f"{key} manquant ou invalide.")
    return int(raw)


def api_cmd(body: dict) -> dict:
    """toast (u | job | tous), kick (u), drain (job), remove_item et set_money (joueur en ligne)."""
    op = str(body.get("op") or "")
    fields: dict[str, Any] = {k: body.get(k) for k in ("title", "text", "reason", "uid", "where", "amount", "delay", "urgent")}
    if body.get("userId"):
        fields["u"] = _int(body, "userId")
    if body.get("job"):
        fields["job"] = str(body["job"])
    if op == "toast" and not (fields.get("u") or fields.get("job")):
        fields["job"] = "*"
    if op in ("kick", "remove_item", "set_money") and not fields.get("u"):
        raise ValueError("Joueur manquant.")
    if op == "drain" and not fields.get("job"):
        raise ValueError("Serveur manquant.")
    if op in ("kick", "remove_item", "set_money") and not live.find_player(fields["u"]):
        raise ValueError("Ce joueur n'est sur aucun serveur d'après le registre live.")
    res = commands.send(op, **fields)
    db.audit(f"cmd_{op}", res["target"], {k: v for k, v in fields.items() if v not in (None, "")} | {"id": res["id"]}, True)
    return res


def api_restart(body: dict) -> dict:
    res = commands.restart_servers(bool(body.get("allVersions")), int(body.get("bleedMinutes") or 0))
    if body.get("announce"):
        res["announce"] = _announce_from_template("maintenance")
    return res


def api_edit_plan(body: dict) -> dict:
    return edits.plan(_int(body, "userId"), str(body.get("op") or ""), body.get("params") or {})


def api_ban(body: dict) -> dict:
    days: Any = body.get("days")
    res = commands.ban(_int(body, "userId"), float(days) if days not in (None, "", 0, "0") else None,
                       str(body.get("displayReason") or ""), str(body.get("privateReason") or ""),
                       bool(body.get("alts", True)))
    db.audit("ban", str(body.get("userId")), {"days": days or "définitif",
             "motif": str(body.get("displayReason") or "")[:120], "alts": bool(body.get("alts", True))}, True)
    return res


def api_ban_wave(body: dict) -> dict:
    """Vague de bans (espace Securite) : meme motif pour tous, un resultat par joueur."""
    ids = [int(x) for x in (body.get("userIds") or []) if str(x).isdigit()][:50]
    if not ids:
        raise ValueError("Aucun joueur selectionne.")
    out: list[dict] = []
    for uid in ids:
        try:
            api_ban({**body, "userId": uid})
            out.append({"userId": uid, "ok": True})
        except Exception as exc:                               # noqa: BLE001
            out.append({"userId": uid, "ok": False, "error": str(exc)[:200]})
    return {"ok": all(r["ok"] for r in out), "results": out}


def api_cards_preview(body: dict) -> dict:
    card, action = _card_action(body)
    templates = {t["id"]: t for t in store.load_templates()}
    if action["id"] == "faction_announce":
        arch = roblox_api.faction_war_archive()
        if not arch:
            raise ValueError("Aucune saison close a annoncer (archive introuvable).")
        out = []
        for faction in config.FACTIONS:
            tpl = templates.get("faction_win" if faction == arch.get("winner") else "faction_loss")
            if tpl:
                extra = {"{FACTION}": faction, "{FACTION_TOP}": "(top 5 de la faction)"}
                out.append({"channel": f"{faction}/{tpl['channel']}", "title": tvars.resolve(tpl["title"], extra),
                            "body": tvars.resolve(tpl["body"], extra), "ping": tpl.get("ping", "")})
        return {"card": card["key"], "action": action["id"], "messages": out}
    if action.get("template"):
        tpl = templates.get(action["template"])
        if not tpl:
            raise ValueError(f"Modele '{action['template']}' introuvable : cree-le dans Modeles.")
        return {"card": card["key"], "action": action["id"], "messages": [{
            "channel": tpl.get("channel", ""), "title": tvars.resolve(tpl["title"]),
            "body": tvars.resolve(tpl["body"]), "ping": tpl.get("ping", "")}]}
    raise ValueError("Cette action ne publie rien.")


def api_cards_act(body: dict) -> dict:
    card, action = _card_action(body)
    key = card["key"]
    if action["id"] == "faction_announce":
        res = api_faction_announce({})
        ok = all(r.get("sent") for r in res.get("results", []))
    elif action.get("template"):
        res = _announce_from_template(action["template"], card=key)
        ok = bool(res.get("sent"))
        if ok and key.startswith("schedule:"):
            store.mark_schedule_done(key.split(":", 1)[1])
    elif action["id"] == "todo_done":
        res = todo.mark(key.split(":", 1)[1], True)
        ok = True
    else:
        raise ValueError("Action non executable depuis le serveur.")
    db.audit("card_action", key, {"action": action["id"], "label": action["label"], "title": card["title"],
                                  "ok": ok}, ok, key)
    cards.invalidate()
    return {"ok": ok, "result": res, **cards.overview()}


# NOTIFICATIONS JOUEURS (lot 4) : catalogue, apercu, campagnes. Voir core/notify.py.
def _notify_target(body: dict) -> tuple[str, dict, str | None, dict | None]:
    """Cle, parametres, sujet et carte d'origine. Depuis une carte, le sujet vient de la carte."""
    key = str(body.get("key") or "")
    raw = body.get("params")
    params = raw if isinstance(raw, dict) else {}
    ref = str(body["ref"]) if body.get("ref") else None
    card = None
    if body.get("card"):
        card = cards.find(str(body["card"]))
        action = next((a for a in card["actions"] if a["id"] == body.get("action") and a["kind"] == "notify"), None)
        if not action:
            raise ValueError("Cette carte ne propose pas cette notification.")
        key, ref = action["notify"], action["ref"]
        params = {**action.get("params", {}), **params}
    return key, params, ref, card


def api_notify_preview(body: dict) -> dict:
    key, params, ref, _ = _notify_target(body)
    return notify.preview(key, params, ref)


def api_notify_send(body: dict) -> dict:
    key, params, ref, card = _notify_target(body)
    res = notify.start(key, params, ref, card=card["key"] if card else None)
    if card:
        db.audit("card_action", card["key"], {"action": f"notify:{key}", "label": f"Notification {key}",
                                              "title": card["title"], "ok": True, "campaign": res["campaign"]},
                 True, card["key"])
        cards.invalidate()
    return res


def api_boost(body: dict) -> dict:
    if body.get("action") == "clear":
        roblox_api.clear_boost()
        result: dict = {"ok": True, "cleared": True}
        if body.get("announce"):
            result["discord"] = _announce_from_template("boost_end")
        return result

    record = roblox_api.set_boost(
        xp=body.get("xp", 1), gold=body.get("gold", 1), war=body.get("war", 1),
        minutes=body.get("minutes", 60), name=body.get("name", "BOOST"),
        desc=body.get("desc", ""))
    result = {"ok": True, "boost": record}
    if body.get("announce"):
        result["discord"] = _announce_from_template("boost", tvars.boost_context(record))
    return result


def _flag(query: dict, name: str) -> bool:
    return str(query.get(name, ["0"])[0]) in ("1", "true")


def _user_id(query: dict) -> int:
    raw = str(query.get("userId", [""])[0])
    if not raw.isdigit():
        raise players.PlayerError("userId manquant ou invalide.")
    return int(raw)


ROUTES_GET = {
    "/api/status": lambda q: api_status(),
    "/api/channels": lambda q: {"channels": discord_api.get_channels()},
    "/api/roles": lambda q: {"roles": discord_api.get_roles()},
    "/api/templates": lambda q: {"templates": store.load_templates()},
    "/api/schedule": lambda q: {"schedule": store.load_schedule()},
    "/api/history": lambda q: {"history": store.load_history()},
    "/api/factionwar": api_factionwar,
    "/api/ranked": api_ranked,
    "/api/ranked/preview": lambda q: ranked_rewards.preview(),
    "/api/configs": lambda q: configs_api.overview(),
    "/api/modes": lambda q: modes.get(),
    "/api/rewards": lambda q: rewards.get(),
    "/api/settings": lambda q: {"settings": store.load_settings()},
    "/api/vars": lambda q: {"catalog": [{"key": k, "desc": d} for k, d in tvars.CATALOG]},
    # Jeu en direct (registre CC_Servers_V1) et contrats publies par les places.
    "/api/live": lambda q: live.servers(force=_flag(q, "force")),
    "/api/live/contracts": lambda q: live.contracts(force=_flag(q, "force")),
    # Ce que Roblox mesure (Analytics) : joueurs, crashs serveur par cause, FPS, memoire...
    "/api/trends": lambda q: analytics.overview(
        int(q.get("hours", ["24"])[0]) if str(q.get("hours", ["24"])[0]).isdigit() else 24,
        force=_flag(q, "force")),
    # Journal du veilleur (crashs, demarrages, fermetures) et courbe des joueurs sur 24 h.
    "/api/live/events": lambda q: watch.snapshot(
        int(q.get("since", ["0"])[0]) if str(q.get("since", ["0"])[0]).isdigit() else 0),
    # Fiche joueur : lecture seule, a la demande, cache 60 s (force=1 pour relire).
    "/api/player/search": lambda q: players.resolve(q.get("q", [""])[0]),
    "/api/player": lambda q: players.summary(_user_id(q), force=_flag(q, "force")),
    "/api/player/inventory": lambda q: players.inventory(_user_id(q), force=_flag(q, "force")),
    "/api/player/stash": lambda q: players.stash(_user_id(q), force=_flag(q, "force")),
    # Accueil : cartes « A faire » (etat cache 30 s) et journal d'audit.
    "/api/home": lambda q: cards.overview(force=_flag(q, "force")),
    "/api/journal": lambda q: {"rows": db.audit_rows(
        int(q.get("limit", ["200"])[0]) if str(q.get("limit", ["200"])[0]).isdigit() else 200)},
    # Actions (lot 3) : etat d'une commande, bans, copies de modification.
    "/api/cmd": lambda q: commands.status(str(q.get("id", [""])[0])),
    "/api/bans": lambda q: commands.bans(),
    "/api/edits": lambda q: {"backups": db.backups_for(_user_id(q))},
    # Documents du depot affiches dans le Guide (liste fermee, lus a chaque ouverture).
    "/api/docs": lambda q: docs.all_text(),
    # Reste a faire : actions manuelles du developpeur, verifiees automatiquement (cache 30 min).
    "/api/todo": lambda q: todo.overview(force=_flag(q, "force")),
    # Securite : pieges anti-triche, lus a la demande (voir GUIDE_PIEGES.md).
    "/api/security/honeypots": lambda q: roblox_api.honeypot_list(
        int(q.get("limit", ["50"])[0]) if str(q.get("limit", ["50"])[0]).isdigit() else 50),
    "/api/security/honeypot": lambda q: roblox_api.honeypot_detail(int(q["userId"][0])),
    # Sonde de chaque droit de la cle Open Cloud : a la demande seulement (~10 appels).
    "/api/permissions": lambda q: roblox_api.probe_permissions(),
    # Arsenal : purement local -- aucun appel Roblox ni Discord.
    "/api/arsenal": lambda q: arsenal.overview(),
    # Notifications joueurs : catalogue, Asset IDs, campagnes et registre du jour (local).
    "/api/notify": lambda q: notify.overview(),
    # Lot 6 : automatisations, webhooks Roblox recus
    "/api/automations": lambda q: automations.overview(),
    "/api/webhooks": lambda q: {"events": webhooks.recent(), "configured": bool(config.ROBLOX_WEBHOOK_SECRET)},
}


def api_preview(body: dict) -> dict:
    """Rend le message exactement comme il partira, sans l'envoyer."""
    return {
        "title": tvars.resolve(body.get("title", "")),
        "body": tvars.resolve(body.get("body", "")),
        "footer": tvars.resolve(body.get("footer", "")),
    }

def api_arsenal(body: dict) -> dict:
    """Ecrit l'arsenal puis rend la vue complete : la page recoit les scores
    recalcules et les alertes sans avoir a redemander."""
    arsenal.save(body)
    return arsenal.overview()


def api_arsenal_level(body: dict) -> dict:
    """Persiste un deplacement de la timeline sans reecrire les autres champs."""
    arsenal.set_level(body.get("name"), body.get("level"))  # type: ignore[arg-type]  # valide dans arsenal
    return arsenal.overview()


def api_arsenal_outfit_level(body: dict) -> dict:
    """Persiste le deplacement d'une tenue sur la timeline, sans toucher au reste."""
    arsenal.set_outfit_level(body.get("id"), body.get("level"))  # type: ignore[arg-type]  # valide dans arsenal
    return arsenal.overview()


ROUTES_POST = {
    "/api/announce": api_announce,
    "/api/preview": api_preview,
    "/api/boost": api_boost,
    "/api/templates": lambda b: {"templates": store.save_templates(b.get("templates", []))},
    "/api/schedule": lambda b: {"schedule": store.save_schedule(b.get("schedule", []))},
    "/api/settings": lambda b: {"settings": store.save_settings(b.get("settings", {}))},
    "/api/rewards": api_rewards,
    "/api/faction/announce": api_faction_announce,
    "/api/ranked/pay": api_ranked_pay,
    "/api/give": api_give,
    "/api/give/preview": api_give_preview,
    "/api/wipe": api_wipe,
    "/api/configs": api_configs,
    "/api/modes": api_modes,
    "/api/arsenal": api_arsenal,
    "/api/arsenal/level": api_arsenal_level,
    "/api/arsenal/outfit-level": api_arsenal_outfit_level,
    "/api/maintenance/scan": api_maint_scan,
    "/api/maintenance/purge": api_maint_purge,
    "/api/cmd": api_cmd,
    "/api/edit/plan": api_edit_plan,
    "/api/edit/apply": lambda b: edits.apply(str(b.get("token") or "")),
    "/api/edit/undo": lambda b: edits.undo(_int(b, "backupId")),
    "/api/ban": api_ban,
    "/api/ban/wave": api_ban_wave,
    "/api/unban": lambda b: commands.unban(_int(b, "userId")),
    "/api/restart": api_restart,
    "/api/cards/preview": api_cards_preview,
    "/api/cards/act": api_cards_act,
    "/api/cards/state": lambda b: cards.set_state(str(b.get("key") or ""), str(b.get("state") or ""),
                                                  int(b["until"]) if str(b.get("until") or "").isdigit() else None),
    "/api/todo": lambda b: todo.mark(str(b.get("id") or ""), bool(b.get("done"))),
    "/api/notify/config": lambda b: {"ok": True, **notify.save_config(b.get("ids") or {}, b.get("testUserId"))},
    "/api/notify/preview": api_notify_preview,
    "/api/notify/send": api_notify_send,
    "/api/notify/test": lambda b: notify.test(str(b.get("key") or ""),
                                              int(b["userId"]) if str(b.get("userId") or "").isdigit() else None,
                                              b.get("params") if isinstance(b.get("params"), dict) else None),
    "/api/notify/stop": lambda b: notify.stop(),
    "/api/automations": lambda b: automations.save(str(b.get("rule") or ""),
                                                   b.get("config") if isinstance(b.get("config"), dict) else {}),
    "/api/automations/cancel": lambda b: {**automations.cancel(str(b.get("card") or ""), str(b.get("action") or "")),
                                          **cards.overview()},
    "/api/erasure/plan": lambda b: erasure.plan(_int(b, "userId"), str(b["card"]) if b.get("card") else None),
    "/api/erasure/apply": lambda b: {**erasure.apply(str(b.get("token") or ""), str(b.get("confirm") or "")),
                                     **cards.overview(force=True)},
}


# Ecritures journalisees automatiquement (journal d'audit, ecran Journal). Les envois
# Discord sont deja traces un par un ; l'arsenal (glisser-deposer) est trop bavard.
AUDITED_POST = {
    "/api/boost": "boost", "/api/modes": "modes", "/api/rewards": "rewards", "/api/give": "give",
    "/api/wipe": "wipe", "/api/ranked/pay": "ranked_pay", "/api/configs": "configs",
    "/api/maintenance/purge": "maintenance_purge", "/api/settings": "settings",
    "/api/templates": "templates", "/api/schedule": "schedule",
    "/api/unban": "unban", "/api/restart": "restart", "/api/ban/wave": "ban_wave",
    "/api/notify/config": "notify_config", "/api/notify/send": "notify_send",
    "/api/notify/test": "notify_test", "/api/notify/stop": "notify_stop",
}


def _audit_safe(action: str, detail: dict, ok: bool) -> None:
    try:
        db.audit(action, "", detail, ok)
    except Exception:                                          # noqa: BLE001
        pass   # le journal ne doit jamais faire echouer l'action elle-meme


def _summary(body) -> dict:
    """Resume court d'une requete pour le journal : jamais de liste ni de texte entier."""
    out = {}
    for k, v in (body or {}).items() if isinstance(body, dict) else []:
        if isinstance(v, list):
            out[k] = f"{len(v)} element(s)"
        elif isinstance(v, dict):
            out[k] = f"{len(v)} champ(s)"
        elif isinstance(v, str):
            out[k] = v[:80]
        else:
            out[k] = v
    return out
