"""
Acces a la console : connexion Discord OAuth2, sessions, roles, CSRF, limite de debit.

Deux modes :
  * LOCAL (aucun DISCORD_CLIENT_ID / SECRET) : pas de connexion. Le CC n'ecoute alors que sur
    la boucle locale (server.py refuse le reste) et l'en-tete Host doit etre localhost, ce qui
    bloque le DNS rebinding. Toutes les ecritures exigent quand meme l'en-tete X-CC-CSRF : une
    page tierce ouverte dans le navigateur ne peut pas l'envoyer sans preflight CORS, refuse.
  * HEBERGE : connexion « Se connecter avec Discord » (scope identify seulement). L'acces est
    une liste d'identifiants Discord par role, dans l'environnement :
        CC_ADMINS   tout, y compris wipe, dons, retraits, effacement RTBF, automatisations ;
        CC_MODS     lire, message aux joueurs, kick, reporter ou ignorer une carte ;
        CC_VIEWERS  lecture seule.
    Le role est relu a CHAQUE requete : retirer un identifiant coupe l'acces immediatement,
    sessions ouvertes comprises.

Session : jeton aleatoire de 256 bits dans un cookie HttpOnly, Secure (en HTTPS),
SameSite=Strict, prefixe __Host-. La base ne garde que son empreinte SHA-256 : une copie de
cc.db ne permet pas de se connecter. Expiration glissante (CC_SESSION_DAYS, 30 j par defaut).
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import config, db

ROLES = ("viewer", "mod", "admin")
RANK = {r: i for i, r in enumerate(ROLES)}
ROLE_LABEL = {"viewer": "Lecture", "mod": "Modérateur", "admin": "Administrateur"}

AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
TOKEN_URL = "https://discord.com/api/oauth2/token"
ME_URL = "https://discord.com/api/users/@me"

CSRF_HEADER = "x-cc-csrf"
STATE_COOKIE = "cc_oauth"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
TOUCH_EVERY_S = 3600

# Ecritures permises en dessous d'administrateur. Tout le reste est reserve aux admins.
PREVIEW_POST = {"/api/preview", "/api/cards/preview", "/api/notify/preview", "/api/give/preview"}
MOD_POST = PREVIEW_POST | {"/api/cmd", "/api/cards/state", "/api/todo", "/api/automations/cancel"}
MOD_CMD_OPS = {"toast", "kick"}

# Jeton CSRF du mode local : un par processus, lu par la page via /api/me (meme origine).
LOCAL_CSRF = secrets.token_urlsafe(24)
LOCAL_USER = {"id": 0, "name": "local", "avatar": None, "role": "admin", "csrf": LOCAL_CSRF, "local": True}


class AuthError(Exception):
    """Echec de connexion, message lisible."""


def enabled() -> bool:
    return bool(config.DISCORD_CLIENT_ID and config.DISCORD_CLIENT_SECRET)


def is_loopback(host: str) -> bool:
    host = (host or "").strip("[]").lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def startup_problems(host: str) -> list[str]:
    """Ce qui empeche de demarrer sans risque. Vide = on peut ecouter."""
    if not enabled():
        if not is_loopback(host):
            return [f"CC_HOST={host} expose la console sans connexion. Configure DISCORD_CLIENT_ID, "
                    "DISCORD_CLIENT_SECRET, CC_PUBLIC_URL et CC_ADMINS (docs/OPERATIONS.md, "
                    "« Héberger »), ou remets CC_HOST=127.0.0.1."]
        return []
    out = []
    if not config.PUBLIC_URL:
        out.append("CC_PUBLIC_URL manquant (adresse publique, ex. https://cc.exemple.fr) : "
                   "Discord y renvoie apres la connexion.")
    elif not config.PUBLIC_URL.startswith("https://") and not is_loopback(
            urllib.parse.urlsplit(config.PUBLIC_URL).hostname or ""):
        out.append("CC_PUBLIC_URL doit etre en https:// (sinon le cookie de session circule en clair).")
    if not config.ADMINS:
        out.append("CC_ADMINS vide : personne ne pourrait se connecter. Mets ton identifiant Discord.")
    return out


def secure_cookies() -> bool:
    return config.PUBLIC_URL.startswith("https://")


def session_cookie() -> str:
    # __Host- : le navigateur refuse le cookie s'il n'est pas Secure, sans Domain, Path=/.
    return "__Host-cc" if secure_cookies() else "cc_session"


def role_for(user_id: int) -> str | None:
    uid = int(user_id)
    if uid in config.ADMINS:
        return "admin"
    if uid in config.MODS:
        return "mod"
    if uid in config.VIEWERS:
        return "viewer"
    return None


def actor(user: dict | None) -> str:
    if not user or user.get("local"):
        return "local"
    return f"{user.get('name') or '?'} ({user.get('id')})"


# POLITIQUE ---------------------------------------------------------------------------
def check(role: str, method: str, path: str) -> str | None:
    """None si permis, sinon le message de refus (403)."""
    if method in ("GET", "HEAD"):
        return None
    if role == "admin":
        return None
    allowed = MOD_POST if role == "mod" else PREVIEW_POST
    if path in allowed:
        return None
    return ("Réservé aux administrateurs." if role == "mod"
            else "Accès en lecture seule : cette action est réservée à l'équipe.")


def check_cmd(role: str, op: str) -> str | None:
    if role == "admin" or (role == "mod" and op in MOD_CMD_OPS):
        return None
    return "Un modérateur peut envoyer un message ou kicker ; le reste est réservé aux administrateurs."


def permissions(role: str) -> dict:
    return {"write": role in ("mod", "admin"), "admin": role == "admin",
            "cmdOps": sorted(MOD_CMD_OPS) if role == "mod" else (["*"] if role == "admin" else [])}


# SESSIONS ----------------------------------------------------------------------------
def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def ttl_s() -> int:
    return max(1, config.SESSION_DAYS) * 86400


def create_session(user: dict, ip: str = "", agent: str = "") -> str:
    token = secrets.token_urlsafe(32)
    db.add_session(_hash(token), int(user["id"]), str(user.get("name") or ""), user.get("avatar"),
                   secrets.token_urlsafe(24), ttl_s(), ip, agent)
    return token


def resolve(token: str | None) -> dict | None:
    """Session valide -> utilisateur avec son role ACTUEL ; sinon None."""
    if not token or len(token) > 200:
        return None
    sid = _hash(token)
    row = db.get_session(sid)
    if not row:
        return None
    role = role_for(row["user_id"])
    if role is None:                     # retire des listes depuis la connexion
        db.delete_session(sid)
        return None
    if time.time() - row["seen"] > TOUCH_EVERY_S:
        db.touch_session(sid, ttl_s())
    return {"id": row["user_id"], "name": row["name"], "avatar": row["avatar"], "role": role,
            "csrf": row["csrf"], "sid": sid, "local": False}


def end_session(token: str | None) -> None:
    if token:
        db.delete_session(_hash(token))


def csrf_ok(user: dict, header: str | None) -> bool:
    return bool(header) and secrets.compare_digest(str(header), str(user.get("csrf") or ""))


# DISCORD OAUTH2 ----------------------------------------------------------------------
def redirect_uri() -> str:
    return f"{config.PUBLIC_URL}/auth/callback"


def new_state() -> str:
    return secrets.token_urlsafe(24)


def authorize_url(state: str) -> str:
    q = urllib.parse.urlencode({"client_id": config.DISCORD_CLIENT_ID, "redirect_uri": redirect_uri(),
                                "response_type": "code", "scope": "identify", "state": state,
                                "prompt": "none"})
    return f"{AUTHORIZE_URL}?{q}"


def _http(req: urllib.request.Request) -> dict:
    req.add_header("User-Agent", "ShroudWarCommandCenter (https://github.com, 1.0)")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8") or "{}")
            return data if isinstance(data, dict) else {}
    except urllib.error.HTTPError as exc:
        raise AuthError(f"Discord a refusé la connexion (HTTP {exc.code}).") from exc
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise AuthError("Discord ne répond pas. Réessaie dans un instant.") from exc


def exchange(code: str) -> dict:
    """Code d'autorisation -> profil Discord {id, name, avatar}. Le jeton Discord est jete."""
    if not code or len(code) > 200:
        raise AuthError("Code de connexion invalide.")
    body = urllib.parse.urlencode({"grant_type": "authorization_code", "code": code,
                                   "redirect_uri": redirect_uri(), "client_id": config.DISCORD_CLIENT_ID,
                                   "client_secret": config.DISCORD_CLIENT_SECRET}).encode("ascii")
    tok = _http(urllib.request.Request(TOKEN_URL, data=body, method="POST",
                                       headers={"Content-Type": "application/x-www-form-urlencoded"}))
    access = tok.get("access_token")
    if not access:
        raise AuthError("Discord n'a pas fourni de jeton.")
    me = _http(urllib.request.Request(ME_URL, headers={"Authorization": f"Bearer {access}"}))
    uid = str(me.get("id") or "")
    if not uid.isdigit():
        raise AuthError("Profil Discord illisible.")
    avatar = (f"https://cdn.discordapp.com/avatars/{uid}/{me['avatar']}.png?size=64"
              if me.get("avatar") else None)
    return {"id": int(uid), "name": str(me.get("global_name") or me.get("username") or uid)[:80],
            "avatar": avatar}


# LIMITE DE DEBIT ---------------------------------------------------------------------
class RateLimiter:
    """Seau a jetons par cle (utilisateur ou IP). En memoire : un seul processus."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buckets: dict[str, tuple[float, float]] = {}

    def allow(self, key: str, per_minute: int, burst: int, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        rate = per_minute / 60.0
        with self._lock:
            tokens, last = self._buckets.get(key, (float(burst), now))
            tokens = min(float(burst), tokens + (now - last) * rate)
            ok = tokens >= 1.0
            self._buckets[key] = (tokens - 1.0 if ok else tokens, now)
            if len(self._buckets) > 5000:            # garde-fou memoire
                self._buckets = dict(list(self._buckets.items())[-1000:])
            return ok


LIMITS = {"write": (60, 20), "auth": (10, 10), "webhook": (300, 100)}
limiter = RateLimiter()


def rate_ok(kind: str, key: str) -> bool:
    per_minute, burst = LIMITS[kind]
    return limiter.allow(f"{kind}:{key}", per_minute, burst)
