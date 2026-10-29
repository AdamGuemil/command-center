from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

CC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CC))

from core import config, ranked_rewards, roblox_api  # noqa: E402


class RankedRewardsTests(unittest.TestCase):
    def test_ranked_title_uses_display_season_and_migrates_legacy_label(self):
        self.assertEqual(ranked_rewards._format_title("S%d RANKED #1", 0),
                         "S1 RANKED #1")
        self.assertEqual(ranked_rewards._format_title("RANKED TOP 3", 7),
                         "S8 RANKED TOP 3")
        self.assertEqual(ranked_rewards._format_title("S8 RANKED TOP 3", 7),
                         "S8 RANKED TOP 3")
        self.assertEqual(ranked_rewards._format_title("", 7), "")

    def test_preview_formats_title_with_the_confirmed_week(self):
        tiers = [{"maxRank": 1, "gold": 12, "xp": 34,
                  "title": "S%d CHAMPION", "badges": []}]
        ladder = {"rows": [{"rank": 1, "userId": 10, "name": "Alpha",
                             "lp": 900, "faction": "Rainor"}], "error": None}
        with (patch.object(ranked_rewards, "get_tiers", return_value=tiers),
              patch.object(roblox_api, "ranked_top", return_value=ladder),
              patch.object(roblox_api, "fw_week_index", return_value=7),
              patch.object(ranked_rewards, "_last_payout_meta", return_value=None)):
            result = ranked_rewards.preview()

        self.assertEqual(result["week"], 7)
        self.assertEqual(result["rows"][0]["title"], "S8 CHAMPION")

    def test_pay_keeps_preview_week_at_season_rollover(self):
        plan = {
            "week": 7,
            "error": None,
            "rows": [{"rank": 1, "userId": 10, "name": "Alpha", "lp": 900,
                      "faction": "Rainor", "gold": 12, "xp": 34,
                      "title": "S8 CHAMPION", "badges": []}],
        }
        with (patch.object(ranked_rewards, "preview", return_value=plan),
              patch.object(ranked_rewards.time, "time", return_value=1_234),
              patch.object(ranked_rewards, "_read_index", return_value=[]),
              patch.object(roblox_api, "datastore_set") as datastore_set,
              patch.object(roblox_api, "publish"),
              patch.object(roblox_api, "fw_week_index",
                           side_effect=AssertionError("week must not be read twice"))):
            ranked_rewards.pay(notify_roblox=False)

        first_payout = datastore_set.call_args_list[0].args[2]
        self.assertEqual(first_payout["week"], 7)
        self.assertEqual(first_payout["entries"]["10"]["title"], "S8 CHAMPION")

    def test_tiers_are_persisted_in_live_store_and_published(self):
        tiers = [{"maxRank": 3, "gold": 123, "xp": 456,
                  "title": "TOP", "badges": "8, 9"}]
        with (patch.object(ranked_rewards.time, "time", return_value=1_234),
              patch.object(roblox_api, "datastore_set") as datastore_set,
              patch.object(roblox_api, "publish") as publish,
              patch.object(ranked_rewards.store, "save_settings") as save_settings):
            clean = ranked_rewards.save_tiers(tiers)

        datastore_set.assert_called_once_with(
            config.FW_DATASTORE, "ranked_rewards_config",
            {"tiers": clean, "updatedAt": 1_234})
        save_settings.assert_called_once_with({"rankedTiers": clean})
        publish.assert_called_once_with(config.FW_TOPIC, {"kind": "ranked_rewards"})
        self.assertEqual(clean[0]["badges"], [8, 9])

    def test_remote_tiers_override_local_cache_across_seasons(self):
        remote = [{"maxRank": 1, "gold": 77, "xp": 88,
                   "title": "REMOTE", "badges": []}]
        with (patch.object(roblox_api, "datastore_get",
                          return_value={"tiers": remote, "updatedAt": 1}),
              patch.object(ranked_rewards.store, "load_settings",
                           return_value={"rankedTiers": ranked_rewards.DEFAULT_TIERS})):
            tiers = ranked_rewards.get_tiers()
        self.assertEqual(tiers[0]["gold"], 77)
        self.assertEqual(tiers[0]["title"], "REMOTE")

    def test_legacy_local_tiers_are_migrated_when_remote_key_is_empty(self):
        local = [{"maxRank": 5, "gold": 12, "xp": 34,
                  "title": "LOCAL", "badges": []}]
        with (patch.object(roblox_api, "datastore_get", return_value=None),
              patch.object(roblox_api, "datastore_set") as datastore_set,
              patch.object(roblox_api, "publish") as publish,
              patch.object(ranked_rewards.store, "load_settings",
                           return_value={"rankedTiers": local}),
              patch.object(ranked_rewards.time, "time", return_value=99)):
            tiers = ranked_rewards.get_tiers()

        datastore_set.assert_called_once_with(
            config.FW_DATASTORE, "ranked_rewards_config",
            {"tiers": tiers, "updatedAt": 99})
        publish.assert_called_once_with(config.FW_TOPIC, {"kind": "ranked_rewards"})

    def test_ranked_top_hydrates_factions_without_changing_lp(self):
        rows = [
            {"rank": 1, "userId": "10", "value": 900},
            {"rank": 2, "userId": "11", "value": 700},
        ]

        def meta(_store, key):
            return {"10": "Rainor"} if key == "s_2" else {"11": "Rusfor"}

        with (patch.object(roblox_api, "_ordered_top", return_value=(rows, None)),
              patch.object(roblox_api, "resolve_usernames",
                           return_value={"10": "Alpha", "11": "Bravo"}),
              patch.object(roblox_api, "datastore_get", side_effect=meta)):
            result = roblox_api.ranked_top(25)

        self.assertEqual([r["lp"] for r in result["rows"]], [900, 700])
        self.assertEqual([r["faction"] for r in result["rows"]], ["Rainor", "Rusfor"])


if __name__ == "__main__":
    unittest.main()
