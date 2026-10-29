"""
Notifications joueurs (Experience Notifications, Open Cloud).

Ce que Roblox impose (guide « Experience notifications ») :
  * le TEXTE se cree dans le Creator Hub (Engagement, Notifications), 99 caracteres max,
    parametres entre accolades ; aucune API ne le cree. Le CC garde seulement son Asset ID ;
  * seuls les joueurs de 13 ans ou plus inscrits aux notifications de l'experience les recoivent ;
  * UNE notification par joueur, par experience et par jour ; Roblox reduit aussi la portee
    selon l'engagement. La livraison n'est jamais garantie ;
  * l'experience doit avoir au moins 100 visites ;
  * droit de cle : User Notifications, Write (user.user-notification:write).

Ce module :
  * CATALOGUE : les six notifications retenues (decision D4), leurs parametres, leur
    `launch_data` (ecran ouvert au Hub par LaunchRouter) et leur audience ;
  * data/notifications.json : l'Asset ID de chaque texte, colle depuis le Creator Hub ;
  * audiences calculees depuis le jeu : classements de guerre de la semaine
    (FWLB_w<semaine>_<faction>), bordereau ranked, et l'index d'activite CC_LastSeen
    (OrderedDataStore ecrit par le Hub a chaque arrivee, valeur = heure Unix) ;
  * registre `notified` (une ligne par joueur et par jour UTC) : un joueur deja servi
    aujourd'hui est saute, et la plus forte des notifications du jour est gardee
    (le resultat de saison n'utilise pas le jour des joueurs qui attendent leur ranked) ;
  * campagnes : un envoi a la fois, en tache de fond, rythme et interruptible. Un 429 est
    compte comme « deja servi » ; une serie de 429 met la campagne en pause.

Rien ne part sans clic : chaque campagne passe par un apercu (audience, deja servis, texte).
"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from . import config, db, ranked_rewards, roblox_api

CONFIG_FILE = config.DATA_DIR / "notifications.json"
API = "https://apis.roblox.com/cloud/v2/users/{uid}/notifications"
HOUR = 3600
TEXT_MAX = 99                 # limite du Creator Hub
PARAM_MAX = 60                # valeur de parametre : courte, le texte entier doit rester lisible
LAUNCH_MAX = 200              # octets, limite Roblox
MAX_AUDIENCE = 20000
SEND_INTERVAL_S = 0.12        # ~8 envois par seconde
THROTTLE_PAUSE = 10           # 429 consecutifs avant de mettre la campagne en pause
FAIL_STOP = 15                # erreurs consecutives (reseau, 5xx) avant d'arreter
ACTIVITY_BASE = "CC_LastSeen"
MESSAGE_ID = re.compile(r"^[A-Za-z0-9-]{4,64}$")


class NotifyError(Exception):
    pass


# CATALOGUE -------------------------------------------------------------------
# Ordre = priorite, de la plus forte a la plus faible (§5.3 du plan).
CATALOGUE: list[dict] = [
    {"key": "RANKED_REWARD", "input": [], "label": "Récompense ranked",
     "text": "You finished #{rank} in Ranked. Your {gold} gold is waiting.",
     "params": ["rank", "gold"], "perPlayer": ["rank", "gold"], "launch": "open=ranked",
     "audience": "Joueurs du dernier versement ranked (top 25).",
     "trigger": "Carte « Ranked versé » de l'Accueil, après le versement automatique du jeu."},
    {"key": "SEASON_RESULT", "input": [], "label": "Résultat de saison",
     "text": "Season {season} is over: {faction} won. Claim your war rewards.",
     "params": ["season", "faction"], "perPlayer": [], "launch": "open=war",
     "audience": "Joueurs qui ont contribué à la saison close (classements des deux factions). "
                 "Si le ranked n'est pas encore versé, le top ranked est mis de côté pour RANKED_REWARD.",
     "trigger": "Carte « Saison close » de l'Accueil."},
    {"key": "EVENT_LIVE", "input": ["event", "hours"], "label": "Événement en cours",
     "text": "{event} is live for {hours}h.",
     "params": ["event", "hours"], "perPlayer": [], "launch": "open=play",
     "audience": "Joueurs absents depuis 2 à 14 jours.",
     "trigger": "Carte « Boost en cours » ou « OPERATIONS ouvert » de l'Accueil."},
    {"key": "SEASON_ENDING", "input": [], "label": "Fin de saison dans 24 h",
     "text": "24h left in Season {season}. {faction} needs you.",
     "params": ["season", "faction"], "perPlayer": ["faction"], "launch": "open=war",
     "audience": "Joueurs qui ont contribué cette semaine mais ne sont pas venus depuis 24 h ; "
                 "chacun reçoit le nom de sa faction.",
     "trigger": "Carte « Dernière ligne droite » (vendredi 18 h, heure de Paris)."},
    {"key": "UPDATE", "input": ["version", "headline"], "label": "Mise à jour",
     "text": "Update {version} is out: {headline}",
     "params": ["version", "headline"], "perPlayer": [], "launch": "open=play",
     "audience": "Joueurs venus dans les 30 derniers jours.",
     "trigger": "Manuel, depuis cet écran, après une mise à jour."},
    {"key": "COMEBACK", "input": [], "label": "Retour des inactifs",
     "text": "Your squad misses you. Your return bonus is waiting.",
     "params": [], "perPlayer": [], "launch": "open=play",
     "audience": "Joueurs absents depuis 7 à 30 jours, au plus une fois par semaine chacun.",
     "trigger": "Carte hebdomadaire de l'Accueil."},
]
BY_KEY = {c["key"]: c for c in CATALOGUE}
# Ecran ouvert au Hub par chaque launch_data (NotificationServer.server.luau, ROUTES).
SCREENS = {"open=war": "Faction War", "open=ranked": "Ranked", "open=play": "Jouer", "open=crates": "Caisses"}
PRIORITY = [c["key"] for c in CATALOGUE]
SAMPLE = {"rank": "3", "gold": "12,500", "season": "12", "faction": "Rainor", "event": "Double XP",
          "hours": "24", "version": "0.9", "headline": "New map and ranked rewards"}


def render(text: str, params: dict) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: str(params.get(m.group(1), m.group(0))), text)


def day_of(ts: int) -> str:
    """Jour UTC : le quota de Roblox est quotidien, on se cale sur UTC."""
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")


def iso_week(ts: int) -> str:
    y, w, _ = datetime.fromtimestamp(ts, timezone.utc).isocalendar()
    return f"{y}-W{w:02d}"


# CONFIGURATION (Asset IDs) -----------------------------------------------------
def load_config() -> dict:
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    ids = data.get("ids") if isinstance(data.get("ids"), dict) else {}
    test = data.get("testUserId")
    return {"ids": {k: str(v) for k, v in ids.items() if k in BY_KEY and v},
            "testUserId": int(test) if str(test or "").isdigit() else None}


def save_config(ids: dict, test_user_id=None) -> dict:
    clean = {}
    for key, value in (ids or {}).items():
        if key not in BY_KEY:
            raise NotifyError(f"Notification inconnue : {key}.")
        value = str(value or "").strip()
        if not value:
            continue
        if not MESSAGE_ID.match(value):
            raise NotifyError(f"{key} : l'Asset ID copié depuis le Creator Hub ne contient que des chiffres, "
                              "des lettres et des tirets.")
        clean[key] = value
    test = str(test_user_id or "").strip()
    if test and not test.isdigit():
        raise NotifyError("Compte de test : un userId numérique.")
    data = {"ids": clean, "testUserId": int(test) if test else None}
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(CONFIG_FILE)
    return load_config()


def configured() -> set[str]:
    return set(load_config()["ids"])


# LECTURES DU JEU (remplacables en test) --------------------------------------
def activity_store() -> str:
    return config.datastore_name(ACTIVITY_BASE)


def read_seen(min_age_h: int, max_age_h: int, now: int) -> tuple[dict[int, int], str | None]:
    """Joueurs dont la derniere arrivee au Hub date de [min_age_h, max_age_h] heures.
    Renvoie ({userId: heure Unix}, erreur). L'index ne garde que la DERNIERE arrivee."""
    now_h = now // HOUR
    lo, hi = now_h - max_age_h, now_h - min_age_h
    base = (f"{roblox_api.OPEN_CLOUD}/ordered-data-stores/v1/universes/{config.ROBLOX_UNIVERSE_ID}"
            f"/orderedDataStores/{urllib.parse.quote(activity_store(), safe='')}/scopes/global/entries")
    out: dict[int, int] = {}
    token = None
    for _ in range(400):
        params = {"max_page_size": 100, "order_by": "desc", "filter": f"entry >= {lo} && entry <= {hi}"}
        if token:
            params["page_token"] = token
        try:
            data = roblox_api._oc_request("GET", f"{base}?{urllib.parse.urlencode(params)}") or {}
        except roblox_api.RobloxError as exc:
            if "404" in str(exc):
                return out, None          # index jamais ecrit : audience vide, pas une panne
            return out, str(exc)
        for e in data.get("entries") or []:
            uid = str(e.get("id") or "")
            if uid.isdigit():
                out[int(uid)] = int(e.get("value") or 0)
                if len(out) >= MAX_AUDIENCE:
                    return out, f"Audience plafonnée à {MAX_AUDIENCE} joueurs."
        token = data.get("nextPageToken")
        if not token:
            break
    return out, None


