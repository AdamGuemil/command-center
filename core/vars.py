"""
Variables dynamiques dans les annonces.

Ecris {RUSFOR} dans un modele et il devient le vrai score au moment de
l'envoi. C'est ce qui rend les annonces MODULAIRES : un seul modele
"classement" republiable chaque semaine sans jamais le reediter.

Les variables couteuses (Faction War = 8 lectures DataStore) ne sont
resolues QUE si le texte les utilise reellement.
"""

from __future__ import annotations

import re
import time

from . import config

# Documentation affichee dans le dashboard (panneau d'aide du composeur).
CATALOG = [
    ("{GAME_URL}", "Lien de l'experience Roblox"),
    ("{GAME_NAME}", "Nom du jeu"),
    ("{DISCORD_INVITE}", "Lien d'invitation Discord"),
    ("{PLAYING}", "Joueurs connectes en ce moment"),
    ("{VISITS}", "Nombre total de visites"),
    ("{FAVORITES}", "Nombre de favoris"),
    ("{WEEK}", "Numero de saison AFFICHE (decalage applique)"),
    ("{WEEK_REAL}", "Numero de semaine reel (cle de stockage)"),
    ("{RUSFOR}", "Score Rusfor de la semaine"),
    ("{RAINOR}", "Score Rainor de la semaine"),
    ("{LEADER}", "Faction en tete (ou 'Nobody' si egalite)"),
    ("{SPREAD}", "Ecart entre les deux factions"),
    ("{REMAINING}", "Temps restant avant la fin de la semaine"),
    # Semaine CLOSE : a utiliser pour annoncer un RESULTAT apres la bascule.
    ("{LAST_SEASON}", "Numero de la saison qui vient de se cloturer"),
    ("{LAST_WINNER}", "Faction victorieuse de la saison close"),
    ("{LAST_RUSFOR}", "Score final Rusfor de la saison close"),
    ("{LAST_RAINOR}", "Score final Rainor de la saison close"),
    ("{DATE}", "Date du jour (AAAA-MM-JJ)"),
    ("{IN_24H}", "Echeance dans 24h, en heure locale du lecteur"),
    ("{IN_48H}", "Echeance dans 48h, en heure locale du lecteur"),
    ("{RANKED_TOP}", "Top 10 du ladder ranked, deja formate"),
    # Ces cinq-la ne sont remplies QUE dans l'annonce automatique de boost.
    ("{BOOST_NAME}", "Nom du boost (annonce de boost)"),
    ("{BOOST_XP}", "Multiplicateur XP (annonce de boost)"),
    ("{BOOST_GOLD}", "Multiplicateur or (annonce de boost)"),
    ("{BOOST_WAR}", "Multiplicateur guerre (annonce de boost)"),
    ("{BOOST_ENDS}", "Fin du boost, en heure locale du lecteur"),
]

_FW_KEYS = ("{WEEK}", "{WEEK_REAL}", "{RUSFOR}", "{RAINOR}", "{LEADER}",
            "{SPREAD}", "{REMAINING}")
_GAME_KEYS = ("{PLAYING}", "{VISITS}", "{FAVORITES}")
_RANKED_KEYS = ("{RANKED_TOP}",)
_LAST_KEYS = ("{LAST_SEASON}", "{LAST_WINNER}", "{LAST_RUSFOR}", "{LAST_RAINOR}")


def _fmt_duration(seconds: int) -> str:
    seconds = max(0, int(seconds))
    d, h = seconds // 86400, (seconds % 86400) // 3600
    m = (seconds % 3600) // 60
    if d:
        return f"{d}d {h:02d}h"
    if h:
        return f"{h}h {m:02d}m"
    return f"{m}m"


