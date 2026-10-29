"""
Configuration, apercu et fallback manuel des recompenses ranked.

DECLENCHEMENT NORMAL : automatique cote jeu a chaque cloture de saison. Le
fallback historique peut encore ecrire un BORDEREAU immuable dans le DataStore,
puis publier sur FW_Event. Le jeu distribue ce bordereau via
RankedRewardService, en modele "pull" : chaque joueur se reconcilie lui-meme,
donc un joueur hors ligne au moment du versement le recoit a son retour, et
appuyer deux fois sur le bouton ne verse jamais deux fois (l'id fait foi).

Le bordereau porte les MONTANTS, pas seulement les rangs : le jeu n'a donc
aucune config a connaitre, il livre ce qui est ecrit -- apres l'avoir reclampe,
parce qu'un serveur ne fait jamais confiance a une valeur venue du reseau.
"""

from __future__ import annotations

import time

from . import config, roblox_api, store

INDEX_KEY = "ranked_payout_index"
CONFIG_KEY = "ranked_rewards_config"
# Ancienne cle unique. On l'ECRIT ENCORE, pour qu'un serveur qui n'aurait pas
# recu la mise a jour du code continue a fonctionner. Elle sera retirable une
# fois tous les serveurs a jour.
LEGACY_KEY = "ranked_payout_latest"

# Nombre de bordereaux conserves. Chacun est relu une fois par joueur a sa
# premiere connexion suivante : au-dela d'une poignee, le cout de
# reconciliation deviendrait sensible pour un gain nul.
KEEP_PAYOUTS = 8

# Memes plafonds que les recompenses de guerre (FactionWarConfig.MAX_REWARD_*).
MAX_GOLD = 50000
MAX_XP = 25000

# Bareme par defaut. Editable depuis le dashboard (data/settings.json).
DEFAULT_TIERS = [
    {"maxRank": 1,  "gold": 15000, "xp": 8000, "title": "S%d RANKED #1"},
    {"maxRank": 3,  "gold": 9000,  "xp": 5000, "title": "S%d RANKED TOP 3"},
    {"maxRank": 10, "gold": 5000,  "xp": 2500, "title": "S%d RANKED TOP 10"},
    {"maxRank": 25, "gold": 2000,  "xp": 1000, "title": ""},
]


def _badge_list(value) -> list[int]:
    """Ids de badges : accepte une chaine "123, 456" ou une liste."""
    if value in (None, "", []):
        return []
    if isinstance(value, str):
        value = [v for v in value.replace(";", ",").split(",") if v.strip()]
    out = []
    for raw in value or []:
        try:
            n = int(str(raw).strip())
        except (TypeError, ValueError):
            continue
        if n > 0 and n not in out:
            out.append(n)
    return out[:5]


class PayoutError(Exception):
    """Erreur de versement, message destine a l'utilisateur."""


def _clean_tiers(tiers: list[dict]) -> list[dict]:
    clean: list[dict] = []
    for i, t in enumerate(tiers or [], start=1):
        try:
            clean.append({
                "maxRank": max(1, int(t.get("maxRank", 1))),
                "gold": max(0, min(int(t.get("gold", 0)), MAX_GOLD)),
                "xp": max(0, min(int(t.get("xp", 0)), MAX_XP)),
                "title": str(t.get("title") or "").strip(),
                # Accepte "123, 456" (saisie UI) comme [123, 456] (API).
                "badges": _badge_list(t.get("badges")),
            })
        except (TypeError, ValueError):
            raise PayoutError(f"Palier #{i} : valeur numerique invalide.") from None
    if not clean:
        raise PayoutError("Il faut au moins un palier.")
    # RewardFor prend le premier palier ou rank <= maxRank : l'ordre croissant
    # est obligatoire, sinon le #1 toucherait la recompense du top 25.
    clean.sort(key=lambda t: t["maxRank"])
    return clean


def get_tiers() -> list[dict]:
    """Le DataStore est la source persistante inter-saisons. Le JSON local
    reste un cache de secours, puis les valeurs embarquees ferment la chaine."""
    remote_read = False
    record = None
    try:
        record = roblox_api.datastore_get(config.FW_DATASTORE, CONFIG_KEY)
        remote_read = True
        remote = record.get("tiers") if isinstance(record, dict) else None
        if isinstance(remote, list) and remote:
            return _clean_tiers(remote)
    except Exception:                                           # noqa: BLE001
        pass
    local = store.load_settings().get("rankedTiers")
    try:
        clean = _clean_tiers(local) if isinstance(local, list) and local else _clean_tiers(DEFAULT_TIERS)
    except PayoutError:
        clean = _clean_tiers(DEFAULT_TIERS)

    # Migration unique de l'ancien reglage local : avant l'automatisation, le
    # bareme ne vivait que dans settings.json. Une lecture distante REUSSIE et
    # vide autorise sa copie ; une panne reseau, elle, ne declenche aucune ecriture.
    if remote_read and record is None and isinstance(local, list) and local:
        try:
            roblox_api.datastore_set(config.FW_DATASTORE, CONFIG_KEY,
                                     {"tiers": clean, "updatedAt": int(time.time())})
            roblox_api.publish(config.FW_TOPIC, {"kind": "ranked_rewards"})
        except Exception:                                       # noqa: BLE001
            pass
    return clean


