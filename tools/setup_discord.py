"""
================================================================================
 SERVER SETUP (run ONCE) — Discord for "Shroud War"
================================================================================
Builds the server ONCE: roles, categories, channels, native AutoMod, native
Onboarding (faction), in-game webhooks, and the info/rules/ticket panels. Writes
`bot_data.json` for the runtime bot (discord_bot.py).

WHAT NEEDS A 24/7 PROCESS vs NOT
  • No process needed (works with the bot OFFLINE):
      structure/roles, AutoMod, Onboarding faction picker, game->Discord webhooks.
  • Needs discord_bot.py running (host it in the cloud, NOT your PC):
      tickets, logging, /link, /sync (Roblox<->Discord role sync).

 TOKEN SECURITY — never hardcode it. Read from env var:
   PowerShell : $env:DISCORD_BOT_TOKEN = "your_token"
 INSTALL : pip install -U "discord.py>=2.4" aiohttp
 INTENTS : enable SERVER MEMBERS (+ MESSAGE CONTENT for the runtime bot).
 RUN     : python tools/setup_discord.py   (CC_SETUP_WIPE=1 pour repartir de zero)
================================================================================
"""

import asyncio
import json
import os
import sys
from datetime import timedelta
from pathlib import Path

import discord

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # lance depuis tools/ ou la racine
from core import config as cc_config  # noqa: E402

# La console Windows est en cp1252 par defaut : tout print() contenant un emoji
# leve UnicodeEncodeError et interrompt le setup en plein milieu. On force
# l'UTF-8 sur la sortie (affichage local uniquement).
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# CONFIGURATION
BOT_TOKEN = cc_config.DISCORD_BOT_TOKEN
GUILD_ID  = int(cc_config.DISCORD_GUILD_ID or 0)

GAME_NAME       = cc_config.GAME_NAME
ROBLOX_GAME_URL = cc_config.GAME_URL
FACTION_1       = "Rusfor"
FACTION_2       = "Rainor"
FACTION_1_COLOR = discord.Color.from_rgb(214, 48, 49)
FACTION_2_COLOR = discord.Color.from_rgb(41, 128, 185)

# DANGER : supprime TOUS les salons et roles supprimables avant de reconstruire. Desactive
# par defaut ; a activer explicitement (CC_SETUP_WIPE=1) sur un serveur neuf uniquement.
WIPE_FIRST        = os.environ.get("CC_SETUP_WIPE") == "1"
WIPE_COUNTDOWN    = 6
ENABLE_RANK_ROLES = True    # LP tiers (mirror in-game ranked)
ENABLE_LEVEL_ROLES = True
ENABLE_MODES      = True     # per-mode channels (DUALS / DOMINATION / EXFIL)
ENABLE_COMPETITIVE = True
ENABLE_PLAYTEST   = True
ENABLE_GAME_FEED  = True     # webhook channels for in-game -> Discord
ENABLE_AUTOMOD    = True
ENABLE_ONBOARDING = True     # native faction picker (needs Community mode enabled)
ENABLE_SERVER_SETTINGS = True
CONFIG_OUT = "bot_data.json"

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
client = discord.Client(intents=intents)

DATA: dict = {}
def log(m, i=0): print(("  " * i) + m)


# HELPERS
async def wipe_server(guild):
    log("🧨 WIPE: deleting existing channels & roles…")
    for ch in list(guild.channels):
        try: await ch.delete(reason="Setup wipe"); log(f"- channel {ch.name}", 1)
        except discord.HTTPException as e: log(f"⚠️ {ch.name}: {e}", 1)
    top = guild.me.top_role
    for r in list(guild.roles):
        if r.is_default() or r.managed or r >= top: continue
        try: await r.delete(reason="Setup wipe"); log(f"- role {r.name}", 1)
        except discord.HTTPException as e: log(f"⚠️ {r.name}: {e}", 1)
    log("🧼 Wipe done.\n")

