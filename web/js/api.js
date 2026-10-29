//  api.js — acces au serveur local
//  Le navigateur ne detient AUCUN secret : il envoie des intentions,
//  le serveur local (server.py) fait les appels Discord / Roblox.

async function req(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  let data;
  try {
    data = await res.json();
  } catch {
    throw new Error(`Reponse illisible du serveur (HTTP ${res.status})`);
  }
  if (!res.ok || data.error) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

const get = (path) => req(path);
const post = (path, body) => req(path, { method: "POST", body: JSON.stringify(body) });

export const api = {
  status: () => get("/api/status"),
  permissions: () => get("/api/permissions"),
  live: (force = false) => get(`/api/live${force ? "?force=1" : ""}`),
  docs: () => get("/api/docs"),
  cmd: (payload) => post("/api/cmd", payload),
  cmdStatus: (id) => get(`/api/cmd?id=${encodeURIComponent(id)}`),
  editPlan: (payload) => post("/api/edit/plan", payload),
  editApply: (token) => post("/api/edit/apply", { token }),
  editUndo: (backupId) => post("/api/edit/undo", { backupId }),
  edits: (userId) => get(`/api/edits?userId=${userId}`),
  ban: (payload) => post("/api/ban", payload),
  banWave: (payload) => post("/api/ban/wave", payload),
  unban: (userId) => post("/api/unban", { userId }),
  bans: () => get("/api/bans"),
  restart: (payload) => post("/api/restart", payload),
  home: (force = false) => get(`/api/home${force ? "?force=1" : ""}`),
  cardPreview: (key, action) => post("/api/cards/preview", { key, action }),
  cardAct: (key, action) => post("/api/cards/act", { key, action }),
  cardState: (key, state, until = null) => post("/api/cards/state", { key, state, until }),
  journal: (limit = 300) => get(`/api/journal?limit=${limit}`),
  todo: (force = false) => get(`/api/todo${force ? "?force=1" : ""}`),
  notify: () => get("/api/notify"),
  notifySaveConfig: (ids, testUserId) => post("/api/notify/config", { ids, testUserId }),
  notifyPreview: (payload) => post("/api/notify/preview", payload),
  notifySend: (payload) => post("/api/notify/send", payload),
  notifyTest: (key, userId) => post("/api/notify/test", { key, userId }),
  notifyStop: () => post("/api/notify/stop", {}),
  markTodo: (id, done) => post("/api/todo", { id, done }),
  trends: (hours = 24, force = false) => get(`/api/trends?hours=${hours}${force ? "&force=1" : ""}`),
  liveEvents: (since = 0) => get(`/api/live/events?since=${since}`),
  contracts: (force = false) => get(`/api/live/contracts${force ? "?force=1" : ""}`),
  playerSearch: (q) => get(`/api/player/search?q=${encodeURIComponent(q)}`),
  player: (userId, force = false) => get(`/api/player?userId=${userId}${force ? "&force=1" : ""}`),
  playerInventory: (userId, force = false) => get(`/api/player/inventory?userId=${userId}${force ? "&force=1" : ""}`),
  playerStash: (userId, force = false) => get(`/api/player/stash?userId=${userId}${force ? "&force=1" : ""}`),
  honeypots: (limit = 50) => get(`/api/security/honeypots?limit=${limit}`),
  honeypot: (userId) => get(`/api/security/honeypot?userId=${encodeURIComponent(userId)}`),
  channels: () => get("/api/channels"),
  roles: () => get("/api/roles"),
  vars: () => get("/api/vars"),

  arsenal: () => get("/api/arsenal"),
  saveArsenal: (data) => post("/api/arsenal", data),
  setArsenalLevel: (name, level) => post("/api/arsenal/level", { name, level }),
  setOutfitLevel: (id, level) => post("/api/arsenal/outfit-level", { id, level }),

  templates: () => get("/api/templates"),
  saveTemplates: (templates) => post("/api/templates", { templates }),

  schedule: () => get("/api/schedule"),
  saveSchedule: (schedule) => post("/api/schedule", { schedule }),

  history: () => get("/api/history"),

  preview: (payload) => post("/api/preview", payload),
  announce: (payload) => post("/api/announce", payload),

  announceFactions: () => post("/api/faction/announce", {}),
  factionWar: (week) => get(`/api/factionwar${week != null ? `?week=${week}` : ""}`),
  ranked: (limit = 20) => get(`/api/ranked?limit=${limit}`),
  rankedPreview: () => get("/api/ranked/preview"),
  payRanked: (payload) => post("/api/ranked/pay", payload),
  saveRankedTiers: (tiers) => post("/api/ranked/pay", { action: "tiers", tiers }),

  rewards: () => get("/api/rewards"),
  saveRewards: (payload) => post("/api/rewards", payload),
  resetRewards: () => post("/api/rewards", { action: "reset" }),

  settings: () => get("/api/settings"),
  saveSettings: (settings) => post("/api/settings", { settings }),
  boost: (payload) => post("/api/boost", payload),

  givePreview: (payload) => post("/api/give/preview", payload),
  give: (payload) => post("/api/give", payload),
  wipe: (payload) => post("/api/wipe", payload),

  configs: () => get("/api/configs"),
  configsOverwrite: (values) => post("/api/configs", { action: "overwrite", values }),
  configsPublish: () => post("/api/configs", { action: "publish" }),

  modes: () => get("/api/modes"),
  saveModes: (values) => post("/api/modes", { action: "save", values }),
  resetModes: () => post("/api/modes", { action: "reset" }),

  maintScan: (payload) => post("/api/maintenance/scan", payload),
  maintPurge: (userIds) => post("/api/maintenance/purge", { userIds }),
};
