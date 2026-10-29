"""Lot 1 : contrats, registre live et fiche joueur (lecture seule, a la demande)."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

CC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CC))

from core import config, live, players, roblox_api  # noqa: E402


def contract(kind: str, version: str, **extra) -> dict:
    return {"contractRev": 1, "placeKind": kind, "dsVersion": version,
            "stores": {"profile": f"GlobalData_{version}"}, "offers": [], **extra}


class LiveTests(unittest.TestCase):
    def setUp(self):
        live._registry_cache.update(at=0, data=None)
        live._contract_cache.update(at=0, data=None)
        players._cache.clear()

    def read_contracts(self, hub, match):
        by_key = {f"place_{config.ROBLOX_PLACE_ID}": hub,
                  f"place_{config.ROBLOX_GAME_PLACE_ID}": match}
        with patch.object(roblox_api, "datastore_get",
                          side_effect=lambda store, key: by_key.get(key)) as get:
            result = live.contracts(force=True)
        # Le contrat vit dans un magasin NON versionne : lisible quand DS_VERSION change.
        self.assertTrue(all(call.args[0] == "CC_Contract" for call in get.call_args_list))
        return result

    def test_hub_and_match_on_different_data_versions_is_reported(self):
        result = self.read_contracts(contract("hub", config.DATASTORE_VERSION),
                                     contract("match", "OLD_VERSION"))
        joined = " ".join(result["issues"])
        self.assertIn("HUB et MATCH visent des données différentes", joined)
        self.assertIn("OLD_VERSION", joined)

    def test_missing_or_unknown_contract_is_reported(self):
        result = self.read_contracts(None, contract("match", config.DATASTORE_VERSION,
                                                    contractRev=99))
        joined = " ".join(result["issues"])
        self.assertIn("aucun contrat publié", joined)
        self.assertIn("v99 inconnu", joined)

    def test_missing_contract_is_retried_without_reopening_the_view(self):
        with (patch.object(live.time, "time", return_value=1000) as now,
              patch.object(roblox_api, "datastore_get", return_value=None) as read):
            self.assertTrue(live.contracts()["issues"])
            read.return_value = contract("hub", config.DATASTORE_VERSION)
            now.return_value = 1009
            self.assertTrue(live.contracts()["issues"])
            self.assertEqual(read.call_count, 2)
            now.return_value = 1010
            self.assertEqual(live.contracts()["issues"], [])
            self.assertEqual(read.call_count, 4)
            now.return_value = 1020
            live.contracts()
            self.assertEqual(read.call_count, 4)
            live.contracts(force=True)
            self.assertEqual(read.call_count, 6)

    def test_registry_presence_changes_are_visible_after_short_cache(self):
        with (patch.object(live.time, "time", return_value=1000) as now,
              patch.object(live, "_list_registry", return_value=[]) as read):
            self.assertEqual(live.servers()["summary"]["players"], 0)
            read.return_value = [{"jobId": "j", "kind": "hub", "hb": 1000,
                                  "players": [{"u": 7, "n": "Bob"}]}]
            now.return_value = 1002
            self.assertEqual(live.servers()["summary"]["players"], 0)
            now.return_value = 1003
            self.assertEqual(live.servers()["summary"]["players"], 1)
            self.assertEqual(read.call_count, 2)

    def test_store_names_follow_the_hub_contract(self):
        with patch.object(live, "contracts", return_value={"places": [
                {"kind": "hub", "contract": contract("hub", "HUB_V")}]}):
            stores = live.store_names()
        self.assertEqual(stores["profile"], "GlobalData_HUB_V")
        # Ce que le contrat ne precise pas retombe sur la version du CC.
        self.assertEqual(stores["stash"], config.datastore_name("PlayerData_Stash"))

    def test_registry_parses_items_marks_stale_and_finds_players(self):
        now = 2_000_000_000
        page = {"memoryStoreSortedMapItems": [
            {"id": "job-a", "value": {"kind": "match", "mode": "DUALS", "hb": now - 5,
                                      "startedAt": now - 600, "placeVersion": 42,
                                      "players": [{"u": 7, "n": "Alpha", "t": 1}]}},
            # Valeur rendue en chaine JSON par certaines versions de l'API : acceptee.
            {"id": "job-b", "value": json.dumps({"kind": "hub", "hb": now - 10, "players": [{"u": 8}]})},
            {"id": "job-c", "value": {"kind": "match", "mode": "EXFIL", "hb": now - 300,
                                      "players": [{"u": 9, "n": "Ghost"}]}},
        ]}
        with (patch.object(roblox_api, "_oc_request", return_value=page),
              patch.object(roblox_api, "resolve_usernames", return_value={"8": "Bravo"}),
              patch.object(live.time, "time", return_value=now)):
            data = live.servers(force=True)
            where = live.find_player(7)
            ghost = live.find_player(9)

        self.assertIsNone(data["error"])
        self.assertEqual(data["summary"]["players"], 2)          # le serveur mort ne compte pas
        self.assertEqual(data["summary"]["byMode"], {"DUALS": 1})
        stale = next(s for s in data["servers"] if s["jobId"] == "job-c")
        self.assertTrue(stale["stale"])
        hub = next(s for s in data["servers"] if s["jobId"] == "job-b")
        self.assertEqual(hub["players"][0]["n"], "Bravo")
        self.assertEqual(where["mode"], "DUALS")
        self.assertIsNone(ghost)

    def test_registry_error_is_returned_not_raised(self):
        with patch.object(roblox_api, "_oc_request", side_effect=roblox_api.RobloxError("403")):
            data = live.servers(force=True)
        self.assertEqual(data["servers"], [])
        self.assertIn("403", data["error"])


class PlayerTests(unittest.TestCase):
    def setUp(self):
        players._cache.clear()

    def test_decode_item_keeps_mods_bag_contents_and_quantity(self):
        item = {"u": "uid1", "i": "AK74", "x": 1, "y": 2, "r": True,
                "a": {"ItemName": "AK-74", "Quantity": 3, "Tint": {"_t": "C3", "r": 1}},
                "m": [{"s": "sight", "i": "RedDot"}],
                "b": [{"u": "uid2", "i": "Bandage", "a": {"Quantity": 2}}]}
        decoded = players.decode_item(item)
        self.assertEqual(decoded["label"], "AK-74")
        self.assertEqual(decoded["quantity"], 3)
        self.assertTrue(decoded["rotated"])
        self.assertEqual(decoded["attrs"]["Tint"], "<C3>")
        self.assertEqual(decoded["mods"], [{"slot": "sight", "id": "RedDot", "template": None}])
        self.assertEqual(decoded["contents"][0]["quantity"], 2)

    def test_stash_reads_tabs_from_the_hub_store(self):
        saved = {"_v": 2, "unlockedTabs": 2, "tabs": [
            {"name": "Armes", "items": [{"u": "a", "i": "M4"}]}, {"name": "Vide", "items": []}]}
        with (patch.object(live, "store_names", return_value={"stash": "PlayerData_Stash_X"}),
              patch.object(roblox_api, "datastore_get", return_value=saved) as get):
            st = players.stash(55)
            players.stash(55)                                 # second appel : cache

        get.assert_called_once_with("PlayerData_Stash_X", "55")
        self.assertEqual(st["tabs"][0]["name"], "Armes")
        self.assertEqual(st["tabs"][0]["items"][0]["id"], "M4")

    def test_summary_sections_fail_independently(self):
        stores = {k: f"{k}_store" for k in ("profile", "skills", "inventory", "stash", "sanctions",
                                             "exfilClaim", "blackMarketDebts", "honeypot")}

        def get(store, key):
            if store == "profile_store":
                return {"faction": "Rainor", "money": 1200, "lp": 210,
                        "market": {"listings": [1, 2], "mail": []}}
            if store == "honeypot_store":
                raise roblox_api.RobloxError("403 honeypot")
            return None

        with (patch.object(live, "store_names", return_value=stores),
              patch.object(live, "find_player", return_value=None),
              patch.object(live, "offers", return_value=[]),
              patch.object(roblox_api, "datastore_get", side_effect=get),
              patch.object(roblox_api, "_oc_request", return_value=None),
              patch.object(roblox_api, "resolve_usernames", return_value={"55": "Target"}),
              patch.object(players, "_headshot", return_value=None)):
            summary = players.summary(55)

        sections = summary["sections"]
        self.assertTrue(sections["profile"]["ok"])
        self.assertEqual(sections["profile"]["data"]["money"], 1200)
        self.assertEqual(sections["profile"]["data"]["market"], {"listings": 2, "mail": 0})
        self.assertFalse(sections["honeypot"]["ok"])
        self.assertIn("403", sections["honeypot"]["error"])
        self.assertEqual(sections["identity"]["data"]["name"], "Target")

    def test_resolve_rejects_unknown_usernames(self):
        with patch.object(roblox_api, "resolve_user_ids", return_value={}):
            with self.assertRaises(players.PlayerError):
                players.resolve("Nobody")


if __name__ == "__main__":
    unittest.main()
