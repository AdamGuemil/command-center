"""
Arsenal — les armes, leurs stats, leur score, leur prix et leur niveau.

POURQUOI ICI. Ces donnees vivaient dans une seconde application (`game-level/`),
avec sa propre page web, son propre serveur et son propre format. Deux outils
pour un seul jeu, c'est deux endroits ou chercher et deux occasions de diverger :
tout est regroupe dans le Command Center.

CE QUI CHANGE PAR RAPPORT A `game-level` :

  * LE NIVEAU ET LE PRIX RESTENT MANUELS. Le Command Center les conserve et
    genere un bloc ShopConfig a versionner ; il ne publie aucune economie live.
  * LE SCORE RESTE CALCULE depuis les stats, avec le meme modele lineaire
    (`scoreModel`, editable). Il situe une arme dans sa categorie et devient son
    rang relatif dans la classe pour aider l'operateur a verifier la progression.
  * LES CATEGORIES SONT CELLES DU JEU (`ShopConfig.WEAPON_CLASSES` : ar, br,
    carbine, smg, lmg, dmr, sniper, shotgun, pistol, mpistol...) et non plus
    des libelles francais propres a l'outil. Un seul vocabulaire.

LES HABITS (`outfits`) SUIVENT LE MEME CHEMIN QUE LES ARMES. Une ligne = une tenue
(haut + bas, memes prix et niveau). Son `source` dit d'ou elle vient : seule la
source `shop` s'achete ; les autres (starters, kits d'abonnement, Mercenary) sont
generees dans `ShopConfig.NO_BUY`. Le bloc Luau est produit ICI (et non dans la
page) pour qu'un test compare le ShopConfig du jeu au JSON.

SOURCE LOCALE. Ce module lit et ecrit le JSON ; il ne contacte jamais Roblox.
La commande Studio relit l'API locale pour les Tools. Le generateur ShopConfig
versionne les prix et niveaux requis. Contrat complet :
`guides/GUIDE_ECONOMIE_ARSENAL.md`.
"""

from __future__ import annotations

import json
from typing import Any

from . import config

ARSENAL_FILE = config.DATA_DIR / "arsenal.json"

# Modele de score par defaut, repris tel quel de `game-level/data/balance.json`
# (regresse sur le roster, R^2 ~ 0.98). Editable depuis la page.
DEFAULT_SCORE_MODEL = {
    "const": 0.0,
    "damage": 0.32,
    "dps": 0.02,
    "rangeStuds": 0.0026,
    "pen": 0.24,
    "stabH": 0.20,
    "stabV": 0.25,
    "poids": -0.012,
}

# Les classes du JEU. Meme liste et meme ordre que ShopConfig.WEAPON_CLASSES :
# c'est la seule facon que les deux ne divergent pas en silence.
CLASSES = [
    {"id": "ar", "label": "Assault Rifles", "hands": 2},
    {"id": "br", "label": "Battle Rifles", "hands": 2},
    {"id": "carbine", "label": "Carbines", "hands": 2},
    {"id": "smg", "label": "SMG", "hands": 2},
    {"id": "lmg", "label": "LMG", "hands": 2},
    {"id": "dmr", "label": "DMR", "hands": 2},
    {"id": "sniper", "label": "Snipers", "hands": 2},
    {"id": "shotgun", "label": "Shotguns", "hands": 2},
    {"id": "launcher", "label": "Launchers", "hands": 2},
    {"id": "pistol", "label": "Pistols", "hands": 1},
    {"id": "revolver", "label": "Revolvers", "hands": 1},
    {"id": "mpistol", "label": "Machine Pistols", "hands": 1},
    {"id": "melee", "label": "Melee", "hands": 1},
]

FACTIONS = ["Neutral", "Rainor", "Rusfor"]
RARITIES = ["Common", "Uncommon", "Rare", "Epic", "Legendary"]

# D'ou vient une tenue. Seule `shop` s'achete : les autres finissent dans NO_BUY.
SOLD_SOURCE = "shop"
OUTFIT_SOURCES = [
    {"id": "shop", "label": "Shop (vendue)"},
    {"id": "starter", "label": "Starter de specialisation"},
    {"id": "subscription", "label": "Kit d'abonnement"},
    {"id": "mercenary", "label": "Kit Mercenary"},
]
OUTFIT_BLOCK_BEGIN = "-- COMMAND_CENTER_OUTFIT_SHOP_BEGIN"
OUTFIT_BLOCK_END = "-- COMMAND_CENTER_OUTFIT_SHOP_END"

