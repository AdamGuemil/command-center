"""
Base locale du Command Center (SQLite, bibliotheque standard, fichier data/cc.db).

Tables :
  events  evenements recus du jeu (bus CC_Events_V1), dedoublonnes par id
  audit   journal de ce que le CC a fait : envois Discord, ecritures Roblox, cartes traitees.
          Remplace data/history.json (migre au premier demarrage, fichier conserve).
  cards   etat des cartes de l'Accueil : faite, ignoree, ou repoussee jusqu'a une date.
  commands  commandes envoyees aux serveurs (cc_cmd) ; leurs accuses sont des evenements.
  backups   entree d'origine de chaque modification hors ligne d'un joueur (annulation).
  notified  registre des notifications joueurs : une ligne par joueur et par jour UTC (Roblox
            n'en delivre qu'une par jour et par experience ; ne pas gaspiller la suivante).
  campaigns envois de notifications : cle du catalogue, sujet (ref), progression, erreur.

Une connexion par appel, sous verrou : le serveur HTTP et le veilleur ecrivent depuis des
fils differents, et le volume est minuscule. Le fichier est local et non versionne.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from . import config

DB_FILE = config.DATA_DIR / "cc.db"
HISTORY_FILE = config.DATA_DIR / "history.json"
EVENT_RETENTION_S = 90 * 86400
AUDIT_KEEP = 5000

_lock = threading.RLock()
_ready: set[str] = set()

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  id TEXT PRIMARY KEY, type TEXT NOT NULL, at INTEGER NOT NULL, job TEXT, place TEXT,
  data TEXT NOT NULL, received INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS events_type_at ON events(type, at);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT, at INTEGER NOT NULL, action TEXT NOT NULL,
  target TEXT, detail TEXT, ok INTEGER NOT NULL DEFAULT 1, card TEXT
);
CREATE INDEX IF NOT EXISTS audit_at ON audit(at);
CREATE INDEX IF NOT EXISTS audit_card ON audit(card);
CREATE TABLE IF NOT EXISTS cards (
  key TEXT PRIMARY KEY, state TEXT NOT NULL, until INTEGER, at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS commands (
  id TEXT PRIMARY KEY, op TEXT NOT NULL, at INTEGER NOT NULL, target TEXT, payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS backups (
  id INTEGER PRIMARY KEY AUTOINCREMENT, at INTEGER NOT NULL, user_id INTEGER NOT NULL, op TEXT NOT NULL,
  store TEXT NOT NULL, key TEXT NOT NULL, before TEXT, after TEXT, etag_after TEXT, params TEXT,
  undone_at INTEGER
);
CREATE INDEX IF NOT EXISTS backups_user ON backups(user_id);
CREATE TABLE IF NOT EXISTS notified (
  user_id INTEGER NOT NULL, day TEXT NOT NULL, key TEXT NOT NULL, at INTEGER NOT NULL,
  status TEXT NOT NULL, campaign INTEGER, PRIMARY KEY (user_id, day)
);
CREATE INDEX IF NOT EXISTS notified_key_at ON notified(key, at);
CREATE TABLE IF NOT EXISTS campaigns (
  id INTEGER PRIMARY KEY AUTOINCREMENT, at INTEGER NOT NULL, key TEXT NOT NULL, ref TEXT,
  params TEXT, card TEXT, total INTEGER NOT NULL DEFAULT 0, sent INTEGER NOT NULL DEFAULT 0,
  throttled INTEGER NOT NULL DEFAULT 0, skipped INTEGER NOT NULL DEFAULT 0,
  failed INTEGER NOT NULL DEFAULT 0, state TEXT NOT NULL, error TEXT, finished_at INTEGER
);
CREATE INDEX IF NOT EXISTS campaigns_key_ref ON campaigns(key, ref);
"""


def _path() -> Path:
    return DB_FILE


