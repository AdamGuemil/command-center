"""
Mode demo : `CC_DEMO=1` lance le Command Center sans aucune cle, sur un faux univers.

Tout le CC parle a Roblox et a Discord par `urllib.request.urlopen`. En demo, cette fonction
est remplacee par un routeur en memoire qui repond comme les vraies API (memes chemins,
memes formats, memes codes d'erreur). Le reste du code ne sait pas qu'il est en demo : c'est
le meme chemin que la production, de bout en bout.

Le faux univers :
  * deux Hubs et quatre matchs qui battent toutes les 5 s dans le registre `CC_Servers_V1` ;
    un Hub tourne sur l'ancienne version de la place (redemarrage a essayer) ;
  * une saison qui se clot toutes les 10 minutes (archive, puis versement ranked une
    minute plus tard, chacun annonce sur le bus d'evenements) ;
  * des evenements du jeu de temps en temps : anticheat, piege, avis negatif, rafale
    d'erreurs de script ;
  * des profils, inventaires et stash lisibles, des bans, un index d'activite pour les
    notifications, des Analytics plausibles ;
  * un faux serveur Discord : les annonces sont « envoyees » et gardees en memoire.

Les donnees locales de la demo vivent dans data/demo/ (jamais melangees aux vraies).
Rien ne sort de la machine.
"""

from __future__ import annotations

import io
import json
import random
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from email.message import Message

from . import config

SEASON_S = 600                  # une saison toutes les 10 minutes
FIRST_CLOSE_IN_S = 180          # la premiere cloture arrive 3 minutes apres le lancement
PAYOUT_DELAY_S = 60
TICK_S = 5
HUB_PLACE, GAME_PLACE, UNIVERSE = "4000000001", "4000000002", "4000000000"
NEW_VERSION, OLD_VERSION = 42, 41
FACTIONS = ("Rainor", "Rusfor")
MODES = [("DUALS", 2, ["Quarry", "Rooftops"]), ("DOMINATION", 10, ["Harbor", "Refinery"]),
         ("EXFIL", 8, ["Marsh", "Old Town"]), ("OPERATIONS", 12, ["Citadel"])]
FIRST = ["Rook", "Vanta", "Kestrel", "Onyx", "Mara", "Juno", "Talon", "Brick", "Sable", "Nova",
         "Hex", "Ivo", "Lumen", "Pike", "Rhea", "Quill", "Atlas", "Wren", "Dax", "Zola"]
LAST = ["Shade", "Byte", "Fox", "Hollow", "Ridge", "Volt", "Stone", "Ward", "Drift", "Spark"]

_real_urlopen = urllib.request.urlopen
_installed = False


# REPONSES HTTP ----------------------------------------------------------------
class _Response:
    def __init__(self, status: int, payload):
        self.status = status
        raw = payload if isinstance(payload, (bytes, bytearray)) else (
            b"" if payload is None else json.dumps(payload).encode("utf-8"))
        self._buf = io.BytesIO(raw)
        self.headers = Message()

    def read(self, *a):
        return self._buf.read(*a)

    def getcode(self):
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _error(url: str, code: int, message: str = ""):
    body = json.dumps({"message": message or f"demo {code}"}).encode("utf-8")
    return urllib.error.HTTPError(url, code, message or "demo", Message(), io.BytesIO(body))