def save_tiers(tiers: list[dict]) -> list[dict]:
    clean = _clean_tiers(tiers)
    record = {"tiers": clean, "updatedAt": int(time.time())}
    # Ecriture distante d'abord : l'interface ne doit jamais annoncer "sauve"
    # si seul le cache de ce PC a ete modifie.
    roblox_api.datastore_set(config.FW_DATASTORE, CONFIG_KEY, record)
    store.save_settings({"rankedTiers": clean})
    try:
        roblox_api.publish(config.FW_TOPIC, {"kind": "ranked_rewards"})
    except Exception:                                           # noqa: BLE001
        # La cle persistante fait foi et sera relue a la cloture. Le push ne
        # sert qu'a rafraichir les caches des serveurs deja ouverts.
        pass
    return clean


def _reward_for(rank: int, tiers: list[dict]) -> dict | None:
    for t in tiers:
        if rank <= t["maxRank"]:
            return t
    return None


def _format_title(title: str, week: int) -> str:
    """Remplace le jeton saison par le numero affiche (index semaine + 1)."""
    template = str(title or "")
    if not template:
        return ""
    first_word = template.split(maxsplit=1)[0]
    already_formatted = first_word.startswith("S") and first_word[1:].isdigit()
    if "%d" not in template and not already_formatted:
        template = "S%d " + template
    return template.replace("%d", str(int(week) + 1))


def preview(limit: int = 25) -> dict:
    """Ce qui SERAIT verse, sans rien ecrire. Le dashboard le montre avant
    de demander confirmation : on ne verse pas a l'aveugle."""
    tiers = get_tiers()
    res = roblox_api.ranked_top(limit)
    if res.get("error"):
        return {"rows": [], "error": res["error"], "tiers": tiers}

    week = roblox_api.fw_week_index()
    rows = []
    for r in res["rows"]:
        rw = _reward_for(r["rank"], tiers)
        if not rw:
            continue
        rows.append({**r, "gold": rw["gold"], "xp": rw["xp"],
                     "title": _format_title(rw["title"], week),
                     "badges": rw.get("badges") or []})
    return {"rows": rows, "error": None, "tiers": tiers, "week": week,
            "lastPayout": _last_payout_meta()}


def _read_index() -> list:
    try:
        idx = roblox_api.datastore_get(config.FW_DATASTORE, INDEX_KEY)
    except Exception:                                          # noqa: BLE001
        return []
    return idx if isinstance(idx, list) else []


def _last_payout_meta() -> dict | None:
    idx = _read_index()
    return idx[0] if idx else None


def pay(limit: int = 25, notify_roblox: bool = True) -> dict:
    """Ecrit le bordereau, previent les serveurs, et notifie les joueurs."""
    plan = preview(limit)
    if plan.get("error"):
        raise PayoutError(plan["error"])
    if not plan["rows"]:
        raise PayoutError("Aucun joueur classe : rien a verser.")

    now = int(time.time())
    payout = {
        # L'id porte l'horodatage : deux versements distincts ne peuvent pas
        # se confondre, et rejouer le meme ne verse rien de plus.
        "id": f"p{now}",
        "at": now,
        # Meme semaine que l'apercu confirme : aucun decalage possible si le
        # paiement est lance exactement au changement de saison.
        "week": plan["week"],
        "entries": {
            str(r["userId"]): {
                "rank": r["rank"], "lp": r["lp"],
                "faction": r.get("faction"),
                "gold": min(int(r["gold"]), MAX_GOLD),
                "xp": min(int(r["xp"]), MAX_XP),
                "title": r["title"],
                "badges": r.get("badges") or [],
            }
            for r in plan["rows"]
        },
        "ladder": [
            {"rank": r["rank"], "userId": r["userId"], "name": r["name"],
             "lp": r["lp"], "faction": r.get("faction")}
            for r in plan["rows"]
        ],
    }

    # 1) Le bordereau, sous SA PROPRE cle : il ne sera jamais ecrase.
    roblox_api.datastore_set(config.FW_DATASTORE,
                             f"ranked_payout_{payout['id']}", payout)

    # 2) L'index, ecrit APRES le bordereau. Cet ordre compte : si l'ecriture de
    #    l'index echoue, on a un bordereau orphelin (inoffensif) plutot qu'un
    #    index pointant vers une cle inexistante.
    index = [{"id": payout["id"], "at": now, "count": len(payout["entries"])}]
    index += [e for e in _read_index()
              if isinstance(e, dict) and e.get("id") != payout["id"]]
    roblox_api.datastore_set(config.FW_DATASTORE, INDEX_KEY, index[:KEEP_PAYOUTS])

    # 3) Ancienne cle, pour les serveurs pas encore a jour.
    roblox_api.datastore_set(config.FW_DATASTORE, LEGACY_KEY, payout)

    # Sans ce push, seuls les joueurs se connectant PLUS TARD seraient servis.
    roblox_api.publish(config.FW_TOPIC, {"kind": "ranked_payout", "id": payout["id"]})

    notified: dict = {"campaign": None, "error": None}
    if notify_roblox:
        # Notification RANKED_REWARD : meme ordonnanceur que l'Accueil (core/notify.py).
        # Un echec ne remet jamais en cause le versement, deja ecrit et distribue.
        try:
            from . import notify
            res = notify.start("RANKED_REWARD", ref=payout["id"])
            notified = {"campaign": res["campaign"], "error": None}
        except Exception as exc:                               # noqa: BLE001
            notified = {"campaign": None, "error": str(exc)[:300]}

    return {"ok": True, "payout": {"id": payout["id"], "count": len(payout["entries"])},
            "rows": plan["rows"], "notified": notified}
