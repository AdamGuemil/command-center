"""Lot 3 : commandes, bans, modifications hors ligne sous verrou et annulation."""
from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
import urllib.parse
from pathlib import Path
from unittest.mock import patch

CC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CC))

from core import commands, config, db, edits, live, roblox_api  # noqa: E402

INV = {"_v": 2, "active": "primary",
       "equipped": {"primary": {"u": "w1", "i": "AK74"}, "backpack": {"u": "bag", "i": "Bag", "b": [{"u": "m1", "i": "Medkit"}]}},
       "pockets": [{"u": "p1", "i": "Ammo"}, {"u": "p2", "i": "Bandage"}]}
STASH = {"_v": 2, "tabs": [{"name": "Main", "items": [{"u": "s1", "i": "Helmet"}]}]}
STORES = {"profile": "GlobalData_T", "inventory": "Inv_T", "stash": "Stash_T"}


class FakeCloud:
    """Open Cloud minimal : entrees avec etag, verrou MemoryStore, publication."""
    def __init__(self):
        self.entries = {("Inv_T", "7"): {"value": json.loads(json.dumps(INV)), "etag": "e1", "users": ["users/7"]},
                        ("GlobalData_T", "p_7"): {"value": {"money": 100, "lp": 5}, "etag": "g1"}}
        self.locks, self.calls, self.published = set(), [], []

    def __call__(self, method, url, body=None, headers=None):
        self.calls.append((method, url, json.loads(body) if body else None))
        if "/data-stores/" in url:
            path = url.split("/data-stores/")[1]
            store, key = path.split("/entries/")
            k = (store, key)
            if method == "GET":
                e = self.entries.get(k)
                return dict(e) if e else None
            if method == "PATCH":
                data = json.loads(body)
                if data.get("etag") != self.entries[k]["etag"]:
                    raise roblox_api.RobloxError("HTTP 409 : ABORTED")
                n = int(self.entries[k]["etag"][1:]) + 1
                self.entries[k] = {**self.entries[k], "value": data["value"], "etag": f"{self.entries[k]['etag'][0]}{n}"}
                return {"etag": self.entries[k]["etag"]}
        if "/sorted-maps/CC_EditLocks/items" in url:
            if method == "POST":
                item = urllib.parse.unquote(url.split("?id=")[1])
                if item in self.locks:
                    raise roblox_api.RobloxError("HTTP 409 : ALREADY_EXISTS")
                self.locks.add(item)
            elif method == "DELETE":
                self.locks.discard(urllib.parse.unquote(url.rsplit("/", 1)[1]))
            return {}
        return {}


class ActionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cloud = FakeCloud()
        self.online = None
        self.patches = [
            patch.object(db, "DB_FILE", Path(self.tmp.name) / "cc.db"),
            patch.object(db, "HISTORY_FILE", Path(self.tmp.name) / "none.json"),
            patch.object(edits, "SETTLE_S", 0),
            patch.object(config, "ROBLOX_UNIVERSE_ID", "1"),
            patch.object(roblox_api, "_oc_request", side_effect=self.cloud),
            patch.object(roblox_api, "publish", side_effect=lambda topic, msg: self.cloud.published.append(msg)),
            patch.object(live, "store_names", return_value=STORES),
            patch.object(live, "servers", return_value={"servers": []}),
            patch.object(live, "find_player", side_effect=lambda uid: self.online),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    # modifications pures
    def test_remove_item_everywhere(self):
        new, it, where = edits.remove_item(INV, "inventory", "m1")
        self.assertEqual((it["i"], where), ("Medkit", "sac porté (backpack)"))
        self.assertEqual(new["equipped"]["backpack"]["b"], [])
        self.assertEqual(len(INV["equipped"]["backpack"]["b"]), 1, "l'original n'est jamais modifie")
        new, it, where = edits.remove_item(INV, "inventory", "w1")
        self.assertNotIn("primary", new["equipped"])
        new, it, _ = edits.remove_item(INV, "inventory", "p2")
        self.assertEqual([x["u"] for x in new["pockets"]], ["p1"])
        new, it, where = edits.remove_item(STASH, "stash", "s1")
        self.assertEqual(new["tabs"][0]["items"], [])
        with self.assertRaises(edits.EditError):
            edits.remove_item(INV, "inventory", "nope")

    # hors ligne
    def test_offline_edit_writes_with_etag_backup_and_undo(self):
        p = edits.plan(7, "remove_item", {"where": "inventory", "uid": "p1"})
        self.assertEqual(p["path"], "offline")
        self.assertIn("Ammo", p["change"]["before"])
        r = edits.apply(p["token"])
        stored = self.cloud.entries[("Inv_T", "7")]
        self.assertEqual([x["u"] for x in stored["value"]["pockets"]], ["p2"])
        patch_call = [c for c in self.cloud.calls if c[0] == "PATCH"][0]
        self.assertEqual(patch_call[2]["etag"], "e1")
        self.assertEqual(patch_call[2]["users"], ["users/7"], "les metadonnees de l'entree sont gardees")
        self.assertEqual(self.cloud.locks, set(), "le verrou est leve")
        edits.undo(r["backup"])
        self.assertEqual(len(self.cloud.entries[("Inv_T", "7")]["value"]["pockets"]), 2)
        with self.assertRaises(edits.EditError):
            edits.undo(r["backup"])

    def test_offline_edit_refused_when_game_wrote_or_player_joined(self):
        p = edits.plan(7, "set_money", {"amount": 500})
        self.cloud.entries[("GlobalData_T", "p_7")]["etag"] = "g9"        # le jeu a ecrit
        with self.assertRaises(edits.EditError):
            edits.apply(p["token"])
        self.assertEqual(self.cloud.locks, set())
        p = edits.plan(7, "set_money", {"amount": 500})
        self.online = {"jobId": "j"}
        with self.assertRaises(edits.EditError):
            edits.apply(p["token"])
        self.assertEqual(self.cloud.entries[("GlobalData_T", "p_7")]["value"]["money"], 100)

    def test_lock_already_taken(self):
        self.cloud.locks.add("edit:7")
        p = edits.plan(7, "set_money", {"amount": 1})
        with self.assertRaises(edits.EditError) as ctx:
            edits.apply(p["token"])
        self.assertIn("verrou", str(ctx.exception))

    def test_undo_refused_after_player_progress(self):
        p = edits.plan(7, "set_money", {"amount": 900})
        r = edits.apply(p["token"])
        self.cloud.entries[("GlobalData_T", "p_7")]["etag"] = "g42"
        with self.assertRaises(edits.EditError):
            edits.undo(r["backup"])

    # commandes et bans
    def test_send_command_and_acks(self):
        r = commands.send("kick", u=7, reason="bye")
        msg = self.cloud.published[0]
        self.assertEqual((msg["kind"], msg["op"], msg["u"]), ("cc_cmd", "kick", 7))
        self.assertGreater(msg["exp"], msg["at"])
        db.add_events([{"id": f"cmd_ack:{r['id']}:abcd1234", "type": "cmd_ack", "at": int(time.time()),
                        "job": "abcd1234", "place": "hub", "data": {"cmd": r["id"], "ok": True, "msg": "Bob expulse"}}])
        with patch("core.events.poll", return_value=[]):
            s = commands.status(r["id"])
        self.assertTrue(s["done"])
        self.assertEqual(s["acks"][0]["msg"], "Bob expulse")
        with self.assertRaises(commands.CommandError):
            commands.send("toast", job="*", text="x" * 2000 + "é" * 400, title="t" * 300, reason="r" * 300,
                          where="w" * 300, uid="u" * 300)
        with self.assertRaises(commands.CommandError):
            commands.send("format_c")

    def test_toast_finishes_for_one_target_and_collects_broadcast_acks(self):
        for target, broadcast in (("abcd1234", False), ("*", True)):
            with self.subTest(target=target), patch.object(commands.time, "time", return_value=1000):
                sent = commands.send("toast", job=target, text="hello")
                db.add_events([{"id": f"cmd_ack:{sent['id']}:abcd1234", "type": "cmd_ack",
                                "at": 1000, "job": "abcd1234", "place": "hub",
                                "data": {"cmd": sent["id"], "ok": True}}])
                with (patch("core.events.poll"), patch("core.events.status", return_value={"lastError": None})):
                    self.assertEqual(commands.status(sent["id"])["done"], not broadcast)
                    with patch.object(commands.time, "time", return_value=1045):
                        self.assertTrue(commands.status(sent["id"])["done"])

    def test_status_exposes_ack_read_errors_without_claiming_execution_failed(self):
        sent = commands.send("toast", job="*", text="hello")
        with (patch("core.events.poll"), patch("core.events.status", return_value={"lastError": "403 queue"})):
            status = commands.status(sent["id"])
        self.assertEqual(status["ackError"], "403 queue")
        self.assertFalse(status["done"])
        self.assertFalse(status["expired"])

    def test_ban_and_restart_bodies(self):
        self.online = {"jobId": "j"}
        r = commands.ban(7, 7, "Cheating", "honeypot", include_alts=True)
        patch_call = [c for c in self.cloud.calls if c[0] == "PATCH"][0]
        self.assertIn("user-restrictions/7?updateMask=gameJoinRestriction", patch_call[1])
        g = patch_call[2]["gameJoinRestriction"]
        self.assertEqual((g["active"], g["duration"], g["excludeAltAccounts"]), (True, "604800s", False))
        self.assertIsNotNone(r["kick"], "joueur en ligne : kick envoye")
        with self.assertRaises(commands.CommandError):
            commands.ban(7, None, "  ")
        commands.restart_servers(False, 10)
        post = [c for c in self.cloud.calls if c[1].endswith(":restartServers")][0]
        self.assertEqual(post[2], {"closeAllVersions": False, "bleedOffServers": True, "bleedOffDurationMinutes": 10})


if __name__ == "__main__":
    unittest.main()
