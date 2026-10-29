"""
================================================================================
 RUNTIME BOT (keep online 24/7) — Shroud War Discord
================================================================================
Handles everything that needs a live bot:
  • Tickets       : "Create Ticket" button -> private staff channel + close button.
  • Logging       : joins/leaves/bans/edits/deletes/role changes -> log channels.
  • Reaction roles: faction + notification roles (from #choose-your-faction / #notification-roles).
  • Roblox link   : /link + /confirm (profile-code verification, no third-party needed).
  • Roblox sync   : /sync + periodic task -> faction / LP tier / level roles from OpenCloud.

Run `discord_setup.py` ONCE first (it writes bot_data.json used here).

 ENV VARS
   DISCORD_BOT_TOKEN   (required)
   ROBLOX_OPENCLOUD_KEY (optional — only for /sync; from create.roblox.com > Open Cloud)
 INSTALL : pip install -U "discord.py>=2.4" aiohttp
 INTENTS : SERVER MEMBERS + MESSAGE CONTENT (portal > Bot).
================================================================================
"""
import datetime
import json
import os
import random
import string

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

from core import config as cc_config

# CONFIGURATION
BOT_TOKEN         = os.environ.get("DISCORD_BOT_TOKEN", "")
OPENCLOUD_KEY     = os.environ.get("ROBLOX_OPENCLOUD_KEY", "")
DATA_FILE         = "bot_data.json"
LINKS_FILE        = "roblox_links.json"     # {discord_id: roblox_id}
AUTOROLE_NEW      = "🆕 New"                 # role given on join ("" to disable)
SYNC_EVERY_MIN    = 30                       # periodic Roblox->roles sync

# --- Roblox OpenCloud (fill to enable /sync) ---
# Les noms viennent du meme resolver que le dashboard et SharedConfig.luau.
ROBLOX_UNIVERSE_ID = int(cc_config.ROBLOX_UNIVERSE_ID or 0)
PROFILE_DATASTORE  = cc_config.datastore_name("GlobalData")   # faction + LP
PROFILE_KEY_TMPL   = "p_{userId}"
XP_DATASTORE       = cc_config.datastore_name("PlayerData_Skills&XP")
XP_KEY_TMPL        = "p_{userId}"

DATA = json.load(open(DATA_FILE, encoding="utf-8")) if os.path.exists(DATA_FILE) else {}
GUILD_ID = DATA.get("guild_id", 0)
LINKS = json.load(open(LINKS_FILE, encoding="utf-8")) if os.path.exists(LINKS_FILE) else {}
PENDING: dict[int, dict] = {}   # discord_id -> {"roblox_id":.., "code":..}

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


def save_links(): json.dump(LINKS, open(LINKS_FILE, "w", encoding="utf-8"), indent=2)
def guild_obj(): return bot.get_guild(GUILD_ID)
def role_by_id(g, rid): return g.get_role(rid) if rid else None
def role_by_name(g, name): return discord.utils.get(g.roles, name=name)

async def log_to(channel_id, embed):
    g = guild_obj(); ch = g and g.get_channel(channel_id)
    if ch:
        try: await ch.send(embed=embed)
        except discord.HTTPException: pass


# PERSISTENT TICKETS
class TicketPanel(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)

    @discord.ui.button(label="Create Ticket", emoji="🎫",
                       style=discord.ButtonStyle.primary, custom_id="ticket:create")
    async def create(self, interaction: discord.Interaction, button: discord.ui.Button):
        g = interaction.guild
        cat = g.get_channel(DATA.get("tickets_category_id", 0))
        # one open ticket per user (topic stores owner id)
        for ch in (cat.text_channels if cat else []):
            if ch.topic and str(interaction.user.id) in ch.topic:
                return await interaction.response.send_message(
                    f"You already have an open ticket: {ch.mention}", ephemeral=True)
        RO = discord.PermissionOverwrite
        ow = {g.default_role: RO(view_channel=False),
              interaction.user: RO(view_channel=True, send_messages=True, attach_files=True),
              g.me: RO(view_channel=True, send_messages=True)}
        for rid in DATA.get("staff_role_ids", []):
            r = g.get_role(rid)
            if r: ow[r] = RO(view_channel=True, send_messages=True)
        ch = await g.create_text_channel(
            f"ticket-{interaction.user.name}"[:90], category=cat, overwrites=ow,
            topic=f"Ticket owner: {interaction.user.id}", reason="Ticket")
        staff_ping = " ".join(f"<@&{rid}>" for rid in DATA.get("staff_role_ids", []))
        await ch.send(content=f"{interaction.user.mention} {staff_ping}",
            embed=discord.Embed(title="🎫 Ticket opened", color=discord.Color.green(),
                description="Describe your issue. A staff member will be with you shortly."),
            view=TicketClose())
        await interaction.response.send_message(f"Ticket created: {ch.mention}", ephemeral=True)


