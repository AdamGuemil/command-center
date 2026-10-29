from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

CC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CC))

from core import config, grants, live, modes, roblox_api  # noqa: E402


class CommandCenterBridgeTests(unittest.TestCase):
    def test_operations_event_is_off_by_default_and_keeps_its_deadline(self):
        self.assertFalse(modes.DEFAULT["operations"]["up"])
        clean = modes._sanitize({
            "operations": {"up": True, "minLevel": "12", "endsAt": "123456"},
        })
        self.assertEqual(clean["operations"], {
            "up": True, "minLevel": 12, "endsAt": 123456,
        })
        self.assertTrue(clean["domination"]["up"])

    def test_modes_save_publishes_live_operations_window(self):
        values = {
            "operations": {"up": True, "minLevel": 10, "endsAt": 999999},
            "domination": {"up": True, "minLevel": 0},
        }
        with (patch.object(modes.store, "save_settings"),
              patch.object(roblox_api, "datastore_set") as datastore_set,
              patch.object(roblox_api, "publish") as publish):
            clean = modes.save(values)

        datastore_set.assert_called_once_with(config.FW_DATASTORE, modes.MODES_KEY, clean)
        publish.assert_called_once_with(config.FW_TOPIC, {"kind": "modes"})
        self.assertEqual(clean["operations"]["endsAt"], 999999)

    def test_faction_season_bounds_stay_at_18h_in_france_across_dst(self):
        paris = ZoneInfo("Europe/Paris")
        for week in (-1, 0, 7, 8, 29, 30, 52):
            starts, ends = roblox_api.fw_week_bounds(week)
            local_start = datetime.fromtimestamp(starts, paris)
            local_end = datetime.fromtimestamp(ends, paris)
            self.assertEqual((local_start.weekday(), local_start.hour, local_start.minute),
                             (5, 18, 0))
            self.assertEqual((local_end.weekday(), local_end.hour, local_end.minute),
                             (5, 18, 0))
            self.assertEqual(roblox_api.fw_week_index(starts - 1), week - 1)
            self.assertEqual(roblox_api.fw_week_index(starts), week)

    def test_season_one_starts_on_september_fifth(self):
        paris = ZoneInfo("Europe/Paris")
        launch = int(datetime(2026, 9, 5, 18, tzinfo=paris).timestamp())
        preseason = int(datetime(2026, 9, 3, 12, tzinfo=paris).timestamp())
        self.assertEqual(config.DATASTORE_VERSION, "SW_DEV_1")
        self.assertEqual(roblox_api.fw_week_bounds(0)[0], launch)
        self.assertEqual(roblox_api.fw_week_bounds(-1)[1], launch)
        for timestamp, season in ((preseason, 0), (launch - 1, 0), (launch, 1)):
            with self.subTest(timestamp=timestamp):
                with (patch.object(roblox_api.time, "time", return_value=timestamp),
                      patch.object(roblox_api, "datastore_get", return_value=None)):
                    state = roblox_api.faction_war_state()
                self.assertEqual(state["season"], season)
                self.assertEqual(state["totals"], {"Rainor": 0, "Rusfor": 0})

    def test_boost_writes_live_store_then_publishes(self):
        with (patch.object(roblox_api, "datastore_set") as datastore_set,
              patch.object(roblox_api, "publish") as publish,
              patch.object(roblox_api.time, "time", return_value=1_000)):
            record = roblox_api.set_boost(2, 3, 4, 15, "test")

        datastore_set.assert_called_once_with(
            config.datastore_name("FactionWar"), "event_override", record)
        publish.assert_called_once_with("FW_Event", {"kind": "event"})
        self.assertEqual(record["endsAt"], 1_900)

    def test_give_writes_grant_and_index_to_live_store(self):
        writes = []
        with (patch.object(grants.time, "time", return_value=2_000),
              patch.object(roblox_api, "resolve_usernames",
                           return_value={"123": "Target"}),
              patch.object(roblox_api, "datastore_get", return_value=[]),
              patch.object(roblox_api, "datastore_set",
                           side_effect=lambda store, key, value: writes.append((store, key, value))),
              patch.object(roblox_api, "publish") as publish,
              patch.object(grants.store, "save_settings")):
            result = grants.give({"audience": "users", "users": [123], "gold": 50})

        self.assertTrue(result["ok"])
        self.assertEqual([entry[0] for entry in writes], [config.FW_DATASTORE] * 2)
        self.assertEqual([entry[1] for entry in writes], ["grant_g2000", "grant_index"])
        publish.assert_called_once_with(
            "FW_Event", {"kind": "grant", "id": "g2000", "applyNow": False})

    def test_publish_uses_cloud_v2_universe_message(self):
        calls = []
        with patch.object(roblox_api, "_oc_request",
                          side_effect=lambda method, url, body=None, headers=None:
                          calls.append((method, url, body))):
            roblox_api.publish("FW_Event", {"kind": "event"})

        method, url, body = calls[0]
        self.assertEqual(method, "POST")
        self.assertTrue(url.endswith(
            f"/cloud/v2/universes/{config.ROBLOX_UNIVERSE_ID}:publishMessage"))
        self.assertNotIn("messaging-service/v1", url)
        payload = json.loads(body)
        # Le jeu fait JSONDecode du message : il doit rester une CHAINE JSON.
        self.assertEqual(payload["topic"], "FW_Event")
        self.assertEqual(json.loads(payload["message"]), {"kind": "event"})

    def test_permission_probe_names_the_missing_scope(self):
        def fake_call(method, url, body=None, headers=None):
            return (403, "Insufficient scope") if ":publishMessage" in url else (200, "")

        with (patch.object(config, "ROBLOX_OPENCLOUD_KEY", "test-key"),
              patch.object(live, "offers", return_value=[
                  {"kind": "subscription", "subscriptionId": "EXP-1"}]),
              patch.object(roblox_api, "_probe_call", side_effect=fake_call)):
            report = roblox_api.probe_permissions()

        rows = {r["id"]: r for r in report["rows"]}
        self.assertFalse(report["ok"])
        self.assertEqual(rows["messaging"]["state"], "bad")
        self.assertIn("Messaging Service", rows["messaging"]["hint"])
        self.assertEqual(rows["ds_write"]["state"], "ok")
        self.assertEqual(rows["subscriptions"]["state"], "ok")
        # Ces deux droits ne se testent qu'en agissant : jamais sondes.
        self.assertEqual(rows["notifications"]["state"], "skip")
        self.assertEqual(rows["restart"]["state"], "skip")

    def test_permission_probe_never_touches_live_keys(self):
        urls = []
        with (patch.object(config, "ROBLOX_OPENCLOUD_KEY", "test-key"),
              patch.object(live, "offers", return_value=[]),
              patch.object(roblox_api, "_probe_call",
                           side_effect=lambda method, url, body=None, headers=None:
                           urls.append((method, url, body)) or (200, ""))):
            roblox_api.probe_permissions()

        for method, url, body in urls:
            if method in ("POST", "DELETE") and "entryKey" in url:
                self.assertIn("entryKey=cc_probe", url)
            if url.endswith(":publishMessage"):
                self.assertEqual(json.loads(body)["topic"], "CC_Probe")
        self.assertFalse(any("restartServers" in url or "notifications" in url
                             for _, url, _ in urls))

    def test_honeypot_reads_mirror_the_game_stores(self):
        # Miroir de HoneypotService.luau : DataStore Honeypot_<v>, cle u_<userId>,
        # et index ordonne HoneypotIndex_<v> (valeur = date du dernier appel).
        with (patch.object(roblox_api, "_ordered_top",
                           return_value=([{"rank": 1, "userId": 42, "value": 1_790_000_000}], None)) as top,
              patch.object(roblox_api, "resolve_usernames", return_value={"42": "Cheater"}),
              patch.object(roblox_api, "datastore_get", return_value={"hits": 3}) as get):
            listing = roblox_api.honeypot_list(10)
            detail = roblox_api.honeypot_detail(42)

        top.assert_called_once_with(config.datastore_name("HoneypotIndex"), 10)
        self.assertEqual(listing["rows"][0]["lastAt"], 1_790_000_000)
        get.assert_called_once_with(config.datastore_name("Honeypot"), "u_42")
        self.assertEqual(detail["record"], {"hits": 3})

    def test_active_audience_reads_versioned_faction_leaderboards(self):
        stores = []

        def ordered(store, _cap=5000):
            stores.append(store)
            return [123], None

        with (patch.object(roblox_api, "fw_week_index", return_value=7),
              patch.object(roblox_api, "ordered_all_ids", side_effect=ordered)):
            ids, error = grants._active_user_ids()

        self.assertIsNone(error)
        self.assertEqual(ids, [123])
        self.assertEqual(stores, [
            config.datastore_name("FWLB_w7_Rainor"),
            config.datastore_name("FWLB_w7_Rusfor"),
        ])


if __name__ == "__main__":
    unittest.main()