def read_contributors(week: int) -> tuple[dict[int, str], str | None]:
    """Joueurs presents au classement de guerre d'une semaine, avec leur faction."""
    out: dict[int, str] = {}
    err = None
    for faction in config.FACTIONS:
        ids, e = roblox_api.ordered_all_ids(config.datastore_name(f"FWLB_w{week}_{faction}"), MAX_AUDIENCE)
        err = err or e
        for uid in ids:
            out.setdefault(uid, faction)
    return out, err


def read_payout(payout_id: str | None) -> dict | None:
    index = ranked_rewards._read_index()
    if not payout_id:
        payout_id = next((e.get("id") for e in index if isinstance(e, dict) and e.get("id")), None)
    if not payout_id:
        return None
    doc = roblox_api.datastore_get(config.FW_DATASTORE, f"ranked_payout_{payout_id}")
    return doc if isinstance(doc, dict) else None


def read_ranked_reserve(week: int) -> tuple[set[int], bool]:
    """Joueurs a garder pour RANKED_REWARD : le top ranked tant que la semaine n'est pas versee.
    Renvoie (ids, deja_verse)."""
    index = ranked_rewards._read_index()
    if any(isinstance(e, dict) and e.get("week") == week for e in index):
        return set(), True
    try:
        rows = ranked_rewards.preview(25).get("rows") or []
    except Exception:                                         # noqa: BLE001
        rows = []
    return {int(r["userId"]) for r in rows if str(r.get("userId", "")).isdigit()}, False


