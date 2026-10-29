"""Automatisations : manuel par defaut, delai fixe, heures calmes, interrupteur, echecs."""
from __future__ import annotations

import pytest

from core import automations, db, discord_api, roblox_api

NOW = 1793300000


def card(key="fw_result:w7", done=()):
    acts = [{"id": "faction_announce", "kind": "publish", "label": "Annonces"},
            {"id": "template:factionwar_result", "kind": "publish", "label": "Résultat", "template": "factionwar_result"},
            {"id": "notify:SEASON_RESULT", "kind": "notify", "label": "Notifier", "notify": "SEASON_RESULT", "ref": "w7"},
            {"id": "go:#live", "kind": "go", "label": "Live", "href": "#live"},
            {"id": "erase", "kind": "erase", "label": "Effacer"}]
    for a in acts:
        a["done"] = a["id"] in done
    return {"key": key, "title": "Saison 8 close", "actions": acts}


@pytest.fixture()
def ran(monkeypatch):
    calls: list[tuple[str, str]] = []

    def execute(c, a):
        calls.append((c["key"], a["id"]))
        return True, None
    monkeypatch.setattr(automations, "_execute", execute)
    monkeypatch.setattr(discord_api, "post_ops_log", lambda *a, **k: {})
    monkeypatch.setattr(automations.notify, "_running", lambda: False)
    return calls


def test_everything_is_manual_by_default(ran):
    assert automations.tick(NOW, [card()]) == []
    assert ran == [] and db.auto_runs() == {}


def test_immediate_rule_runs_only_its_checked_publications(ran):
    automations.save("season_result", {"mode": "auto", "actions": ["template:factionwar_result", "notify:SEASON_RESULT"]})
    out = automations.tick(NOW, [card()])
    assert ran == [("fw_result:w7", "template:factionwar_result"), ("fw_result:w7", "notify:SEASON_RESULT")]
    assert all(r["ok"] for r in out)
    assert db.auto_runs()[("fw_result:w7", "notify:SEASON_RESULT")]["state"] == "done"
    assert automations.tick(NOW + 60, [card()]) == []           # deja fait : jamais deux fois


def test_delay_counts_from_first_sight_and_can_be_cancelled(ran):
    automations.save("season_result", {"mode": "delay", "delay": 30, "actions": ["template:factionwar_result",
                                                                                 "faction_announce"]})
    automations.tick(NOW, [card()])
    assert ran == []
    automations.cancel("fw_result:w7", "faction_announce")
    automations.tick(NOW + 29 * 60, [card()])
    assert ran == []
    automations.tick(NOW + 30 * 60, [card()])
    assert ran == [("fw_result:w7", "template:factionwar_result")]
    with pytest.raises(ValueError):
        automations.cancel("fw_result:w7", "faction_announce")


def test_quiet_hours_hold_the_send(ran):
    automations.save("_global", {"quietStart": "23:00", "quietEnd": "09:00"})
    automations.save("boost_end", {"mode": "auto", "actions": ["template:boost_end"]})
    c = {"key": "boost_end:1", "title": "Boost fini",
         "actions": [{"id": "template:boost_end", "kind": "publish", "label": "Annoncer", "template": "boost_end"}]}
    night = int(roblox_api.FW_EPOCH_LOCAL.replace(hour=2).timestamp()) + 7 * 86400
    automations.tick(night, [c])
    assert ran == []
    automations.tick(night + 7 * 3600, [c])                       # 09:00 a Paris
    assert ran == [("boost_end:1", "template:boost_end")]
    assert automations.in_quiet(night, "23:00", "09:00") and not automations.in_quiet(night, "", "")


def test_all_manual_switch_cancels_what_was_planned(ran):
    automations.save("season_result", {"mode": "delay", "delay": 10, "actions": ["faction_announce"]})
    automations.tick(NOW, [card()])
    automations.save("_global", {"allManual": True})
    assert db.auto_runs()[("fw_result:w7", "faction_announce")]["state"] == "cancelled"
    automations.tick(NOW + 3600, [card()])
    assert ran == []


def test_failure_is_kept_for_manual_retry(monkeypatch, ran):
    monkeypatch.setattr(automations, "_execute", lambda c, a: (_ for _ in ()).throw(RuntimeError("Discord 500")))
    automations.save("season_result", {"mode": "auto", "actions": ["faction_announce"]})
    out = automations.tick(NOW, [card()])
    assert out == [{"card": "fw_result:w7", "action": "faction_announce", "ok": False, "error": "Discord 500"}]
    assert db.auto_runs()[("fw_result:w7", "faction_announce")]["state"] == "failed"
    assert db.audit_rows(5, "auto_failed")[0]["actor"] == "auto"
    automations.tick(NOW + 60, [card()])                           # pas de nouvel essai seul


def test_destructive_actions_can_never_be_enabled():
    with pytest.raises(ValueError):
        automations.save("season_result", {"mode": "auto", "actions": ["erase", "go:#live"]})
    cfg = automations.save("season_result", {"mode": "auto", "actions": ["erase", "faction_announce"]})
    rule = next(r for r in cfg["rules"] if r["id"] == "season_result")
    assert rule["config"]["actions"] == ["faction_announce"]
    for r in automations.RULES:
        assert all(k.startswith(("template:", "notify:")) or k == "faction_announce" for k in r["actions"])


def test_bad_settings_are_refused():
    for cfg in ({"mode": "fast"}, {"mode": "delay", "delay": 500, "actions": ["faction_announce"]}):
        with pytest.raises(ValueError):
            automations.save("season_result", cfg)
    with pytest.raises(ValueError):
        automations.save("_global", {"quietStart": "25:00", "quietEnd": "09:00"})
    with pytest.raises(ValueError):
        automations.save("_global", {"quietStart": "23:00"})


def test_cards_show_what_will_leave_alone(ran):
    automations.save("season_result", {"mode": "delay", "delay": 5, "actions": ["faction_announce"]})
    c = card()
    automations.annotate([c], NOW)
    assert c["actions"][0]["auto"] == {"state": "pending", "due": None}
    assert "auto" not in c["actions"][1]
    automations.tick(NOW, [card()])
    c = card()
    automations.annotate([c], NOW)
    assert c["actions"][0]["auto"]["state"] == "planned" and c["actions"][0]["auto"]["due"] == NOW + 300


def test_scheduled_announcements_use_their_own_template(ran):
    automations.save("schedule", {"mode": "auto", "actions": ["template:*"]})
    c = {"key": "schedule:ab12", "title": "Annonce prévue", "actions": [
        {"id": "template:maintenance", "kind": "publish", "label": "Publier maintenant", "template": "maintenance"}]}
    automations.tick(NOW, [c])
    assert ran == [("schedule:ab12", "template:maintenance")]
