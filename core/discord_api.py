"""
Client REST Discord — stdlib uniquement (aucun pip install).

POURQUOI PAS discord.py ICI : envoyer un message ne demande QUE l'API REST.
discord.py ouvre une connexion gateway (websocket) qui prend ~5 s a s'etablir
et ne sert a rien pour un simple POST. En REST pur, une annonce part en ~300 ms
et le script n'a aucune dependance.

(setup_discord.py garde discord.py : construire un serveur entier demande
beaucoup plus que du REST brut.)
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from . import config

API = "https://discord.com/api/v10"


class DiscordError(Exception):
    """Erreur d'appel Discord, avec un message deja lisible par un humain."""


def _request(method: str, path: str, payload: dict | None = None) -> dict | list | None:
    if not config.DISCORD_BOT_TOKEN:
        raise DiscordError("DISCORD_BOT_TOKEN absent (voir .env)")

    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        f"{API}{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Bot {config.DISCORD_BOT_TOKEN}",
            "Content-Type": "application/json",
            "User-Agent": "ShroudWarCommandCenter (local, 1.0)",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        if exc.code == 401:
            raise DiscordError(
                "Token invalide (401). Regenere-le dans le Developer Portal."
            ) from exc
        if exc.code == 403:
            raise DiscordError(
                "Permissions insuffisantes (403). Le bot a besoin de : Voir le "
                "salon, Envoyer des messages, Integrer des liens, et Mentionner "
                "@everyone si tu utilises un ping."
            ) from exc
        if exc.code == 404:
            raise DiscordError("Ressource introuvable (404) : salon ou serveur inexistant.") from exc
        if exc.code == 429:
            raise DiscordError("Rate limit Discord (429). Reessaie dans quelques secondes.") from exc
        raise DiscordError(f"HTTP {exc.code} : {detail}") from exc
    except urllib.error.URLError as exc:
        raise DiscordError(f"Reseau indisponible : {exc.reason}") from exc


# ---------------------------------------------------------------- LECTURE ---
def get_guild() -> dict:
    return _request("GET", f"/guilds/{config.DISCORD_GUILD_ID}?with_counts=true")  # type: ignore[return-value]


def get_channels() -> list[dict]:
    """Salons texte/annonces, tries par position, avec leur categorie."""
    raw = _request("GET", f"/guilds/{config.DISCORD_GUILD_ID}/channels") or []
    cats = {c["id"]: c["name"] for c in raw if c.get("type") == 4}
    # 0 = texte, 5 = annonces, 15 = forum
    out = [
        {
            "id": c["id"],
            "name": c["name"],
            "type": c.get("type"),
            "category": cats.get(c.get("parent_id"), ""),
            "position": c.get("position", 0),
            "is_news": c.get("type") == 5,
        }
        for c in raw
        if c.get("type") in (0, 5, 15)
    ]
    out.sort(key=lambda c: (c["category"], c["position"]))
    return out


def get_roles() -> list[dict]:
    raw = _request("GET", f"/guilds/{config.DISCORD_GUILD_ID}/roles") or []
    return sorted(
        [
            {"id": r["id"], "name": r["name"], "color": r.get("color", 0)}
            for r in raw
            if r["name"] != "@everyone"
        ],
        key=lambda r: r["name"].lower(),
    )


def get_bot() -> dict:
    return _request("GET", "/users/@me")  # type: ignore[return-value]


# ---------------------------------------------------------------- ECRITURE --
def resolve_channel_mentions(text: str, channels: list[dict]) -> str:
    """Remplace les <#nom-de-salon> par de vraies mentions <#id> cliquables.
    Discord n'accepte que des IDs : sans ca le message afficherait
    litteralement "<#choose-your-faction>"."""
    import re

    by_name = {c["name"].lower(): c["id"] for c in channels}

    def sub(match):
        name = match.group(1)
        if name.isdigit():
            return match.group(0)
        cid = by_name.get(name.lower())
        return f"<#{cid}>" if cid else f"#{name}"

    return re.sub(r"<#([A-Za-z0-9_\-]+)>", sub, text)


def find_channel_ref(ref: str, channels: list[dict]) -> dict | None:
    """Trouve un salon a partir d'une reference.

    Deux formes acceptees :
      "general"                       -> par nom (premier trouve)
      "RUSFOR/faction-announcements"  -> nom QUALIFIE par sa categorie

    La seconde est INDISPENSABLE ici : les deux factions ont chacune un salon
    nomme "faction-announcements". Sans qualification, on posterait toujours
    dans celui de la premiere faction trouvee.
    """
    ref = (ref or "").strip().lstrip("#")
    if not ref:
        return None
    if "/" in ref:
        cat, name = ref.split("/", 1)
        cat, name = cat.strip().lower(), name.strip().lower()
        for c in channels:
            if c["name"].lower() == name and cat in (c["category"] or "").lower():
                return c
        return None
    for c in channels:
        if c["name"].lower() == ref.lower():
            return c
    return None


def build_embed(title: str, body: str, color: int, footer: str = "",
                image: str = "") -> dict:
    embed: dict = {"description": body, "color": int(color)}
    if title:
        embed["title"] = title
    if footer:
        embed["footer"] = {"text": footer}
    if image:
        embed["image"] = {"url": image}
    return embed


# Salon d'AUDIT : chaque action de pilotage (give / boost / publication de config)
# y laisse une trace. Indispensable quand plusieurs personnes ont acces au dashboard.
OPS_LOG_CHANNEL = "ops-log"


def post_ops_log(title: str, body: str, color: int = 0x5865F2) -> dict:
    """Poste une entree d'audit dans #ops-log. BEST-EFFORT : ne leve jamais -- un
    echec d'audit ne doit pas faire echouer l'action pilotee. Renvoie {sent, error?}."""
    try:
        channels = get_channels()
        ch = find_channel_ref(OPS_LOG_CHANNEL, channels)
        if not ch:
            return {"sent": False, "error": f"salon #{OPS_LOG_CHANNEL} introuvable "
                    "(cree-le, ou relance setup_discord.py)"}
        send_message(ch["id"], build_embed(title, body, color, footer="Command Center"))
        return {"sent": True, "channel": OPS_LOG_CHANNEL}
    except Exception as exc:                                    # noqa: BLE001
        return {"sent": False, "error": str(exc)}


def send_message(channel_id: str, embed: dict, ping: str = "",
                 publish: bool = False) -> dict:
    """Poste un embed. `ping` : "" | "everyone" | "here" | id de role."""
    content = ""
    allowed: dict = {"parse": []}
    if ping == "everyone":
        content, allowed = "@everyone", {"parse": ["everyone"]}
    elif ping == "here":
        content, allowed = "@here", {"parse": ["everyone"]}
    elif ping:
        content, allowed = f"<@&{ping}>", {"roles": [ping]}

    payload = {"embeds": [embed], "allowed_mentions": allowed}
    if content:
        payload["content"] = content

    msg: dict | None = _request("POST", f"/channels/{channel_id}/messages", payload)  # type: ignore[assignment]

    if publish and msg:
        try:
            _request("POST", f"/channels/{channel_id}/messages/{msg['id']}/crosspost")
            msg["published"] = True
        except DiscordError:
            # Salon non-Annonces : l'echec du crosspost ne doit pas faire
            # croire que le message n'est pas parti.
            msg["published"] = False
    return msg or {}


def recent_messages(channel_id: str, limit: int = 50) -> list[dict]:
    return _request("GET", f"/channels/{channel_id}/messages?limit={limit}") or []  # type: ignore[return-value]
