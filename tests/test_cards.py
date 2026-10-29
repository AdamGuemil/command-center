"""Accueil : chaque situation produit la bonne carte, avec une cle stable."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

CC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CC))

from core import cards  # noqa: E402

NOW = 2_000_000_000
WEEK_START = NOW - 3600


def state(**over):
    s = {
        "now": NOW, "season": {"week": 10, "startsAt": WEEK_START, "endsAt": WEEK_START + 7 * 86400},
        "openCloudOk": True, "discordOk": True, "errors": {}, "boost": None, "archive": None,
        "payouts": [], "contractIssues": [], "placeVersions": [10], "servers": 2, "operations": {},
        "todo": [], "schedule": [], "templates": {}, "events": [],
    }
    s.update(over)
    return s


def keys(s):
    return {c["key"]: c for c in cards.build(s, NOW)}


class CardTests(unittest.TestCase):
    def test_quiet_state_has_no_card(self):
        self.assertEqual(keys(state(archive={"winner": "Rainor", "Rainor": 5, "Rusfor": 3,
                                              "closedAt": WEEK_START + 60},
                                     payouts=[{"week": 9, "count": 12, "at": WEEK_START + 120}])).keys(),
                         {"fw_result:w9", "ranked_top:w9"})

    def test_season_closed_card_offers_both_publications(self):
        c = keys(state(archive={"winner": "Rainor", "Rainor": 12340, "Rusfor": 11020,
                                "closedAt": WEEK_START + 60}))["fw_result:w9"]
        self.assertEqual(c["prio"], "high")
        self.assertIn("Saison 10 close : Rainor gagne", c["title"])
        self.assertIn("12 340", c["context"])
        self.assertEqual([a["id"] for a in c["actions"]], ["faction_announce", "template:factionwar_result"])

    def test_close_pending_when_no_archive(self):
        self.assertIn("fw_pending:w9", keys(state()))
        early = state(season={"week": 10, "startsAt": NOW - 60, "endsAt": NOW + 7 * 86400})
        self.assertNotIn("fw_pending:w9", keys(early))

    def test_ranked_missing_after_30_minutes(self):
        arch = {"winner": "Rusfor", "Rainor": 1, "Rusfor": 2, "closedAt": WEEK_START + 60}
        self.assertIn("ranked_missing:w9", keys(state(archive=arch)))

    def test_j1_card_in_last_day(self):
        s = state(season={"week": 10, "startsAt": NOW - 6 * 86400, "endsAt": NOW + 3600})
        self.assertIn("fw_j1:w10", keys(s))

    def test_boost_ended_and_operations(self):
        s = state(boost={"name": "WEEKEND", "endsAt": NOW - 100},
                  operations={"up": True, "endsAt": NOW - 10})
        k = keys(s)
        self.assertIn(f"boost_end:{NOW - 100}", k)
        self.assertEqual(k[f"ops_close:{NOW - 10}"]["prio"], "high")
        s2 = state(operations={"up": True, "endsAt": NOW + 1800})
        self.assertIn(f"ops_lasthour:{NOW + 1800}", keys(s2))

    def test_versions_and_health(self):
        k = keys(state(placeVersions=[12, 13], openCloudOk=False, discordOk=False,
                       errors={"openCloud": "403"}))
        self.assertIn("versions:12-13", k)
        self.assertEqual(k["cc:opencloud"]["prio"], "crit")
        self.assertIn("cc:discord", k)

    def test_game_events_group_by_player_and_day(self):
        evs = [
            {"id": "a", "type": "ac_flag", "at": NOW - 300, "data": {"u": 7, "title": "Anticheat vitesse · Bob"}},
            {"id": "b", "type": "ac_flag", "at": NOW - 200, "data": {"u": 7, "title": "Anticheat vitesse · Bob"}},
            {"id": "c", "type": "honeypot", "at": NOW - 100, "data": {"u": 9, "trap": "AdminGiveItem", "title": "Piege · Eve"}},
            {"id": "d", "type": "feedback", "at": NOW - 50, "data": {"u": 3, "rating": 1, "text": "lag"}},
            {"id": "e", "type": "error_spike", "at": NOW - 40, "data": {"n": 42, "script": "InventoryServer"}},
        ]
        k = keys(state(events=evs))
        mod = [c for key, c in k.items() if key.startswith("mod:7:")]
        self.assertEqual(len(mod), 1)
        self.assertEqual(mod[0]["count"], 2)
        self.assertEqual(k["honeypot:9"]["actions"][0]["href"], "#players/9")
        self.assertIn("feedback:d", k)
        self.assertIn("42 erreurs", k["errors:e"]["title"])

    def test_todo_items_become_cards(self):
        todo = [{"id": "roblox_alerts", "title": "Alertes", "state": "blocked", "auto": False, "detail": "31/100"},
                {"id": "old_webhooks", "title": "Webhooks", "state": "ready", "auto": False},
                {"id": "analytics_permission", "title": "Analytics", "state": "done", "auto": True}]
        k = keys(state(todo=todo))
        self.assertEqual(k["todo:roblox_alerts"]["prio"], "waiting")
        self.assertEqual(k["todo:old_webhooks"]["prio"], "high")
        self.assertNotIn("todo:analytics_permission", k)

    def test_contract_cards_hidden_when_open_cloud_is_down(self):
        k = keys(state(contractIssues=["absent"], openCloudOk=False))
        self.assertFalse([x for x in k if x.startswith("contract:")])

    def test_contract_key_is_stable(self):
        a = keys(state(contractIssues=["HUB et MATCH divergent"]))
        b = keys(state(contractIssues=["HUB et MATCH divergent"]))
        self.assertEqual(a.keys(), b.keys())


if __name__ == "__main__":
    unittest.main()
