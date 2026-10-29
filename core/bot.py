"""
Bot Discord (gateway), dans le meme processus que le Command Center.

Ce qui demande un bot connecte en permanence :
  * tickets      : bouton « Create Ticket » -> salon prive avec le staff, bouton de fermeture ;
  * journaux     : arrivees, departs, bans, messages edites ou supprimes, roles -> salons de logs ;
  * roles par reaction (faction, notifications) ;
  * liaison Roblox : /link puis /confirm (code dans la description du profil Roblox, sans
    service tiers), /whois ;
  * synchronisation : /sync et toutes les 30 min, roles faction / palier LP / niveau lus dans
    les DataStores du jeu via Open Cloud.

Demarrage : CC_BOT=1 (app.py le lance dans la boucle asyncio de FastAPI), ou `python bot.py`
pour le faire tourner seul. Configuration du serveur Discord : data/bot_data.json, ecrit une
fois par tools/setup_discord.py. Les liaisons Discord <-> Roblox vivent dans data/cc.db
(table discord_links) ; un ancien roblox_links.json est importe au premier demarrage.

Le bot ne fait jamais tomber le CC : sans token, sans bot_data.json ou sans discord.py, il
le dit dans la console et s'arrete seul.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import string
from pathlib import Path
from typing import Any

from . import config, db

log = logging.getLogger("cc.bot")

AUTOROLE_NEW = "🆕 New"          # role donne a l'arrivee ("" pour desactiver)
SYNC_EVERY_MIN = 30
LINK_PREFIX = "SW-"
ROBLOX_USERS = "https://users.roblox.com"
PROFILE_KEY = "p_{userId}"
RANK_TIERS = [("🔥 Elite", 2200), ("🔷 Diamond", 1800), ("💠 Platinum", 1400),
              ("🥇 Gold", 1000), ("🥈 Silver", 600), ("🥉 Bronze", 0)]
LEVEL_TIERS = [("Lvl 100", 100), ("Lvl 75+", 75), ("Lvl 50+", 50), ("Lvl 25+", 25), ("Lvl 10+", 10)]


# DONNEES ----------------------------------------------------------------------
def data_file() -> Path:
    """data/bot_data.json, ou l'ancien emplacement a la racine (avant le lot 5b)."""
    new = config.DATA_DIR / "bot_data.json"
    old = config.ROOT / "bot_data.json"
    return new if new.exists() or not old.exists() else old


def load_data() -> dict:
    try:
        data = json.loads(data_file().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def import_legacy_links() -> int:
    """Importe roblox_links.json (ancien bot) dans la base, une fois."""
    imported = 0
    for path in (config.DATA_DIR / "roblox_links.json", config.ROOT / "roblox_links.json"):
        try:
            links = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for did, rid in (links or {}).items():
            if str(did).isdigit() and str(rid).isdigit() and db.get_link(int(did)) is None:
                db.set_link(int(did), int(rid))
                imported += 1
    return imported


def lp_to_rank(lp: Any) -> str | None:
    if lp is None:
        return None
    try:
        value = float(lp)
    except (TypeError, ValueError):
        return None
    return next((name for name, floor in RANK_TIERS if value >= floor), RANK_TIERS[-1][0])


def level_to_role(level: Any) -> str | None:
    try:
        value = float(level)
    except (TypeError, ValueError):
        return None
    return next((name for name, floor in LEVEL_TIERS if value >= floor), None)


def new_link_code() -> str:
    return LINK_PREFIX + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))