class TicketClose(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)

    @discord.ui.button(label="Close", emoji="🔒",
                       style=discord.ButtonStyle.danger, custom_id="ticket:close")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        ch = interaction.channel
        is_staff = any(r.id in DATA.get("staff_role_ids", []) for r in interaction.user.roles)
        is_owner = ch.topic and str(interaction.user.id) in ch.topic
        if not (is_staff or is_owner):
            return await interaction.response.send_message("Only staff or the owner can close.", ephemeral=True)
        await interaction.response.send_message("🔒 Closing in 5s…")
        await discord.utils.sleep_until(discord.utils.utcnow() + datetime.timedelta(seconds=5))
        await ch.delete(reason=f"Ticket closed by {interaction.user}")


# REACTION ROLES
async def toggle_reaction_role(payload: discord.RawReactionActionEvent, add: bool):
    mapping = DATA.get("reaction_roles", {}).get(str(payload.message_id))
    if not mapping: return
    rid = mapping.get(str(payload.emoji))
    if not rid: return
    g = bot.get_guild(payload.guild_id)
    if not g: return
    member = g.get_member(payload.user_id)
    if not member or member.bot: return
    role = g.get_role(rid)
    if not role: return
    try:
        await (member.add_roles if add else member.remove_roles)(role, reason="Reaction role")
    except discord.HTTPException: pass

@bot.event
async def on_raw_reaction_add(p): await toggle_reaction_role(p, True)
@bot.event
async def on_raw_reaction_remove(p): await toggle_reaction_role(p, False)


# LOGGING
def _e(title, color, desc): return discord.Embed(title=title, color=color, description=desc,
                                                  timestamp=discord.utils.utcnow())

@bot.event
async def on_member_join(m):
    if AUTOROLE_NEW:
        r = role_by_name(m.guild, AUTOROLE_NEW)
        if r:
            try: await m.add_roles(r, reason="Autorole")
            except discord.HTTPException: pass
    age = (discord.utils.utcnow() - m.created_at).days
    await log_to(DATA.get("server_log_channel_id"),
        _e("📥 Member joined", discord.Color.green(),
           f"{m.mention} `{m}`\nAccount age: **{age}** days • Members: **{m.guild.member_count}**"))

@bot.event
async def on_member_remove(m):
    await log_to(DATA.get("server_log_channel_id"),
        _e("📤 Member left", discord.Color.orange(), f"`{m}` ({m.id})"))

@bot.event
async def on_member_ban(guild, user):
    await log_to(DATA.get("mod_log_channel_id"), _e("🔨 Banned", discord.Color.red(), f"`{user}` ({user.id})"))
@bot.event
async def on_member_unban(guild, user):
    await log_to(DATA.get("mod_log_channel_id"), _e("♻️ Unbanned", discord.Color.green(), f"`{user}` ({user.id})"))

@bot.event
async def on_message_delete(msg):
    if not msg.guild or msg.author.bot: return
    await log_to(DATA.get("server_log_channel_id"),
        _e("🗑️ Message deleted", discord.Color.dark_grey(),
           f"**Author:** {msg.author.mention}\n**Channel:** {msg.channel.mention}\n"
           f"**Content:** {msg.content or '*(no text)*'}"[:4000]))