# 1 stud ~ 0.28 m, cale sur les donnees de l'ancien outil.
STUDS_TO_M = 0.28


def _empty() -> dict:
    return {"scoreModel": dict(DEFAULT_SCORE_MODEL), "levelMax": 30, "weapons": [], "outfits": []}


def load() -> dict:
    """Lit l'arsenal. Un fichier absent ou casse rend un arsenal VIDE plutot que
    de lever : la page doit s'ouvrir meme sur une installation neuve."""
    if not ARSENAL_FILE.exists():
        return _empty()
    try:
        data = json.loads(ARSENAL_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _empty()
    if not isinstance(data, dict):
        return _empty()
    data.setdefault("scoreModel", dict(DEFAULT_SCORE_MODEL))
    data.setdefault("levelMax", 30)
    data.setdefault("weapons", [])
    data.setdefault("outfits", [])
    return data


def save(data: dict) -> dict:
    """Ecrit l'arsenal et rend ce qui a ete ecrit (avec les scores recalcules)."""
    try:
        level_max = max(30, int(data.get("levelMax") or 30))
    except (TypeError, ValueError):
        level_max = 30

    weapons = [_clean(w) for w in (data.get("weapons") or [])]
    # Une page ouverte avant l'arrivee des habits n'envoie pas la cle `outfits` :
    # la garder plutot que de vider les tenues a sa premiere sauvegarde.
    raw_outfits = data["outfits"] if "outfits" in data else load().get("outfits")
    outfits = _clean_outfits(raw_outfits or [])
    weapon_level_max = max(
        (int(w["level"]) for w in weapons if isinstance(w.get("level"), (int, float))),
        default=1,
    )
    out: dict[str, Any] = {
        "scoreModel": {**DEFAULT_SCORE_MODEL, **(data.get("scoreModel") or {})},
        "levelMax": max(level_max, weapon_level_max),
        "weapons": weapons,
        "outfits": outfits,
    }
    for w in out["weapons"]:
        w["score"] = score_of(w, out["scoreModel"])
    ARSENAL_FILE.parent.mkdir(parents=True, exist_ok=True)
    ARSENAL_FILE.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


NUMERIC = ("damage", "rpm", "rangeStuds", "pen", "stabH", "stabV", "poids",
           "magCap", "price", "level", "utilityFactor", "statFactor")


def _clean(w: dict) -> dict:
    """Normalise une ligne : les nombres restent des nombres, les textes des
    textes. Le navigateur envoie volontiers des chaines vides pour un champ
    efface -- les stocker telles quelles casserait le calcul de score."""
    cls = str(w.get("cls") or "ar")
    # La distinction PDW n'est plus une categorie de shop : les anciennes
    # entrees sont migrees en SMG a la prochaine sauvegarde.
    if cls == "pdw":
        cls = "smg"

    out: dict[str, Any] = {
        "name": str(w.get("name") or "").strip(),
        "cls": cls,
        "faction": str(w.get("faction") or "Neutral"),
        "rarity": str(w.get("rarity") or "Common"),
        "calibre": str(w.get("calibre") or "").strip(),
        "note": str(w.get("note") or "").strip(),
    }
    for k in NUMERIC:
        v = w.get(k)
        if v is None or v == "":
            out[k] = None
        else:
            try:
                f = float(v)
                out[k] = int(f) if f == int(f) else round(f, 3)
            except (TypeError, ValueError):
                out[k] = None
    if out.get("utilityFactor") is None:
        out["utilityFactor"] = 1.0
    return out


# HABITS

OUTFIT_TEXT = ("id", "label", "topTemplate", "topName", "bottomTemplate", "bottomName", "note")
SOURCE_IDS = [s["id"] for s in OUTFIT_SOURCES]


def _whole(value, label: str, minimum: int) -> int | None:
    """Entier >= minimum, ou None pour un champ vide. Contrairement aux armes, une
    valeur invalide est REFUSEE : elle partirait telle quelle dans le ShopConfig."""
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} : nombre attendu") from exc
    if number != int(number) or int(number) < minimum:
        raise ValueError(f"{label} : entier >= {minimum} attendu")
    return int(number)