async def role(guild, name, color=discord.Color.default(),
               perms=discord.Permissions.none(), hoist=False, mentionable=False):
    ex = discord.utils.get(guild.roles, name=name)
    if ex: return ex
    r = await guild.create_role(name=name, color=color, permissions=perms,
                                hoist=hoist, mentionable=mentionable, reason="Setup")
    log(f"✅ role {name}", 1); return r

async def category(guild, name, overwrites=None):
    ex = discord.utils.get(guild.categories, name=name)
    if ex: return ex
    c = await guild.create_category(name=name, overwrites=overwrites or {}, reason="Setup")
    log(f"📁 {name}"); return c

async def text(guild, name, cat, overwrites=None, topic=None, slowmode=0):
    ex = discord.utils.get(guild.text_channels, name=name, category=cat)
    if ex: return ex
    c = await guild.create_text_channel(name=name, category=cat, overwrites=overwrites or {},
                                        topic=topic, slowmode_delay=slowmode, reason="Setup")
    log(f"# {name}", 1); return c

async def voice(guild, name, cat, overwrites=None, user_limit=0):
    ex = discord.utils.get(guild.voice_channels, name=name, category=cat)
    if ex: return ex
    c = await guild.create_voice_channel(name=name, category=cat, overwrites=overwrites or {},
                                         user_limit=user_limit, reason="Setup")
    log(f"🔊 {name}", 1); return c

async def forum(guild, name, cat, topic=None, tags=None, overwrites=None, slowmode=0):
    ex = discord.utils.get(guild.channels, name=name)
    if ex and getattr(ex, "type", None) == discord.ChannelType.forum: return ex
    ftags = [discord.ForumTag(name=t) for t in (tags or [])]
    try:
        c = await guild.create_forum(name=name, category=cat, topic=topic, available_tags=ftags,
                                     overwrites=overwrites or {}, slowmode_delay=slowmode, reason="Setup")
        log(f"🗂️ forum {name}", 1); return c
    except Exception as e:
        log(f"⚠️ forum {name} -> text fallback ({e})", 1)
        return await text(guild, name, cat, overwrites=overwrites, topic=topic, slowmode=slowmode)

async def post_once(channel, *, embed=None, content=None, view=None, reactions=None):
    hist = [m async for m in channel.history(limit=1)]
    if hist: return hist[0]
    msg = await channel.send(content=content, embed=embed, view=view)
    for r in (reactions or []):
        try: await msg.add_reaction(r)
        except discord.HTTPException: pass
    return msg


# AUTOMOD (native)
async def setup_automod(guild, alert_channel, exempt_roles):
    if not ENABLE_AUTOMOD: return
    log("\n📌 AUTOMOD")
    block = discord.AutoModRuleAction(type=discord.AutoModRuleActionType.block_message)
    alert = discord.AutoModRuleAction(channel_id=alert_channel.id)
    timeout5 = discord.AutoModRuleAction(duration=timedelta(minutes=5))
    # NOTE: presets is a FLAGS object (not a list) -> AutoModPresets(...).
    rules = [
        ("Profanity & Slurs",
         discord.AutoModTrigger(type=discord.AutoModRuleTriggerType.keyword_preset,
             presets=discord.AutoModPresets(profanity=True, slurs=True, sexual_content=True)),
         [block, alert]),
        ("Spam", discord.AutoModTrigger(type=discord.AutoModRuleTriggerType.spam), [block]),
        ("Mention Spam",
         discord.AutoModTrigger(type=discord.AutoModRuleTriggerType.mention_spam, mention_limit=6),
         [block, alert, timeout5]),
        ("No Invite Links",
         discord.AutoModTrigger(type=discord.AutoModRuleTriggerType.keyword,
             regex_patterns=[r"(?i)(discord\.gg|discord(?:app)?\.com/invite|\.gg/)\S+"]),
         [block, alert]),
    ]
    for name, trigger, actions in rules:
        try:
            await guild.create_automod_rule(
                name=name, event_type=discord.AutoModRuleEventType.message_send,
                trigger=trigger, actions=actions, enabled=True,
                exempt_roles=exempt_roles, reason="Setup")
            log(f"✅ automod: {name}", 1)
        except Exception as e:
            log(f"⚠️ automod {name}: {e}", 1)


