"""Notifications joueurs : audiences, registre du jour, campagnes et cartes. Sans reseau."""
from __future__ import annotations

import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

CC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CC))

from core import cards, config, db, notify, roblox_api  # noqa: E402

NOW = 2_000_000_000
H = 3600
WEEK = roblox_api.fw_week_index(NOW)


def readers(**over):
    base = {
        "seen": lambda lo, hi, now: ({uid: hour for uid, hour in SEEN.items()
                                       if now // H - hi <= hour <= now // H - lo}, None),
        "contributors": lambda week: ({1: "Rainor", 2: "Rusfor", 3: "Rainor", 4: "Rusfor"}, None),
        "payout": lambda ref: {"id": "p1", "week": WEEK - 1, "entries": {
            "7": {"rank": 2, "gold": 9000}, "8": {"rank": 1, "gold": 12000}}},
        "ranked_reserve": lambda week: ({3}, False),
        "archive": lambda week: {"winner": "Rusfor"},
        "comeback_recent": lambda now: set(),
        "today": lambda day, ids: db.notified_on(day, ids),
    }
    base.update(over)
    return base


# userId -> heure Unix de la derniere arrivee au Hub
SEEN = {1: NOW // H - 2, 2: NOW // H - 30, 5: NOW // H - 24 * 3, 6: NOW // H - 24 * 10}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        self.patches = [
            patch.object(db, "DB_FILE", tmp / "cc.db"),
            patch.object(notify, "CONFIG_FILE", tmp / "notifications.json"),
            patch.object(config, "ROBLOX_OPENCLOUD_KEY", "k"),
            patch.object(config, "ROBLOX_UNIVERSE_ID", "1"),
        ]
        for p in self.patches:
            p.start()
        notify.save_config({k: f"id-{k.lower().replace('_', '-')}" for k in notify.BY_KEY}, 99)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        notify._current.update(id=None, stop=False)
        self.tmp.cleanup()


class CatalogueTests(unittest.TestCase):
    def test_texts_fit_creator_hub_and_declare_their_params(self):
        for c in notify.CATALOGUE:
            self.assertLessEqual(len(c["text"]), notify.TEXT_MAX, c["key"])
            self.assertEqual(sorted(set(notify.re.findall(r"\{(\w+)\}", c["text"]))), sorted(c["params"]), c["key"])
            self.assertTrue(set(c["perPlayer"]) <= set(c["params"]))
            self.assertRegex(c["launch"], r"^open=(war|ranked|play|crates)$")

    def test_priority_order(self):
        self.assertEqual(notify.PRIORITY, ["RANKED_REWARD", "SEASON_RESULT", "EVENT_LIVE", "SEASON_ENDING",
                                           "UPDATE", "COMEBACK"])


class AudienceTests(Base):
    def test_season_result_keeps_unpaid_ranked_players_for_ranked_reward(self):
        a = notify.audience("SEASON_RESULT", {}, None, NOW, readers())
        self.assertEqual(a["shared"], {"season": str(WEEK), "faction": "Rusfor"})
        self.assertEqual(a["ref"], f"w{WEEK - 1}")
        self.assertEqual(sorted(r["userId"] for r in a["rows"]), [1, 2, 4])
        self.assertEqual(list(a["excluded"].values()), [1])

    def test_season_ending_skips_players_seen_in_24h_and_names_their_faction(self):
        a = notify.audience("SEASON_ENDING", {}, None, NOW, readers())
        self.assertEqual({r["userId"]: r["params"]["faction"] for r in a["rows"]}, {2: "Rusfor", 3: "Rainor", 4: "Rusfor"})

    def test_ranked_reward_is_personal(self):
        a = notify.audience("RANKED_REWARD", {}, None, NOW, readers())
        self.assertEqual(a["ref"], "p1")
        self.assertEqual(a["rows"][0], {"userId": 8, "params": {"rank": "1", "gold": "12,000"}})

    def test_windows_of_absence(self):
        self.assertEqual([r["userId"] for r in notify.audience("EVENT_LIVE", {"event": "Double XP", "hours": 24},
                                                                None, NOW, readers())["rows"]], [5, 6])
        self.assertEqual([r["userId"] for r in notify.audience("COMEBACK", {}, None, NOW, readers())["rows"]], [6])
        self.assertEqual(len(notify.audience("UPDATE", {"version": "0.9", "headline": "x"}, None, NOW,
                                             readers())["rows"]), 4)

    def test_comeback_once_a_week(self):
        a = notify.audience("COMEBACK", {}, None, NOW, readers(comeback_recent=lambda now: {6}))
        self.assertEqual(a["rows"], [])

    def test_missing_param_is_refused(self):
        with self.assertRaises(notify.NotifyError):
            notify.audience("EVENT_LIVE", {"event": "X"}, None, NOW, readers())
        with self.assertRaises(notify.NotifyError):
            notify.audience("EVENT_LIVE", {"event": "X", "hours": "abc"}, None, NOW, readers())

    def test_preview_counts_players_already_served_today(self):
        db.add_notified(2, notify.day_of(NOW), "UPDATE", "sent", None)
        p = notify.preview("SEASON_RESULT", {}, None, NOW, readers())
        self.assertEqual((p["audience"], p["alreadyToday"], p["toSend"]), (3, 1, 2))
        self.assertEqual(p["text"], f"Season {WEEK} is over: Rusfor won. Claim your war rewards.")
        self.assertEqual(p["blockers"], [])

    def test_preview_blocks_without_asset_id(self):
        notify.save_config({}, None)
        p = notify.preview("COMEBACK", {}, None, NOW, readers())
        self.assertTrue(any("Asset ID" in b for b in p["blockers"]))


class CampaignTests(Base):
    def run_campaign(self, key, sender, params=None, rd=None):
        done = threading.Event()
        real = notify._run

        def run(job, s, sleep):
            try:
                real(job, s, sleep)
            finally:
                done.set()
        with patch.object(notify, "_run", run):
            res = notify.start(key, params or {}, None, sender=sender, sleep=lambda s: None, readers=rd or readers())
        self.assertTrue(done.wait(5))
        return res, db.campaigns(1)[0]

    def test_sends_once_per_player_and_day(self):
        calls = []

        def sender(uid, mid, params, launch, category):
            calls.append((uid, mid, params, launch))
            return 200, ""
        res, c = self.run_campaign("SEASON_RESULT", sender)
        self.assertEqual(c["state"], "done")
        self.assertEqual(c["sent"], 3)
        self.assertEqual({x[0] for x in calls}, {1, 2, 4})
        self.assertEqual(calls[0][1:], ("id-season-result", {"season": str(roblox_api.fw_week_index()), "faction": "Rusfor"}, "open=war"))
        # Meme sujet : refuse. Autre notification le meme jour : tous deja servis.
        with self.assertRaises(notify.NotifyError):
            notify.start("SEASON_RESULT", {}, None, readers=readers())
        p = notify.preview("UPDATE", {"version": "1", "headline": "h"}, None, None,
                           readers(seen=lambda lo, hi, now: ({1: 0, 2: 0, 4: 0}, None)))
        self.assertEqual(p["toSend"], 0)

    def test_429_counts_as_served_and_a_series_pauses(self):
        res, c = self.run_campaign("SEASON_RESULT", lambda *a: (429, "Too many requests"))
        self.assertEqual((c["state"], c["throttled"]), ("done", 3))
        many = readers(contributors=lambda w: ({i: "Rainor" for i in range(100, 130)}, None))
        res, c = self.run_campaign("SEASON_ENDING", lambda *a: (429, ""), rd=many)
        self.assertEqual(c["state"], "paused")
        self.assertEqual(c["throttled"], notify.THROTTLE_PAUSE)

    def test_permission_error_stops_and_frees_the_day(self):
        res, c = self.run_campaign("SEASON_RESULT", lambda *a: (403, "user.user-notification:write"))
        self.assertEqual(c["state"], "failed")
        self.assertIn("User Notifications", c["error"])
        self.assertEqual(db.notified_on(notify.day_of(int(notify.time.time()))), set())

    def test_body_matches_open_cloud_contract(self):
        import json
        body = json.loads(notify._body("123", {"rank": "1"}, "open=ranked", "Ranked"))
        self.assertEqual(body["source"], {"universe": "universes/1"})
        self.assertEqual(body["payload"]["message_id"], "123")
        self.assertEqual(body["payload"]["parameters"], {"rank": {"string_value": "1"}})
        self.assertEqual(body["payload"]["join_experience"], {"launch_data": "open=ranked"})


class CardIntegrationTests(Base):
    def state(self, **over):
        s = {"now": NOW, "season": {"week": WEEK, "startsAt": NOW - 3600, "endsAt": NOW + 3600},
             "openCloudOk": True, "discordOk": True, "errors": {}, "boost": None, "archive": None,
             "payouts": [], "contractIssues": [], "placeVersions": [1], "servers": 1, "operations": {},
             "todo": [], "schedule": [], "templates": {}, "events": [],
             "notify": {"ids": list(notify.BY_KEY), "done": [], "lastComeback": NOW}}
        s.update(over)
        return {c["key"]: c for c in cards.build(s, NOW)}

    def test_j1_and_result_cards_offer_notifications(self):
        c = self.state()
        self.assertIn("notify:SEASON_ENDING", [a["id"] for a in c[f"fw_j1:w{WEEK}"]["actions"]])
        c = self.state(archive={"winner": "Rainor", "Rainor": 2, "Rusfor": 1, "closedAt": NOW - 60})
        act = next(a for a in c[f"fw_result:w{WEEK - 1}"]["actions"] if a["kind"] == "notify")
        self.assertEqual((act["notify"], act["ref"], act["params"]), ("SEASON_RESULT", f"w{WEEK - 1}", {"week": WEEK - 1}))

    def test_no_button_without_asset_id(self):
        c = self.state(notify={"ids": [], "done": [], "lastComeback": 0})
        self.assertNotIn("notify:SEASON_ENDING", [a["id"] for a in c[f"fw_j1:w{WEEK}"]["actions"]])
        self.assertFalse(any(k.startswith("comeback:") for k in c))

    def test_event_live_and_comeback_cards(self):
        c = self.state(boost={"name": "DOUBLE XP", "startsAt": NOW - 60, "endsAt": NOW + 6 * H},
                       notify={"ids": list(notify.BY_KEY), "done": [], "lastComeback": 0})
        ev = c[f"event_live:boost:{NOW + 6 * H}"]["actions"][0]
        self.assertEqual(ev["params"], {"event": "DOUBLE XP", "hours": 6})
        self.assertIn(f"comeback:{notify.iso_week(NOW)}", c)
        sent = self.state(boost={"name": "B", "startsAt": NOW, "endsAt": NOW + H},
                          notify={"ids": list(notify.BY_KEY), "done": [f"EVENT_LIVE|boost:{NOW + H}"],
                                  "lastComeback": NOW})
        self.assertFalse(any(k.startswith("event_live:") for k in sent))


if __name__ == "__main__":
    unittest.main()