def _clean_outfit(o: dict) -> dict:
    """Normalise une tenue. Camp, rarete et source sont des valeurs fermees : un
    camp mal ecrit RETIRE l'article du catalogue du jeu, une source inconnue
    vendrait par erreur une tenue de kit."""
    out: dict[str, Any] = {key: str(o.get(key) or "").strip() for key in OUTFIT_TEXT}
    for key, allowed in (("faction", FACTIONS), ("rarity", RARITIES), ("source", SOURCE_IDS)):
        value = str(o.get(key) or allowed[0]).strip()
        if value not in allowed:
            raise ValueError(f"{out['id'] or 'habit'} : {key} inconnu ({value})")
        out[key] = value
    if not out["id"]:
        raise ValueError("Un habit n'a pas d'identifiant")
    out["price"] = _whole(o.get("price"), f"{out['id']} prix", 0)
    out["level"] = _whole(o.get("level"), f"{out['id']} niveau", 1)
    return out


def _clean_outfits(rows: list) -> list[dict]:
    outfits = [_clean_outfit(o) for o in rows]
    ids = [o["id"] for o in outfits]
    duplicated = sorted({i for i in ids if ids.count(i) > 1})
    if duplicated:
        raise ValueError("Identifiant d'habit en double : " + ", ".join(duplicated))
    return outfits


def outfit_pieces(o: dict) -> list[tuple[str, str, str]]:
    """(emplacement, gabarit Studio, _ItemName) du haut puis du bas."""
    return [("top", o.get("topTemplate", ""), o.get("topName", "")),
            ("bottom", o.get("bottomTemplate", ""), o.get("bottomName", ""))]


def outfit_alerts(outfits: list[dict], level_max: int) -> list[dict]:
    """Incoherences des habits. Meme esprit que `alerts` : des avertissements, sauf
    `missing`, `dup` et `level` qui bloquent la copie du bloc ShopConfig (une valeur
    absente ou une cle en double ne donnerait pas ce que l'operateur voit)."""
    out: list[dict] = []
    by_name: dict[str, list[str]] = {}
    by_template: dict[str, list[str]] = {}
    for o in outfits:
        title = f"{o['id']} {o['label']}".strip()
        for slot, template, name in outfit_pieces(o):
            if not template or not name:
                out.append({"kind": "missing", "name": title,
                            "text": f"gabarit ou _ItemName manquant ({slot})"})
            if name:
                by_name.setdefault(name, []).append(o["id"])
            if template:
                by_template.setdefault(template, []).append(o["id"])
        if o["source"] == SOLD_SOURCE:
            if o["price"] is None:
                out.append({"kind": "missing", "name": title, "text": "aucun prix"})
            if o["level"] is None:
                out.append({"kind": "missing", "name": title, "text": "aucun niveau"})
            elif o["level"] > level_max:
                out.append({"kind": "level", "name": title,
                            "text": f"niveau {o['level']} au-dela du niveau max {level_max}"})
    for label, owners in (("_ItemName", by_name), ("gabarit", by_template)):
        for key, ids in owners.items():
            if len(ids) > 1:
                out.append({"kind": "dup", "name": key,
                            "text": f"{label} partage par {', '.join(ids)}"})

    # Vue d'un camp : ses tenues vendues plus les neutres, comme le joueur les voit.
    for faction in ("Rainor", "Rusfor"):
        seen = [o for o in outfits if o["source"] == SOLD_SOURCE
                and o["faction"] in ("Neutral", faction)
                and o["level"] is not None and o["price"] is not None]
        seen.sort(key=lambda o: (o["level"], o["price"]))
        prev = None
        for o in seen:
            if prev and o["price"] < prev["price"]:
                out.append({"kind": "inversion", "name": f"{o['id']} {o['label']}",
                            "faction": faction,
                            "text": f"moins cher que {prev['id']} {prev['label']}, debloque avant"})
            prev = o
    return out


BLOCKING_OUTFIT_ALERTS = ("missing", "dup", "level")


def _lua_string(value: str) -> str:
    escaped = (value.replace("\\", "\\\\").replace('"', '\\"')
               .replace("\r", "\\r").replace("\n", "\\n"))
    return f'"{escaped}"'


