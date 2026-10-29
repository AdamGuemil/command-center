"""
Recompenses de fin de semaine, editables depuis le dashboard.

MODELE : FactionWarConfig.luau reste la VALEUR PAR DEFAUT et le filet de
securite. Ce module ecrit une SURCHARGE dans le DataStore ; le jeu la lit au
demarrage et a chaque push MessagingService. Supprimer la surcharge fait
revenir aux valeurs du fichier -- il n'y a donc aucun etat "casse" possible.

DOUBLE VALIDATION, volontairement redondante :
  * ici, pour echouer tot et expliquer clairement a l'utilisateur ;
  * dans FactionWarConfig.ApplyOverride, parce que le jeu ne doit jamais faire
    confiance a une valeur venue du reseau.
Les plafonds des deux cotes DOIVENT rester identiques (voir MAX_* ci-dessous
et FactionWarConfig.MAX_REWARD_*).
"""

from __future__ import annotations

from typing import Any

from . import config, roblox_api, store

REWARDS_KEY = "rewards_override"

# Miroirs de FactionWarConfig.MAX_REWARD_GOLD / MAX_REWARD_XP.
MAX_GOLD = 50000
MAX_XP = 25000
# Miroir de FactionWarConfig.MAX_REWARD_BADGES.
MAX_BADGES = 5

TIERS = ("1", "2", "3", "4")
TIER_NAMES = {"1": "RECRUE", "2": "SOLDAT", "3": "VETERAN", "4": "HEROS"}

# Valeurs par defaut, RECOPIEES de FactionWarConfig.luau.
#
# ⚠️ A RESYNCHRONISER a la main si tu edites le fichier Luau : ce module ne
# lit pas le Luau. Une divergence ferait afficher au dashboard de fausses
# "valeurs du jeu" -- et le bouton "Revenir aux valeurs du jeu" les montrerait
# comme si c'etait ce que le jeu applique.
# Derniere synchro : paliers 1/700/2000/5000, LOSER_RATIO 0.5.
DEFAULTS: dict[str, Any] = {
    "rewards": {
        "1": {"gold": 500,  "xp": 500,  "kit": "", "badges": []},
        "2": {"gold": 1500, "xp": 1000, "kit": "", "badges": []},
        "3": {"gold": 4000, "xp": 2000, "kit": "kit_war_supply", "badges": []},
        "4": {"gold": 9000, "xp": 4000, "kit": "kit_war_elite", "badges": []},
    },
    "rankBonuses": [
        {"maxRank": 1,  "gold": 10000, "xp": 5000, "title": "S%d CHAMPION"},
        {"maxRank": 3,  "gold": 6000,  "xp": 3000, "title": "S%d ELITE"},
        {"maxRank": 10, "gold": 3000,  "xp": 1500, "title": "S%d TOP 10"},
    ],
    "loserRatio": 0.5,
}


class RewardError(Exception):
    """Erreur de validation, message destine a l'utilisateur."""


def _badges(value, label):
    """Liste d'ids de badges. Accepte "123, 456" ou [123, 456].
    Un badge Roblox se cree A LA MAIN dans le Creator Hub (aucune API) et
    coute 100 Robux : on valide donc juste que ce sont des ids plausibles."""
    if value in (None, "", []):
        return []
    if isinstance(value, str):
        value = [v for v in value.replace(";", ",").split(",") if v.strip()]
    if not isinstance(value, list):
        raise RewardError(f"{label} : liste de badges invalide.")
    out = []
    for raw in value:
        try:
            n = int(str(raw).strip())
        except (TypeError, ValueError):
            raise RewardError(f"{label} : « {raw} » n'est pas un id de badge.") from None
        if n <= 0:
            raise RewardError(f"{label} : id de badge invalide ({n}).")
        if n not in out:
            out.append(n)
    if len(out) > MAX_BADGES:
        raise RewardError(f"{label} : {len(out)} badges, maximum {MAX_BADGES}.")
    return out


def _int_in(value, low, high, label):
    try:
        n = int(float(value))
    except (TypeError, ValueError):
        raise RewardError(f"{label} : « {value} » n'est pas un nombre.") from None
    if n < low or n > high:
        raise RewardError(f"{label} : {n} hors bornes ({low}–{high}).")
    return n


