"""
Cadeaux admin (or / XP / kits / items / badges / titre) depuis le dashboard.

MEME MODELE que ranked_rewards : on ecrit un BORDEREAU IMMUABLE dans le DataStore
puis on publie sur FW_Event. Le jeu distribue via GrantService.luau, en "pull" :
un joueur hors ligne le recoit a son retour, et rejouer le message (ou re-sonder
l'index) ne verse jamais deux fois (l'id fait foi).

TROIS AUDIENCES :
  * users  : liste de pseudos/ids -> resolus ici en userIds -> MAILBOX (offline-safe).
  * active : union des classements de guerre de la semaine -> MAILBOX (offline-safe).
  * online : tous les joueurs CONNECTES a l'instant -> application immediate cote jeu
             (pas de mailbox : "en ligne maintenant"), bornee dans le temps + idempotente.

On ne fait JAMAIS confiance au bordereau cote jeu : GrantService reclampe or/XP/badges.
Ici on valide et on plafonne AUSSI (echouer tot, message clair pour l'utilisateur).
"""

from __future__ import annotations

import time

from . import config, roblox_api, store

INDEX_KEY = "grant_index"

# Nombre de bordereaux conserves (comme les versements ranked).
KEEP_GRANTS = 12

# Memes plafonds que FactionWarConfig.MAX_REWARD_*.
MAX_GOLD = 50000
MAX_XP = 25000
MAX_BADGES = 5

AUDIENCES = ("users", "active", "online")


class GrantError(Exception):
    """Erreur de validation, message destine a l'utilisateur."""


def _int_in(value, low, high, label) -> int:
    try:
        n = int(float(value))
    except (TypeError, ValueError):
        raise GrantError(f"{label} : « {value} » n'est pas un nombre.") from None
    return max(low, min(n, high))


def _badges(value) -> list[int]:
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
    return out[:MAX_BADGES]


def _str_list(value, cap: int) -> list[str]:
    """kits (ids) ou items (ids/specs) : accepte "a, b" ou [..]."""
    if value in (None, "", []):
        return []
    if isinstance(value, str):
        value = [v for v in value.replace(";", ",").split(",") if v.strip()]
    out = []
    for raw in value or []:
        s = str(raw).strip()
        if s:
            out.append(s)
        if len(out) >= cap:
            break
    return out


def _build_reward(payload: dict) -> dict:
    """Valide et normalise la recompense. Leve GrantError si elle est vide."""
    reward: dict = {
        "gold": _int_in(payload.get("gold", 0), 0, MAX_GOLD, "Or"),
        "xp": _int_in(payload.get("xp", 0), 0, MAX_XP, "XP"),
        "kits": _str_list(payload.get("kits"), 10),
        "items": _str_list(payload.get("items"), 20),
        "badges": _badges(payload.get("badges")),
        "title": str(payload.get("title") or "").strip(),
    }
    if (reward["gold"] <= 0 and reward["xp"] <= 0 and not reward["kits"]
            and not reward["items"] and not reward["badges"] and not reward["title"]):
        raise GrantError("Cadeau vide : renseigne au moins un or/XP/kit/item/badge/titre.")
    return reward


def _resolve_users(raw) -> tuple[list[int], list[str]]:
    """Transforme une liste de pseudos/ids en userIds. Renvoie (ids, non_resolus)."""
    if isinstance(raw, str):
        raw = [v for v in raw.replace(";", ",").split(",") if v.strip()]
    ids: list[int] = []
    unresolved: list[str] = []
    names_to_lookup: list[str] = []
    for entry in raw or []:
        s = str(entry).strip()
        if not s:
            continue
        if s.isdigit():
            ids.append(int(s))
        else:
            names_to_lookup.append(s.lstrip("@"))
    if names_to_lookup:
        found = roblox_api.resolve_user_ids(names_to_lookup)  # {name_lower: id}
        for name in names_to_lookup:
            uid = found.get(name.lower())
            if uid:
                ids.append(int(uid))
            else:
                unresolved.append(name)
    # Dedup en preservant l'ordre.
    seen, out = set(), []
    for uid in ids:
        if uid not in seen:
            seen.add(uid)
            out.append(uid)
    return out, unresolved