# LE FAUX UNIVERS --------------------------------------------------------------
class World:
    def __init__(self, seed: int = 7):
        self.rng = random.Random(seed)
        self.lock = threading.RLock()
        self.now0 = int(time.time())
        # Saison courante : se termine FIRST_CLOSE_IN_S apres le lancement, numerotee ~12.
        self.epoch = self.now0 + FIRST_CLOSE_IN_S - SEASON_S - 11 * SEASON_S
        self.ds: dict[str, dict[str, object]] = {}
        self.etags: dict[tuple[str, str], str] = {}
        self.ods: dict[str, dict[str, int]] = {}
        self.maps: dict[str, dict[str, tuple[object, float]]] = {}
        self.queue: list[dict] = []
        self.restrictions: dict[int, dict] = {}
        self.notified: set[tuple[int, str]] = set()
        self.discord: list[dict] = []
        self.configs = {"live": {"matchmaking_open": True, "max_party_size": 4},
                        "draft": {"matchmaking_open": True, "max_party_size": 4}}
        self.servers: dict[str, dict] = {}
        self.pending: list[tuple[float, Callable[[], None]]] = []
        self.next_event = self.now0 + 25
        self.last_week = self.week()
        self.players = self._roster(64)
        self.by_id = {p["u"]: p for p in self.players}
        self._seed()

    # Calendrier ------------------------------------------------------------
    def week(self, now: int | None = None) -> int:
        return (int(now or time.time()) - self.epoch) // SEASON_S

    def bounds(self, week: int) -> tuple[int, int]:
        start = self.epoch + week * SEASON_S
        return start, start + SEASON_S

    # Donnees de depart -----------------------------------------------------
    def _roster(self, n: int) -> list[dict]:
        out: list[dict] = []
        used: set[str] = set()
        while len(out) < n:
            name = f"{self.rng.choice(FIRST)}{self.rng.choice(LAST)}{self.rng.randint(1, 99)}"
            if name in used:
                continue
            used.add(name)
            i = len(out)
            out.append({"u": 9_100_000_000 + i * 7919, "n": name, "f": FACTIONS[i % 2],
                        "l": self.rng.randint(3, 48), "lp": self.rng.randint(800, 2400),
                        "money": self.rng.randint(1_500, 90_000)})
        return out

    def dsn(self, base: str) -> str:
        return config.datastore_name(base)

    def put(self, store: str, key: str, value) -> str:
        self.ds.setdefault(store, {})[key] = value
        etag = uuid.uuid4().hex[:16]
        self.etags[(store, key)] = etag
        return etag

    def get(self, store: str, key: str):
        return self.ds.get(store, {}).get(key)

    def _item(self, template: str, name: str, **attrs) -> dict:
        return {"u": uuid.uuid4().hex[:10], "i": template.lower(), "t": template,
                "a": {"ItemName": name, **attrs}}

    def _seed(self) -> None:
        now = self.now0
        for kind, place in (("hub", HUB_PLACE), ("match", GAME_PLACE)):
            self.put("CC_Contract", f"place_{place}", {
                "contractRev": 1, "placeId": int(place), "placeKind": kind,
                "dsVersion": config.DATASTORE_VERSION, "hubPlaceId": int(HUB_PLACE),
                "gamePlaceId": int(GAME_PLACE), "registryMap": "CC_Servers_V1", "fwTopic": "FW_Event",
                "stores": {k: self.dsn(v) for k, v in {
                    "profile": "GlobalData", "skills": "PlayerData_Skills&XP",
                    "inventory": "PlayerData_Inventory", "stash": "PlayerData_Stash",
                    "sanctions": "Sanctions", "exfilClaim": "ExfilClaim",
                    "blackMarketDebts": "BlackMarketDebts", "factionWar": "FactionWar",
                    "honeypot": "Honeypot", "honeypotIndex": "HoneypotIndex"}.items()},
                "offers": [], "writtenAt": now})
        fw = config.FW_DATASTORE
        for p in self.players:
            uid = p["u"]
            self.put(self.dsn("GlobalData"), f"p_{uid}", {
                "faction": p["f"], "money": p["money"], "lp": p["lp"], "placementsPlayed": 5,
                "specialization": self.rng.choice(["Assault", "Recon", "Support", "Engineer"]),
                "hasFinishedTutorial": True, "lastSeenAt": now - self.rng.randint(0, 6 * 86400),
                "createdAt": now - self.rng.randint(5, 60) * 86400})
            self.put(self.dsn("PlayerData_Skills&XP"), f"p_{uid}", {"level": p["l"], "xp": p["l"] * 830})
            rifle = self._item("M4A1", "M4A1 Carbine", Durability=self.rng.randint(55, 100))
            bag = self._item("Backpack_M", "Medium backpack")
            bag["b"] = [self._item("Bandage", "Bandage", Quantity=3), self._item("Mag556", "5.56 magazine", Quantity=2)]
            self.put(self.dsn("PlayerData_Inventory"), str(uid), {
                "_v": 2, "active": 1,
                "equipped": {"Primary": rifle, "Secondary": self._item("Glock17", "Glock 17"), "Backpack": bag},
                "pockets": [self._item("Grenade", "Frag grenade", Quantity=1)]})
            self.put(self.dsn("PlayerData_Stash"), str(uid), {
                "_v": 2, "unlockedTabs": 2, "permanentTabs": 1,
                "tabs": [{"name": "Main", "items": [self._item("AK47", "AK-47"), self._item("Scope4x", "4x scope"),
                                                     self._item("Medkit", "Medkit", Quantity=2)]},
                         {"name": "Loot", "items": [self._item("GoldBar", "Gold bar", Quantity=4)]}]})
            # Index d'activite : derniere arrivee au Hub, de quelques minutes a 40 jours.
            age_h = self.rng.choice([0, 1, 3, 10, 30, 60, 100, 200, 300, 500, 700, 900])
            self.ods.setdefault(self.dsn("CC_LastSeen"), {})[str(uid)] = now // 3600 - age_h
            self.ods.setdefault(self.dsn("RankedLB"), {})[str(uid)] = p["lp"]
            meta = self.ds.setdefault(self.dsn("RankedMeta"), {}).setdefault(f"s_{uid % 8}", {})
            if isinstance(meta, dict):
                meta[str(uid)] = p["f"]
        # Saison en cours et saison precedente (deja close).
        week = self.week()
        self._season_scores(week - 1, burst=True)
        self._season_scores(week, burst=True)
        self._close_season(week - 1, at=self.bounds(week)[0] + 40, announce=False)
        self._payout(week - 1, at=self.bounds(week)[0] + 100, announce=False)
        # Un boost en cours : la carte « prevenir les absents » et l'ecran Boosts ont du contenu.
        self.put(fw, config.FW_OVERRIDE_KEY, {"id": "admin", "name": "DOUBLE XP", "desc": "Weekend boost",
                                              "startsAt": now - 1800, "endsAt": now + 4 * 3600,
                                              "xpMult": 2, "goldMult": 1, "factionPointMult": 1, "setAt": now - 1800})
        # Un piege anti-triche deja declenche, une sanction en cours.
        cheater = self.players[5]
        self._honeypot(cheater, "AdminGiveCurrency", announce=False)
        self.put(self.dsn("Sanctions"), str(self.players[9]["u"]), {"strikes": 2, "banUntil": 0,
                                                                     "history": [{"at": now - 86400, "reason": "Speed"}]})
        # Serveurs.
        for i in range(2):
            self._spawn_hub(version=NEW_VERSION if i == 0 else OLD_VERSION)
        for mode in MODES:
            self._spawn_match(mode)

    # Simulation ------------------------------------------------------------
    def _free_players(self) -> list[dict]:
        busy = {p["u"] for s in self.servers.values() for p in s["players"]}
        return [p for p in self.players if p["u"] not in busy]

    def _row(self, p: dict, team: int | None = None) -> dict:
        return {"u": p["u"], "n": p["n"], "f": p["f"], "l": p["l"], "t": team,
                "k": 0, "d": 0, "p": self.rng.randint(35, 140)}

    def _spawn_hub(self, version: int = NEW_VERSION) -> None:
        job = uuid.uuid4().hex
        free = self._free_players()
        self.rng.shuffle(free)
        self.servers[job] = {"jobId": job, "kind": "hub", "placeId": int(HUB_PLACE), "placeVersion": version,
                             "startedAt": int(time.time()) - self.rng.randint(600, 7200), "mode": None,
                             "players": [self._row(p) for p in free[:self.rng.randint(5, 9)]], "maxPlayers": 30}

    def _spawn_match(self, mode=None) -> None:
        name, size, maps = mode or self.rng.choice(MODES)
        free = self._free_players()
        if len(free) < size:
            return
        self.rng.shuffle(free)
        job = uuid.uuid4().hex
        self.servers[job] = {"jobId": job, "kind": "match", "placeId": int(GAME_PLACE), "placeVersion": NEW_VERSION,
                             "startedAt": int(time.time()), "mode": name, "map": self.rng.choice(maps),
                             "matchId": uuid.uuid4().hex[:8], "private": True,
                             "players": [self._row(p, i % 2 + 1) for i, p in enumerate(free[:size])],
                             "maxPlayers": size, "ends": int(time.time()) + self.rng.randint(150, 420)}

    def _beat(self, s: dict, now: int) -> None:
        n = len(s["players"])
        for p in s["players"]:
            if s["kind"] == "match" and self.rng.random() < 0.15:
                p["k"] += 1
            p["p"] = max(20, min(220, p["p"] + self.rng.randint(-8, 8)))
        value = {
            "v": 1, "jobId": s["jobId"], "placeId": s["placeId"], "placeVersion": s["placeVersion"],
            "kind": s["kind"], "dsVersion": config.DATASTORE_VERSION, "mode": s.get("mode"),
            "map": s.get("map"), "matchId": s.get("matchId"),
            "phase": None if s["kind"] == "hub" else ("ending" if s.get("ends", now) - now < 20 else "combat"),
            "private": s.get("private"), "startedAt": s["startedAt"],
            "fps": self.rng.randint(54, 60) if n < 10 else self.rng.randint(38, 58),
            "mem": 900 + n * 45 + self.rng.randint(-30, 30), "netIn": 40 + n * 6, "netOut": 60 + n * 11,
            "hbMs": round(self.rng.uniform(1.5, 6.0), 1),
            "ping": round(sum(p["p"] for p in s["players"]) / n) if n else None,
            "maxPlayers": s["maxPlayers"], "discord": {"s": self.rng.randint(0, 30), "d": 0, "f": 0, "t": 0},
            "err": s.get("err"), "players": s["players"], "hb": now,
        }
        self.maps.setdefault("CC_Servers_V1", {})[s["jobId"]] = (value, now + 300)

    def _season_scores(self, week: int, burst: bool = False) -> None:
        fw = config.FW_DATASTORE
        lb = {f: self.ods.setdefault(self.dsn(f"FWLB_w{week}_{f}"), {}) for f in FACTIONS}
        for p in self.players:
            if not burst and self.rng.random() > 0.25:
                continue
            gain = self.rng.randint(20, 400) * (8 if burst else 1)
            lb[p["f"]][str(p["u"])] = lb[p["f"]].get(str(p["u"]), 0) + gain
            shard = f"s_{week}_{p['f']}_{p['u'] % 4}"
            self.put(fw, shard, int(self.get(fw, shard) or 0) + gain)

    def _totals(self, week: int) -> dict:
        fw = config.FW_DATASTORE
        return {f: sum(int(self.get(fw, f"s_{week}_{f}_{i}") or 0) for i in range(4)) for f in FACTIONS}

    def _close_season(self, week: int, at: int, announce: bool = True) -> None:
        totals = self._totals(week)
        winner = max(totals, key=lambda f: totals[f])
        self.put(config.FW_DATASTORE, f"archive_{week}", {"week": week, "winner": winner, **totals, "closedAt": at})
        if announce:
            self.emit("season_closed", {"week": week, "winner": winner, **totals}, f"season_closed:w{week}")

    def _payout(self, week: int, at: int, announce: bool = True) -> None:
        fw = config.FW_DATASTORE
        top = sorted(self.ods.get(self.dsn("RankedLB"), {}).items(), key=lambda kv: -kv[1])[:25]
        pid = f"p{at}"
        entries = {uid: {"rank": i, "lp": lp, "gold": max(500, 2000 - i * 60), "xp": 400, "title": "",
                         "badges": []} for i, (uid, lp) in enumerate(top, start=1)}
        self.put(fw, f"ranked_payout_{pid}", {"id": pid, "at": at, "week": week, "entries": entries,
                                             "count": len(entries)})
        index = [{"id": pid, "at": at, "count": len(entries), "week": week}]
        old = self.get(fw, "ranked_payout_index")
        index += [e for e in (old if isinstance(old, list) else []) if e.get("id") != pid]
        self.put(fw, "ranked_payout_index", index[:8])
        if announce:
            self.emit("ranked_payout", {"id": pid, "week": week, "count": len(entries)}, f"ranked_payout:{pid}")

    def _honeypot(self, p: dict, trap: str, announce: bool = True) -> None:
        now = int(time.time())
        uid = p["u"]
        rec = self.get(self.dsn("Honeypot"), f"u_{uid}") or {"calls": 0, "traps": {}, "samples": []}
        rec["calls"] += self.rng.randint(3, 14)
        rec["traps"][trap] = rec["traps"].get(trap, 0) + 1
        rec["samples"] = (rec["samples"] + [{"trap": trap, "at": now, "args": ["999999"]}])[-5:]
        rec["lastAt"] = now
        self.put(self.dsn("Honeypot"), f"u_{uid}", rec)
        self.ods.setdefault(self.dsn("HoneypotIndex"), {})[str(uid)] = now
        if announce:
            self.emit("honeypot", {"u": uid, "n": p["n"], "trap": trap,
                                   "text": f"{p['n']} a appelé le remote leurre {trap} ({rec['calls']} appels)."})

    def emit(self, t: str, d: dict, eid: str | None = None, server: dict | None = None) -> None:
        srv: dict = server or next(iter(self.servers.values()), None) or {}
        now = int(time.time())
        event = {"id": eid or f"{t}:{uuid.uuid4().hex[:10]}", "t": t, "at": now,
                 "job": str(srv.get("jobId", ""))[:8], "pl": srv.get("kind", "hub"), "d": d}
        self.queue.append({"data": json.dumps(event), "id": uuid.uuid4().hex})

    def _random_event(self, now: int) -> None:
        kind = self.rng.choice(["ac_flag", "ac_flag", "feedback", "honeypot", "sanction", "errors"])
        p = self.rng.choice(self.players)
        if kind == "ac_flag":
            self.emit("ac_flag", {"u": p["u"], "n": p["n"], "title": f"Anticheat : {p['n']}",
                                  "text": f"Vitesse anormale : {self.rng.randint(31, 48)} studs/s pendant 4 s."})
        elif kind == "sanction":
            self.emit("sanction", {"u": p["u"], "n": p["n"], "title": f"Sanction : {p['n']}",
                                   "text": "Avertissement automatique (3e signalement de vitesse)."})
        elif kind == "feedback":
            rating = self.rng.choice([1, 2])
            text = self.rng.choice(["Matchmaking takes forever at night.", "Lost my kit after a disconnect.",
                                    "Too many grenades in DOMINATION."])
            self.emit("feedback", {"u": p["u"], "rating": rating, "title": f"Avis {rating}★ de {p['n']}",
                                   "text": text})
        elif kind == "honeypot":
            self._honeypot(p, self.rng.choice(["AdminGiveCurrency", "DebugSetLevel", "ForceWinMatch"]))
        else:
            srv = self.rng.choice(list(self.servers.values()))
            srv["err"] = {"n": self.rng.randint(22, 60), "s": "InventoryServer",
                          "m": "attempt to index nil with 'Parent'", "at": now // 60 * 60}
            def calm(s: dict = srv) -> None:
                s.pop("err", None)
            self.pending.append((now + 70, calm))

    def tick(self) -> None:
        with self.lock:
            now = int(time.time())
            week = self.week(now)
            if week != self.last_week:
                closed = self.last_week
                self.last_week = week
                self._close_season(closed, now)
                def pay(w: int = closed) -> None:
                    self._payout(w, int(time.time()))
                self.pending.append((now + PAYOUT_DELAY_S, pay))
            self._season_scores(week)
            for at, fn in [x for x in self.pending if x[0] <= now]:
                self.pending.remove((at, fn))
                fn()
            for job, s in list(self.servers.items()):
                if s["kind"] == "match" and now >= s.get("ends", now + 1):
                    del self.servers[job]
                    self.maps.get("CC_Servers_V1", {}).pop(job, None)
                    self._spawn_match()
            while sum(1 for s in self.servers.values() if s["kind"] == "match") < 4:
                before = len(self.servers)
                self._spawn_match()
                if len(self.servers) == before:
                    break
            for s in self.servers.values():
                if s["kind"] == "hub" and self.rng.random() < 0.3:
                    free = self._free_players()
                    if free and len(s["players"]) < 12 and self.rng.random() < 0.6:
                        p = self.rng.choice(free)
                        s["players"].append(self._row(p))
                        self.ods.setdefault(self.dsn("CC_LastSeen"), {})[str(p["u"])] = now // 3600
                    elif len(s["players"]) > 3:
                        s["players"].pop(self.rng.randrange(len(s["players"])))
                self._beat(s, now)
            if now >= self.next_event:
                self.next_event = now + self.rng.randint(35, 80)
                self._random_event(now)

    # Commandes CC -> jeu (cc_cmd) ---------------------------------------------
    def command(self, cmd: dict) -> None:
        op = cmd.get("op")
        targets = []
        if cmd.get("u"):
            uid = int(cmd["u"])
            srv = next((s for s in self.servers.values() if any(p["u"] == uid for p in s["players"])), None)
            targets = [srv] if srv else []
        elif cmd.get("job") == "*":
            targets = list(self.servers.values())
        elif cmd.get("job"):
            targets = [s for s in self.servers.values() if s["jobId"] == cmd["job"]]

        def ack(srv, ok=True, msg=""):
            self.emit("cmd_ack", {"cmd": cmd.get("id"), "op": op, "ok": ok, "msg": msg, "u": cmd.get("u")},
                      f"cmd_ack:{cmd.get('id')}:{srv['jobId'][:8]}", srv)

        def run():
            with self.lock:
                for srv in targets:
                    if op == "kick":
                        srv["players"] = [p for p in srv["players"] if p["u"] != int(cmd["u"])]
                        ack(srv, True, "Joueur expulsé.")
                    elif op == "drain":
                        srv["players"] = []
                        ack(srv, True, f"Bandeau affiché, serveur vidé dans {cmd.get('delay') or 30} s.")
                    elif op == "set_money":
                        p = self.by_id.get(int(cmd["u"]))
                        if p:
                            p["money"] = int(cmd.get("amount") or 0)
                            prof = self.get(self.dsn("GlobalData"), f"p_{p['u']}")
                            if isinstance(prof, dict):
                                prof["money"] = p["money"]
                        ack(srv, True, f"Or fixé à {cmd.get('amount')}.")
                    elif op == "remove_item":
                        ack(srv, False, "Objet porté : le jeu ne retire que les poches et les sacs d'un joueur en ligne.")
                    else:
                        ack(srv, True, "Message affiché.")
        timer = threading.Timer(1.5, run)   # le temps d'un aller-retour MessagingService
        timer.daemon = True
        timer.start()

    def restart(self, all_versions: bool) -> None:
        for job, s in list(self.servers.items()):
            if all_versions or s["placeVersion"] != NEW_VERSION:
                del self.servers[job]
                self.maps.get("CC_Servers_V1", {}).pop(job, None)
                if s["kind"] == "hub":
                    self._spawn_hub()
                else:
                    self._spawn_match()


WORLD: World | None = None


# ROUTEUR ----------------------------------------------------------------------
def _json(body: bytes | None):
    if not body:
        return {}
    try:
        return json.loads(body.decode("utf-8"))
    except ValueError:
        return {}


def _filter_range(expr: str) -> tuple[float, float]:
    lo, hi = float("-inf"), float("inf")
    for part in (expr or "").split("&&"):
        bits = part.split()
        if len(bits) == 3 and bits[1] == ">=":
            lo = float(bits[2])
        elif len(bits) == 3 and bits[1] == "<=":
            hi = float(bits[2])
    return lo, hi


def _page(items: list, token: str | None, size: int) -> tuple[list, str | None]:
    start = int(token or 0)
    nxt = start + size
    return items[start:nxt], (str(nxt) if nxt < len(items) else None)


def _analytics(body: dict) -> dict:
    step = {"OneMinute": 60, "HalfHour": 1800, "OneHour": 3600, "OneDay": 86400}.get(str(body.get("granularity")), 1800)
    start = datetime.fromisoformat(str(body.get("startTime")).replace("Z", "+00:00"))
    end = datetime.fromisoformat(str(body.get("endTime")).replace("Z", "+00:00"))
    metric = body.get("metric")
    breakdown = (body.get("breakdown") or [None])[0]
    known: dict[str, list[str | None]] = {"Place": [HUB_PLACE, GAME_PLACE], "CrashType": ["OutOfMemory", "Timeout"],
                                          "DataStoreStatus": ["Success", "Throttled"]}
    groups = known.get(str(breakdown), [None])
    base = {"PeakConcurrentPlayers": 40, "ServerCrashCount": 0.2, "ServerFrameRateP10": 52,
            "MemoryUsageP90": 1500, "CpuTimeP90": 9, "ClientCrashRate15m": 0.6,
            "DataStoreRequestsByStatus": 900, "DailyActiveUsers": 260, "DailyRevenue": 1800}.get(str(metric), 10)
    values = []
    for gi, g in enumerate(groups):
        points: list[dict] = []
        t = start
        rng = random.Random(f"{metric}{g}")
        while t <= end and len(points) < 2000:
            hour = t.hour + t.minute / 60
            wave = 0.6 + 0.4 * abs(((hour - 6) % 24) - 12) / 12
            v = base * (wave if metric in ("PeakConcurrentPlayers", "DataStoreRequestsByStatus") else 1)
            v *= (1 - 0.35 * gi) if g else 1
            if metric == "ServerCrashCount":
                v = 1 if rng.random() < (0.002 if step < 1800 else 0.03) else 0
            elif g == "Throttled":
                v = base * 0.02
            points.append({"time": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "value": round(v * rng.uniform(0.9, 1.1), 2)})
            t += timedelta(seconds=step)
        values.append({"breakdowns": [{"dimension": breakdown, "value": g}] if g else [], "dataPoints": points})
    return {"done": True, "response": {"values": values}}


def _world() -> World:
    if WORLD is None:
        raise RuntimeError("mode demo non installe")
    return WORLD


def route(method: str, url: str, body: bytes | None):
    """(status, payload) ; leve HTTPError comme la vraie API."""
    w = _world()
    parsed = urllib.parse.urlparse(url)
    host, path = parsed.netloc, urllib.parse.unquote(parsed.path)
    q = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
    with w.lock:
        # --- Discord -----------------------------------------------------------
        if host == "discord.com":
            return _discord(method, path, body)
        # --- API publiques Roblox ------------------------------------------------
        if host == "games.roblox.com":
            if path.endswith("/servers/Public"):
                return 200, {"data": [{"id": s["jobId"], "playing": len(s["players"]), "maxPlayers": s["maxPlayers"]}
                                      for s in w.servers.values() if s["kind"] == "hub"]}
            return 200, {"data": [{"id": int(UNIVERSE), "name": "Shroud War (démo)", "playing":
                                   sum(len(s["players"]) for s in w.servers.values()),
                                   "visits": 48_210,
                                   "favoritedCount": 1_930, "maxPlayers": 30, "isGenreEnforced": False}]}
        if host == "users.roblox.com":
            data = _json(body)
            if path.endswith("/usernames/users"):
                wanted = {str(n).lower(): n for n in data.get("usernames", [])}
                return 200, {"data": [{"requestedUsername": wanted[p["n"].lower()], "id": p["u"], "name": p["n"],
                                       "displayName": p["n"]} for p in w.players if p["n"].lower() in wanted]}
            ids = {int(i) for i in data.get("userIds", [])}
            return 200, {"data": [{"id": p["u"], "name": p["n"], "displayName": p["n"]}
                                  for p in w.players if p["u"] in ids]}
        if host == "thumbnails.roblox.com":
            return 200, {"data": []}
        if host != "apis.roblox.com":
            raise _error(url, 404, "hôte inconnu en démo")
        # --- Analytics -----------------------------------------------------------
        if path.startswith("/analytics-query-api/"):
            return 200, _analytics(_json(body)) if method == "POST" else {"done": True, "response": {"values": []}}
        # --- DataStores v1 -------------------------------------------------------
        if "/standard-datastores/datastore/entries" in path:
            store = q.get("datastoreName", "")
            if path.endswith("/entry"):
                key = q.get("entryKey", "")
                if method == "GET":
                    value = w.get(store, key)
                    if value is None:
                        raise _error(url, 404, "NOT_FOUND")
                    return 200, json.loads(json.dumps(value))
                if method == "POST":
                    w.put(store, key, json.loads((body or b"null").decode("utf-8")))
                    return 200, {"version": uuid.uuid4().hex[:8]}
                if method == "DELETE":
                    w.ds.get(store, {}).pop(key, None)
                    return 204, None
            keys = sorted(k for k in w.ds.get(store, {}) if k.startswith(q.get("prefix", "")))
            page, nxt = _page(keys, q.get("cursor"), int(q.get("limit", 100)))
            return 200, {"keys": [{"key": k} for k in page], "nextPageCursor": nxt}
        # --- Ordered DataStores v1 -----------------------------------------------
        if "/ordered-data-stores/v1/" in path:
            store = path.split("/orderedDataStores/")[1].split("/")[0]
            entries = w.ods.get(store, {})
            lo, hi = _filter_range(q.get("filter", ""))
            rows = sorted(((k, v) for k, v in entries.items() if lo <= v <= hi),
                          key=lambda kv: kv[1], reverse=q.get("order_by") == "desc")
            page, nxt = _page(rows, q.get("page_token"), int(q.get("max_page_size", 10)))
            return 200, {"entries": [{"id": k, "value": v, "path": f"entries/{k}"} for k, v in page],
                         "nextPageToken": nxt}
        # --- Cloud v2 --------------------------------------------------------------
        if path.endswith(":publishMessage"):
            msg = _json(body)
            try:
                inner = json.loads(msg.get("message") or "{}")
            except ValueError:
                inner = {}
            if inner.get("kind") == "cc_cmd":
                w.command(inner)
            return 200, {}
        if path.endswith(":restartServers"):
            w.restart(bool(_json(body).get("closeAllVersions")))
            return 200, {}
        if "/data-stores/" in path and "/entries/" in path:
            store = path.split("/data-stores/")[1].split("/")[0]
            key = path.split("/entries/")[1]
            if method == "GET":
                value = w.get(store, key)
                if value is None:
                    raise _error(url, 404, "NOT_FOUND")
                return 200, {"path": path, "id": key, "value": json.loads(json.dumps(value)),
                             "etag": w.etags.get((store, key), "e0"), "users": [], "attributes": {}}
            if method == "PATCH":
                data = _json(body)
                if data.get("etag") and data["etag"] != w.etags.get((store, key)):
                    raise _error(url, 409, "ABORTED: etag mismatch")
                etag = w.put(store, key, data.get("value"))
                return 200, {"path": path, "id": key, "value": data.get("value"), "etag": etag}
        if "/memory-store/sorted-maps/" in path:
            name = path.split("/sorted-maps/")[1].split("/")[0]
            items = w.maps.setdefault(name, {})
            now = time.time()
            for k in [k for k, (_, exp) in items.items() if exp < now]:
                del items[k]
            if path.endswith("/items") and method == "GET":
                listed: list = sorted(items.items(), key=lambda kv: kv[0])
                page, nxt = _page(listed, q.get("pageToken"), int(q.get("maxPageSize", 100)))
                return 200, {"memoryStoreSortedMapItems": [{"id": k, "value": v, "path": f"items/{k}"}
                                                           for k, (v, _) in page], "nextPageToken": nxt}
            if path.endswith("/items") and method == "POST":
                item = q.get("id", "")
                if item in items:
                    raise _error(url, 409, "ALREADY_EXISTS")
                data = _json(body)
                ttl = float(str(data.get("ttl") or "60s").rstrip("s") or 60)
                items[item] = (data.get("value"), now + ttl)
                return 200, {"id": item}
            item = path.rsplit("/", 1)[-1]
            if method == "DELETE":
                if item not in items:
                    raise _error(url, 404, "NOT_FOUND")
                del items[item]
                return 200, {}
            if item in items:
                return 200, {"id": item, "value": items[item][0]}
            raise _error(url, 404, "NOT_FOUND")
        if "/memory-store/queues/" in path:
            if path.endswith(":read"):
                count = int(q.get("count", 10))
                taken, w.queue = w.queue[:count], w.queue[count:]
                return 200, {"queueItems": taken, "id": uuid.uuid4().hex if taken else None}
            return 200, {}
        if "/user-restrictions" in path:
            tail = path.split("/user-restrictions")[1].strip("/")
            if not tail:
                bans = [{"path": f"universes/{UNIVERSE}/user-restrictions/{uid}", "user": f"users/{uid}",
                         "gameJoinRestriction": r} for uid, r in w.restrictions.items() if r.get("active")]
                return 200, {"userRestrictions": bans, "nextPageToken": None}
            uid = int(tail)
            if method == "PATCH":
                rest = _json(body).get("gameJoinRestriction") or {}
                rest = {**rest, "startTime": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
                w.restrictions[uid] = rest
                return 200, {"path": f"universes/{UNIVERSE}/user-restrictions/{uid}", "gameJoinRestriction": rest}
            rest = w.restrictions.get(uid)
            if not rest:
                return 200, {"path": f"universes/{UNIVERSE}/user-restrictions/{uid}",
                             "gameJoinRestriction": {"active": False}}
            return 200, {"gameJoinRestriction": rest}
        if "/subscription-products/" in path:
            raise _error(url, 404, "NOT_FOUND")
        if path.startswith("/cloud/v2/users/") and path.endswith("/notifications"):
            uid = int(path.split("/users/")[1].split("/")[0])
            day = time.strftime("%Y-%m-%d", time.gmtime())
            if (uid, day) in w.notified:
                raise _error(url, 429, "Too many notifications for this user today.")
            w.notified.add((uid, day))
            nid = str(uuid.uuid4())
            return 200, {"path": f"users/{uid}/notifications/{nid}", "id": nid}
        if path.startswith("/creator-configs-public-api/"):
            if method == "GET" and path.endswith("/revisions"):
                return 200, {"revisions": []}
            if method == "GET":
                return 200, dict(w.configs["draft" if path.endswith("/draft") else "live"])
            if method in ("PUT", "PATCH"):
                values = _json(body).get("config") or {}
                w.configs["draft"] = values if method == "PUT" else {**w.configs["draft"], **values}
                return 200, dict(w.configs["draft"])
            if path.endswith("/publish"):
                w.configs["live"] = dict(w.configs["draft"])
            return 200, {}
        raise _error(url, 404, f"route non simulée : {method} {path}")


def _discord(method: str, path: str, body: bytes | None):
    w = _world()
    path = path.replace("/api/v10", "")
    guild = config.DISCORD_GUILD_ID
    channels = [("1", "INFO", 4, None), ("10", "announcements", 5, "1"), ("11", "patch-notes", 0, "1"),
                ("12", "leaderboard-and-scores", 0, "1"), ("13", "playtest-announcements", 0, "1"),
                ("2", "RAINOR", 4, None), ("20", "faction-announcements", 0, "2"),
                ("3", "RUSFOR", 4, None), ("30", "faction-announcements", 0, "3"),
                ("4", "STAFF", 4, None), ("40", "ops-log", 0, "4")]
    if path == "/users/@me":
        return 200, {"id": "1", "username": "Shroud CC (démo)"}
    if path.startswith(f"/guilds/{guild}/channels"):
        return 200, [{"id": i, "name": n, "type": t, "parent_id": p, "position": k}
                     for k, (i, n, t, p) in enumerate(channels)]
    if path.startswith(f"/guilds/{guild}/roles"):
        return 200, [{"id": "100", "name": "@everyone"}, {"id": "101", "name": "Rainor", "color": 0x2980B9},
                     {"id": "102", "name": "Rusfor", "color": 0xD63031}, {"id": "103", "name": "Playtesters"}]
    if path.startswith(f"/guilds/{guild}"):
        return 200, {"id": guild, "name": "Shroud War (démo)", "approximate_member_count": 1_204,
                     "approximate_presence_count": 187}
    if path.startswith("/channels/") and path.endswith("/messages") and method == "POST":
        msg = {"id": uuid.uuid4().hex[:18], "channel_id": path.split("/")[2], **_json(body),
               "timestamp": datetime.now(timezone.utc).isoformat()}
        w.discord.append(msg)
        del w.discord[:-200]
        return 200, msg
    if path.endswith("/crosspost"):
        return 200, {}
    if path.startswith("/channels/") and "/messages" in path:
        cid = path.split("/")[2]
        return 200, [m for m in reversed(w.discord) if m["channel_id"] == cid][:50]
    raise _error(f"https://discord.com/api/v10{path}", 404, "Unknown")


def urlopen(req, data=None, timeout=None, **kw):
    if isinstance(req, str):
        req = urllib.request.Request(req, data=data)
    method = req.get_method()
    status, payload = route(method, req.full_url, req.data)
    return _Response(status, payload)


# INSTALLATION -----------------------------------------------------------------
def install() -> World:
    """Branche la demo : identifiants fictifs, faux reseau, calendrier accelere, simulation."""
    global WORLD, _installed
    if _installed and WORLD:
        return WORLD
    from . import notify, roblox_api
    config.ROBLOX_OPENCLOUD_KEY = config.ROBLOX_OPENCLOUD_KEY or "demo-key"
    config.ROBLOX_UNIVERSE_ID = UNIVERSE
    config.ROBLOX_PLACE_ID = HUB_PLACE
    config.ROBLOX_GAME_PLACE_ID = GAME_PLACE
    config.DISCORD_BOT_TOKEN = "demo-token"
    config.DISCORD_GUILD_ID = "5000000000"
    config.GAME_NAME = "Shroud War (démo)"
    world = WORLD = World()
    urllib.request.urlopen = urlopen  # type: ignore[assignment]
    roblox_api.fw_week_index = world.week     # type: ignore[assignment]
    roblox_api.fw_week_bounds = world.bounds  # type: ignore[assignment]
    if not notify.CONFIG_FILE.exists():
        notify.save_config({k: f"{1700000000 + i}" for i, k in enumerate(notify.BY_KEY)}, world.players[0]["u"])

    def loop():
        while True:
            try:
                world.tick()
            except Exception as exc:                            # noqa: BLE001
                print(f"  [demo] simulation : {exc}")
            time.sleep(TICK_S)
    world.tick()
    threading.Thread(target=loop, name="demo-world", daemon=True).start()
    _installed = True
    return world


def uninstall() -> None:
    """Pour les tests : rend le vrai reseau."""
    global _installed
    urllib.request.urlopen = _real_urlopen  # type: ignore[assignment]
    _installed = False