@bot.event
async def on_message_edit(before, after):
    if not before.guild or before.author.bot or before.content == after.content: return
    desc = (f"**Author:** {before.author.mention} in {before.channel.mention}\n"
            f"**Before:** {before.content or '—'}\n**After:** {after.content or '—'}")[:4000]
    await log_to(DATA.get("server_log_channel_id"),
                 _e("✏️ Message edited", discord.Color.gold(), desc))

@bot.event
async def on_member_update(before, after):
    added = set(after.roles) - set(before.roles)
    removed = set(before.roles) - set(after.roles)
    if added or removed:
        chg = "".join(f"\n+ {r.name}" for r in added) + "".join(f"\n- {r.name}" for r in removed)
        await log_to(DATA.get("server_log_channel_id"),
            _e("🏷️ Roles updated", discord.Color.blurple(), f"{after.mention}```{chg}```"))


# ROBLOX: LINK & SYNC
ROBLOX_USERS = "https://users.roblox.com"

async def roblox_user_id(session, username):
    async with session.post(f"{ROBLOX_USERS}/v1/usernames/users",
                            json={"usernames": [username], "excludeBannedUsers": True}) as r:
        j = await r.json()
    data = j.get("data") or []
    return data[0]["id"] if data else None

async def roblox_description(session, roblox_id):
    async with session.get(f"{ROBLOX_USERS}/v1/users/{roblox_id}") as r:
        j = await r.json()
    return j.get("description", "") or ""

async def opencloud_entry(session, datastore, key):
    if not (OPENCLOUD_KEY and ROBLOX_UNIVERSE_ID): return None
    url = (f"https://apis.roblox.com/datastores/v1/universes/{ROBLOX_UNIVERSE_ID}"
           f"/standard-datastores/datastore/entries/entry")
    params = {"datastoreName": datastore, "entryKey": key}
    async with session.get(url, params=params, headers={"x-api-key": OPENCLOUD_KEY}) as r:
        if r.status != 200: return None
        try: return await r.json()
        except Exception: return None

async def fetch_player_profile(session, roblox_id):
    """Reads game data via OpenCloud. Returns a merged dict. ADAPT the field names
    below to your actual DataStore layout (faction / lp / level)."""
    prof = await opencloud_entry(session, PROFILE_DATASTORE, PROFILE_KEY_TMPL.format(userId=roblox_id)) or {}
    xp   = await opencloud_entry(session, XP_DATASTORE, XP_KEY_TMPL.format(userId=roblox_id)) or {}
    return {"raw_profile": prof, "raw_xp": xp,
            "faction": prof.get("faction") or prof.get("Faction"),
            "lp":      prof.get("lp") or prof.get("LP") or (prof.get("stats") or {}).get("lp"),
            "level":   xp.get("level") or xp.get("Level")}

def lp_to_rank(lp):
    if lp is None: return None
    for name, floor in [("🔥 Elite",2200),("🔷 Diamond",1800),("💠 Platinum",1400),
                        ("🥇 Gold",1000),("🥈 Silver",600),("🥉 Bronze",0)]:
        if lp >= floor: return name
    return "🥉 Bronze"

def level_to_role(level):
    if level is None: return None
    for name, floor in [("Lvl 100",100),("Lvl 75+",75),("Lvl 50+",50),("Lvl 25+",25),("Lvl 10+",10)]:
        if level >= floor: return name
    return None

async def sync_member(session, member: discord.Member):
    rid = LINKS.get(str(member.id))
    if not rid: return "not linked"
    prof = await fetch_player_profile(session, rid)
    g = member.guild
    to_add, to_remove = [], []
    # Faction
    fac_ids = DATA.get("faction_role_ids", {})
    fac_name = (prof.get("faction") or "").capitalize()
    for fname, frid in fac_ids.items():
        r = g.get_role(frid)
        if r: (to_add if fname.lower() == fac_name.lower() else to_remove).append(r)
    # LP tier
    rank_name = lp_to_rank(prof.get("lp"))
    for rname, rrid in DATA.get("rank_role_ids", {}).items():
        r = g.get_role(rrid)
        if r: (to_add if rname == rank_name else to_remove).append(r)
    # Level
    lvl_name = level_to_role(prof.get("level"))
    for lname, lrid in DATA.get("level_role_ids", {}).items():
        r = g.get_role(lrid)
        if r: (to_add if lname == lvl_name else to_remove).append(r)
    try:
        if to_add: await member.add_roles(*to_add, reason="Roblox sync")
        if to_remove: await member.remove_roles(*to_remove, reason="Roblox sync")
    except discord.HTTPException: pass
    return f"faction={fac_name or '?'} lp={prof.get('lp')} level={prof.get('level')}"