def build_context(text: str) -> dict:
    """Construit la table de substitution, en ne payant que ce qui sert."""
    ctx = {
        "{GAME_URL}": config.GAME_URL,
        "{GAME_NAME}": config.GAME_NAME,
        "{DISCORD_INVITE}": config.DISCORD_INVITE or "",
        "{DATE}": time.strftime("%Y-%m-%d"),
        # Horodatages Discord relatifs : "<t:UNIX:R>" s'affiche "dans 24 heures"
        # dans la LANGUE et le FUSEAU de chaque lecteur, et se met a jour tout
        # seul. Bien plus fiable qu'ecrire une heure en dur, que la moitie des
        # joueurs interpreterait mal.
        "{IN_24H}": f"<t:{int(time.time()) + 86400}:R>",
        "{IN_48H}": f"<t:{int(time.time()) + 172800}:R>",
    }

    if any(k in text for k in _GAME_KEYS):
        from . import roblox_api
        health = roblox_api.game_health()
        ctx["{PLAYING}"] = str(health.get("playing", "?"))
        ctx["{VISITS}"] = f"{health.get('visits', 0):,}".replace(",", " ")
        ctx["{FAVORITES}"] = f"{health.get('favorites', 0):,}".replace(",", " ")

    if any(k in text for k in _RANKED_KEYS):
        from . import roblox_api
        res = roblox_api.ranked_top(10)
        if res.get("error") or not res["rows"]:
            # Ne jamais publier un classement vide en le faisant passer pour
            # reel : on le dit, l'auteur decide s'il poste quand meme.
            ctx["{RANKED_TOP}"] = "*(classement indisponible)*" if res.get("error") \
                else "*(aucun joueur classé pour le moment)*"
        else:
            medals = {1: "🥇", 2: "🥈", 3: "🥉"}
            lines = []
            for r in res["rows"]:
                badge = medals.get(r["rank"], f"**#{r['rank']}**")
                lines.append(f"{badge} **{r['name']}** — {r['lp']} LP")
            ctx["{RANKED_TOP}"] = "\n".join(lines)

    if any(k in text for k in _LAST_KEYS):
        from . import roblox_api
        arch = roblox_api.faction_war_archive()
        if arch:
            ctx["{LAST_SEASON}"] = str(arch.get("season", "?"))
            ctx["{LAST_WINNER}"] = arch.get("winner") or "Nobody"
            ctx["{LAST_RUSFOR}"] = str(arch.get("Rusfor", 0))
            ctx["{LAST_RAINOR}"] = str(arch.get("Rainor", 0))
        # Sinon on laisse les variables VISIBLES : mieux vaut un message
        # manifestement incomplet qu'un resultat invente a 0-0.

    if any(k in text for k in _FW_KEYS):
        from . import roblox_api, store
        try:
            st = roblox_api.faction_war_state()
            # {WEEK} est un LIBELLE, pas une cle : il doit refleter le decalage
            # d'affichage choisi dans le dashboard, sinon Discord annoncerait
            # "Week 132" pendant que l'interface affiche "Week 2".
            # {WEEK} = numero de SAISON affiche. L'epoque du jeu est calee sur
            # le 05/09/2026 a 18h00 en France, donc la saison 1 tombe juste. Le
            # decalage reste disponible si tu veux renumeroter plus tard.
            offset = int(store.load_settings().get("seasonLabelOffset") or 0)
            ctx["{WEEK}"] = str(st.get("season", st["week"] + 1) - offset)
            ctx["{WEEK_REAL}"] = str(st["week"])
            ctx["{RUSFOR}"] = str(st["totals"]["Rusfor"])
            ctx["{RAINOR}"] = str(st["totals"]["Rainor"])
            ctx["{LEADER}"] = st["leader"] or "Nobody"
            ctx["{SPREAD}"] = str(st["spread"])
            ctx["{REMAINING}"] = _fmt_duration(st["remaining"])
        except Exception:                                      # noqa: BLE001
            # Open Cloud indisponible : on laisse les variables visibles plutot
            # que de poster un message avec des zeros trompeurs.
            pass

    return ctx


def resolve(text: str, extra: dict | None = None) -> str:
    """`extra` : substitutions specifiques a un contexte (ex. les details d'un
    boost qu'on vient d'activer). Elles gagnent sur le catalogue global."""
    if not text:
        return text
    ctx = build_context(text)
    if extra:
        ctx.update(extra)
    for key, value in ctx.items():
        text = text.replace(key, str(value))
    return text


def boost_context(record: dict) -> dict:
    """Substitutions decrivant un boost qu'on vient d'activer."""
    ends = int(record.get("endsAt", 0))
    return {
        "{BOOST_NAME}": record.get("name", "BOOST"),
        "{BOOST_XP}": f"{float(record.get('xpMult', 1)):g}",
        "{BOOST_GOLD}": f"{float(record.get('goldMult', 1)):g}",
        "{BOOST_WAR}": f"{float(record.get('factionPointMult', 1)):g}",
        "{BOOST_DURATION}": _fmt_duration(ends - int(time.time())),
        # Horodatage Discord : s'affiche dans le fuseau de CHAQUE lecteur.
        "{BOOST_ENDS}": f"<t:{ends}:R>",
    }


def unresolved(text: str) -> list[str]:
    """Variables restees non remplacees — le dashboard previent avant l'envoi."""
    known = {k for k, _ in CATALOG}
    return [m for m in re.findall(r"\{[A-Z_]+\}", text or "") if m in known]