READERS = {
    "seen": read_seen,
    "contributors": read_contributors,
    "payout": read_payout,
    "ranked_reserve": read_ranked_reserve,
    "archive": lambda week: roblox_api.faction_war_archive(week),
    "comeback_recent": lambda now: db.notified_since("COMEBACK", now - 7 * 86400),
    "today": lambda day, ids: db.notified_on(day, ids),
}


# AUDIENCES -------------------------------------------------------------------
def _clean_params(entry: dict, given: dict) -> dict:
    out = {}
    for p in entry["params"]:
        if p in entry["perPlayer"]:
            continue
        value = str(given.get(p, "")).strip()
        if not value:
            raise NotifyError(f"Paramètre « {p} » manquant.")
        if len(value) > PARAM_MAX:
            raise NotifyError(f"« {p} » : {PARAM_MAX} caractères au plus (le texte entier doit rester court).")
        out[p] = value
    return out


def audience(key: str, given: dict | None = None, ref: str | None = None, now: int | None = None,
             readers: dict | None = None) -> dict:
    """Destinataires d'une notification. Ne touche ni Roblox en ecriture ni le registre.

    Renvoie {key, ref, shared (parametres communs), rows [{userId, params}], excluded {raison: n},
    notes, errors}. Leve NotifyError si l'envoi n'a pas de sens (parametre manquant, rien a annoncer).
    """
    if key not in BY_KEY:
        raise NotifyError(f"Notification inconnue : {key}.")
    entry = BY_KEY[key]
    r = {**READERS, **(readers or {})}
    now = int(now or time.time())
    given = dict(given or {})
    week = roblox_api.fw_week_index(now)
    notes: list[str] = []
    errors: list[str] = []
    excluded: dict[str, int] = {}
    rows: list[dict] = []

    if key == "RANKED_REWARD":
        payout = r["payout"](ref)
        if not payout:
            raise NotifyError("Aucun versement ranked trouvé : rien à annoncer.")
        ref = str(payout.get("id") or ref or "")
        shared = {}
        for uid, e in (payout.get("entries") or {}).items():
            if str(uid).isdigit() and isinstance(e, dict):
                rows.append({"userId": int(uid), "params": {"rank": str(int(e.get("rank") or 0)),
                                                            "gold": f"{int(e.get('gold') or 0):,}"}})  # texte anglais : 12,000
        rows.sort(key=lambda x: int(x["params"]["rank"]))
        notes.append(f"Versement {ref}, semaine {int(payout.get('week') or 0) + 1}.")

    elif key == "SEASON_RESULT":
        closed = int(given.get("week", week - 1))
        arch = r["archive"](closed)
        winner = given.get("faction") or (arch or {}).get("winner")
        if not winner:
            raise NotifyError(f"La saison {closed + 1} n'est pas encore close : aucun gagnant connu.")
        shared = _clean_params(entry, {"season": closed + 1, "faction": winner})
        ref = ref or f"w{closed}"
        contrib, err = r["contributors"](closed)
        if err:
            errors.append(f"Classements de guerre : {err}")
        reserve, paid = r["ranked_reserve"](closed)
        kept = [uid for uid in contrib if uid in reserve]
        if kept:
            excluded["gardés pour RANKED_REWARD (ranked pas encore versé)"] = len(kept)
        rows = [{"userId": uid, "params": {}} for uid in contrib if uid not in reserve]

    elif key == "SEASON_ENDING":
        shared = _clean_params(entry, {"season": week + 1})
        ref = ref or f"w{week}"
        contrib, err = r["contributors"](week)
        if err:
            errors.append(f"Classements de guerre : {err}")
        recent, err = r["seen"](0, 24, now)
        if err:
            errors.append(f"Index d'activité : {err}")
        here = [uid for uid in contrib if uid in recent]
        if here:
            excluded["venus dans les dernières 24 h"] = len(here)
        rows = [{"userId": uid, "params": {"faction": f}} for uid, f in contrib.items() if uid not in recent]

    else:
        windows = {"EVENT_LIVE": (48, 14 * 24), "UPDATE": (0, 30 * 24), "COMEBACK": (7 * 24, 30 * 24)}
        lo, hi = windows[key]
        shared = _clean_params(entry, given)
        if key == "EVENT_LIVE":
            if not str(shared["hours"]).isdigit() or not 1 <= int(shared["hours"]) <= 336:
                raise NotifyError("« hours » : un nombre d'heures entre 1 et 336.")
            ref = ref or f"event:{shared['event']}:{day_of(now)}"
        elif key == "UPDATE":
            ref = ref or f"update:{shared['version']}"
        else:
            ref = ref or iso_week(now)
        seen, err = r["seen"](lo, hi, now)
        if err:
            errors.append(f"Index d'activité : {err}")
        ids = list(seen)
        if key == "COMEBACK":
            recent = r["comeback_recent"](now)
            skip = [u for u in ids if u in recent]
            if skip:
                excluded["déjà relancés cette semaine"] = len(skip)
            ids = [u for u in ids if u not in recent]
        rows = [{"userId": uid, "params": {}} for uid in sorted(ids, key=lambda u: -seen[u])]
        if not seen and not err:
            notes.append("L'index d'activité ne contient personne dans cette fenêtre. Il se remplit à chaque "
                         "arrivée au Hub, une fois le lot 4 publié en jeu.")

    if len(rows) > MAX_AUDIENCE:
        excluded["au-delà du plafond"] = len(rows) - MAX_AUDIENCE
        rows = rows[:MAX_AUDIENCE]
    return {"key": key, "ref": ref, "shared": shared, "rows": rows, "excluded": excluded,
            "notes": notes, "errors": errors}


