//  alerts.js — suivi des evenements live deja vus, partage entre la barre d'etat et Live.
//  Le dernier evenement vu est garde dans ce navigateur (localStorage) : c'est un confort,
//  le journal lui-meme vit cote serveur (data/live_events.json).

const SEEN_KEY = "cc.live.lastSeenEvent";
const NOTIFIED_KEY = "cc.live.lastNotifiedEvent";

function read(key) {
  try { return Number(localStorage.getItem(key) || 0); } catch { return 0; }
}
function write(key, value) {
  try { localStorage.setItem(key, String(value)); } catch { /* stockage indisponible */ }
}

export const alerts = {
  lastSeen: () => read(SEEN_KEY),
  markSeen(id) { if (id > read(SEEN_KEY)) write(SEEN_KEY, id); },
  lastNotified: () => read(NOTIFIED_KEY),
  markNotified(id) { if (id > read(NOTIFIED_KEY)) write(NOTIFIED_KEY, id); },
  /** Evenements qui demandent l'attention : crashs et avertissements non vus. */
  unseen(events) {
    const seen = read(SEEN_KEY);
    return events.filter((e) => e.id > seen && (e.level === "crit" || e.level === "warn"));
  },
};

export function notificationsAvailable() {
  return typeof Notification !== "undefined";
}

/** Notification systeme pour un crash, si l'utilisateur l'a autorisee. */
export function notifyBrowser(event) {
  if (!notificationsAvailable() || Notification.permission !== "granted") return;
  try {
    new Notification(`Shroud War : ${event.server || "serveur"}`, { body: event.text, tag: `cc-${event.id}` });
  } catch { /* certains navigateurs refusent hors contexte securise */ }
}
