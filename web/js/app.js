//  app.js — amorcage, routage et barre d'etat
import { api, me } from "./api.js";
import { h, mount, toast } from "./ui.js";
import * as V from "./views.js";
import { viewGuide } from "./guide.js";
import { viewArsenal } from "./arsenal.js";
import { viewLive, viewPlayers } from "./live.js";
import { viewTrends } from "./trends.js";
import { viewTodo } from "./todo.js";
import { viewHome } from "./home.js";
import { viewNotify } from "./notify.js";
import { viewAutomations } from "./automations.js";
import { installPalette, openPalette } from "./palette.js";
import { alerts, notifyBrowser } from "./alerts.js";

const main = document.getElementById("main");
const pills = document.getElementById("status-pills");
const pulse = document.getElementById("pulse");
const liveBadge = document.getElementById("live-badge");
const homeBadge = document.getElementById("home-badge");

const VIEWS = {
  home: viewHome,
  live: viewLive,
  todo: viewTodo,
  trends: viewTrends,
  players: viewPlayers,
  security: V.viewSecurity,
  factionwar: V.viewFactionWar,
  ranked: V.viewRanked,
  rewards: V.viewRewards,
  boost: V.viewBoost,
  give: V.viewGive,
  modes: V.viewModes,
  configs: V.viewConfigs,
  arsenal: viewArsenal,
  compose: V.viewCompose,
  templates: V.viewTemplates,
  schedule: V.viewSchedule,
  notify: viewNotify,
  history: V.viewHistory,
  automations: viewAutomations,
  health: V.viewHealth,
  guide: viewGuide,
};
const DEFAULT_VIEW = "home";
const PULSE_MS = 20000;

let currentView = DEFAULT_VIEW;

// Une adresse peut porter une sous-page apres la vue : #guide/pipelines/ancre.
const baseOf = (name) => String(name || "").split("/")[0];

async function show(name) {
  let full = String(name || "");
  if (!VIEWS[baseOf(full)]) full = DEFAULT_VIEW;
  name = baseOf(full);
  currentView = name;
  const hash = decodeURIComponent(location.hash.slice(1));
  if (baseOf(hash) !== name || (full.includes("/") && hash !== full)) history.replaceState(null, "", `#${full}`);
  document.querySelectorAll(".nav-item, .tab[data-view]").forEach((el) =>
    el.classList.toggle("active", el.dataset.view === name));
  setNav(false);
  mount(main, h("div", { class: "empty" }, "Chargement…"));
  try {
    await VIEWS[name](main);
  } catch (e) {
    mount(main,
      h("div", { class: "banner bad" }, `Erreur : ${e.message}`),
      h("div", { class: "muted" }, "Si le serveur ne répond plus, relance-le (python server.py, ou docker compose up -d)."));
  }
  refreshBadge();
}

function renderPills() {
  const s = V.state.status || {};
  const items = [["Discord", s.discord?.ok], ["Open Cloud", s.boostOk !== false]];
  pills.replaceChildren(...items.map(([label, ok]) =>
    h("span", { class: `pill ${ok ? "ok" : "bad"}`, title: ok ? "Connecté" : "Voir Santé" }, label)));
}

//  BARRE D'ETAT : joueurs par place, serveurs, alertes. Lue dans le cache du veilleur.
let events = [];
let lastEventId = 0;
let lastLive = null;

function refreshBadge() {
  const n = alerts.unseen(events).length;
  liveBadge.replaceChildren(...(n ? [h("span", { class: "nav-badge", title: `${n} alerte(s) non vue(s)` }, String(n))] : []));
  renderPulse();
}

function pulseItem(view, valueText, unit, opts = {}) {
  const b = h("button", { class: `pulse-item ${opts.alert ? "alert" : ""}`, title: opts.title || "" }, [
    opts.dot ? h("span", { class: `pulse-dot ${opts.dot}` }) : null,
    h("span", {}, opts.label || ""),
    h("b", {}, valueText),
    unit ? h("span", { class: "unit" }, unit) : null,
  ]);
  b.addEventListener("click", () => show(view));
  return b;
}

