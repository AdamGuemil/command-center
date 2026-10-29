"""
Documents techniques affiches dans l'ecran Guide.

Les fichiers Markdown sont lus a chaque ouverture : l'application montre toujours la
version du depot, sans copie a tenir a jour. Seuls les documents de la liste ci-dessous
sont servis (aucun chemin ne vient du navigateur). Les documents du depot du jeu
(guides) ne sont lus que si CC_GAME_ROOT designe ce depot : sinon ils disparaissent
simplement de la liste.
"""

from __future__ import annotations

from pathlib import Path

from . import config

PROJECT = config.GAME_ROOT or next((p for p in config.ROOT.parents if (p / "HUB").is_dir()), None)
MAX_BYTES = 400_000


def _in_project(rel: str) -> Path | None:
    return PROJECT / rel if PROJECT else None


# (id, titre, resume, chemin)
DOCS = [
    ("pipelines", "Pipelines", "Chaque flux de données : source, transport, destination, rythme, coût, panne.",
     config.ROOT / "docs" / "PIPELINES.md"),
    ("architecture", "Décisions d'architecture", "Pourquoi lire le jeu plutôt que recevoir, réutiliser FW_Event, SQLite.",
     config.ROOT / "docs" / "ARCHITECTURE.md"),
    ("pieges", "Pièges anti-triche", "Les remotes leurres, leur stockage et les règles à ne jamais enfreindre.",
     _in_project("claude_works/guides/GUIDE_PIEGES.md")),
    ("plan", "Plan du Command Center", "Lots, décisions et ce qui reste à construire.",
     _in_project("claude_works/PLAN_COMMAND_CENTER.md")),
    ("readme", "Installation et clés", "Démarrage, clés Open Cloud et Discord, sécurité, fichiers.",
     config.ROOT / "docs" / "OPERATIONS.md"),
]


def _path(doc_id: str) -> Path | None:
    for did, _, _, path in DOCS:
        if did == doc_id:
            return path
    return None


def listing() -> dict:
    out = []
    for did, title, summary, path in DOCS:
        if path is None or not path.is_file():
            continue
        out.append({"id": did, "title": title, "summary": summary,
                    "file": path.name, "updatedAt": int(path.stat().st_mtime)})
    return {"docs": out}


def read(doc_id: str) -> dict:
    path = _path(doc_id)
    if path is None:
        raise ValueError("Document inconnu.")
    if not path.is_file():
        raise ValueError(f"{path.name} est introuvable dans ce dossier.")
    raw = path.read_bytes()[:MAX_BYTES]
    return {"id": doc_id, "file": path.name, "updatedAt": int(path.stat().st_mtime),
            "markdown": raw.decode("utf-8", "replace").replace("\r\n", "\n")}


def all_text() -> dict:
    """Tous les documents disponibles, pour la recherche du Guide (lue une fois par visite)."""
    return {"docs": [{**d, "markdown": read(d["id"])["markdown"]} for d in listing()["docs"]]}
