# Architecture decisions

Short records of the choices that shape the Command Center. Each one says what was
decided, why, and what it costs.

## ADR 1: pull, not push

**Context.** Roblox offers webhooks for commerce and compliance (refunds, subscriptions,
right to erasure) but none for gameplay: no "season closed", no "server started", no
"player flagged". A game server can call out over HTTP, but only to a public HTTPS endpoint,
and the console started life on a home PC.

**Decision.** The game writes small, bounded state into Open Cloud stores and the console
reads it:

- a **heartbeat** per server in the MemoryStore sorted map `CC_Servers_V1` (30 s, plus on
  joins and leaves, at most one write every 2 s; entries expire after 300 s);
- **events** in the MemoryStore queue `CC_Events_V1` (season closed, ranked payout, sanction,
  cheat flag, honeypot, low rating, command acknowledgement), read every 20 s and discarded
  once stored locally;
- a **contract** per place in the DataStore `CC_Contract` (data version, store names,
  offers), so the console targets the right stores and flags a hub and a match that disagree.

**Consequences.** No public endpoint and nothing to authenticate on the game side; the
console can be off for a while and catch up (events wait up to 2 days, season results are
also derived from the archive). Latency is seconds, not milliseconds, which is fine for
operations. The MemoryStore budget is shared with matchmaking, so every writer is bounded:
the game stops queueing past 40 unread events, and counters live in the heartbeat. A test in
the game repository fails if these bounds are loosened.

## ADR 2: commands travel on the existing FW_Event topic

**Context.** The console needs to reach running servers (message a player, kick, drain a
server, change gold, remove an item). The game already subscribes every server to one
MessagingService topic, `FW_Event`, for boosts, modes and rewards.

**Decision.** Commands are another message kind on that topic:
`{kind: "cc_cmd", id, op, exp, ...}`, under 1 KB. Only the server hosting the target player
(or the targeted job id) executes; it answers with a `cmd_ack` event on the bus, which the
console shows in the dialog that sent the command. Ids are remembered to ignore replays, and
commands expire after two minutes.

**Consequences.** No new subscription per server (MessagingService subscriptions are a
limited resource) and one code path for every console-to-game write. MessagingService
delivery is not guaranteed, so the console treats a missing acknowledgement as "unknown",
never as "failed", and says so. Offline players are edited through DataStores instead,
under a lock the game waits on.

## ADR 3: SQLite

**Context.** The console stores events from the game, an audit journal, card states
(done, snoozed, dismissed), commands and their acknowledgements, backups taken before each
offline edit, and the notification register (one row per player per day). It ran as a
single process on one machine.

**Decision.** One SQLite file, `data/cc.db`, opened per call under a process lock, standard
library only. JSON files remain for hand-edited data (announcement templates, settings,
arsenal).

**Consequences.** Zero setup and trivially backed up; enough for thousands of events per
day. The schema is plain SQL, so moving to PostgreSQL when the console is hosted with
several workers (lot 6) is a driver change, not a redesign.

## ADR 4: a demo world behind the real network layer

**Context.** A console for a live game is hard to show or to test without the game.

**Decision.** `CC_DEMO=1` replaces `urllib.request.urlopen` with an in-memory router that
implements the Roblox and Discord endpoints the console uses (same paths, payloads and error
codes) and runs a small simulation. Nothing else in the code knows it is in demo mode.

**Consequences.** The demo exercises the production code paths end to end, including error
handling (409 on a taken lock, 429 on a second notification the same day). The simulation
has to follow API changes; tests cover the main flows (registry, season close, command
acknowledgement, offline edit, notification limit).