# ONBOARDING (native)
async def setup_onboarding(guild, default_channels, f1_role, f2_role, notif_roles):
    """Native onboarding = faction (required) + notifications (optional). No bot needed.
    Members pick these on arrival and can change them anytime via 'Channels & Roles'."""
    if not ENABLE_ONBOARDING or not hasattr(guild, "edit_onboarding"): return
    log("\n📌 ONBOARDING (needs Community mode)")
    try:
        faction_prompt = discord.OnboardingPrompt(
            type=discord.OnboardingPromptType.multiple_choice,
            title="Choose your faction",
            single_select=True, required=True, in_onboarding=True,
            options=[discord.OnboardingPromptOption(title=FACTION_1, emoji="🔴", roles=[f1_role]),
                     discord.OnboardingPromptOption(title=FACTION_2, emoji="🔵", roles=[f2_role])])
        notif_prompt = discord.OnboardingPrompt(
            type=discord.OnboardingPromptType.multiple_choice,
            title="Notifications (optional)",
            single_select=False, required=False, in_onboarding=True,
            options=[discord.OnboardingPromptOption(title=r.name, roles=[r]) for r in notif_roles.values()])
        await guild.edit_onboarding(prompts=[faction_prompt, notif_prompt],
                                    default_channels=default_channels, enabled=True,
                                    mode=discord.OnboardingMode.onboarding_default, reason="Setup")
        log("✅ onboarding: faction + notification pickers (no bot needed)", 1)
    except Exception as e:
        log(f"⚠️ onboarding skipped ({e}). Enable Community in Server Settings, then re-run.", 1)


