from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

CC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CC))

from core import arsenal  # noqa: E402


class ArsenalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.arsenal_file = Path(self.tmp.name) / "arsenal.json"
        self.file_patch = patch.object(arsenal, "ARSENAL_FILE", self.arsenal_file)
        self.file_patch.start()

    def tearDown(self):
        self.file_patch.stop()
        self.tmp.cleanup()

    @staticmethod
    def weapon(name="Test", cls="pdw", level=3):
        return {
            "name": name,
            "cls": cls,
            "faction": "Neutral",
            "rarity": "Common",
            "damage": 10,
            "rpm": 600,
            "rangeStuds": 100,
            "pen": 10,
            "stabH": 20,
            "stabV": 20,
            "poids": 10,
            "price": 1000,
            "level": level,
        }

    def test_save_migrates_pdw_and_keeps_extendable_level_max(self):
        saved = arsenal.save({"levelMax": 35, "weapons": [self.weapon()]})
        self.assertEqual(saved["levelMax"], 35)
        self.assertEqual(saved["weapons"][0]["cls"], "smg")
        view = arsenal.overview()
        self.assertEqual(view["levelMax"], 35)
        self.assertNotIn("pdw", [row["id"] for row in view["classes"]])

    def test_weapon_beyond_cap_extends_timeline_automatically(self):
        saved = arsenal.save({"levelMax": 30, "weapons": [self.weapon(level=35)]})
        self.assertEqual(saved["levelMax"], 35)

    def test_drag_level_endpoint_persists_only_requested_weapon(self):
        arsenal.save({
            "levelMax": 30,
            "weapons": [self.weapon("A", "smg", 4), self.weapon("B", "ar", 9)],
        })
        arsenal.set_level("A", 35)
        saved = arsenal.load()
        by_name = {row["name"]: row for row in saved["weapons"]}
        self.assertEqual(by_name["A"]["level"], 35)
        self.assertEqual(by_name["B"]["level"], 9)
        self.assertEqual(saved["levelMax"], 35)

    def test_invalid_drag_is_rejected(self):
        arsenal.save({"weapons": [self.weapon()]})
        with self.assertRaisesRegex(ValueError, "superieur"):
            arsenal.set_level("Test", 0)
        with self.assertRaisesRegex(ValueError, "introuvable"):
            arsenal.set_level("Absente", 5)

    @staticmethod
    def outfit(oid="T01", **fields):
        row = {
            "id": oid, "label": "Test", "faction": "Rainor", "rarity": "Common",
            "source": "shop", "price": 1000, "level": 5,
            "topTemplate": f"Rainor_{oid}_Jacket", "topName": f"Rainor {oid} Jacket",
            "bottomTemplate": f"Rainor_{oid}_Pants", "bottomName": f"Rainor {oid} Pants",
        }
        row.update(fields)
        return row

    def test_outfits_round_trip_and_survive_a_save_without_the_key(self):
        arsenal.save({"weapons": [self.weapon()], "outfits": [self.outfit()]})
        # Une page ouverte avant l'arrivee des habits ne les envoie pas : ils restent.
        arsenal.save({"weapons": [self.weapon()]})
        saved = arsenal.load()
        self.assertEqual([o["id"] for o in saved["outfits"]], ["T01"])
        self.assertEqual(saved["outfits"][0]["price"], 1000)
        row = arsenal.overview()["outfits"][0]
        self.assertTrue(row["sold"])

    def test_outfit_values_that_would_reach_the_game_are_validated(self):
        for bad, pattern in (
            ({"faction": "Rainer"}, "faction inconnu"),
            ({"rarity": "Mythic"}, "rarity inconnu"),
            ({"source": "gift"}, "source inconnu"),
            ({"price": -5}, "prix"),
            ({"level": 0}, "niveau"),
            ({"level": 2.5}, "niveau"),
            ({"id": ""}, "identifiant"),
        ):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, pattern):
                arsenal.save({"outfits": [self.outfit(**bad)]})
        with self.assertRaisesRegex(ValueError, "double"):
            arsenal.save({"outfits": [self.outfit("A"), self.outfit("A")]})

    def test_shop_block_sells_shop_outfits_and_locks_the_others(self):
        outfits = [
            self.outfit("S1", price=1500, level=7),
            self.outfit("K1", source="subscription", price=None, level=None),
        ]
        saved = arsenal.save({"outfits": outfits})["outfits"]
        block = arsenal.outfit_shop_block(saved, 40)
        self.assertEqual(block["issues"], [])
        code = block["code"]
        self.assertIn('["Rainor S1 Jacket"] = 1500,', code)
        self.assertIn('["Rainor S1 Pants"] = 7,', code)
        # Une tenue de kit n'a ni niveau ni prix, et finit dans NO_BUY.
        self.assertNotIn('["Rainor K1 Jacket"]', code)
        self.assertIn('"Rainor K1 Jacket",', code)
        self.assertNotIn('"Rainor S1 Jacket",', code)
        self.assertTrue(code.startswith(arsenal.OUTFIT_BLOCK_BEGIN))
        self.assertTrue(code.endswith(arsenal.OUTFIT_BLOCK_END))

    def test_outfit_alerts_block_the_copy_when_the_block_would_be_wrong(self):
        outfits = arsenal.save({"outfits": [
            self.outfit("A", price=None),
            self.outfit("B", level=45),
            self.outfit("C", topName="Rainor B Jacket"),
        ]})["outfits"]
        kinds = {a["kind"] for a in arsenal.outfit_alerts(outfits, 40)}
        self.assertTrue({"missing", "level", "dup"} <= kinds)
        self.assertTrue(arsenal.outfit_shop_block(outfits, 40)["issues"])

    def test_inversion_is_a_warning_not_a_blocker(self):
        outfits = arsenal.save({"outfits": [
            self.outfit("A", price=5000, level=5),
            self.outfit("B", price=2000, level=10),
        ]})["outfits"]
        alerts = arsenal.outfit_alerts(outfits, 40)
        self.assertEqual([(a["kind"], a["faction"]) for a in alerts], [("inversion", "Rainor")])
        self.assertEqual(arsenal.outfit_shop_block(outfits, 40)["issues"], [])

    def test_outfit_level_drag_persists_one_outfit_within_the_cap(self):
        arsenal.save({"levelMax": 40, "outfits": [self.outfit("A", level=3), self.outfit("B", level=9)]})
        arsenal.set_outfit_level("A", 40)
        by_id = {o["id"]: o for o in arsenal.load()["outfits"]}
        self.assertEqual((by_id["A"]["level"], by_id["B"]["level"]), (40, 9))
        with self.assertRaisesRegex(ValueError, "niveau max"):
            arsenal.set_outfit_level("A", 41)
        with self.assertRaisesRegex(ValueError, "introuvable"):
            arsenal.set_outfit_level("ZZ", 5)

if __name__ == "__main__":
    unittest.main()