@contextmanager
def connect():
    path = _path()
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(path, timeout=10)
        con.row_factory = sqlite3.Row
        try:
            if str(path) not in _ready:
                con.executescript(SCHEMA)
                _migrate_history(con)
                _ready.add(str(path))
            yield con
            con.commit()
        finally:
            con.close()


def _migrate_history(con) -> None:
    """Importe history.json une seule fois (le fichier reste en place, en lecture seule)."""
    if con.execute("SELECT 1 FROM meta WHERE k = 'history_migrated'").fetchone():
        return
    try:
        rows = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        rows = []
    for r in reversed(rows if isinstance(rows, list) else []):
        if not isinstance(r, dict):
            continue
        con.execute("INSERT INTO audit(at, action, target, detail, ok) VALUES (?,?,?,?,?)",
                    (int(r.get("at") or 0), "discord_send", str(r.get("channel") or ""),
                     json.dumps({"title": r.get("title") or "", "error": r.get("detail") or ""},
                                ensure_ascii=False), 1 if r.get("ok") else 0))
    con.execute("INSERT OR REPLACE INTO meta(k, v) VALUES ('history_migrated', ?)", (str(int(time.time())),))


# EVENEMENTS
def add_events(events: list[dict]) -> list[dict]:
    """Enregistre les evenements nouveaux ; renvoie ceux qui n'etaient pas deja connus."""
    fresh, now = [], int(time.time())
    with connect() as con:
        for e in events:
            cur = con.execute(
                "INSERT OR IGNORE INTO events(id, type, at, job, place, data, received) VALUES (?,?,?,?,?,?,?)",
                (str(e["id"]), str(e["type"]), int(e.get("at") or now), e.get("job"), e.get("place"),
                 json.dumps(e.get("data") or {}, ensure_ascii=False), now))
            if cur.rowcount:
                fresh.append(e)
        con.execute("DELETE FROM events WHERE at < ?", (now - EVENT_RETENTION_S,))
    return fresh


def events(types: tuple[str, ...] | None = None, since: int = 0, limit: int = 200) -> list[dict]:
    sql = "SELECT * FROM events WHERE at >= ?"
    args: list[object] = [since]
    if types:
        sql += f" AND type IN ({','.join('?' * len(types))})"
        args += list(types)
    sql += " ORDER BY at DESC LIMIT ?"
    args.append(limit)
    with connect() as con:
        return [{"id": r["id"], "type": r["type"], "at": r["at"], "job": r["job"], "place": r["place"],
                 "data": json.loads(r["data"] or "{}")} for r in con.execute(sql, args)]


# JOURNAL D'AUDIT
def audit(action: str, target: str = "", detail: dict | str | None = None, ok: bool = True,
          card: str | None = None) -> None:
    text = detail if isinstance(detail, str) else json.dumps(detail or {}, ensure_ascii=False)
    with connect() as con:
        con.execute("INSERT INTO audit(at, action, target, detail, ok, card) VALUES (?,?,?,?,?,?)",
                    (int(time.time()), action, target[:200], text[:2000], 1 if ok else 0, card))
        con.execute("DELETE FROM audit WHERE id <= (SELECT MAX(id) FROM audit) - ?", (AUDIT_KEEP,))


def audit_rows(limit: int = 200, action: str | None = None) -> list[dict]:
    sql = "SELECT * FROM audit"
    args: list[object] = []
    if action:
        sql += " WHERE action = ?"
        args.append(action)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(limit)
    with connect() as con:
        out = []
        for r in con.execute(sql, args):
            try:
                detail = json.loads(r["detail"] or "{}")
            except ValueError:
                detail = r["detail"]
            out.append({"id": r["id"], "at": r["at"], "action": r["action"], "target": r["target"],
                        "detail": detail, "ok": bool(r["ok"]), "card": r["card"]})
        return out


