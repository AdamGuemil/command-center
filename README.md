# Shroud War Command Center

A live-ops console for **Shroud War**, a Roblox PvP experience: live servers and players,
season automation, player actions, out-of-game notifications and Discord announcements,
from one page. It tells the operator *what to do now* instead of waiting to be asked.

![CI](https://github.com/AdamGuemil/command-center/actions/workflows/ci.yml/badge.svg)

> The interface and the detailed operating docs are in French (the team's language).
> One Python process (FastAPI) serves the API, the UI, the Discord bot and the automation loop;
> no build step for the front end. Hosted behind Caddy with Discord sign-in, or run locally without it.

![Home: cards that say what needs attention](docs/images/home.png)

## What it does

| Area | What the operator gets |
|---|---|
| **Home** | One card per thing that needs attention (season closed, ranked payout, cheat, honeypot, crash burst, mixed place versions, manual setup tasks), each with a preview of exactly what will be published. Cards are computed by a pure function and keyed for idempotence. |
| **Live** | Every hub and match: mode, map, phase, players, FPS, memory, ping, place version; crash and freeze detection; restart old versions with an in-game banner. |
| **Players** | Connected roster and a full player sheet (profile, inventory and stash decoded, bans, honeypots); message, kick, ban, gold, item removal, gifts, with undo. |
| **Offline edits** | Write a player's data while they are offline without ever being overwritten: MemoryStore lock, presence checked twice, `etag`-conditioned write, original kept for undo. |
| **Notifications** | Roblox experience notifications (6 templates): audiences from the game's own indexes, one notification per player per day enforced by a local register, the strongest one kept. |
| **Broadcast** | Discord announcements with live variables (`{RUSFOR}`, `{IN_24H}`...), templates shared with a CLI, scheduler, audit journal. |
| **Roblox webhooks** | Refunds, subscription cancellations and right-to-erasure requests arrive signed (HMAC) and become cards; erasure deletes every player key after a typed confirmation. |
| **Automations** | Per rule: manual (default), delayed with a cancel button on the card, or immediate; quiet hours; one switch puts everything back to manual. Destructive actions are never automatable. |
| **Access** | Sign in with Discord; admins, moderators (read, message, kick) and viewers by Discord id; every action in the journal carries its author. Phone layout for Home, Live and player sheets. |
| **Health** | One probe per Open Cloud permission: the screen names the exact scope that is missing. `/healthz` for uptime monitors. |

![Live servers](docs/images/live.png)

## Architecture

```mermaid
flowchart LR
  subgraph Roblox
    G["Game servers<br/>Hub and matches"]
    OC[("Open Cloud<br/>DataStores, MemoryStore,<br/>Messaging, Analytics")]
  end
  CC["Command Center<br/>FastAPI + Discord bot"]
  UI["Web UI<br/>ES modules, no build"]
  DB[("SQLite<br/>events, audit, campaigns")]
  D["Discord"]
  P["Players<br/>site and app"]
  WH["Roblox webhooks"]
  B["Browser<br/>PC or phone"]
  CD["Caddy (HTTPS)"]
  G -- "heartbeat, events, contract" --> OC
  OC -- "read (pull)" --> CC
  CC -- "writes + publish FW_Event" --> OC
  OC -- "MessagingService" --> G
  CC --- DB
  CC <-- "JSON API" --> UI
  B -- "Discord sign-in" --> CD --> CC
  WH -- "HMAC-signed POST" --> CD
  CC -- "bot (REST + gateway)" --> D
  CC -- "notifications" --> OC
  OC -.-> P
```

- **The game pushes nothing to the outside world.** Servers write small, bounded state into
  Open Cloud stores (a heartbeat in a MemoryStore sorted map, events in a MemoryStore queue,
  a contract per place); the Command Center reads them. No public endpoint, no inbound
  traffic, nothing to secure on the game side. See [ADR 1](docs/ARCHITECTURE.md#adr-1-pull-not-push).
- **Commands reuse the game's existing messaging topic** (`FW_Event`), with ids, expiry and
  acknowledgements on the event bus. See [ADR 2](docs/ARCHITECTURE.md#adr-2-commands-travel-on-the-existing-fw_event-topic).
- **FastAPI** serves the same JSON routes as before; handlers stay synchronous and run in
  the thread pool, so the Discord bot shares the event loop. See [ADR 4](docs/ARCHITECTURE.md#adr-4-fastapi-with-synchronous-handlers).
- **SQLite** keeps events, the audit journal, card state, command history, edit backups,
  the notification register and Discord-Roblox account links. See [ADR 3](docs/ARCHITECTURE.md#adr-3-sqlite).
- **Access** is Discord sign-in against an allowlist of Discord ids, with server-side sessions,
  CSRF tokens and rate limits; without it the console refuses to leave loopback. See [ADR 5](docs/ARCHITECTURE.md#adr-5-discord-login-an-id-allowlist-server-side-sessions).
- **Webhooks** only verify and store; **automations** call the same handlers as a click. See
  [ADR 6](docs/ARCHITECTURE.md#adr-6-webhooks-verify-and-store-automations-reuse-the-click-path).
- **Every data flow** (source, transport, destination, rate, cost, failure mode) is listed in
  [docs/PIPELINES.md](docs/PIPELINES.md).

## Roblox limits, taken as design constraints

| Limit | Consequence here |
|---|---|
| No webhook for gameplay events | Pull model: the console reads what the game writes. |
| MemoryStore memory is shared by the whole universe (64 KB + 1.2 KB per player), matchmaking included | The event queue expires after 2 days and the game stops writing past 40 unread events; a counter goes in the heartbeat, never in the queue. |
| MessagingService messages are 1 KB, unacknowledged | Commands carry an id and an expiry; servers acknowledge on the event bus. |
| One experience notification per player per day; text created by hand in the Creator Hub | Local per-day register, priority order, campaigns paused on repeated 429s; templates only referenced by asset id. |
| A live server overwrites a player's data on its next save | Offline edits go through a lock the game waits on; online edits are sent to the hosting server. |
| Analytics need ~100 daily users for some features | Setup tasks wait for the threshold and turn into "now's the time" cards. |

## Repository layout

```
server.py            launcher (uvicorn on 127.0.0.1:8787, single instance)
app.py               FastAPI app: JSON API from core/handlers.py, static UI, lifespan
announce.py          CLI for Discord announcements (shares templates with the UI)
bot.py               runs the Discord bot alone (it normally runs inside the server, CC_BOT=1)
core/                domain modules: API handlers, Discord bot, live registry, cards, events, commands, edits,
                     notifications, players, Faction War, ranked, analytics...
web/                 UI: index.html, css/, js/ (ES modules)
data/                seed data: announcement templates, settings, arsenal
docs/                PIPELINES.md, ARCHITECTURE.md (ADRs), OPERATIONS.md (French ops guide),
                     contract.schema.json
tests/               pytest suite (no network); tests/e2e: Playwright UI test with mocked API
tools/               setup_discord.py (one-shot server builder), Cloudflare webhook relay
deploy/              Caddyfile (HTTPS reverse proxy used by docker-compose.yml)
```

## Run it

**Locally** (no sign-in, loopback only):

```bash
pip install -r requirements.txt
cp .env.example .env         # Open Cloud key, universe and place ids, Discord bot token
python server.py             # http://127.0.0.1:8787, opens the browser; API docs at /api/docs
```

**Hosted** (HTTPS, Discord sign-in, always on): fill the "Heberge" part of `.env` (OAuth
client, public URL, domain, admin ids), point the domain's DNS at the server, then

```bash
docker compose up -d --build  # the console behind Caddy, data in a named volume
```

Step-by-step, including Roblox webhooks and the uptime probe, in
[docs/OPERATIONS.md](docs/OPERATIONS.md#héberger). The console refuses to start exposed
without sign-in configured. The Open Cloud permissions to grant, and how to check them, are in
[docs/OPERATIONS.md](docs/OPERATIONS.md#clés-à-créer). Set `CC_GAME_ROOT` to the game
repository to read the data version from `SharedConfig.luau` and show the game's guides.

## Quality

```bash
pip install -r requirements-dev.txt
pytest                      # cards, notifications, commands, offline edits, access, webhooks, automations...
ruff check . && mypy        # lint and types
node tests/e2e/browser_live.cjs   # UI test against a mocked API (Playwright)
```

CI runs all of the above on Python 3.11 to 3.13, builds the Docker image, checks that it
refuses to start exposed without sign-in and that it serves only the login page to anonymous
visitors, then publishes the image of every green `main` commit to `ghcr.io`.

## Roadmap

- Automatic deployment of the published image to the chosen host.
- Match history (`match_end`) and failed-receipt events on the bus; ending a running match.

## License

[MIT](LICENSE). Security reports: see [SECURITY.md](SECURITY.md).