def outfit_shop_block(outfits: list[dict], level_max: int) -> dict:
    """Bloc Luau des habits pour ShopConfig, plus ce qui empeche de le copier.

    A coller APRES `ShopConfig.NO_BUY` : prix de toute tenue qui en a un, niveau des
    tenues vendues, NO_BUY des autres. Les balises delimitent ce que le prochain
    export remplace.
    """
    ordered = sorted(outfits, key=lambda o: (
        o["faction"], o["level"] is None, o["level"] or 0, o["id"]))
    prices: list[tuple[str, int]] = []
    levels: list[tuple[str, int]] = []
    locked: list[str] = []
    for o in ordered:
        for _slot, _template, name in outfit_pieces(o):
            if not name:
                continue
            if o["price"] is not None:
                prices.append((name, o["price"]))
            if o["source"] == SOLD_SOURCE:
                if o["level"] is not None:
                    levels.append((name, o["level"]))
            else:
                locked.append(name)

    def table(rows: list[tuple[str, int]]) -> str:
        return "\n".join(f"\t[{_lua_string(name)}] = {value}," for name, value in rows)

    code = "\n".join([
        OUTFIT_BLOCK_BEGIN,
        "-- Genere depuis Command Center > Arsenal > Habits. Ne pas editer a la main :",
        "-- le prochain export remplace tout ce qui se trouve entre les deux balises.",
        "-- A placer apres ShopConfig.NO_BUY. Les habits vendus recoivent prix et niveau ;",
        "-- starters, kits d'abonnement et Mercenary sont ajoutes a NO_BUY.",
        "",
        "for itemName, price in pairs({",
        table(prices),
        "}) do",
        "\tShopConfig.PRICES[itemName] = price",
        "end",
        "",
        "for itemName, requiredLevel in pairs({",
        table(levels),
        "}) do",
        "\tShopConfig.LEVEL_REQ[itemName] = requiredLevel",
        "end",
        "",
        "for _, itemName in ipairs({",
        "\n".join(f"\t{_lua_string(name)}," for name in locked),
        "}) do",
        "\tShopConfig.NO_BUY[itemName] = true",
        "end",
        "",
        OUTFIT_BLOCK_END,
    ])
    issues = [f"{a['name']} : {a['text']}" for a in outfit_alerts(outfits, level_max)
              if a["kind"] in BLOCKING_OUTFIT_ALERTS]
    return {"code": code, "issues": issues}


def dps_of(w: dict) -> float | None:
    """Degats par seconde theoriques : degats x cadence."""
    dmg, rpm = w.get("damage"), w.get("rpm")
    if not dmg or not rpm:
        return None
    return round(dmg * rpm / 60.0, 1)


def score_of(w: dict, model: dict | None = None) -> float | None:
    """Score de puissance, modele lineaire sur les stats.

    Le niveau et le prix restent manuels. Le score situe seulement l'arme dans
    sa categorie pour faciliter l'audit de la progression.
    """
    m = {**DEFAULT_SCORE_MODEL, **(model or {})}
    if w.get("damage") is None:
        return None
    dps = dps_of(w) or 0.0
    s = (m["const"]
         + m["damage"] * (w.get("damage") or 0)
         + m["dps"] * dps
         + m["rangeStuds"] * (w.get("rangeStuds") or 0)
         + m["pen"] * (w.get("pen") or 0)
         + m["stabH"] * (w.get("stabH") or 0)
         + m["stabV"] * (w.get("stabV") or 0)
         + m["poids"] * (w.get("poids") or 0))
    return round(s, 1)