# CARTES
def card_states() -> dict[str, dict]:
    with connect() as con:
        return {r["key"]: {"state": r["state"], "until": r["until"], "at": r["at"]}
                for r in con.execute("SELECT * FROM cards")}


def set_card(key: str, state: str, until: int | None = None) -> None:
    if state not in ("done", "dismissed", "snoozed", "open"):
        raise ValueError("Etat de carte inconnu.")
    with connect() as con:
        if state == "open":
            con.execute("DELETE FROM cards WHERE key = ?", (key,))
        else:
            con.execute("INSERT OR REPLACE INTO cards(key, state, until, at) VALUES (?,?,?,?)",
                        (key, state, until, int(time.time())))


# COMMANDES ENVOYEES AUX SERVEURS
def add_command(cmd_id: str, op: str, target: str, payload: dict) -> None:
    with connect() as con:
        con.execute("INSERT OR REPLACE INTO commands(id, op, at, target, payload) VALUES (?,?,?,?,?)",
                    (cmd_id, op, int(time.time()), target, json.dumps(payload, ensure_ascii=False)))


def get_command(cmd_id: str) -> dict | None:
    with connect() as con:
        r = con.execute("SELECT * FROM commands WHERE id = ?", (cmd_id,)).fetchone()
        if not r:
            return None
        acks = [{"at": a["at"], "job": a["job"], "place": a["place"], **json.loads(a["data"] or "{}")}
                for a in con.execute("SELECT * FROM events WHERE id LIKE ? ORDER BY at", (f"cmd_ack:{cmd_id}:%",))]
        return {"id": r["id"], "op": r["op"], "at": r["at"], "target": r["target"],
                "payload": json.loads(r["payload"] or "{}"), "acks": acks}


# COPIES AVANT MODIFICATION
def add_backup(user_id: int, op: str, store: str, key: str, before, after, etag_after: str | None,
               params: dict) -> int:
    with connect() as con:
        cur = con.execute(
            "INSERT INTO backups(at, user_id, op, store, key, before, after, etag_after, params) VALUES (?,?,?,?,?,?,?,?,?)",
            (int(time.time()), int(user_id), op, store, key, json.dumps(before, ensure_ascii=False),
             json.dumps(after, ensure_ascii=False), etag_after, json.dumps(params or {}, ensure_ascii=False)))
        return int(cur.lastrowid)


def _backup_row(r) -> dict:
    return {"id": r["id"], "at": r["at"], "userId": r["user_id"], "op": r["op"], "store": r["store"],
            "key": r["key"], "before": json.loads(r["before"] or "null"), "after": json.loads(r["after"] or "null"),
            "etagAfter": r["etag_after"], "params": json.loads(r["params"] or "{}"), "undoneAt": r["undone_at"]}


def get_backup(backup_id: int) -> dict | None:
    with connect() as con:
        r = con.execute("SELECT * FROM backups WHERE id = ?", (int(backup_id),)).fetchone()
        return _backup_row(r) if r else None