def preview(key: str, given: dict | None = None, ref: str | None = None, now: int | None = None,
            readers: dict | None = None) -> dict:
    """Ce qui partirait : audience, deja servis aujourd'hui, texte rendu, avertissements."""
    return _plan(key, given, ref, now, readers)[1]


def _plan(key: str, given: dict | None, ref: str | None, now: int | None, readers: dict | None) -> tuple[dict, dict]:
    now = int(now or time.time())
    entry = BY_KEY.get(key) or {}
    aud = audience(key, given, ref, now, readers)
    r = {**READERS, **(readers or {})}
    cfg = load_config()
    day = day_of(now)
    ids = [x["userId"] for x in aud["rows"]]
    served = r["today"](day, ids) if ids else set()
    to_send = [x for x in aud["rows"] if x["userId"] not in served]
    sample_params = {**SAMPLE, **aud["shared"], **(to_send[0]["params"] if to_send else {})}
    blockers, warnings = [], []
    if key not in cfg["ids"]:
        blockers.append("Asset ID absent : crée le texte dans le Creator Hub et colle son ID dans Notifications.")
    if not (config.ROBLOX_OPENCLOUD_KEY and config.ROBLOX_UNIVERSE_ID):
        blockers.append("Clé Open Cloud absente.")
    if not to_send:
        blockers.append("Personne à notifier." if not aud["rows"] else "Tous les destinataires ont déjà reçu "
                        "une notification aujourd'hui (UTC).")
    prior = [c for c in db.campaigns(5, key, aud["ref"]) if c["state"] in ("running", "done")]
    if prior:
        blockers.append(f"Déjà envoyée pour ce sujet ({aud['ref']}) le "
                        f"{datetime.fromtimestamp(prior[0]['at']).strftime('%d/%m à %H:%M')}.")
    if _running():
        blockers.append("Une autre campagne est en cours : attends sa fin ou arrête-la.")
    warnings += aud["errors"]
    return aud, {
        "key": key, "label": entry.get("label"), "ref": aud["ref"], "shared": aud["shared"],
        "text": render(entry.get("text", ""), sample_params), "launch": entry.get("launch"),
        "audience": len(aud["rows"]), "alreadyToday": len(aud["rows"]) - len(to_send),
        "toSend": len(to_send), "excluded": aud["excluded"], "notes": aud["notes"],
        "warnings": warnings, "blockers": blockers,
        "sample": [x["userId"] for x in to_send[:8]],
        "minutes": round(len(to_send) * SEND_INTERVAL_S / 60, 1),
    }


