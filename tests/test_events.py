"""Bus d'evenements : lecture, dedoublonnage, retrait, base locale."""
from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

CC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CC))

from core import config, db, events, roblox_api, store  # noqa: E402


def item(t, eid, at=None, **d):
    at = at or int(time.time())
    return {"path": "x", "data": json.dumps({"id": eid, "t": t, "at": at, "job": "abcd1234", "pl": "hub", "d": d})}


class EventsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        (tmp / "history.json").write_text(json.dumps([
            {"at": 5, "channel": "announcements", "title": "Old", "ok": True, "detail": ""}]), encoding="utf-8")
        self.patches = [patch.object(db, "DB_FILE", tmp / "cc.db"), patch.object(db, "HISTORY_FILE", tmp / "history.json"),
                        patch.object(config, "ROBLOX_OPENCLOUD_KEY", "k"), patch.object(config, "ROBLOX_UNIVERSE_ID", "1")]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_parse_rejects_garbage(self):
        self.assertIsNone(events.parse_item({"data": "not json"}))
        self.assertIsNone(events.parse_item({"data": {"no": "type"}}))
        e = events.parse_item(item("honeypot", "h1", u=5, trap="X"))
        self.assertEqual((e["type"], e["data"]["u"], e["place"]), ("honeypot", 5, "hub"))

    def test_poll_stores_discards_and_dedupes(self):
        calls = []

        def fake(method, url, body=None, headers=None):
            calls.append((method, url.split("/memory-store/")[1], body))
            if url.endswith("count=100&invisibilityWindow=60s"):
                return {"readId": "r1", "items": [item("season_closed", "season_closed:w9", week=9),
                                                   item("season_closed", "season_closed:w9", week=9)]}
            return None

        with patch.object(roblox_api, "_oc_request", side_effect=fake):
            fresh = events.poll()
            again = events.poll()
        self.assertEqual([e["id"] for e in fresh], ["season_closed:w9"])
        self.assertEqual(again, [])
        discards = [c for c in calls if "items:discard" in c[1]]
        self.assertEqual(json.loads(discards[0][2]), {"readId": "r1"})
        self.assertTrue(any(c[0] == "DELETE" and "CC_EventsBacklog" in c[1] for c in calls))
        self.assertEqual(len(db.events(("season_closed",))), 1)

    def test_live_queue_envelope_persists_ack_before_discard(self):
        db.add_command("c1", "toast", "job:abcd1234", {})
        calls = []
        def cloud(method, url, body=None, headers=None):
            calls.append((method, url))
            if "items:read" in url:
                return {"id": "live-read", "queueItems": [
                    item("cmd_ack", "cmd_ack:c1:abcd1234", cmd="c1", ok=True, msg="recu")]}
            if "items:discard" in url:
                self.assertEqual(json.loads(body), {"readId": "live-read"})
                self.assertEqual(len(db.get_command("c1")["acks"]), 1)
            return {}
        with patch.object(roblox_api, "_oc_request", side_effect=cloud):
            self.assertEqual(len(events.poll()), 1)
            self.assertEqual(events.poll(), [])
        self.assertIsNone(events.status()["lastError"])
        self.assertEqual(len([c for c in calls if "items:discard" in c[1]]), 2)

    def test_unknown_queue_envelope_does_not_discard_or_clear_backlog(self):
        with patch.object(roblox_api, "_oc_request", return_value={"readId": "r", "unexpected": []}) as call:
            self.assertEqual(events.poll(), [])
        self.assertEqual(call.call_count, 1)
        self.assertIn("inconnu", events.status()["lastError"])

    def test_poll_never_raises(self):
        with patch.object(roblox_api, "_oc_request", side_effect=roblox_api.RobloxError("403")):
            self.assertEqual(events.poll(), [])
        self.assertIn("403", events.status()["lastError"])

    def test_history_is_migrated_once_and_sends_are_journaled(self):
        store.log_send("ops-log", "Nouveau", False, "boom", card="fw_result:w9")
        rows = store.load_history()
        self.assertEqual([r["title"] for r in rows], ["Nouveau", "Old"])
        self.assertFalse(rows[0]["ok"])
        self.assertEqual(db.audit_rows(5)[0]["card"], "fw_result:w9")

    def test_card_states(self):
        db.set_card("k", "snoozed", 123)
        self.assertEqual(db.card_states()["k"]["until"], 123)
        db.set_card("k", "open")
        self.assertNotIn("k", db.card_states())
        with self.assertRaises(ValueError):
            db.set_card("k", "weird")


if __name__ == "__main__":
    unittest.main()