def _active_user_ids() -> tuple[list[int], str | None]:
    """Union des joueurs "actifs" cette semaine = presents aux classements de guerre
    des DEUX factions (meme detection que les recompenses de guerre)."""
    week = roblox_api.fw_week_index()
    all_ids: list[int] = []
    seen = set()
    err = None
    for faction in ("Rainor", "Rusfor"):
        store_name = config.datastore_name(f"FWLB_w{week}_{faction}")
        ids, e = roblox_api.ordered_all_ids(store_name)
        err = err or e
        for uid in ids:
            if uid not in seen:
                seen.add(uid)
                all_ids.append(uid)
    return all_ids, err


def _read_index() -> list:
    try:
        idx = roblox_api.datastore_get(config.FW_DATASTORE, INDEX_KEY)
    except Exception:                                          # noqa: BLE001
        return []
    return idx if isinstance(idx, list) else []


def preview(payload: dict) -> dict:
    """Ce qui SERAIT donne, sans rien ecrire. Resout l'audience et la recompense,
    et RAPPELLE que les items/kits ne se reclament qu'au HUB."""
    audience = str(payload.get("audience") or "users").lower()
    if audience not in AUDIENCES:
        raise GrantError(f"Audience inconnue : {audience} (users | active | online).")

    reward = _build_reward(payload)

    target_ids: list[int] = []
    unresolved: list[str] = []
    resolved: list[dict] = []
    note = None
    if audience == "users":
        target_ids, unresolved = _resolve_users(payload.get("users"))
        if not target_ids:
            raise GrantError("Aucun joueur valide. Rappel : mets le NOM D'UTILISATEUR "
                             "(@pseudo), PAS le nom affiché — ou colle directement l'userId.")
        # Renvoie qui a ete resolu (pseudo -> userId) pour que l'operateur VERIFIE avant
        # d'envoyer : c'est la cause n°1 d'un give sans effet (mauvais joueur ciblé).
        names = roblox_api.resolve_usernames(target_ids)
        resolved = [{"userId": uid, "name": names.get(str(uid), f"#{uid}")} for uid in target_ids]
    elif audience == "active":
        target_ids, err = _active_user_ids()
        if err:
            note = f"Lecture des classements partielle : {err}"
        if not target_ids:
            raise GrantError("Aucun joueur actif cette semaine (classements vides).")
    else:  # online
        note = ("Audience « en ligne » : livraison immediate aux joueurs connectes au "
                "moment de l'envoi. Les joueurs hors ligne ne la recoivent PAS.")

    has_items = bool(reward["kits"] or reward["items"])
    hub_note = ("Les items/kits ne se reclament qu'au HUB (en raid ils seraient effaces) : "
                "l'or et l'XP arrivent partout, les objets attendent le retour au Hub."
                if has_items else None)

    return {
        "audience": audience,
        "reward": reward,
        # Les ids RESOLUS sont renvoyes pour que `give` les REUTILISE au lieu de refaire
        # la resolution (cf. give). C'est ce qui evite qu'un second appel reseau rate
        # transforme un don cible en bordereau sans destinataire.
        "targetIds": target_ids,
        "targetCount": (len(target_ids) if audience != "online" else None),
        "unresolved": unresolved,
        "resolved": resolved,
        "note": note,
        "hubNote": hub_note,
        "maxGold": MAX_GOLD, "maxXP": MAX_XP,
    }


