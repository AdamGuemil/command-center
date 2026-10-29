#!/usr/bin/env python3
"""
================================================================================
 Command Center : lanceur
================================================================================
 Lance l'interface sur http://127.0.0.1:8787 (FastAPI + uvicorn, voir app.py) et sert
 d'intermediaire vers Discord et Roblox.

 POURQUOI UN SERVEUR PLUTOT QU'UNE PAGE STATIQUE :
 le token du bot et la cle Open Cloud ne doivent JAMAIS arriver dans le navigateur.
 La page n'envoie que des intentions ("poste ce message") ; le serveur detient les
 secrets et fait les appels.

 LANCEMENT
   python server.py            (ou double-clic sur start.bat)
================================================================================
"""

from __future__ import annotations

import socket
import sys
import threading
import webbrowser

from core import auth, config


def _bind(host: str, port: int) -> socket.socket:
    """Ouvre le port SANS SO_REUSEADDR, exclusif sous Windows.

    Sous Windows, SO_REUSEADDR laisse DEUX processus ecouter le meme port : on relance
    le CC, l'ancien tourne toujours, les requetes partent chez l'un ou l'autre et l'on
    croit que le .env n'est pas relu. Une 2e instance doit echouer franchement.
    """
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    if sys.platform == "win32" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    sock.bind((host, port))
    sock.listen(128)
    sock.setblocking(False)
    return sock


def main() -> None:
    try:
        import uvicorn
    except ImportError:
        print("\n  Dependances manquantes : pip install -r requirements.txt\n")
        raise SystemExit(1) from None

    problems = auth.startup_problems(config.HOST)
    if problems:
        print("\n  Demarrage refuse :")
        for p in problems:
            print(f"   - {p}")
        print()
        raise SystemExit(1)

    url = config.PUBLIC_URL + "/" if auth.enabled() and config.PUBLIC_URL else f"http://{config.HOST}:{config.PORT}/"
    try:
        sock = _bind(config.HOST, config.PORT)
    except OSError as exc:
        print(f"\n  Impossible d'ouvrir le port {config.PORT} : {exc}\n")
        print("  Un Command Center tourne deja. N'en lance qu'UN a la fois,")
        print("  sinon tu parles a l'ancien process (ex. : .env qui semble ignore).\n")
        print("  Ferme l'autre fenetre (Ctrl+C), ou trouve-le puis arrete-le :\n")
        print(f'    netstat -ano | findstr ":{config.PORT}"')
        print("    taskkill /F /PID <le_PID_affiche>\n")
        raise SystemExit(1) from exc

    gaps = config.missing_secrets()
    print("=" * 70)
    print(f"  COMMAND CENTER : {config.GAME_NAME}")
    print("=" * 70)
    print(f"  Interface : {url}")
    print(f"  API       : {url}api/docs")
    if auth.enabled():
        print(f"  Acces     : connexion Discord, {len(config.ADMINS)} admin(s), {len(config.MODS)} modo(s), "
              f"{len(config.VIEWERS)} lecteur(s)")
    else:
        print("  Acces     : mode local, sans connexion (ecoute sur cette machine seulement)")
    if config.BOT:
        print("  Bot Discord : demarre dans ce processus (CC_BOT=1).")
    if gaps:
        print(f"\n  Non configure : {', '.join(gaps)}")
        print("  L'interface demarre quand meme et t'indiquera quoi brancher.")
        print("  Copie .env.example vers .env et remplis-le.")
    print("\n  Le .env est lu au demarrage : relance le serveur apres l'avoir modifie.")
    print("  Ctrl+C pour arreter. Rien ne tourne apres l'arret.\n")

    if config.OPEN_BROWSER and not auth.enabled():
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    # Derriere Caddy (docker-compose), l'IP du visiteur et le schema https arrivent par
    # X-Forwarded-* : on ne les croit que venant des proxys listes dans CC_TRUSTED_PROXIES.
    server = uvicorn.Server(uvicorn.Config("app:app", log_level="warning", access_log=False,
                                           lifespan="on", proxy_headers=True,
                                           forwarded_allow_ips=config.TRUSTED_PROXIES))
    try:
        server.run(sockets=[sock])
    finally:
        sock.close()


if __name__ == "__main__":
    main()
