"""Mode demo : le faux univers repond comme les vraies API, et le CC s'en sert sans le savoir."""
from __future__ import annotations

import json
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from core import cards, config, db, demo, events, live, notify, roblox_api


class DemoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        self.saved = {k: getattr(config, k) for k in (
            "ROBLOX_OPENCLOUD_KEY", "ROBLOX_UNIVERSE_ID", "ROBLOX_PLACE_ID", "ROBLOX_GAME_PLACE_ID",
            "DISCORD_BOT_TOKEN", "DISCORD_GUILD_ID", "GAME_NAME")}
        self.saved_fw = (roblox_api.fw_week_index, roblox_api.fw_week_bounds)
        self.patches = [patch.object(db, "DB_FILE", tmp / "cc.db"),
                        patch.object(notify, "CONFIG_FILE", tmp / "notifications.json"),
                        patch.object(demo.threading.Thread, "start", lambda self: None)]
        for p in self.patches:
            p.start()
        demo._installed = False
        self.world = demo.install()
        live._registry_cache.update(at=0.0, data=None)
        live._contract_cache.update(at=0.0, data=None)
        cards.invalidate()

    def tearDown(self):
        demo.uninstall()
        for k, v in self.saved.items():
            setattr(config, k, v)
        roblox_api.fw_week_index, roblox_api.fw_week_bounds = self.saved_fw
        for p in self.patches:
            p.stop()
        live._registry_cache.update(at=0.0, data=None)
        live._contract_cache.update(at=0.0, data=None)
        cards.invalidate()
        self.tmp.cleanup()

    def test_live_registry_and_contracts(self):
        data = live.servers(force=True)
        self.assertIsNone(data["error"])
        self.assertEqual(data["summary"]["hubs"], 2)
        self.assertGreaterEqual(data["summary"]["matches"], 3)
        self.assertEqual(data["summary"]["placeVersions"], [demo.OLD_VERSION, demo.NEW_VERSION])
        self.assertEqual(live.contracts(force=True)["issues"], [])

    def test_season_closes_then_pays_and_reaches_the_home_page(self):
        w = self.world
        w.epoch -= demo.SEASON_S          # la saison en cours se termine maintenant
        w.tick()
        closed = w.last_week - 1
        self.assertIsNotNone(roblox_api.faction_war_archive(closed))
        types = [json.loads(i["data"])["t"] for i in w.queue]
        self.assertIn("season_closed", types)
        for at, fn in list(w.pending):
            if fn.__name__ == "pay":
                w.pending.remove((at, fn))
                fn()
        fresh = events.poll()
        self.assertTrue({"season_closed", "ranked_payout"} <= {e["type"] for e in fresh})
        keys = {c["key"] for c in cards.overview(force=True)["cards"]}
        self.assertIn(f"fw_result:w{closed}", keys)
        self.assertIn(f"ranked_top:w{closed}", keys)

    def test_command_is_acknowledged_by_the_hosting_server(self):
        from core import commands
        srv = next(s for s in self.world.servers.values() if s["players"])
        uid = srv["players"][0]["u"]
        with patch.object(demo.threading, "Timer", lambda d, fn: type("T", (), {"start": lambda s: fn(),
                                                                                 "daemon": True})()):
            cmd = commands.send("kick", u=uid, reason="test")
        events.poll()
        acks = db.get_command(cmd["id"])["acks"]
        self.assertTrue(acks and acks[0]["ok"])
        self.assertFalse(any(p["u"] == uid for p in srv["players"]))

    def test_notifications_are_limited_to_one_per_day(self):
        url = f"https://apis.roblox.com/cloud/v2/users/{self.world.players[0]['u']}/notifications"
        req = urllib.request.Request(url, data=b"{}", method="POST")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 429)

    def test_offline_edit_respects_the_etag(self):
        from core import edits
        uid = self.world._free_players()[0]["u"]
        plan = edits.plan(uid, "set_money", {"amount": 4321})
        with patch.object(edits, "SETTLE_S", 0):
            res = edits.apply(plan["token"])
        self.assertTrue(res["ok"])
        prof = roblox_api.datastore_get(config.datastore_name("GlobalData"), f"p_{uid}")
        self.assertEqual(prof["money"], 4321)

    def test_unknown_route_is_a_404_not_a_crash(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(urllib.request.Request("https://example.com/x"))
        self.assertEqual(ctx.exception.code, 404)
        self.assertLess(time.time() - self.world.now0, 60)


if __name__ == "__main__":
    unittest.main()