def overview() -> dict:
    """Tout ce dont la page a besoin, en un appel : les armes avec leurs valeurs
    derivees, le modele de score, les listes de choix, et les ALERTES."""
    data = load()
    model = data["scoreModel"]
    weapons = []
    for w in data["weapons"]:
        row = dict(w)
        row["score"] = score_of(w, model)
        row["dps"] = dps_of(w)
        row["rangeM"] = round((w.get("rangeStuds") or 0) * STUDS_TO_M, 1) or None
        weapons.append(row)
    level_max = max(30, int(data.get("levelMax") or 30))
    # Un fichier edite a la main peut contenir une tenue invalide : la page doit
    # quand meme s'ouvrir pour la corriger, d'ou le tri plutot que l'exception.
    outfits = []
    for raw in data.get("outfits") or []:
        try:
            outfits.append(_clean_outfit(raw))
        except ValueError:
            continue
    return {
        "weapons": weapons,
        "scoreModel": model,
        "levelMax": level_max,
        "classes": CLASSES,
        "factions": FACTIONS,
        "rarities": RARITIES,
        "alerts": alerts(weapons),
        "outfits": [{**o, "sold": o["source"] == SOLD_SOURCE} for o in outfits],
        "outfitSources": OUTFIT_SOURCES,
        "outfitAlerts": outfit_alerts(outfits, level_max),
        "outfitShop": outfit_shop_block(outfits, level_max),
    }


def set_outfit_level(outfit_id: str, level: int) -> dict:
    """Deplace une tenue sur la timeline et persiste immediatement son niveau."""
    key = str(outfit_id or "").strip()
    if not key:
        raise ValueError("Identifiant d'habit manquant")
    try:
        clean_level = int(level)
    except (TypeError, ValueError) as exc:
        raise ValueError("Le niveau doit etre un entier") from exc
    if clean_level < 1:
        raise ValueError("Le niveau doit etre superieur ou egal a 1")

    data = load()
    level_max = max(30, int(data.get("levelMax") or 30))
    if clean_level > level_max:
        raise ValueError(f"Le niveau depasse le niveau max ({level_max})")
    for outfit in data.get("outfits") or []:
        if outfit.get("id") == key:
            outfit["level"] = clean_level
            return save(data)
    raise ValueError(f"Habit introuvable : {key}")


def set_level(name: str, level: int) -> dict:
    """Deplace une arme sur la timeline et persiste immediatement son niveau."""
    weapon_name = str(name or "").strip()
    if not weapon_name:
        raise ValueError("Nom d'arme manquant")
    try:
        clean_level = int(level)
    except (TypeError, ValueError) as exc:
        raise ValueError("Le niveau doit etre un entier") from exc
    if clean_level < 1:
        raise ValueError("Le niveau doit etre superieur ou egal a 1")

    data = load()
    for weapon in data.get("weapons") or []:
        if weapon.get("name") == weapon_name:
            weapon["level"] = clean_level
            data["levelMax"] = max(30, int(data.get("levelMax") or 30), clean_level)
            return save(data)
    raise ValueError(f"Arme introuvable : {weapon_name}")


def alerts(weapons: list[dict]) -> list[dict]:
    """Incoherences du reglage manuel. Ce sont des AVERTISSEMENTS, jamais des
    corrections : une arme volontairement chere et faible est un choix legitime.

    Le meme esprit que `/shopaudit` en jeu -- et les memes trois questions :
    est-ce ordonne, y a-t-il des doublons, manque-t-il une valeur.
    """
    out: list[dict] = []
    by_class: dict[str, list[dict]] = {}
    for w in weapons:
        if not w.get("name"):
            continue
        if w.get("price") is None:
            out.append({"kind": "missing", "name": w["name"], "text": "aucun prix"})
        if w.get("level") is None:
            out.append({"kind": "missing", "name": w["name"], "text": "aucun niveau"})
        by_class.setdefault(w.get("cls") or "?", []).append(w)

    for cls, rows in by_class.items():
        # Vue d'un camp : ses armes plus les neutres. C'est ce que le joueur voit.
        for faction in ("Rainor", "Rusfor"):
            seen = [w for w in rows if w.get("faction") in ("Neutral", faction)]
            seen = [w for w in seen if w.get("level") is not None]
            seen.sort(key=lambda w: (w["level"], w.get("score") or 0))
            prev = None
            for w in seen:
                if prev:
                    if w["level"] == prev["level"]:
                        out.append({"kind": "dup", "name": w["name"], "cls": cls,
                                    "faction": faction,
                                    "text": f"meme niveau que {prev['name']}"})
                    if (w.get("score") or 0) < (prev.get("score") or 0):
                        out.append({"kind": "inversion", "name": w["name"], "cls": cls,
                                    "faction": faction,
                                    "text": f"score plus bas que {prev['name']}, debloque avant"})
                prev = w
    return out
