"""
Pont vers l'API Open Cloud "Configs" (create.roblox.com/docs/production/configs).

Permet d'editer les CONFIGS LIVE de l'experience (valeurs modifiables sans republier)
depuis le dashboard : lire le publie et le brouillon, ecrire le brouillon, PUBLIER,
lister et restaurer des revisions.

ATTENTION — API RECENTE. Le schema exact des corps de requete n'est pas encore
stabilise dans la doc publique. On envoie ce qui est documente et on REMONTE
FIDELEMENT le message d'erreur de Roblox (au lieu d'echouer en silence) : si une
requete est rejetee, tu vois pourquoi, et on ajuste. Les LECTURES (GET) sont sures.

SCOPE de cle Open Cloud : la page create.roblox.com/docs ne nomme pas encore le scope
precis ; il faut l'ajouter dans Creator Hub > Open Cloud > API Keys pour cet univers.
En cas de 403, le message ci-dessous le rappelle.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from . import config

BASE = "https://apis.roblox.com/creator-configs-public-api/v1/configs"

# Repository = espace de noms de config. Roblox en fournit un par defaut ; "live"
# est le nom courant. Surchargeable si besoin.
DEFAULT_REPO = "live"


class ConfigError(Exception):
    """Erreur d'appel Configs, message destine a l'utilisateur."""


def _url(repo: str, suffix: str = "") -> str:
    return (f"{BASE}/universes/{config.ROBLOX_UNIVERSE_ID}"
            f"/repositories/{repo}{suffix}")


def _request(method: str, url: str, body: dict | None = None):
    if not config.ROBLOX_OPENCLOUD_KEY:
        raise ConfigError("ROBLOX_OPENCLOUD_KEY absent (voir .env).")
    if not config.ROBLOX_UNIVERSE_ID:
        raise ConfigError("ROBLOX_UNIVERSE_ID absent (voir .env).")

    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"x-api-key": config.ROBLOX_OPENCLOUD_KEY,
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        if exc.code == 401:
            raise ConfigError("Cle Open Cloud invalide (401).") from exc
        if exc.code == 403:
            raise ConfigError(
                "Cle Open Cloud sans le scope Configs (403). Ajoute la permission "
                "'Configs' (ou le scope indique par Roblox) a ta cle Open Cloud, "
                "sur CET univers, dans Creator Hub > Open Cloud > API Keys. "
                f"Detail : {detail}") from exc
        if exc.code == 404:
            raise ConfigError(
                f"Introuvable (404) : le repository '{DEFAULT_REPO}' existe-t-il ? "
                f"Cree au moins une config dans Creator Hub > Configs. Detail : {detail}"
            ) from exc
        raise ConfigError(f"HTTP {exc.code} : {detail}") from exc
    except urllib.error.URLError as exc:
        raise ConfigError(f"Reseau indisponible : {exc.reason}") from exc


# LECTURES
def get_published(repo: str = DEFAULT_REPO) -> dict:
    """Valeurs actuellement EN LIGNE (vues par les joueurs)."""
    return _request("GET", _url(repo)) or {}


def get_draft(repo: str = DEFAULT_REPO) -> dict:
    """Brouillon courant (non encore publie)."""
    return _request("GET", _url(repo, "/draft")) or {}


def get_full(repo: str = DEFAULT_REPO) -> dict:
    """Config + metadonnees (revision courante, etc.)."""
    return _request("GET", _url(repo, "/full")) or {}


def revisions(repo: str = DEFAULT_REPO) -> dict:
    """Historique des revisions publiees."""
    return _request("GET", _url(repo, "/revisions")) or {}


# ECRITURES
def overwrite_draft(values: dict, repo: str = DEFAULT_REPO) -> dict:
    """Remplace TOUT le brouillon par `values`. (PUT :overwrite)"""
    if not isinstance(values, dict):
        raise ConfigError("Les valeurs de config doivent etre un objet clef/valeur.")
    return _request("PUT", _url(repo, "/draft:overwrite"), {"config": values})


def patch_draft(values: dict, repo: str = DEFAULT_REPO) -> dict:
    """Met a jour PARTIELLEMENT le brouillon (les cles fournies). (PATCH /draft)"""
    if not isinstance(values, dict):
        raise ConfigError("Les valeurs de config doivent etre un objet clef/valeur.")
    return _request("PATCH", _url(repo, "/draft"), {"config": values})


def publish(repo: str = DEFAULT_REPO) -> dict:
    """Deploie le brouillon en PRODUCTION (5-15 min de propagation cote joueurs)."""
    return _request("POST", _url(repo, "/publish"), {})


def restore_revision(revision_id: str, repo: str = DEFAULT_REPO) -> dict:
    """Prepare un retour a une revision anterieure (a publier ensuite)."""
    return _request("POST", _url(repo, f"/revisions/{revision_id}/restore"), {})


# FACADE
def overview(repo: str = DEFAULT_REPO) -> dict:
    """Etat pour le dashboard : publie + brouillon + diff, ou erreur claire.
    Ne LEVE pas : renvoie {ok, error} pour que le panneau s'affiche toujours."""
    try:
        published = get_published(repo)
    except ConfigError as exc:
        return {"ok": False, "error": str(exc)}
    draft = {}
    draft_err = None
    try:
        draft = get_draft(repo)
    except ConfigError as exc:
        draft_err = str(exc)   # pas de brouillon = normal, on n'echoue pas

    return {"ok": True, "repo": repo, "published": published,
            "draft": draft, "draftError": draft_err}