# ENVOI -----------------------------------------------------------------------
_run_lock = threading.Lock()
_current: dict = {"id": None, "stop": False}


def _running() -> bool:
    return _current["id"] is not None


def _body(message_id: str, params: dict, launch: str, category: str) -> bytes:
    # snake_case : c'est la forme qu'acceptait deja l'ancien envoi ranked en production.
    payload = {"type": "MOMENT", "message_id": message_id,
               "join_experience": {"launch_data": launch[:LAUNCH_MAX]},
               "analytics_data": {"category": category}}
    if params:
        payload["parameters"] = {k: {"string_value": str(v)} for k, v in params.items()}
    return json.dumps({"source": {"universe": f"universes/{config.ROBLOX_UNIVERSE_ID}"},
                       "payload": payload}).encode("utf-8")


def send_one(user_id: int, message_id: str, params: dict, launch: str, category: str) -> tuple[int, str]:
    """Un envoi. Renvoie (code HTTP, detail) ; 0 = reseau injoignable."""
    req = urllib.request.Request(API.format(uid=int(user_id)), data=_body(message_id, params, launch, category),
                                 method="POST", headers={"x-api-key": config.ROBLOX_OPENCLOUD_KEY,
                                                         "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, ""
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        try:
            detail = json.loads(detail).get("message") or detail
        except ValueError:
            pass
        return exc.code, detail
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return 0, str(getattr(exc, "reason", exc))[:200]


def explain(code: int, detail: str) -> str:
    if code == 403:
        return ("Droit manquant : ajoute « User Notifications → Write » à la clé Open Cloud "
                "(section des droits utilisateur, distincte des droits d'univers). " + detail[:120])
    if code == 400:
        return ("Requête refusée : les paramètres envoyés ne correspondent pas au texte du Creator Hub, "
                "ou l'Asset ID est faux. " + detail[:160])
    if code == 404:
        return "Asset ID introuvable sur cette expérience : recopie-le depuis le Creator Hub. " + detail[:120]
    if code == 401:
        return "Clé Open Cloud invalide ou expirée."
    return f"HTTP {code} : {detail[:160] or 'sans détail'}"


def start(key: str, given: dict | None = None, ref: str | None = None, card: str | None = None,
          sender=None, sleep=time.sleep, readers: dict | None = None) -> dict:
    """Cree la campagne et l'envoie en tache de fond. Leve NotifyError si l'apercu bloque."""
    aud, p = _plan(key, given, ref, None, readers)
    if p["blockers"]:
        raise NotifyError(" ".join(p["blockers"]))
    cfg = load_config()
    entry = BY_KEY[key]
    with _run_lock:
        if _running():
            raise NotifyError("Une autre campagne est en cours.")
        cid = db.add_campaign(key, aud["ref"], aud["shared"], card, len(aud["rows"]))
        _current.update(id=cid, stop=False)
    job = {"id": cid, "key": key, "messageId": cfg["ids"][key], "launch": entry["launch"],
           "category": entry["label"], "shared": aud["shared"], "rows": aud["rows"]}
    t = threading.Thread(target=_run, args=(job, sender or send_one, sleep), daemon=True, name=f"notify-{cid}")
    t.start()
    return {"ok": True, "campaign": cid, "ref": aud["ref"], "total": len(aud["rows"]), "toSend": p["toSend"]}


def _run(job: dict, sender, sleep) -> None:
    cid = job["id"]
    counts = {"sent": 0, "throttled": 0, "skipped": 0, "failed": 0}
    state, error = "done", None
    in_429 = fails = 0
    try:
        for i, row in enumerate(job["rows"]):
            if _current["stop"]:
                state, error = "stopped", "Arrêtée depuis le Command Center."
                break
            uid = row["userId"]
            day = day_of(int(time.time()))
            if not db.add_notified(uid, day, job["key"], "pending", cid):
                counts["skipped"] += 1          # deja servi aujourd'hui (autre campagne, ou test)
                continue
            code, detail = sender(uid, job["messageId"], {**job["shared"], **row["params"]},
                                  job["launch"], job["category"])
            if 200 <= code < 300:
                counts["sent"] += 1
                in_429 = fails = 0
                _set_status(uid, day, "sent")
            elif code == 429:
                # Quota du joueur deja consomme, ou limite de debit de la cle : on ne peut pas
                # distinguer. Isole = joueur deja servi ; en serie = pause, pour reprendre plus tard.
                counts["throttled"] += 1
                in_429 += 1
                _set_status(uid, day, "throttled")
                if in_429 >= THROTTLE_PAUSE:
                    state, error = "paused", ("Roblox limite les envois (429 en série). Relance la campagne "
                                              "plus tard : les joueurs déjà servis seront sautés.")
                    break
                sleep(min(10, 2 * in_429))
            elif code in (400, 401, 403, 404):
                db.release_notified(uid, day, cid)
                counts["failed"] += 1
                state, error = "failed", explain(code, detail)
                break
            else:
                db.release_notified(uid, day, cid)
                counts["failed"] += 1
                fails += 1
                if fails >= FAIL_STOP:
                    state, error = "failed", f"{fails} erreurs d'affilée. Dernière : {explain(code, detail)}"
                    break
            if i % 10 == 0:
                db.update_campaign(cid, **counts)
            sleep(SEND_INTERVAL_S)
    except Exception as exc:                                  # noqa: BLE001
        state, error = "failed", f"Erreur interne : {exc}"
    finally:
        db.update_campaign(cid, **counts, state=state, error=error, finished_at=int(time.time()))
        db.audit("notify_done", job["key"], {"campaign": cid, **counts, "state": state, "error": error},
                 state == "done")
        with _run_lock:
            _current.update(id=None, stop=False)


def _set_status(uid: int, day: str, status: str) -> None:
    with db.connect() as con:
        con.execute("UPDATE notified SET status = ? WHERE user_id = ? AND day = ?", (status, int(uid), day))


def stop() -> dict:
    if not _running():
        raise NotifyError("Aucune campagne en cours.")
    _current["stop"] = True
    return {"ok": True, "campaign": _current["id"]}


def test(key: str, user_id: int | None = None, given: dict | None = None) -> dict:
    """Envoie le texte a UN compte (le tien) avec des valeurs d'exemple. Consomme son jour."""
    if key not in BY_KEY:
        raise NotifyError(f"Notification inconnue : {key}.")
    cfg = load_config()
    uid = int(user_id or cfg["testUserId"] or 0)
    if not uid:
        raise NotifyError("Renseigne d'abord le compte de test (ton userId).")
    if key not in cfg["ids"]:
        raise NotifyError("Asset ID absent pour ce texte.")
    entry = BY_KEY[key]
    params = {p: str((given or {}).get(p) or SAMPLE.get(p, p)) for p in entry["params"]}
    code, detail = send_one(uid, cfg["ids"][key], params, entry["launch"], f"{entry['label']} (test)")
    day = day_of(int(time.time()))
    if 200 <= code < 300:
        db.add_notified(uid, day, key, "test", None)
        return {"ok": True, "userId": uid, "text": render(entry["text"], params),
                "note": "Envoyée. Elle arrive dans les notifications Roblox du compte (site ou appli), "
                        "seulement s'il a 13 ans ou plus et a accepté les notifications de Shroud War."}
    if code == 429:
        return {"ok": False, "userId": uid, "error": "Ce compte a déjà reçu une notification de Shroud War "
                                                    "aujourd'hui (UTC) : réessaie demain, ou avec un autre compte."}
    return {"ok": False, "userId": uid, "error": explain(code, detail)}


# VUE -------------------------------------------------------------------------
def overview() -> dict:
    cfg = load_config()
    now = int(time.time())
    day = day_of(now)
    campaigns = db.campaigns(30)
    for c in campaigns:
        c["label"] = BY_KEY.get(c["key"], {}).get("label", c["key"])
    return {
        "catalogue": [{**c, "messageId": cfg["ids"].get(c["key"]), "priority": i + 1,
                       "length": len(c["text"]), "screen": SCREENS.get(c["launch"], c["launch"])}
                      for i, c in enumerate(CATALOGUE)],
        "testUserId": cfg["testUserId"],
        "campaigns": campaigns,
        "running": _current["id"],
        "today": {"day": day, "byKey": db.notified_count(day)},
        "activityStore": activity_store(),
        "limits": {"text": TEXT_MAX, "param": PARAM_MAX, "intervalS": SEND_INTERVAL_S},
    }


def readiness() -> dict:
    """Pour les cartes : textes configures et sujets deja envoyes."""
    ids = configured()
    done = {(c["key"], c["ref"]) for c in db.campaigns(200) if c["state"] in ("running", "done")}
    last_comeback = next((c["at"] for c in db.campaigns(1, "COMEBACK") if c["state"] in ("running", "done")), 0)
    return {"ids": sorted(ids), "done": sorted(f"{k}|{r}" for k, r in done), "lastComeback": last_comeback}