# SLASH COMMANDS
@bot.tree.command(description="Link your Roblox account (step 1).")
@app_commands.describe(roblox_username="Your exact Roblox username")
async def link(interaction: discord.Interaction, roblox_username: str):
    async with aiohttp.ClientSession() as s:
        rid = await roblox_user_id(s, roblox_username)
    if not rid:
        return await interaction.response.send_message("❌ Roblox user not found.", ephemeral=True)
    code = "HF-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    PENDING[interaction.user.id] = {"roblox_id": rid, "code": code}
    await interaction.response.send_message(
        f"Step 1/2 ✅ Found `{roblox_username}` (id {rid}).\n"
        f"Now put this code in your Roblox **About/Description**:\n```{code}```"
        f"Then run **/confirm**.", ephemeral=True)

@bot.tree.command(description="Confirm your Roblox link (step 2).")
async def confirm(interaction: discord.Interaction):
    p = PENDING.get(interaction.user.id)
    if not p:
        return await interaction.response.send_message("Run **/link** first.", ephemeral=True)
    async with aiohttp.ClientSession() as s:
        desc = await roblox_description(s, p["roblox_id"])
    if p["code"] not in desc:
        return await interaction.response.send_message(
            "❌ Code not found in your Roblox description yet. Add it and retry.", ephemeral=True)
    LINKS[str(interaction.user.id)] = p["roblox_id"]; save_links(); PENDING.pop(interaction.user.id, None)
    r = role_by_id(interaction.guild, DATA.get("linked_role_id"))
    if r:
        try: await interaction.user.add_roles(r, reason="Roblox linked")
        except discord.HTTPException: pass
    async with aiohttp.ClientSession() as s:
        res = await sync_member(s, interaction.user)
    await interaction.response.send_message(f"✅ Linked! Synced: `{res}`", ephemeral=True)

@bot.tree.command(description="Re-sync your in-game faction / rank / level roles.")
async def sync(interaction: discord.Interaction):
    if str(interaction.user.id) not in LINKS:
        return await interaction.response.send_message("Link first with **/link**.", ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    async with aiohttp.ClientSession() as s:
        res = await sync_member(s, interaction.user)
    await interaction.followup.send(f"🔄 {res}", ephemeral=True)

@bot.tree.command(description="Show a member's linked Roblox account.")
async def whois(interaction: discord.Interaction, member: discord.Member):
    rid = LINKS.get(str(member.id))
    await interaction.response.send_message(
        f"{member.mention} → Roblox id `{rid}` (https://www.roblox.com/users/{rid}/profile)"
        if rid else f"{member.mention} is not linked.", ephemeral=True)


@tasks.loop(minutes=SYNC_EVERY_MIN)
async def periodic_sync():
    g = guild_obj()
    if not g or not (OPENCLOUD_KEY and ROBLOX_UNIVERSE_ID): return
    async with aiohttp.ClientSession() as s:
        for did in list(LINKS.keys()):
            m = g.get_member(int(did))
            if m: await sync_member(s, m)


# READY
@bot.event
async def on_ready():
    bot.add_view(TicketPanel())   # persistent
    bot.add_view(TicketClose())
    try:
        await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
    except Exception as e:
        print("tree sync:", e)
    if not periodic_sync.is_running():
        periodic_sync.start()
    print(f"🟢 Online as {bot.user}. Tickets + logging + reaction-roles + Roblox link/sync active.")


if __name__ == "__main__":
    if not BOT_TOKEN: raise SystemExit("❌ Set DISCORD_BOT_TOKEN.")
    if not DATA: raise SystemExit("❌ bot_data.json missing — run discord_setup.py first.")
    bot.run(BOT_TOKEN)