def backups_for(user_id: int, limit: int = 30) -> list[dict]:
    with connect() as con:
        rows = con.execute("SELECT * FROM backups WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                           (int(user_id), limit)).fetchall()
        out = []
        for r in rows:
            b = _backup_row(r)
            b.pop("before")                        # la fiche n'a besoin que du resume
            b.pop("after")
            out.append(b)
        return out


def mark_backup_undone(backup_id: int) -> None:
    with connect() as con:
        con.execute("UPDATE backups SET undone_at = ? WHERE id = ?", (int(time.time()), int(backup_id)))


# NOTIFICATIONS JOUEURS
NOTIFIED_KEEP_S = 60 * 86400


def notified_on(day: str, user_ids: list[int] | None = None) -> set[int]:
    """Joueurs deja notifies ce jour-la (UTC), parmi `user_ids` ou tous."""
    with connect() as con:
        if user_ids is None:
            rows = con.execute("SELECT user_id FROM notified WHERE day = ?", (day,))
            return {int(r["user_id"]) for r in rows}
        out: set[int] = set()
        ids = [int(u) for u in user_ids]
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            rows = con.execute(f"SELECT user_id FROM notified WHERE day = ? AND user_id IN ({','.join('?' * len(chunk))})",
                               (day, *chunk))
            out.update(int(r["user_id"]) for r in rows)
        return out


def notified_since(key: str, since: int) -> set[int]:
    with connect() as con:
        return {int(r["user_id"]) for r in con.execute(
            "SELECT user_id FROM notified WHERE key = ? AND at >= ?", (key, since))}


def add_notified(user_id: int, day: str, key: str, status: str, campaign: int | None) -> bool:
    """Reserve le jour du joueur. False si un autre envoi l'a deja pris."""
    now = int(time.time())
    with connect() as con:
        cur = con.execute("INSERT OR IGNORE INTO notified(user_id, day, key, at, status, campaign) VALUES (?,?,?,?,?,?)",
                          (int(user_id), day, key, now, status, campaign))
        con.execute("DELETE FROM notified WHERE at < ?", (now - NOTIFIED_KEEP_S,))
        return bool(cur.rowcount)


def release_notified(user_id: int, day: str, campaign: int | None) -> None:
    """Libere le jour reserve quand l'envoi a echoue sans rien consommer chez Roblox."""
    with connect() as con:
        con.execute("DELETE FROM notified WHERE user_id = ? AND day = ? AND campaign IS ?",
                    (int(user_id), day, campaign))


def notified_count(day: str) -> dict[str, int]:
    with connect() as con:
        return {r["key"]: int(r["n"]) for r in con.execute(
            "SELECT key, COUNT(*) AS n FROM notified WHERE day = ? GROUP BY key", (day,))}


def add_campaign(key: str, ref: str, params: dict, card: str | None, total: int) -> int:
    with connect() as con:
        cur = con.execute("INSERT INTO campaigns(at, key, ref, params, card, total, state) VALUES (?,?,?,?,?,?,?)",
                          (int(time.time()), key, ref, json.dumps(params or {}, ensure_ascii=False), card,
                           int(total), "running"))
        return int(cur.lastrowid)


def update_campaign(campaign_id: int, **fields) -> None:
    allowed = {"sent", "throttled", "skipped", "failed", "state", "error", "finished_at", "total"}
    cols = [k for k in fields if k in allowed]
    if not cols:
        return
    with connect() as con:
        con.execute(f"UPDATE campaigns SET {', '.join(f'{c} = ?' for c in cols)} WHERE id = ?",
                    (*[fields[c] for c in cols], int(campaign_id)))


def _campaign_row(r) -> dict:
    return {"id": r["id"], "at": r["at"], "key": r["key"], "ref": r["ref"],
            "params": json.loads(r["params"] or "{}"), "card": r["card"], "total": r["total"],
            "sent": r["sent"], "throttled": r["throttled"], "skipped": r["skipped"], "failed": r["failed"],
            "state": r["state"], "error": r["error"], "finishedAt": r["finished_at"]}


def campaigns(limit: int = 50, key: str | None = None, ref: str | None = None) -> list[dict]:
    sql = "SELECT * FROM campaigns WHERE 1=1"
    args: list[object] = []
    if key:
        sql += " AND key = ?"
        args.append(key)
    if ref is not None:
        sql += " AND ref = ?"
        args.append(ref)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(limit)
    with connect() as con:
        return [_campaign_row(r) for r in con.execute(sql, args)]


def close_stale_campaigns() -> None:
    """Au demarrage : une campagne restee « running » a ete coupee par l'arret du CC."""
    with connect() as con:
        con.execute("UPDATE campaigns SET state = 'stopped', error = COALESCE(error, ?), finished_at = ? "
                    "WHERE state = 'running'", ("Interrompue par l'arrêt du Command Center.", int(time.time())))
