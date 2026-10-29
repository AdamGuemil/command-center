"""
Configuration centralisee du Command Center.

Toutes les valeurs sensibles viennent de VARIABLES D'ENVIRONNEMENT ou du
fichier .env local. Rien n'est jamais code en dur, et rien n'est jamais
expose au navigateur (voir core/discord_api.py : le serveur local fait les
appels, la page web ne voit que des resultats deja filtres).
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# Console Windows en UTF-8 (sinon UnicodeEncodeError sur les emojis)
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
WEB_DIR = ROOT / "web"


def _load_dotenv() -> None:
    """Charge .env s'il existe. Format : CLE=valeur, # pour les commentaires.
    Les vraies variables d'environnement gagnent toujours sur le fichier."""
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_dotenv()


def _get(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


# Discord
DISCORD_BOT_TOKEN = _get("DISCORD_BOT_TOKEN")
DISCORD_GUILD_ID = _get("DISCORD_GUILD_ID")
DISCORD_INVITE = _get("DISCORD_INVITE")

# Roblox
# UNIVERSE_ID != PLACE_ID. L'universe (ou "experience") regroupe les places.
# Open Cloud travaille sur l'universe. Tu le trouves dans Creator Hub >
# ton experience > ... > Copy Universe ID.
ROBLOX_UNIVERSE_ID = _get("ROBLOX_UNIVERSE_ID")
ROBLOX_PLACE_ID = _get("ROBLOX_PLACE_ID")
# Place MATCH/BATTLE : son contrat (CC_Contract) est lu a cote de celui du HUB.
ROBLOX_GAME_PLACE_ID = _get("ROBLOX_GAME_PLACE_ID")
ROBLOX_OPENCLOUD_KEY = _get("ROBLOX_OPENCLOUD_KEY")
# Notifications joueurs : les Asset IDs des textes du Creator Hub vivent dans
# data/notifications.json, saisis depuis l'ecran Diffusion > Notifications (core/notify.py).

GAME_NAME = _get("GAME_NAME", "Shroud War")
GAME_URL = _get("ROBLOX_GAME_URL", f"https://www.roblox.com/games/{ROBLOX_PLACE_ID}" if ROBLOX_PLACE_ID else "")

# Depot du jeu (facultatif) : dossier qui contient HUB/ et GAME/. Sert a lire la version des
# donnees et a afficher ses guides dans l'ecran Guide.
GAME_ROOT = Path(_get("CC_GAME_ROOT")).expanduser() if _get("CC_GAME_ROOT") else None

# Serveur local
HOST = _get("CC_HOST", "127.0.0.1")
PORT = int(_get("CC_PORT", "8787") or 8787)
OPEN_BROWSER = _get("CC_OPEN_BROWSER", "1") != "0"   # 0 dans un conteneur
WATCH = _get("CC_WATCH", "1") != "0"                 # veilleur live (0 : tests)
BOT = _get("CC_BOT") in ("1", "true", "yes")          # bot Discord dans le meme processus

# Constantes partagees avec le jeu
# La version des donnees (SharedConfig.DS_VERSION) prefixe tous les magasins. Ordre :
#   1. CC_DATASTORE_VERSION, explicite ;
#   2. SharedConfig.luau du depot du jeu (CC_GAME_ROOT, ou un dossier parent qui contient HUB/) ;
#   3. valeur par defaut. Le contrat publie par le jeu (CC_Contract, ecran Sante et Live)
#      signale toute difference : le CC ne devine jamais en silence.
def _game_datastore_version() -> tuple[str, str]:
    explicit = _get("CC_DATASTORE_VERSION")
    if explicit:
        return explicit, "CC_DATASTORE_VERSION"
    project = GAME_ROOT or next((p for p in ROOT.parents if (p / "HUB").is_dir()), None)
    if project is None:
        return "SW_DEV_1", "valeur par defaut"
    # HUB fait foi pour les jumeaux : on lit sa copie, GAME n'est qu'un repli.
    for place in ("HUB", "GAME"):
        shared = project / place / "ReplicatedStorage/Systems/Core/SharedConfig.luau"
        try:
            source = shared.read_text(encoding="utf-8")
        except OSError:
            continue
        match = re.search(r'SharedConfig\.DS_VERSION\s*=\s*"([^"]+)"', source)
        if match:
            return match.group(1), str(shared)
    return "SW_DEV_1", "valeur par defaut"


DATASTORE_VERSION, DATASTORE_VERSION_SOURCE = _game_datastore_version()


def datastore_name(base: str) -> str:
    """Miroir de SharedConfig.dsName(base)."""
    return f"{base}_{DATASTORE_VERSION}"


# Autres contrats du pont Open Cloud. Sources : EventService / EventConfig.
FW_DATASTORE = datastore_name("FactionWar")
FW_OVERRIDE_KEY = "event_override"
FW_TOPIC = "FW_Event"
EVENT_MAX_MULT = 5.0
EVENT_MAX_MINUTES = 20160  # 14 jours

FACTIONS = ("Rusfor", "Rainor")

COLORS = {
    "rusfor": 0xD63031,
    "rainor": 0x2980B9,
    "neutral": 0x5865F2,
    "gold": 0xF1C40F,
    "green": 0x2ECC71,
    "orange": 0xE67E22,
    "red": 0xE74C3C,
}


def missing_secrets() -> list[str]:
    """Liste ce qui manque pour que TOUT fonctionne. Sert au panneau d'etat :
    on veut dire precisement quoi brancher, pas juste 'erreur'."""
    gaps = []
    if not DISCORD_BOT_TOKEN:
        gaps.append("DISCORD_BOT_TOKEN")
    if not DISCORD_GUILD_ID:
        gaps.append("DISCORD_GUILD_ID")
    if not ROBLOX_OPENCLOUD_KEY:
        gaps.append("ROBLOX_OPENCLOUD_KEY")
    if not ROBLOX_UNIVERSE_ID:
        gaps.append("ROBLOX_UNIVERSE_ID")
    return gaps
