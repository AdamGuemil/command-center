#!/usr/bin/env python3
"""
================================================================================
 announce.py — Poster une annonce Discord en ligne de commande
================================================================================
 Meme moteur que le dashboard (core/), mais sans ouvrir de navigateur. Pratique
 pour un .bat planifie ou un envoi rapide.

 Aucune dependance : REST pur via la bibliotheque standard. Une annonce part en
 ~300 ms (discord.py aurait ouvert une connexion gateway inutile de ~5 s).

 UTILISATION
   python announce.py --list                  # modeles disponibles + variables
   python announce.py launch --dry-run        # previsualiser SANS envoyer
   python announce.py launch                  # envoyer
   python announce.py factionwar              # publie le classement en direct
   python announce.py patch --title "v0.4.1" --body "- Fix HUD DUALS"
   python announce.py launch --channel general --ping everyone
================================================================================
"""

from __future__ import annotations

import argparse
import sys

from core import config, discord_api, store
from core import vars as tvars


def find_template(key: str) -> dict | None:
    for t in store.load_templates():
        if t["id"] == key or t["name"].lower() == key.lower():
            return t
    return None


def main():
    p = argparse.ArgumentParser(description="Poster une annonce Discord.")
    p.add_argument("template", nargs="?", default="launch")
    p.add_argument("--list", action="store_true", help="lister les modeles")
    p.add_argument("--channel", help="forcer le salon (nom)")
    p.add_argument("--title", help="remplacer le titre")
    p.add_argument("--body", help="remplacer le corps")
    p.add_argument("--image", help="URL d'une grande image")
    p.add_argument("--ping", help="everyone | here | <id de role>")
    p.add_argument("--publish", action="store_true", help="diffuser aux serveurs abonnes")
    p.add_argument("--dry-run", action="store_true", help="previsualiser sans envoyer")
    args = p.parse_args()

    templates = store.load_templates()

    if args.list:
        print(f"\nModeles ({len(templates)}) :\n")
        for t in templates:
            print(f"  {t['id']:<12} -> #{t['channel']:<24} {t['title']}")
        print("\nVariables disponibles :")
        for key, desc in tvars.CATALOG:
            print(f"  {key:<18} {desc}")
        print()
        return

    tpl = find_template(args.template)
    if not tpl:
        sys.exit(f"❌ Modele inconnu : '{args.template}'. "
                 f"Dispo : {', '.join(t['id'] for t in templates)}")

    title = tvars.resolve(args.title if args.title is not None else tpl["title"])
    body = tvars.resolve(args.body if args.body is not None else tpl["body"])
    channel_name = args.channel or tpl["channel"]
    ping = args.ping if args.ping is not None else tpl.get("ping", "")

    if args.dry_run:
        print("=" * 70)
        print(f"SALON : #{channel_name}")
        print(f"PING  : {ping or '(aucun)'}")
        print(f"TITRE : {title}")
        print("-" * 70)
        print(body)
        print("=" * 70)
        print("\n(--dry-run : rien n'a ete envoye)")
        return

    if not config.DISCORD_BOT_TOKEN:
        sys.exit('❌ DISCORD_BOT_TOKEN absent. Copie .env.example vers .env, '
                 'ou : $env:DISCORD_BOT_TOKEN = "ton_token"')

    try:
        channels = discord_api.get_channels()
        target = next((c for c in channels
                       if c["name"].lower() == channel_name.lstrip("#").lower()), None)
        if not target:
            print(f"❌ Salon #{channel_name} introuvable.")
            print("   Disponibles :", ", ".join(c["name"] for c in channels))
            sys.exit(1)

        embed = discord_api.build_embed(
            title=title,
            body=discord_api.resolve_channel_mentions(body, channels),
            color=int(tpl.get("color") or config.COLORS["neutral"]),
            footer=tvars.resolve(tpl.get("footer", "")),
            image=args.image or tpl.get("image", ""),
        )
        msg = discord_api.send_message(target["id"], embed, ping=ping,
                                       publish=args.publish)
        store.log_send(target["name"], title, True)
        print(f"✅ Poste dans #{target['name']}")
        if args.publish:
            print("📡 Publie." if msg.get("published")
                  else "⚠️  Publication ignoree : ce salon n'est pas de type Annonces.")
    except Exception as exc:                                   # noqa: BLE001
        store.log_send(channel_name, title, False, str(exc))
        sys.exit(f"❌ {exc}")


if __name__ == "__main__":
    main()