# BOT --------------------------------------------------------------------------
def build(data: dict):
    """Construit le bot (discord.py importe ici : le CC tourne sans lui)."""
    import aiohttp
    import discord
    from discord import app_commands
    from discord.ext import commands, tasks

    guild_id = int(data.get("guild_id") or config.DISCORD_GUILD_ID or 0)
    pending: dict[int, dict] = {}

    intents = discord.Intents.default()
    intents.guilds = True
    intents.members = True
    intents.message_content = True
    bot = commands.Bot(command_prefix="!", intents=intents)

    def guild_obj():
        return bot.get_guild(guild_id)

    async def log_to(channel_id, embed) -> None:
        g = guild_obj()
        ch = g.get_channel(channel_id) if g and channel_id else None
        if ch:
            try:
                await ch.send(embed=embed)
            except discord.HTTPException:
                pass

    def embed(title: str, color, desc: str):
        return discord.Embed(title=title, color=color, description=desc, timestamp=discord.utils.utcnow())

    # Tickets (vues persistantes : elles survivent au redemarrage du bot).
    class TicketPanel(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=None)

        @discord.ui.button(label="Create Ticket", emoji="🎫", style=discord.ButtonStyle.primary,
                           custom_id="ticket:create")
        async def create(self, interaction: discord.Interaction, button: discord.ui.Button):
            g = interaction.guild
            cat = g.get_channel(data.get("tickets_category_id", 0))
            for ch in (cat.text_channels if cat else []):
                if ch.topic and str(interaction.user.id) in ch.topic:
                    await interaction.response.send_message(
                        f"You already have an open ticket: {ch.mention}", ephemeral=True)
                    return
            ro = discord.PermissionOverwrite
            overwrites = {g.default_role: ro(view_channel=False),
                          interaction.user: ro(view_channel=True, send_messages=True, attach_files=True),
                          g.me: ro(view_channel=True, send_messages=True)}
            for rid in data.get("staff_role_ids", []):
                role = g.get_role(rid)
                if role:
                    overwrites[role] = ro(view_channel=True, send_messages=True)
            ch = await g.create_text_channel(f"ticket-{interaction.user.name}"[:90], category=cat,
                                             overwrites=overwrites,
                                             topic=f"Ticket owner: {interaction.user.id}", reason="Ticket")
            staff = " ".join(f"<@&{rid}>" for rid in data.get("staff_role_ids", []))
            await ch.send(content=f"{interaction.user.mention} {staff}",
                          embed=discord.Embed(title="🎫 Ticket opened", color=discord.Color.green(),
                                              description="Describe your issue. A staff member will be "
                                                          "with you shortly."),
                          view=TicketClose())
            await interaction.response.send_message(f"Ticket created: {ch.mention}", ephemeral=True)

    class TicketClose(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=None)

        @discord.ui.button(label="Close", emoji="🔒", style=discord.ButtonStyle.danger, custom_id="ticket:close")
        async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
            ch = interaction.channel
            is_staff = any(r.id in data.get("staff_role_ids", []) for r in interaction.user.roles)
            is_owner = bool(ch.topic and str(interaction.user.id) in ch.topic)
            if not (is_staff or is_owner):
                await interaction.response.send_message("Only staff or the owner can close.", ephemeral=True)
                return
            await interaction.response.send_message("🔒 Closing in 5s…")
            await asyncio.sleep(5)
            await ch.delete(reason=f"Ticket closed by {interaction.user}")

    # Roles par reaction.
    async def toggle_reaction_role(payload, add: bool) -> None:
        mapping = data.get("reaction_roles", {}).get(str(payload.message_id))
        rid = mapping.get(str(payload.emoji)) if mapping else None
        g = bot.get_guild(payload.guild_id) if rid else None
        member = g.get_member(payload.user_id) if g else None
        role = g.get_role(rid) if g else None
        if not member or member.bot or not role:
            return
        try:
            await (member.add_roles if add else member.remove_roles)(role, reason="Reaction role")
        except discord.HTTPException:
            pass

    @bot.event
    async def on_raw_reaction_add(payload):
        await toggle_reaction_role(payload, True)

    @bot.event
    async def on_raw_reaction_remove(payload):
        await toggle_reaction_role(payload, False)

    # Journaux.
    @bot.event
    async def on_member_join(m):
        if AUTOROLE_NEW:
            role = discord.utils.get(m.guild.roles, name=AUTOROLE_NEW)
            if role:
                try:
                    await m.add_roles(role, reason="Autorole")
                except discord.HTTPException:
                    pass
        age = (discord.utils.utcnow() - m.created_at).days
        await log_to(data.get("server_log_channel_id"),
                     embed("📥 Member joined", discord.Color.green(),
                           f"{m.mention} `{m}`\nAccount age: **{age}** days • Members: **{m.guild.member_count}**"))

    @bot.event
    async def on_member_remove(m):
        await log_to(data.get("server_log_channel_id"),
                     embed("📤 Member left", discord.Color.orange(), f"`{m}` ({m.id})"))

    @bot.event
    async def on_member_ban(guild, user):
        await log_to(data.get("mod_log_channel_id"), embed("🔨 Banned", discord.Color.red(), f"`{user}` ({user.id})"))

    @bot.event
    async def on_member_unban(guild, user):
        await log_to(data.get("mod_log_channel_id"),
                     embed("♻️ Unbanned", discord.Color.green(), f"`{user}` ({user.id})"))

    @bot.event
    async def on_message_delete(msg):
        if not msg.guild or msg.author.bot:
            return
        await log_to(data.get("server_log_channel_id"),
                     embed("🗑️ Message deleted", discord.Color.dark_grey(),
                           (f"**Author:** {msg.author.mention}\n**Channel:** {msg.channel.mention}\n"
                            f"**Content:** {msg.content or '*(no text)*'}")[:4000]))

    @bot.event
    async def on_message_edit(before, after):
        if not before.guild or before.author.bot or before.content == after.content:
            return
        desc = (f"**Author:** {before.author.mention} in {before.channel.mention}\n"
                f"**Before:** {before.content or '—'}\n**After:** {after.content or '—'}")[:4000]
        await log_to(data.get("server_log_channel_id"), embed("✏️ Message edited", discord.Color.gold(), desc))

    @bot.event
    async def on_member_update(before, after):
        added = set(after.roles) - set(before.roles)
        removed = set(before.roles) - set(after.roles)
        if added or removed:
            change = "".join(f"\n+ {r.name}" for r in added) + "".join(f"\n- {r.name}" for r in removed)
            await log_to(data.get("server_log_channel_id"),
                         embed("🏷️ Roles updated", discord.Color.blurple(), f"{after.mention}```{change}```"))

    # Roblox : liaison et synchronisation.
    async def roblox_user_id(session, username: str):
        async with session.post(f"{ROBLOX_USERS}/v1/usernames/users",
                                json={"usernames": [username], "excludeBannedUsers": True}) as r:
            rows = (await r.json()).get("data") or []
        return rows[0]["id"] if rows else None

    async def roblox_description(session, roblox_id: int) -> str:
        async with session.get(f"{ROBLOX_USERS}/v1/users/{roblox_id}") as r:
            return (await r.json()).get("description", "") or ""

    async def opencloud_entry(session, datastore: str, key: str) -> dict:
        if not (config.ROBLOX_OPENCLOUD_KEY and config.ROBLOX_UNIVERSE_ID):
            return {}
        url = (f"https://apis.roblox.com/datastores/v1/universes/{config.ROBLOX_UNIVERSE_ID}"
               "/standard-datastores/datastore/entries/entry")
        async with session.get(url, params={"datastoreName": datastore, "entryKey": key},
                               headers={"x-api-key": config.ROBLOX_OPENCLOUD_KEY}) as r:
            if r.status != 200:
                return {}
            try:
                value = await r.json()
            except Exception:                                   # noqa: BLE001
                return {}
        return value if isinstance(value, dict) else {}

    async def sync_member(session, member) -> str:
        rid = db.get_link(member.id)
        if not rid:
            return "not linked"
        prof = await opencloud_entry(session, config.datastore_name("GlobalData"), PROFILE_KEY.format(userId=rid))
        xp = await opencloud_entry(session, config.datastore_name("PlayerData_Skills&XP"),
                                   PROFILE_KEY.format(userId=rid))
        faction = str(prof.get("faction") or "").capitalize()
        rank = lp_to_rank(prof.get("lp"))
        level = level_to_role(xp.get("level"))
        g = member.guild
        to_add: list = []
        to_remove: list = []
        for groups, wanted in ((data.get("faction_role_ids", {}), faction),
                               (data.get("rank_role_ids", {}), rank),
                               (data.get("level_role_ids", {}), level)):
            for name, role_id in groups.items():
                role = g.get_role(role_id)
                if role:
                    (to_add if wanted and name.lower() == str(wanted).lower() else to_remove).append(role)
        try:
            if to_add:
                await member.add_roles(*to_add, reason="Roblox sync")
            if to_remove:
                await member.remove_roles(*to_remove, reason="Roblox sync")
        except discord.HTTPException:
            pass
        return f"faction={faction or '?'} lp={prof.get('lp')} level={xp.get('level')}"

    @bot.tree.command(description="Link your Roblox account (step 1).")
    @app_commands.describe(roblox_username="Your exact Roblox username")
    async def link(interaction: discord.Interaction, roblox_username: str):
        async with aiohttp.ClientSession() as s:
            rid = await roblox_user_id(s, roblox_username)
        if not rid:
            await interaction.response.send_message("❌ Roblox user not found.", ephemeral=True)
            return
        code = new_link_code()
        pending[interaction.user.id] = {"roblox_id": rid, "code": code}
        await interaction.response.send_message(
            f"Step 1/2 ✅ Found `{roblox_username}` (id {rid}).\n"
            f"Now put this code in your Roblox **About/Description**:\n```{code}```Then run **/confirm**.",
            ephemeral=True)

    @bot.tree.command(description="Confirm your Roblox link (step 2).")
    async def confirm(interaction: discord.Interaction):
        p = pending.get(interaction.user.id)
        if not p:
            await interaction.response.send_message("Run **/link** first.", ephemeral=True)
            return
        async with aiohttp.ClientSession() as s:
            desc = await roblox_description(s, p["roblox_id"])
        if p["code"] not in desc:
            await interaction.response.send_message(
                "❌ Code not found in your Roblox description yet. Add it and retry.", ephemeral=True)
            return
        db.set_link(interaction.user.id, int(p["roblox_id"]))
        pending.pop(interaction.user.id, None)
        role = interaction.guild.get_role(data.get("linked_role_id") or 0)
        if role:
            try:
                await interaction.user.add_roles(role, reason="Roblox linked")
            except discord.HTTPException:
                pass
        async with aiohttp.ClientSession() as s:
            res = await sync_member(s, interaction.user)
        await interaction.response.send_message(f"✅ Linked! Synced: `{res}`", ephemeral=True)

    @bot.tree.command(description="Re-sync your in-game faction / rank / level roles.")
    async def sync(interaction: discord.Interaction):
        if not db.get_link(interaction.user.id):
            await interaction.response.send_message("Link first with **/link**.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        async with aiohttp.ClientSession() as s:
            res = await sync_member(s, interaction.user)
        await interaction.followup.send(f"🔄 {res}", ephemeral=True)

    @bot.tree.command(description="Show a member's linked Roblox account.")
    async def whois(interaction: discord.Interaction, member: discord.Member):
        rid = db.get_link(member.id)
        await interaction.response.send_message(
            f"{member.mention} → Roblox id `{rid}` (https://www.roblox.com/users/{rid}/profile)"
            if rid else f"{member.mention} is not linked.", ephemeral=True)

    @tasks.loop(minutes=SYNC_EVERY_MIN)
    async def periodic_sync():
        g = guild_obj()
        if not g or not (config.ROBLOX_OPENCLOUD_KEY and config.ROBLOX_UNIVERSE_ID):
            return
        async with aiohttp.ClientSession() as s:
            for did, _rid in db.links():
                member = g.get_member(did)
                if member:
                    await sync_member(s, member)

    @bot.event
    async def on_ready():
        bot.add_view(TicketPanel())
        bot.add_view(TicketClose())
        try:
            await bot.tree.sync(guild=discord.Object(id=guild_id))
        except Exception as exc:                                # noqa: BLE001
            log.warning("Synchronisation des commandes : %s", exc)
        if not periodic_sync.is_running():
            periodic_sync.start()
        print(f"  Bot Discord en ligne : {bot.user} (tickets, journaux, roles, liaison Roblox).")

    return bot


async def run() -> None:
    """Lance le bot jusqu'a l'annulation de la tache. Ne leve jamais vers l'appelant."""
    if not config.DISCORD_BOT_TOKEN:
        print("  Bot Discord : DISCORD_BOT_TOKEN absent, bot non demarre.")
        return
    data = load_data()
    if not data:
        print("  Bot Discord : data/bot_data.json absent (lance tools/setup_discord.py), bot non demarre.")
        return
    try:
        bot = build(data)
    except ImportError:
        print("  Bot Discord : discord.py absent (pip install -r requirements.txt), bot non demarre.")
        return
    n = await asyncio.to_thread(import_legacy_links)
    if n:
        print(f"  Bot Discord : {n} liaison(s) Roblox importee(s) depuis roblox_links.json.")
    try:
        await bot.start(config.DISCORD_BOT_TOKEN)
    except asyncio.CancelledError:
        raise
    except Exception as exc:                                    # noqa: BLE001
        print(f"  Bot Discord arrete : {exc}")
    finally:
        if not bot.is_closed():
            await bot.close()