def validate(payload: dict) -> dict:
    """Valide et normalise une surcharge. Leve RewardError avec un message
    precis -- l'utilisateur doit savoir QUEL champ pose probleme."""
    if not isinstance(payload, dict):
        raise RewardError("Payload invalide.")

    rewards: dict[str, Any] = {}
    src = payload.get("rewards") or {}
    for tier in TIERS:
        row = src.get(tier) or {}
        name = TIER_NAMES[tier]
        rewards[tier] = {
            "gold": _int_in(row.get("gold", DEFAULTS["rewards"][tier]["gold"]),
                            0, MAX_GOLD, f"Palier {name} — or"),
            "xp": _int_in(row.get("xp", DEFAULTS["rewards"][tier]["xp"]),
                          0, MAX_XP, f"Palier {name} — XP"),
            "kit": str(row.get("kit") or "").strip(),
            "badges": _badges(row.get("badges"), f"Palier {name} — badges"),
        }

    bonuses = []
    for i, b in enumerate(payload.get("rankBonuses") or [], start=1):
        bonuses.append({
            "maxRank": _int_in(b.get("maxRank", 1), 1, 1000, f"Bonus #{i} — rang max"),
            "gold": _int_in(b.get("gold", 0), 0, MAX_GOLD, f"Bonus #{i} — or"),
            "xp": _int_in(b.get("xp", 0), 0, MAX_XP, f"Bonus #{i} — XP"),
            "title": str(b.get("title") or "").strip(),
            "badges": _badges(b.get("badges"), f"Bonus #{i} — badges"),
        })
    if not bonuses:
        bonuses = DEFAULTS["rankBonuses"]
    # Meme tri que cote Luau : RankBonusFor prend le premier palier ou
    # rank <= maxRank, donc un ordre decroissant donnerait au top 1 la
    # recompense du top 10.
    bonuses.sort(key=lambda b: b["maxRank"])

    ratio = payload.get("loserRatio", DEFAULTS["loserRatio"])
    try:
        ratio = float(ratio)
    except (TypeError, ValueError):
        raise RewardError("Ratio perdant : valeur non numerique.") from None
    if not (0 <= ratio <= 1):
        raise RewardError(f"Ratio perdant : {ratio} doit etre entre 0 et 1.")

    return {"rewards": rewards, "rankBonuses": bonuses, "loserRatio": ratio}


def get() -> dict:
    """Surcharge courante. -> { values, overridden, error, source }

    COPIE LOCALE : chaque application est aussi ecrite dans data/settings.json.
    Si Open Cloud est injoignable, on reaffiche CE que tu as saisi plutot que
    les valeurs par defaut -- sinon l'interface donnerait l'impression que ton
    travail est perdu, et tu le ressaisirais pour rien.
    """
    local = store.load_settings().get("rewardsLast")
    base = {"maxGold": MAX_GOLD, "maxXP": MAX_XP, "defaults": DEFAULTS}

    try:
        stored = roblox_api.datastore_get(config.FW_DATASTORE, REWARDS_KEY)
    except Exception as exc:                                   # noqa: BLE001
        if isinstance(local, dict):
            return {"values": local, "overridden": True, "source": "local",
                    "error": f"{exc} — affichage de ta dernière saisie locale.",
                    **base}
        return {"values": DEFAULTS, "overridden": False, "source": "defaults",
                "error": str(exc), **base}

    if isinstance(stored, dict):
        return {"values": stored, "overridden": True, "source": "remote",
                "error": None, **base}
    return {"values": DEFAULTS, "overridden": False, "source": "defaults",
            "error": None, **base}


def set_override(payload: dict) -> dict:
    clean = validate(payload)
    # Copie locale AVANT l'ecriture distante : si Open Cloud echoue, ta saisie
    # n'est pas perdue et sera reaffichee telle quelle.
    store.save_settings({"rewardsLast": clean})
    roblox_api.datastore_set(config.FW_DATASTORE, REWARDS_KEY, clean)
    # Sans ce push, le changement n'arriverait qu'au prochain demarrage serveur.
    roblox_api.publish(config.FW_TOPIC, {"kind": "rewards"})
    return clean


def clear_override() -> None:
    """Supprime la surcharge : le jeu revient aux valeurs de FactionWarConfig."""
    store.save_settings({"rewardsLast": None})
    roblox_api.datastore_delete(config.FW_DATASTORE, REWARDS_KEY)
    roblox_api.publish(config.FW_TOPIC, {"kind": "rewards"})
