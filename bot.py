#!/usr/bin/env python3
"""Lance le bot Discord seul, sans l'interface. Le code vit dans core/bot.py.

D'habitude inutile : `CC_BOT=1 python server.py` le demarre dans le meme processus.
"""

import asyncio

from core import bot

if __name__ == "__main__":
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        pass