function renderPulse() {
  const s = lastLive?.summary;
  // Alertes = problemes EN COURS (serveur muet ou lent). Les evenements non vus, eux,
  // s'affichent en pastille sur Live.
  const servers = lastLive?.servers || [];
  const dead = servers.filter((x) => x.stale).length;
  const slow = servers.filter((x) => !x.stale && typeof x.fps === "number" && x.fps < 30).length;
  if (!s) {
    pulse.replaceChildren(pulseItem("live", "—", "", { label: "Jeu", dot: "", title: "Registre live pas encore lu" }));
    return;
  }
  const modes = Object.entries(s.playersByMode || {}).map(([m, n]) => `${m.toLowerCase()} ${n}`).join(", ");
  pulse.replaceChildren(
    pulseItem("live", String(s.players ?? 0), "en jeu", {
      label: "", dot: lastLive.error ? "down" : "live",
      title: lastLive.error ? `Registre illisible : ${lastLive.error}` : "Joueurs connectés, toutes places" }),
    pulseItem("live", String(s.hubPlayers ?? 0), `au Hub, ${s.hubs ?? 0} serv.`, { label: "Hub" }),
    pulseItem("live", String(s.matchPlayers ?? 0), `en match, ${s.matches ?? 0} serv.`, {
      label: "Matchs", title: modes ? `Par mode : ${modes}` : "Aucun match" }),
    pulseItem("live", String(dead + slow), dead + slow === 1 ? "alerte" : "alertes", {
      label: "", alert: dead > 0,
      title: dead + slow ? `${dead} serveur(s) muet(s), ${slow} lent(s)` : "Aucun serveur en difficulté" }),
  );
}

async function pollPulse() {
  try {
    lastLive = await api.live();
    const snap = await api.liveEvents(lastEventId);
    const fresh = snap.events || [];
    if (fresh.length) {
      const firstLoad = lastEventId === 0;
      events = events.concat(fresh).slice(-300);
      lastEventId = fresh[fresh.length - 1].id;
      // Un crash survenu pendant que la page est ouverte : notice + notification systeme.
      for (const e of fresh) {
        if (e.level === "crit" && e.id > alerts.lastNotified()) {
          if (!firstLoad) {
            toast(e.text, "bad");
            notifyBrowser(e);
          }
          alerts.markNotified(e.id);
        }
      }
    }
  } catch { /* serveur local injoignable : la barre garde son dernier etat */ }
  refreshBadge();
}

//  ACCUEIL : pastille du nombre de cartes importantes, et notice quand une nouvelle carte
//  importante apparait (fin de saison, triche, tache devenue possible...). Le serveur garde
//  son calcul 30 s : relire toutes les 2 min ne coute presque rien.
const HOME_MS = 2 * 60 * 1000;
const HOME_SEEN_KEY = "cc.home.notified";

function renderHome(data) {
  const urgent = (data?.cards || []).filter((c) => c.prio === "crit" || c.prio === "high");
  const n = (data?.cards || []).length;
  document.getElementById("tab-home-badge").textContent = n ? String(n) : "";
  homeBadge.replaceChildren(...(n ? [h("span", {
    class: `nav-badge${urgent.length ? "" : " soft"}`,
    title: `${n} carte(s) à traiter, dont ${urgent.length} importante(s)`,
  }, String(n))] : []));
  let seen = [];
  try { seen = JSON.parse(localStorage.getItem(HOME_SEEN_KEY) || "[]"); } catch { /* stockage indisponible */ }
  const fresh = urgent.filter((c) => !seen.includes(c.key));
  if (fresh.length && seen.length + fresh.length > 0 && localStorage.getItem(HOME_SEEN_KEY) !== null) {
    for (const c of fresh.slice(0, 3)) {
      toast(c.title, c.prio === "crit" ? "bad" : "ok");
      notifyBrowser({ id: `home-${c.key}`, server: "Accueil", text: c.title });
    }
  }
  try { localStorage.setItem(HOME_SEEN_KEY, JSON.stringify([...new Set([...seen, ...urgent.map((c) => c.key)])].slice(-300))); } catch { /* idem */ }
}

async function pollHome() {
  try { renderHome(await api.home()); } catch { /* serveur local injoignable */ }
}
window.addEventListener("cc:home", (e) => renderHome(e.detail));

// La vue Live signale qu'elle a affiche les alertes (evenement DOM : pas d'import croise).
window.addEventListener("cc:alerts-seen", refreshBadge);