def give(payload: dict, notify_roblox: bool = True) -> dict:
    """Ecrit le bordereau, previent les serveurs (publish), et renvoie le recap."""
    plan = preview(payload)
    audience = plan["audience"]
    reward = plan["reward"]

    now = int(time.time())
    grant = {
        "id": f"g{now}",
        "at": now,
        "audience": audience,
        "reward": reward,
    }
    if audience in ("users", "active"):
        # REUTILISE la resolution du preview -- on ne la REFAIT PAS.
        #
        # Avant, `give` relancait _resolve_users / _active_user_ids, soit un SECOND appel
        # HTTP a l'API Roblox. Or `roblox_api.resolve_user_ids` avale toute exception et
        # renvoie {} : un rate-limit ou une coupure sur ce second appel produisait
        # `userIds = []`. Le bordereau partait alors SANS destinataire, et cote jeu
        # `depositOne` marquait le don comme traite POUR TOUT LE MONDE (grantClaims) --
        # perte definitive, pendant que l'interface affichait « Cadeau envoye » avec le
        # compte issu du preview.
        ids = list(plan.get("targetIds") or [])
        if not ids:
            # Echouer BRUYAMMENT plutot que d'ecrire un bordereau vide : un don sans cible
            # ne peut pas etre rejoue, l'idempotence cote jeu le condamne definitivement.
            raise GrantError(
                "Resolution des destinataires vide : aucun bordereau ecrit. "
                "Verifie les noms d'utilisateur (@pseudo, pas le nom affiche) puis reessaie."
            )
        grant["userIds"] = ids

    # 1) Le bordereau, sous SA PROPRE cle : jamais ecrase.
    roblox_api.datastore_set(config.FW_DATASTORE, f"grant_{grant['id']}", grant)

    # 2) L'index APRES le bordereau (un orphelin est inoffensif ; un index pointant
    #    dans le vide ne l'est pas). On garde les KEEP_GRANTS derniers.
    index = [{"id": grant["id"], "at": now, "audience": audience,
              "count": len(grant.get("userIds") or [])}]
    index += [e for e in _read_index()
              if isinstance(e, dict) and e.get("id") != grant["id"]]
    roblox_api.datastore_set(config.FW_DATASTORE, INDEX_KEY, index[:KEEP_GRANTS])

    # 3) Push : sans ca, "online" raterait tout le monde et users/active attendraient
    #    la prochaine connexion / le sondage.
    applied_now = (audience == "online")
    if notify_roblox:
        roblox_api.publish(config.FW_TOPIC, {"kind": "grant", "id": grant["id"],
                                             "applyNow": applied_now})

    # Copie locale (historique dashboard).
    store.save_settings({"grantLast": {"id": grant["id"], "audience": audience,
                                       "reward": reward, "at": now}})

    return {"ok": True, "grant": {"id": grant["id"], "audience": audience},
            "targetCount": plan.get("targetCount"), "unresolved": plan.get("unresolved"),
            "note": plan.get("note"), "hubNote": plan.get("hubNote")}


# WIPE
def wipe(payload: dict, notify_roblox: bool = True) -> dict:
    """Ecrit un bordereau de WIPE (inventaire courant + equipe + stash) et publie.
    DESTRUCTIF. Audiences 'users' (liste) ou 'online' UNIQUEMENT -- jamais 'active'
    (wiper tous les joueurs actifs de la semaine serait catastrophique). Le wipe
    ne s'applique qu'au HUB cote jeu (un joueur en raid est wipe a son retour)."""
    audience = str(payload.get("audience") or "users").lower()
    if audience not in ("users", "online"):
        raise GrantError("Wipe : audience 'users' (liste) ou 'online' seulement "
                         "(pas 'active' -- trop dangereux).")

    target_ids: list[int] = []
    unresolved: list[str] = []
    if audience == "users":
        target_ids, unresolved = _resolve_users(payload.get("users"))
        if not target_ids:
            raise GrantError("Aucun joueur valide a wiper.")

    now = int(time.time())
    grant = {
        "id": f"w{now}",
        "at": now,
        "audience": audience,
        "kind": "wipe",
    }
    if audience == "users":
        grant["userIds"] = target_ids

    roblox_api.datastore_set(config.FW_DATASTORE, f"grant_{grant['id']}", grant)
    index = [{"id": grant["id"], "at": now, "audience": audience, "kind": "wipe",
              "count": len(target_ids)}]
    index += [e for e in _read_index()
              if isinstance(e, dict) and e.get("id") != grant["id"]]
    roblox_api.datastore_set(config.FW_DATASTORE, INDEX_KEY, index[:KEEP_GRANTS])

    if notify_roblox:
        roblox_api.publish(config.FW_TOPIC, {"kind": "grant", "id": grant["id"],
                                             "applyNow": (audience == "online")})

    return {"ok": True, "wipe": {"id": grant["id"], "audience": audience},
            "targetCount": (len(target_ids) if audience == "users" else None),
            "unresolved": unresolved}
