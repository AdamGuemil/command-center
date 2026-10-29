"""Reste a faire : chaque verification automatique donne le bon etat."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

CC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CC))

from core import analytics, todo, watch  # noqa: E402


def dau(*values):
    return [{"key": {}, "points": [(i, float(v)) for i, v in enumerate(values)]}]


class TodoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = patch.object(todo, "STATE_FILE", Path(self.tmp.name) / "todo.json")
        self.p.start()
        todo._cache.update(at=0.0, checks={})
        watch._state.update(unbridged=set(), seeded=True)

    def tearDown(self):
        self.p.stop()
        self.tmp.cleanup()

    def states(self, series=None, error=None):
        def fake(*_a, **_k):
            if error:
                raise analytics.AnalyticsError(error)
            return series
        with patch.object(analytics, "query", side_effect=fake):
            return {i["id"]: i for i in todo.overview(force=True)["items"]}

    def test_alerts_wait_for_100_daily_players(self):
        items = self.states(dau(12, 40, 37))
        self.assertEqual(items["analytics_permission"]["state"], "done")
        self.assertEqual(items["roblox_alerts"]["state"], "blocked")
        self.assertIn("40", items["roblox_alerts"]["detail"])
        self.assertEqual(self.states(dau(80, 131))["roblox_alerts"]["state"], "ready")

    def test_missing_permission_blocks_alert_check(self):
        items = self.states(error="Droit « Analytics → Read » absent de la clé Open Cloud (HTTP 403).")
        self.assertEqual(items["analytics_permission"]["state"], "todo")
        self.assertEqual(items["roblox_alerts"]["state"], "blocked")

    def test_unknown_permission_is_not_reported_as_done(self):
        items = self.states(error="ROBLOX_OPENCLOUD_KEY absent (voir .env).")
        self.assertEqual(items["analytics_permission"]["state"], "todo")
        self.assertIn("impossible", items["analytics_permission"]["detail"])
        self.assertEqual(items["roblox_alerts"]["state"], "todo")

    def test_manual_done_and_reopen(self):
        with patch.object(analytics, "query", return_value=dau(150)):
            data = todo.mark("roblox_alerts", True)
            self.assertEqual({i["id"]: i["state"] for i in data["items"]}["roblox_alerts"], "done")
            data = todo.mark("roblox_alerts", False)
            self.assertEqual({i["id"]: i["state"] for i in data["items"]}["roblox_alerts"], "ready")
        with self.assertRaises(ValueError):
            todo.mark("analytics_permission", True)

    def test_old_webhooks_wait_for_old_hubs(self):
        watch._state["unbridged"] = {"job-old"}
        self.assertEqual(self.states(dau(5))["old_webhooks"]["state"], "blocked")
        watch._state["unbridged"] = set()
        self.assertEqual(self.states(dau(5))["old_webhooks"]["state"], "ready")


if __name__ == "__main__":
    unittest.main()
