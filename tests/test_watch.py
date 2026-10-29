"""Veilleur live : chaque transition du registre produit le bon evenement."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

CC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CC))

from core import discord_api, live, watch  # noqa: E402


class SyncThread:
    """Remplace threading.Thread : l'envoi Discord s'execute tout de suite, testable."""
    def __init__(self, target=None, args=(), daemon=None, **_):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)

NOW = 2_000_000_000


def server(job, hb_age=5, kind="match", mode="DUALS", fps=60, players=2, version=10, reported=False):
    return {"jobId": job, "kind": kind, "mode": mode, "map": "dust_2", "fps": fps,
            "hb": NOW - hb_age, "stale": hb_age > live.STALE_AFTER_S, "placeVersion": version,
            "players": [{"u": i} for i in range(players)],
            "crashReportedAt": NOW if reported else None}


def registry(*servers):
    fresh = [s for s in servers if not s["stale"]]
    return {"servers": list(servers), "error": None, "summary": {
        "hubs": sum(s["kind"] == "hub" for s in fresh),
        "matches": sum(s["kind"] != "hub" for s in fresh),
        "hubPlayers": sum(len(s["players"]) for s in fresh if s["kind"] == "hub"),
        "matchPlayers": sum(len(s["players"]) for s in fresh if s["kind"] != "hub"),
        "placeVersions": sorted({s["placeVersion"] for s in fresh})}}


class WatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        self.patches = [patch.object(watch, "EVENTS_FILE", tmp / "e.json"),
                        patch.object(watch, "TIMELINE_FILE", tmp / "t.json"),
                        patch.object(discord_api, "post_ops_log", return_value={"sent": True}),
                        patch.object(watch.threading, "Thread", SyncThread)]
        for p in self.patches:
            p.start()
        watch._state.update(known={}, events=[], timeline=[], seeded=False, nextId=1,
                            versionsSig="", unbridged=set(), lastError=None, robloxSeen=set())

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def run_tick(self, data, public=None, now=NOW):
        with patch.object(live, "servers", return_value=data):
            watch.tick(now=now, public=public)
        return [e["kind"] for e in watch._state["events"]]

    def test_discord_losses_are_journaled_with_throttle(self):
        def srv(dropped, failed=0):
            s = server("a")
            s["discord"] = {"s": 40, "d": dropped, "f": failed, "t": 0}
            return s
        self.run_tick(registry(srv(3)))                       # pertes anterieures : base
        self.assertEqual(self.run_tick(registry(srv(3))), [])
        kinds = self.run_tick(registry(srv(8, 1)), now=NOW + 20)
        self.assertEqual(kinds, ["discord"])
        self.assertIn("6 message(s)", watch._state["events"][-1]["text"])
        # Nouvelle hausse dans les 10 min : pas de second evenement...
        self.assertEqual(self.run_tick(registry(srv(12, 1)), now=NOW + 60), ["discord"])
        # ...puis le cumul est signale une fois le delai passe.
        self.run_tick(registry(srv(12, 1)), now=NOW + 20 + watch.DISCORD_EVENT_EVERY_S)
        self.assertEqual([e["kind"] for e in watch._state["events"]], ["discord", "discord"])
        self.assertIn("4 message(s)", watch._state["events"][-1]["text"])

    def test_first_read_only_seeds(self):
        self.assertEqual(self.run_tick(registry(server("a"), server("b"))), [])

    def test_start_and_clean_stop(self):
        self.run_tick(registry(server("a")))
        self.run_tick(registry(server("a"), server("b", kind="hub")))
        kinds = self.run_tick(registry(server("b", kind="hub")))
        self.assertEqual(kinds, ["start", "stop"])

    def test_crash_is_journaled_once(self):
        self.run_tick(registry(server("a", players=4)))
        self.run_tick(registry(server("a", hb_age=90, players=4)))
        self.run_tick(registry(server("a", hb_age=110, players=4)))
        kinds = self.run_tick(registry())               # l'entree finit par expirer
        self.assertEqual(kinds, ["crash"])
        crash = watch._state["events"][0]
        self.assertEqual(crash["level"], "crit")
        self.assertIn("4 joueur(s)", crash["text"])

    def test_cc_posts_to_discord_only_as_last_resort(self):
        with patch.object(discord_api, "post_ops_log", return_value={"sent": True}) as post:
            self.run_tick(registry(server("a")))
            self.run_tick(registry(server("a", hb_age=90)))           # crash vu, pas encore poste
            self.assertEqual(post.call_count, 0)
            self.run_tick(registry(server("a", hb_age=160)))          # aucun veilleur du jeu
            self.run_tick(registry(server("a", hb_age=180)))
        self.assertEqual(post.call_count, 1)

    def test_no_discord_post_when_the_game_watchdog_reported(self):
        with patch.object(discord_api, "post_ops_log", return_value={"sent": True}) as post:
            self.run_tick(registry(server("a")))
            self.run_tick(registry(server("a", hb_age=90, reported=True)))
            self.run_tick(registry(server("a", hb_age=200, reported=True)))
        self.assertEqual(post.call_count, 0)
        self.assertIn("veilleur du jeu", watch._state["events"][0]["text"])

    def test_roblox_crashes_are_journaled_once_with_their_cause(self):
        crashes = [{"at": NOW - 120, "place": "Matchs", "cause": "OutOfMemory", "count": 2}]
        watch.analytics_tick(crashes)
        watch.analytics_tick(crashes)
        events = [e for e in watch._state["events"] if e["kind"] == "roblox_crash"]
        self.assertEqual(len(events), 1)
        self.assertIn("OutOfMemory", events[0]["text"])
        self.assertIn("Matchs", events[0]["text"])

    def test_freeze_then_recovery(self):
        self.run_tick(registry(server("a")))
        self.run_tick(registry(server("a", hb_age=90)))
        kinds = self.run_tick(registry(server("a")))
        self.assertEqual(kinds, ["crash", "recovered"])

    def test_lag_needs_two_low_readings(self):
        self.run_tick(registry(server("a")))
        self.assertEqual(self.run_tick(registry(server("a", fps=20))), [])
        self.assertEqual(self.run_tick(registry(server("a", fps=18))), ["lag"])
        self.assertEqual(self.run_tick(registry(server("a", fps=17))), ["lag"])

    def test_mixed_versions_and_unbridged_hub(self):
        self.run_tick(registry(server("a", version=10)))
        kinds = self.run_tick(registry(server("a", version=10), server("b", version=11)),
                              public=[{"id": "ghost", "playing": 3}, {"id": "a"}])
        self.assertIn("versions", kinds)
        self.assertIn("unbridged", kinds)
        self.assertEqual(kinds.count("unbridged"), 1)

    def test_timeline_keeps_one_point_per_minute(self):
        self.run_tick(registry(server("h", kind="hub", players=5), server("m", players=3)), now=NOW)
        self.run_tick(registry(server("h", kind="hub", players=6)), now=NOW + 20)
        points = watch._state["timeline"]
        self.assertEqual(len({p["at"] for p in points}), len(points))
        self.assertEqual(points[-1]["hub"], 6)


if __name__ == "__main__":
    unittest.main()
