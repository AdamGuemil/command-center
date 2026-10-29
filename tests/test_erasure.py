"""Droit a l'effacement : apercu, confirmation, suppression distante et locale ; sauvegardes."""
from __future__ import annotations

import pytest

from core import config, db, erasure, jobs, live, roblox_api

UID = 4242


@pytest.fixture()
def cloud(monkeypatch):
    existing = {("GlobalData_T", f"p_{UID}"), ("Inv_T", str(UID))}
    deleted: list[tuple[str, str]] = []
    names = {k: v for k, v in {"profile": "GlobalData_T", "skills": "Skills_T", "inventory": "Inv_T",
                               "stash": "Stash_T", "sanctions": "Sanc_T", "exfilClaim": "Exfil_T",
                               "blackMarketDebts": "Debts_T", "honeypot": "Honey_T"}.items()}
    monkeypatch.setattr(live, "store_names", lambda: names)
    monkeypatch.setattr(roblox_api, "fw_week_index", lambda now=None: 1)
    monkeypatch.setattr(roblox_api, "datastore_get", lambda s, k: {"x": 1} if (s, k) in existing else None)
    monkeypatch.setattr(roblox_api, "datastore_delete", lambda s, k: deleted.append((s, k)))

    def oc(method, url, body=None, headers=None):
        if "RankedLB" in url:
            if method == "DELETE":
                deleted.append(("RankedLB", str(UID)))
            return {"value": 10}
        return None
    monkeypatch.setattr(roblox_api, "_oc_request", oc)
    return deleted


def test_plan_lists_every_store_and_what_exists(cloud):
    p = erasure.plan(UID)
    keys = {(r["store"], r["key"]) for r in p["rows"]}
    assert ("GlobalData_T", f"p_{UID}") in keys and ("Debts_T", f"d_{UID}") in keys and ("Honey_T", f"u_{UID}") in keys
    fw = [r for r in p["rows"] if "FWLB_w" in r["store"]]
    assert len(fw) == 2 * len(config.FACTIONS)                     # semaines 0 et 1
    assert p["found"] == 3 and cloud == []                          # l'apercu n'efface rien


def test_apply_needs_the_typed_id_then_erases_remote_and_local(cloud):
    db.set_link(9001, UID)
    db.add_backup(UID, "money", "GlobalData_T", f"p_{UID}", {"money": 1}, {"money": 2}, None, {})
    db.add_events([{"id": "e1", "type": "ac_flag", "data": {"u": UID, "n": "Bob"}},
                   {"id": "e2", "type": "ac_flag", "data": {"u": 1}},
                   {"id": "rbx:n-9", "type": "rbx_erasure", "data": {"userId": UID, "payload": {"UserId": UID}}}])
    db.audit("ban", str(UID), {"motif": "x"})
    p = erasure.plan(UID, card="rtbf:n-9")
    with pytest.raises(ValueError, match="identifiant"):
        erasure.apply(p["token"], "4241")
    out = erasure.apply(p["token"], str(UID))
    assert out["ok"] and sorted(cloud) == sorted([("GlobalData_T", f"p_{UID}"), ("Inv_T", str(UID)),
                                                   ("RankedLB", str(UID))])
    assert out["local"]["links"] == 1 and out["local"]["backups"] == 1 and out["local"]["events"] == 1
    assert db.get_link(9001) is None
    assert {e["id"] for e in db.events()} == {"e2", "rbx:n-9"}
    rbx = next(e for e in db.events() if e["id"] == "rbx:n-9")
    assert rbx["data"]["userId"] is None and rbx["data"]["erasedAt"]
    assert db.audit_rows(20, "ban")[0]["target"] == "[efface]"
    trace = db.audit_rows(5, "erasure")[0]
    assert trace["target"] == "rtbf:n-9" and str(UID) not in str(trace["detail"])
    with pytest.raises(ValueError, match="expiré"):
        erasure.apply(p["token"], str(UID))


def test_daily_backup_keeps_a_bounded_number_of_copies(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BACKUP_DIR", tmp_path / "bk")
    monkeypatch.setattr(config, "BACKUP_KEEP", 2)
    db.audit("probe", "x")
    for day in range(4):
        info = jobs.backup(1793300000 + day * 86400)
    files = sorted(p.name for p in (tmp_path / "bk").glob("cc-*.db"))
    assert len(files) == 2 and info["file"] == files[-1]
    import sqlite3
    con = sqlite3.connect(tmp_path / "bk" / files[-1])
    assert con.execute("SELECT COUNT(*) FROM audit WHERE action = 'probe'").fetchone()[0] == 1
    con.close()
    jobs._state["day"] = None
    jobs.daily(1793300000 + 3 * 86400)                              # copie du jour deja la : rien de plus
    assert len(list((tmp_path / "bk").glob("cc-*.db"))) == 2