# MAIN
@client.event
async def on_ready():
    print(f"Connected as {client.user}\n")
    guild = client.get_guild(GUILD_ID)
    if guild is None:
        print("❌ Guild not found."); await client.close(); return
    if WIPE_FIRST:
        print(f"⚠️ WIPE in {WIPE_COUNTDOWN}s on « {guild.name} ». Ctrl+C to cancel.")
        await asyncio.sleep(WIPE_COUNTDOWN); await wipe_server(guild)

    everyone = guild.default_role
    RO = discord.PermissionOverwrite

    # ------------------------------------------------------------------- ROLES
    print("📌 ROLES")
    r_founder = await role(guild, "👑 Founder", discord.Color.gold(),
                           discord.Permissions(administrator=True), hoist=True)
    r_admin = await role(guild, "🛡️ Admin", discord.Color.dark_red(),
        discord.Permissions(manage_guild=True, manage_channels=True, manage_roles=True,
                            kick_members=True, ban_members=True, manage_messages=True,
                            moderate_members=True, view_audit_log=True), hoist=True)
    r_mod = await role(guild, "🔧 Moderator", discord.Color.from_rgb(52, 152, 219),
        discord.Permissions(kick_members=True, manage_messages=True, moderate_members=True,
                            mute_members=True, move_members=True), hoist=True)
    await role(guild, "🎬 Content Creator", discord.Color.magenta(), hoist=True)
    r_tester = await role(guild, "🧪 Tester", discord.Color.teal(), hoist=True)
    r_f1 = await role(guild, f"🔴 {FACTION_1}", FACTION_1_COLOR, hoist=True, mentionable=True)
    r_f2 = await role(guild, f"🔵 {FACTION_2}", FACTION_2_COLOR, hoist=True, mentionable=True)
    await role(guild, "⭐ Veteran", discord.Color.purple())
    await role(guild, "💎 Booster", discord.Color.from_rgb(244, 127, 255))
    await role(guild, "🐛 Bug Hunter", discord.Color.from_rgb(46, 204, 113))
    await role(guild, "🏆 Champion", discord.Color.from_rgb(241, 196, 15))
    r_linked = await role(guild, "✅ Roblox Linked", discord.Color.from_rgb(87, 242, 135))
    await role(guild, "🆕 New", discord.Color.light_gray())

    rank_ids, level_ids = {}, {}
    if ENABLE_RANK_ROLES:
        print("📌 LP RANK ROLES")
        for name, rgb in [("🥉 Bronze",(169,113,66)),("🥈 Silver",(168,178,189)),
                          ("🥇 Gold",(241,196,15)),("💠 Platinum",(26,188,156)),
                          ("🔷 Diamond",(52,152,219)),("🔥 Elite",(231,76,60))]:
            rr = await role(guild, name, discord.Color.from_rgb(*rgb)); rank_ids[name] = rr.id
    if ENABLE_LEVEL_ROLES:
        print("📌 LEVEL ROLES")
        for name in ["Lvl 10+","Lvl 25+","Lvl 50+","Lvl 75+","Lvl 100"]:
            lr = await role(guild, name, discord.Color.from_rgb(99,110,114)); level_ids[name] = lr.id

    print("📌 NOTIFICATION ROLES")
    notif = {}
    for emoji, name in [("📢","📢 Announcements"),("🧪","🧪 Playtests"),("🎮","🎮 LFG/Scrims"),
                        ("🎉","🎉 Events"),("📺","📺 Livestreams")]:
        notif[emoji] = await role(guild, name, discord.Color.from_rgb(149,165,166), mentionable=True)

    staff_view = {r_mod: RO(view_channel=True), r_admin: RO(view_channel=True),
                  r_founder: RO(view_channel=True)}
    STAFF_IDS = [r_mod.id, r_admin.id, r_founder.id]

    print("\n📌 CATEGORIES & CHANNELS")
    # --- STAFF FIRST (top of the list, as requested; only staff can see it) ---
    c_staff = await category(guild, "🛠️ STAFF", {everyone: RO(view_channel=False), **staff_view})
    await text(guild, "staff-chat", c_staff, topic="🔒 Staff discussion.")
    await text(guild, "dev-todo", c_staff, topic="📋 Dev tasks.")
    ch_modlog = await text(guild, "mod-logs", c_staff, topic="📜 Moderation & AutoMod alerts.")
    ch_serverlog = await text(guild, "server-logs", c_staff, topic="📥 Joins/leaves/edits/deletes.")
    await text(guild, "sanctions", c_staff, topic="⚖️ Sanction history.")
    await voice(guild, "🔒 Staff Voice", c_staff)
    c_tickets = await category(guild, "🎫 TICKETS", {everyone: RO(view_channel=False), **staff_view})

    # --------------------------------------------------------------- INFORMATION
    c_info = await category(guild, "📢 INFORMATION", {everyone: RO(view_channel=True, send_messages=False)})
    ch_announce = await text(guild, "announcements", c_info, topic=f"📢 Official {GAME_NAME} news.")
    ch_rules = await text(guild, "rules", c_info, topic="📜 Read before anything else.")
    await text(guild, "patch-notes", c_info, topic="🛠️ Game update notes.")
    await text(guild, "roadmap", c_info, topic="🗺️ What's coming next.")
    ch_links = await text(guild, "useful-links", c_info, topic="🔗 Game, socials, resources.")

    # --------------------------------------------------------------- START HERE
    c_start = await category(guild, "🚪 START HERE", {everyone: RO(view_channel=True, send_messages=False)})
    ch_welcome = await text(guild, "welcome", c_start, topic="👋 Where to begin.")
    ch_faction = await text(guild, "choose-your-faction", c_start,
        overwrites={everyone: RO(view_channel=True, send_messages=False, add_reactions=False)},
        topic="⚔️ Pick your faction.")
    ch_notifs = await text(guild, "notification-roles", c_start,
        overwrites={everyone: RO(view_channel=True, send_messages=False, add_reactions=False)},
        topic="🔔 Pick the pings you want.")
    await text(guild, "link-your-account", c_start, topic="🔗 Use /link to connect your Roblox account.")
    await text(guild, "introduce-yourself", c_start,
        overwrites={everyone: RO(view_channel=True, send_messages=True)}, topic="🙋 Say hi.", slowmode=30)

    # ----------------------------------------------------------------- COMMUNITY
    c_comm = await category(guild, "💬 COMMUNITY")
    await text(guild, "general", c_comm, topic="💬 General chat.", slowmode=3)
    await text(guild, "off-topic", c_comm, topic="🎲 Anything goes.")
    await text(guild, "memes", c_comm, topic="😂 Memes.")
    await text(guild, "clips-and-screenshots", c_comm, topic="🎬 Your best moments.")
    await text(guild, "artwork", c_comm, topic="🎨 Fan art & creations.")
    await text(guild, "suggestions", c_comm, topic="💡 Ideas for the game/server.")

    # --------------------------------------------------------------------- GAME
    c_game = await category(guild, "⚔️ GAME")
    await text(guild, "looking-for-group", c_game, topic="🤝 Find teammates (LFG).", slowmode=5)
    await text(guild, "leaderboard-and-scores", c_game, topic="🏆 Ranked LP ladder, tops, feats.")
    await text(guild, "builds-and-loadouts", c_game, topic="🛠️ Share gunsmith builds & loadouts.")
    await text(guild, "guides-and-tips", c_game, topic="📈 Guides, tips, meta.")
    await text(guild, "balance-and-meta", c_game, topic="⚖️ Balance debates (weapons, skills, LP).")

    if ENABLE_MODES:
        c_modes = await category(guild, "🎮 GAME MODES")
        await text(guild, "duals-ranked", c_modes, topic="🥇 Competitive DUALS (LP). ARENA + BLITZ.")
        await text(guild, "blitz-objective", c_modes, topic="🎯 BLITZ: attack/defend objective (5v5).")
        await text(guild, "domination", c_modes, topic="💥 Large-team objective combat.")
        await text(guild, "exfil-raids", c_modes, topic="🎒 EXFIL: missions, loot, extraction.")

    if ENABLE_COMPETITIVE:
        c_comp = await category(guild, "🏆 COMPETITIVE")
        await text(guild, "tournament-signups", c_comp, topic="📝 Register your team.")
        await text(guild, "scrims", c_comp, topic="⚔️ Find practice matches.")
        await text(guild, "results-and-brackets", c_comp, topic="📊 Brackets & results.",
            overwrites={everyone: RO(send_messages=False)})

    # -------------------------------------------------- SUPPORT & FEEDBACK
    c_sup = await category(guild, "🐛 SUPPORT")
    # Bug reports = PUBLIC FORUM (native). Each bug = its own post + tags (mode + status).
    await forum(guild, "bug-reports", c_sup, slowmode=15,
        topic=("Report ONE bug per post. Tag the mode + status.\n"
               "Title = short summary. Body: Steps 1)2)3) • Expected • Got • "
               "Frequency (always/sometimes/once) • Proof (clip/screenshot)."),
        tags=["DUALS", "DOMINATION", "EXFIL", "HUB", "Open", "Confirmed", "Fixed", "Duplicate"])
    await text(guild, "feedback-and-ideas", c_sup, topic="📝 Game feedback.")
    ch_support = await text(guild, "support", c_sup, topic="🆘 Open a ticket for help.")

    # --------------------------------------------------- FACTIONS (private)
    fac_ids = {}
    for label, emoji, frole in [(FACTION_1,"🔴",r_f1),(FACTION_2,"🔵",r_f2)]:
        fac_ids[label] = frole.id
        cat_f = await category(guild, f"{emoji} {label.upper()}", {
            everyone: RO(view_channel=False), frole: RO(view_channel=True), **staff_view})
        await text(guild, "faction-announcements", cat_f,
            overwrites={frole: RO(send_messages=False), **staff_view}, topic=f"📢 {label} only.")
        await text(guild, "faction-chat", cat_f, topic=f"💬 {label} HQ.")
        await text(guild, "strategy", cat_f, topic="🧠 Coordination & tactics.")
        await text(guild, "recruitment", cat_f, topic="🤝 Recruit for your squad.")
        await voice(guild, f"{emoji} {label} Voice", cat_f,
            overwrites={everyone: RO(view_channel=False),
                        frole: RO(view_channel=True, connect=True), **staff_view})

    # ------------------------------------------------ GAME FEED (webhooks)
    feed_channels = {}
    if ENABLE_GAME_FEED:
        c_feed = await category(guild, "📡 GAME FEED", {everyone: RO(view_channel=True, send_messages=False)})
        for cname, tp in [("match-results","🎮 Auto-posted match results."),
                         ("live-leaderboard","🏆 Top ranked LP players."),
                         ("level-ups","⬆️ Level-up & milestone feed.")]:
            feed_channels[cname] = await text(guild, cname, c_feed, topic=tp)

    if ENABLE_PLAYTEST:
        c_pt = await category(guild, "🧪 PLAYTEST", {everyone: RO(view_channel=False),
                                                    r_tester: RO(view_channel=True), **staff_view})
        await text(guild, "playtest-announcements", c_pt,
            overwrites={r_tester: RO(send_messages=False), **staff_view}, topic="🧪 Upcoming test sessions.")
        await text(guild, "playtest-feedback", c_pt, topic="🗒️ Detailed tester feedback.")
        await text(guild, "test-builds", c_pt, topic="🔨 Experimental builds / changelogs.")

    # -------------------------------------------------------------------- VOICE
    c_voc = await category(guild, "🎧 VOICE")
    await voice(guild, "General 1", c_voc); await voice(guild, "General 2", c_voc)
    await voice(guild, "🎮 Squad 1", c_voc, user_limit=5); await voice(guild, "🎮 Squad 2", c_voc, user_limit=5)
    await voice(guild, "📺 Streaming", c_voc); await voice(guild, "💤 AFK", c_voc)

    # ----------------------------------------------------------- SERVER SETTINGS
    if ENABLE_SERVER_SETTINGS:
        print("\n📌 SERVER SETTINGS")
        try:
            await guild.edit(verification_level=discord.VerificationLevel.medium,
                             default_notifications=discord.NotificationLevel.only_mentions,
                             system_channel=ch_welcome, reason="Setup")
            log("✅ verification=medium, notifications=mentions, system=#welcome", 1)
        except discord.HTTPException as e:
            log(f"⚠️ settings: {e}", 1)

    await setup_automod(guild, ch_modlog, exempt_roles=[r_founder, r_admin, r_mod])
    await setup_onboarding(guild, [ch_welcome, ch_rules, ch_announce], r_f1, r_f2, notif)

    # ---------------------------------------------------------- WEBHOOKS (feed)
    webhook_urls = {}
    if ENABLE_GAME_FEED:
        print("\n📌 WEBHOOKS (paste into your Roblox game — keep SECRET)")
        for cname, ch in feed_channels.items():
            try:
                wh = await ch.create_webhook(name=f"{GAME_NAME} Feed", reason="Setup")
                webhook_urls[cname] = wh.url; log(f"🔗 {cname}: {wh.url}", 1)
            except discord.HTTPException as e:
                log(f"⚠️ webhook {cname}: {e}", 1)

    # ---------------------------------------------------------------- MESSAGES
    print("\n📌 MESSAGES & PANELS")
    await post_once(ch_rules, embed=discord.Embed(
        title=f"📜 {GAME_NAME} Rules", color=discord.Color.blurple(), description=(
            "**1.** Be respectful — no insults, harassment or discrimination.\n"
            "**2.** Faction rivalry stays **in-game** — no real toxicity.\n"
            "**3.** No spam, flooding or unsolicited ads.\n"
            "**4.** No cheating, exploiting or glitch abuse.\n"
            "**5.** No NSFW / illegal content.\n"
            "**6.** Follow Discord **and** Roblox ToS.\n"
            "**7.** Staff decisions are final.\n\n"
            "⚠️ **Sanctions:** Warning → Mute → Kick → Ban.")))

    await post_once(ch_welcome, embed=discord.Embed(
        title=f"👋 Welcome to {GAME_NAME}!", color=discord.Color.gold(), description=(
            f"🔴🔵 Everything here is **faction-based**. To get started:\n\n"
            f"**1.** Read {ch_rules.mention}\n"
            f"**2.** Pick your faction in {ch_faction.mention}\n"
            f"**3.** Grab your pings in {ch_notifs.mention}\n"
            f"**4.** Link your Roblox account with `/link`\n"
            f"**5.** Introduce yourself and jump in!\n\n"
            f"🎮 **Play:** {ROBLOX_GAME_URL}\nMay the best faction win ⚔️")))

    await post_once(ch_faction, embed=discord.Embed(
        title="⚔️ Choose your faction", color=discord.Color.blurple(), description=(
            f"🔴 **{FACTION_1}**   •   🔵 **{FACTION_2}**\n\n"
            "Pick it on the **welcome screen** when you join, or anytime via **“Channels & Roles”** "
            "at the top of the channel list.\n\n"
            "_(Prefer clickable reactions instead? Invite **Carl-bot** and bind them — see the guide.)_")))

    await post_once(ch_notifs, embed=discord.Embed(
        title="🔔 Notification roles", color=discord.Color.green(), description=(
            "Choose your pings via **“Channels & Roles”** (top of the channel list):\n\n"
            "📢 Announcements • 🧪 Playtests • 🎮 LFG/Scrims • 🎉 Events • 📺 Livestreams")))

    await post_once(ch_links, embed=discord.Embed(
        title="🔗 Useful links", color=discord.Color.blurple(),
        description=f"🎮 **Play:** {ROBLOX_GAME_URL}\n📢 {ch_announce.mention}\n📺 (add YouTube/TikTok/X…)"))

    await post_once(ch_support, embed=discord.Embed(
        title="🎫 Support", color=discord.Color.blurple(),
        description="Need help or want to report a player? A **Ticket Tool** panel will live here — "
                    "click its button to open a private ticket with staff.\n\n"
                    "_(Staff: invite Ticket Tool and point its panel to this channel — see the guide.)_"))

    # ------------------------------------------------------- EXPORT bot_data.json
    DATA.update({
        "guild_id": guild.id, "staff_role_ids": STAFF_IDS, "linked_role_id": r_linked.id,
        "faction_role_ids": fac_ids, "rank_role_ids": rank_ids, "level_role_ids": level_ids,
        "tickets_category_id": c_tickets.id, "mod_log_channel_id": ch_modlog.id,
        "server_log_channel_id": ch_serverlog.id, "webhook_urls": webhook_urls,
    })
    with open(CONFIG_OUT, "w", encoding="utf-8") as f: json.dump(DATA, f, indent=2)
    print(f"\n💾 Wrote {CONFIG_OUT}")
    print("\n✅ Setup complete — NOTHING of yours needs to run 24/7:")
    print("   • faction picker (Onboarding) + AutoMod + in-game feed = native / serverless.")
    print("   • tickets  -> invite Ticket Tool  (https://tickettool.xyz)")
    print("   • logs     -> invite Logger / Dyno / Carl-bot")
    print("   See DISCORD_SETUP_GUIDE.md.")
    await client.close()


if __name__ == "__main__":
    if not BOT_TOKEN: raise SystemExit("❌ Set DISCORD_BOT_TOKEN env var. Never hardcode it.")
    if not GUILD_ID: raise SystemExit("❌ Set GUILD_ID.")
    client.run(BOT_TOKEN)