//  MENU (telephone) : la barre laterale devient un tiroir.
const navEl = document.getElementById("nav");
const menuBtn = document.getElementById("menu-btn");
function setNav(open) {
  document.body.classList.toggle("nav-open", open);
  menuBtn.setAttribute("aria-expanded", String(open));
}
menuBtn.addEventListener("click", () => setNav(!document.body.classList.contains("nav-open")));
document.getElementById("tab-menu").addEventListener("click", () => setNav(!document.body.classList.contains("nav-open")));
document.getElementById("nav-backdrop").addEventListener("click", () => setNav(false));
document.addEventListener("keydown", (e) => { if (e.key === "Escape") setNav(false); });
document.querySelectorAll(".tab[data-view]").forEach((el) => el.addEventListener("click", () => show(el.dataset.view)));

//  COMPTE : qui est connecte, avec quel role ; deconnexion en mode heberge.
async function renderUser() {
  const who = await me();
  const chip = document.getElementById("user-chip");
  if (!who) return;
  document.body.dataset.role = who.role;
  navEl.querySelectorAll("[data-admin]").forEach((el) => { el.hidden = who.role !== "admin"; });
  if (who.local) {
    chip.replaceChildren(h("span", { class: "pill ok", title: "Mode local : pas de connexion, cette machine seulement" }, "Local"));
    return;
  }
  const out = h("button", { class: "btn ghost" }, "Se déconnecter");
  out.addEventListener("click", async () => {
    try { await api.logout(); } catch { /* deja deconnecte */ }
    location.href = "/login";
  });
  chip.replaceChildren(h("details", { class: "user-menu" }, [
    h("summary", { title: `${who.user.name} · ${who.roleLabel}` }, [
      who.user.avatar ? h("img", { src: who.user.avatar, alt: "", width: "24", height: "24" })
        : h("span", { class: "avatar" }, who.user.name.slice(0, 1).toUpperCase()),
      h("span", { class: "user-name" }, who.user.name),
    ]),
    h("div", { class: "user-pop" }, [
      h("div", {}, h("b", {}, who.user.name)), h("div", { class: "muted" }, who.roleLabel), out,
    ]),
  ]));
}

//  AMORCAGE : chaque bloc echoue seul, un Discord KO n'empeche pas d'ouvrir Live.
async function bootstrap() {
  try {
    V.state.status = await api.status();
  } catch (e) {
    toast(`Serveur injoignable : ${e.message}`, "bad");
  }
  renderPills();

  const safe = async (fn, fallback) => { try { return await fn(); } catch { return fallback; } };
  const [ch, ro, tp, vr] = await Promise.all([
    safe(() => api.channels(), { channels: [] }),
    safe(() => api.roles(), { roles: [] }),
    safe(() => api.templates(), { templates: [] }),
    safe(() => api.vars(), { catalog: [] }),
  ]);
  V.state.channels = ch.channels;
  V.state.roles = ro.roles;
  V.state.templates = tp.templates;
  V.state.vars = vr.catalog;
}

document.querySelectorAll(".nav-item").forEach((el) =>
  el.addEventListener("click", () => show(el.dataset.view)));

window.addEventListener("hashchange", () => {
  const name = decodeURIComponent(location.hash.slice(1));
  if (!name) return;
  if (baseOf(name) !== currentView) show(name);
  else if (name.includes("/")) window.dispatchEvent(new CustomEvent(`cc:${currentView}-route`));
});
installPalette();
document.getElementById("palette-btn").addEventListener("click", openPalette);
document.getElementById("refresh-btn").addEventListener("click", async () => {
  await bootstrap();
  await pollPulse();
  await show(currentView);
  toast("Actualisé.");
});

renderPulse();
await renderUser();
try {
  const next = sessionStorage.getItem("cc.next");
  if (next) { sessionStorage.removeItem("cc.next"); history.replaceState(null, "", next); }
} catch { /* stockage indisponible */ }
await bootstrap();
await pollPulse();
setInterval(() => { if (!document.hidden) pollPulse(); }, PULSE_MS);
pollHome();
setInterval(() => { if (!document.hidden) pollHome(); }, HOME_MS);
await show(location.hash.slice(1) || DEFAULT_VIEW);
