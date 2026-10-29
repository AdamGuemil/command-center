"""Analytics Roblox : requete, attente du resultat, decoupage par place."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

CC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CC))

from core import analytics, config  # noqa: E402


class AnalyticsTests(unittest.TestCase):
    def test_query_polls_the_operation_then_parses_breakdowns(self):
        done = {"done": True, "response": {"values": [
            {"breakdowns": [{"dimension": "Place", "value": str(config.ROBLOX_GAME_PLACE_ID)},
                            {"dimension": "CrashType", "value": "OutOfMemory"}],
             "dataPoints": [{"time": "2026-10-28T13:01:00Z", "value": 2},
                            {"time": "2026-10-28T13:00:00Z", "value": 0}]}]}}
        calls = []

        def fake(method, url, body=None):
            calls.append((method, url, body))
            return (202, {"done": False, "path": "v1/universes/1/operations/metrics/x"}) \
                if method == "POST" else (200, done)

        with (patch.object(analytics, "_request", side_effect=fake),
              patch.object(analytics.time, "sleep")):
            crashes = analytics.recent_server_crashes(30)

        self.assertEqual(calls[0][2]["metric"], "ServerCrashCount")
        self.assertEqual(calls[0][2]["granularity"], "OneMinute")
        self.assertEqual(calls[0][2]["breakdown"], ["Place", "CrashType"])
        self.assertTrue(calls[1][1].endswith("/analytics-query-api/v1/universes/1/operations/metrics/x"))
        self.assertEqual(len(crashes), 1)                       # la minute a 0 est ignoree
        self.assertEqual(crashes[0]["place"], "Matchs")
        self.assertEqual(crashes[0]["cause"], "OutOfMemory")

    def test_overview_isolates_failing_panels(self):
        def fake_query(metric, *a, **k):
            if metric == "DailyRevenue":
                raise analytics.AnalyticsError("Droit « Analytics → Read » absent")
            return [{"key": {"Place": str(config.ROBLOX_PLACE_ID)}, "points": [(1, 5.0)]}]

        with patch.object(analytics, "query", side_effect=fake_query):
            data = analytics.overview(24, force=True)
        panels = {p["id"]: p for p in data["panels"]}
        self.assertIsNone(panels["players"]["error"])
        self.assertEqual(panels["players"]["series"][0]["label"], "Hub")
        self.assertIn("Analytics", panels["revenue"]["error"])


if __name__ == "__main__":
    unittest.main()
