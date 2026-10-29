//  live.js — jeu en direct et fiche joueur (lecture seule)
//  Live et Fiches lisent le registre (cache partage de 3 s) toutes les 5 s,
//  seulement tant que l'ecran est affiche. La fiche joueur ne lit l'inventaire et le stash
//  qu'au clic sur leur onglet.
import { api } from "./api.js";
import { h, mount, toast, fmtDuration, fmtDate } from "./ui.js";
import { alerts, notificationsAvailable } from "./alerts.js";
import { backupsDialog, banDialog, drainDialog, editFlow, kickDialog, messageDialog, moneyDialog, restartDialog, unbanDialog } from "./actions.js";

const REFRESH_MS = 5000;
const LOW_FPS = 30;
let pendingPlayer = null;

// Etat de l'ecran Live, garde entre deux rafraichissements et deux visites.
const ui = { filter: "all", query: "", selected: null, checked: new Set(), auto: true };

/** Ouvre la fiche d'un joueur depuis n'importe quel ecran. */
export function openPlayer(userId) {
  pendingPlayer = String(userId);
  document.querySelector('.nav-item[data-view="players"]')?.click();
}

const tag = (text, cls = "") => h("span", { class: `tag ${cls}` }, text);
const shortId = (id) => String(id || "").slice(0, 8);
const timeOf = (ts) => new Date(ts * 1000).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });

// Compteurs du limiteur DiscordFeed de ce serveur depuis son demarrage.
function discordText(d) {
  if (!d) return "—";
  const parts = [`${d.s ?? 0} envoyé(s)`];
  if (d.d) parts.push(`${d.d} abandonné(s) par le limiteur`);
  if (d.f) parts.push(`${d.f} refusé(s) par Discord`);
  return parts.join(", ");
}

function factionText(f) {
  if (!f) return h("span", { class: "muted" }, "—");
  return h("span", { style: `color:var(--${String(f).toLowerCase()})` }, f);
}

function stateOf(srv) {
  if (srv.stale) return ["dead", "Ne répond plus"];
  if (typeof srv.fps === "number" && srv.fps < LOW_FPS) return ["lag", `Lent, ${srv.fps} FPS`];
  return ["", "En ligne"];
}

function placeName(srv) {
  return srv.kind === "hub" ? "Hub" : (srv.mode ? srv.mode.charAt(0) + srv.mode.slice(1).toLowerCase() : "Match");
}

async function copy(text, done = "Copié.") {
  try { await navigator.clipboard.writeText(text); toast(done); }
  catch { toast("Copie impossible dans ce navigateur.", "bad"); }
}

//  Courbe des joueurs sur 24 h (un point par minute, servi par le veilleur).
function sparkline(points) {
  const W = 300, H = 46;
  if (!points || points.length < 2) {
    return h("div", { class: "muted", style: "margin-top:10px" }, "La courbe se remplit tant que le Command Center tourne.");
  }
  const max = Math.max(1, ...points.map((p) => (p.hub || 0) + (p.match || 0)));
  const t0 = points[0].at, t1 = points[points.length - 1].at || t0 + 1;
  const x = (p) => ((p.at - t0) / Math.max(1, t1 - t0)) * W;
  const y = (v) => H - 2 - (v / max) * (H - 6);
  const line = (key) => points.map((p, i) => `${i ? "L" : "M"}${x(p).toFixed(1)},${y(p[key] || 0).toFixed(1)}`).join("");
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("preserveAspectRatio", "none");
  svg.setAttribute("class", "spark");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", `Joueurs sur ${Math.round((t1 - t0) / 3600)} h, maximum ${max}`);
  svg.innerHTML =
    `<path class="area-hub" d="${line("hub")}L${W},${H}L0,${H}Z"/>` +
    `<path class="line-hub" d="${line("hub")}" vector-effect="non-scaling-stroke"/>` +
    `<path class="line-match" d="${line("match")}" vector-effect="non-scaling-stroke"/>`;
  const peak = points.reduce((a, p) => ((p.hub || 0) + (p.match || 0) > (a.hub || 0) + (a.match || 0) ? p : a), points[0]);
  return h("div", {}, [
    svg,
    h("div", { class: "legend" }, [
      h("span", {}, [h("i", { style: "background:var(--accent)" }), "Hub"]),
      h("span", {}, [h("i", { style: "background:var(--info)" }), "Matchs"]),
      h("span", { style: "margin-left:auto" }, `Pic ${max} à ${timeOf(peak.at)}`),
    ]),
  ]);
}

//  LIVE
export async function viewLive(root) {
  const stamp = h("span", { class: "muted" });
  const autoSeg = h("div", { class: "seg", role: "group", "aria-label": "Rafraîchissement" });
  const reloadBtn = h("button", { class: "btn" }, "Relire maintenant");
  const messageAllBtn = h("button", { class: "btn" }, "Message à tous");
  messageAllBtn.addEventListener("click", () => messageDialog({ label: "Tous les joueurs connectés" }));
  const restartBtn = h("button", { class: "btn danger" }, "Redémarrer…");
  restartBtn.addEventListener("click", () => restartDialog());
  const issues = h("div");
  const places = h("div", { class: "places" });
  const listPanel = h("div", { class: "panel" });
  const detailPanel = h("div", { class: "panel" });
  const eventsPanel = h("div", { class: "panel", style: "margin-top:16px" });

  const container = h("div", {}, [
    h("div", { class: "toolbar" }, [h("h2", {}, "Live"), h("div", { class: "spacer" }), stamp, autoSeg, reloadBtn, messageAllBtn, restartBtn]),
    issues, places,
    h("div", { class: "live-grid" }, [h("div", {}, [listPanel]), h("div", {}, [detailPanel, eventsPanel])]),
  ]);
  mount(root, container);

  let data = { servers: [], summary: {} };
  let snap = { events: [], timeline: [], watcher: {} };

  const renderAuto = () => {
    autoSeg.replaceChildren(...[["Auto", true], ["Pause", false]].map(([label, on]) => {
      const b = h("button", { class: ui.auto === on ? "on" : "", title: on ? "Relire toutes les 5 s" : "Figer l'affichage" }, label);
      b.addEventListener("click", () => { ui.auto = on; renderAuto(); });
      return b;
    }));
  };
  renderAuto();

  function renderPlaces() {
    const s = data.summary || {};
    const hubCap = (data.servers || []).filter((x) => x.kind === "hub" && !x.stale)
      .reduce((a, x) => a + (x.maxPlayers || 0), 0);
    const modes = Object.entries(s.playersByMode || {});
    mount(places,
      h("div", { class: "place" }, [
        h("div", { class: "place-name" }, "Hub"),
        h("div", { class: "place-v" }, [String(s.hubPlayers ?? 0), h("small", {}, "joueurs")]),
        h("div", { class: "place-sub" }, [
          h("span", {}, `${s.hubs ?? 0} serveur(s)`),
          hubCap ? h("span", {}, `capacité ${hubCap}`) : null,
        ]),
      ]),
      h("div", { class: "place" }, [
        h("div", { class: "place-name" }, "Matchs"),
        h("div", { class: "place-v" }, [String(s.matchPlayers ?? 0), h("small", {}, "joueurs")]),
        h("div", { class: "place-sub" }, modes.length
          ? modes.map(([m, n]) => h("span", {}, `${m.charAt(0) + m.slice(1).toLowerCase()} : ${n} joueur(s), ${s.byMode?.[m] ?? 0} match(s)`))
          : [h("span", {}, "Aucun match en cours")]),
      ]),
      h("div", { class: "place" }, [
        h("div", { class: "place-name" }, "Évolution sur 24 h"),
        sparkline(snap.timeline),
      ]),
    );
  }

  function filtered() {
    const q = ui.query.trim().toLowerCase();
    return (data.servers || []).filter((srv) => {
      if (ui.filter === "hub" && srv.kind !== "hub") return false;
      if (ui.filter === "match" && srv.kind === "hub") return false;
      if (ui.filter === "alert" && !stateOf(srv)[0]) return false;
      if (!q) return true;
      const hay = [srv.jobId, srv.map, srv.mode, srv.phase, ...(srv.players || []).map((p) => `${p.n || ""} ${p.u}`)]
        .join(" ").toLowerCase();
      return hay.includes(q);
    });
  }

  function renderList() {
    const activeSearch = listPanel.querySelector(".search");
    const selection = activeSearch && document.activeElement === activeSearch
      ? [activeSearch.selectionStart, activeSearch.selectionEnd] : null;
    const all = data.servers || [];
    const counts = {
      all: all.length,
      hub: all.filter((s) => s.kind === "hub").length,
      match: all.filter((s) => s.kind !== "hub").length,
      alert: all.filter((s) => stateOf(s)[0]).length,
    };
    const seg = h("div", { class: "seg", role: "tablist" }, [["all", "Tous"], ["hub", "Hubs"], ["match", "Matchs"], ["alert", "Alertes"]]
      .map(([key, label]) => {
        const b = h("button", { class: ui.filter === key ? "on" : "", role: "tab" }, [label, h("span", { class: "n" }, String(counts[key]))]);
        b.addEventListener("click", () => { ui.filter = key; renderList(); });
        return b;
      }));
    const search = h("input", { class: "search", placeholder: "Joueur, map, identifiant", value: ui.query, "aria-label": "Filtrer les serveurs" });
    search.addEventListener("input", () => {
      ui.query = search.value;
      renderList();
    });

    const rows = filtered();
    for (const id of [...ui.checked]) if (!all.some((s) => s.jobId === id)) ui.checked.delete(id);
    const allChecked = rows.length > 0 && rows.every((s) => ui.checked.has(s.jobId));
    const headBox = h("input", { type: "checkbox", "aria-label": "Tout sélectionner", checked: allChecked });
    headBox.addEventListener("change", () => {
      rows.forEach((s) => (headBox.checked ? ui.checked.add(s.jobId) : ui.checked.delete(s.jobId)));
      renderList();
    });

    const body = rows.map((srv) => {
      const players = srv.players || [];
      const [cls, label] = stateOf(srv);
      const box = h("input", { type: "checkbox", "aria-label": `Sélectionner ${shortId(srv.jobId)}`, checked: ui.checked.has(srv.jobId) });
      box.addEventListener("click", (ev) => ev.stopPropagation());
      box.addEventListener("change", () => {
        box.checked ? ui.checked.add(srv.jobId) : ui.checked.delete(srv.jobId);
        renderList();
      });
      const pct = srv.maxPlayers ? Math.min(100, (players.length / srv.maxPlayers) * 100) : 0;
      const tr = h("tr", { class: `${ui.selected === srv.jobId ? "sel" : ""} ${srv.stale ? "stale" : ""}`, tabindex: "0" }, [
        h("td", { style: "width:28px" }, box),
        h("td", {}, h("span", { class: `state ${cls}`, title: label }, placeName(srv))),
        h("td", {}, srv.map || (srv.kind === "hub" ? "" : "?")),
        h("td", {}, srv.phase || ""),
        h("td", {}, h("div", { class: "cap" }, [
          h("span", {}, srv.maxPlayers ? `${players.length}/${srv.maxPlayers}` : String(players.length)),
          srv.maxPlayers ? h("div", { class: "cap-bar" }, h("i", { class: pct >= 90 ? "full" : "", style: `width:${pct}%` })) : null,
        ])),
        h("td", { class: "num" }, fmtDuration(srv.uptime || 0)),
        h("td", { class: "num" }, srv.fps != null ? String(srv.fps) : ""),
        h("td", { class: "num" }, srv.mem != null ? `${srv.mem}` : ""),
        h("td", { class: "num" }, srv.ping != null ? `${srv.ping}` : ""),
        h("td", { class: "num" }, String(srv.placeVersion ?? "")),
        h("td", {}, h("span", { class: "id" }, shortId(srv.jobId))),
      ]);
      const select = () => { ui.selected = srv.jobId; renderList(); renderDetail(); };
      tr.addEventListener("click", select);
      tr.addEventListener("keydown", (ev) => { if (ev.key === "Enter") select(); });
      return tr;
    });

    const checked = all.filter((s) => ui.checked.has(s.jobId));
    const bulk = checked.length ? h("div", { class: "bulkbar" }, [
      h("b", {}, `${checked.length} sélectionné(s)`),
      h("span", { class: "muted" }, `${checked.reduce((a, s) => a + (s.players || []).length, 0)} joueur(s)`),
      h("div", { class: "spacer" }),
      (() => { const b = h("button", { class: "btn" }, "Copier les identifiants"); b.addEventListener("click", () => copy(checked.map((s) => s.jobId).join("\n"), `${checked.length} identifiant(s) copié(s).`)); return b; })(),
      (() => { const b = h("button", { class: "btn" }, "Envoyer un message"); b.addEventListener("click", () => messageDialog({ jobs: checked.map((s) => s.jobId), label: `${checked.length} serveur(s) sélectionné(s)` })); return b; })(),
      (() => { const b = h("button", { class: "btn danger" }, "Vider"); b.addEventListener("click", () => drainDialog(checked)); return b; })(),
      (() => { const b = h("button", { class: "btn ghost" }, "Désélectionner"); b.addEventListener("click", () => { ui.checked.clear(); renderList(); }); return b; })(),
    ]) : null;

    mount(listPanel,
      h("div", { class: "panel-head" }, [h("h3", {}, "Serveurs"), seg, h("div", { style: "flex:1" }), search]),
      bulk,
      data.error ? h("div", { class: "banner bad", style: "margin:12px" }, `Registre illisible : ${data.error}`) : null,
      rows.length
        ? h("table", { class: "srv-table" }, [
            h("thead", {}, h("tr", {}, [h("th", {}, headBox), ...["Place", "Map", "Phase", "Joueurs"].map((x) => h("th", {}, x)),
              ...[["Depuis", ""], ["FPS", "Images par seconde du serveur"], ["Mo", "Mémoire du serveur"], ["Ping", "Ping moyen des joueurs, en ms"], ["Version", ""]]
                .map(([x, t]) => h("th", { class: "num", title: t }, x)), h("th", {}, "Serveur")])),
            h("tbody", {}, body),
          ])
        : h("div", { class: "empty" }, all.length ? "Aucun serveur ne correspond au filtre."
            : "Aucun serveur ouvert. Le registre se remplit dès qu'un joueur lance une place publiée avec CommandCenterBridge."),
    );
    if (selection) {
      search.focus({ preventScroll: true });
      search.setSelectionRange(...selection);
    }
  }

  function renderDetail() {
    const srv = (data.servers || []).find((s) => s.jobId === ui.selected);
    if (!srv) {
      mount(detailPanel, h("div", { class: "panel-head" }, h("h3", {}, "Serveur")),
        h("div", { class: "empty" }, "Sélectionne un serveur pour voir ses joueurs."));
      return;
    }
    const [cls, label0] = stateOf(srv);
    const label = srv.crashReportedAt ? `${label0}, signalé par le jeu` : label0;
    const players = srv.players || [];
    const joinUrl = srv.kind === "hub" && srv.placeId
      ? `https://www.roblox.com/games/start?placeId=${srv.placeId}&gameInstanceId=${encodeURIComponent(srv.jobId)}` : null;
    const copyBtn = h("button", { class: "btn" }, "Copier l'identifiant");
    copyBtn.addEventListener("click", () => copy(srv.jobId));
    mount(detailPanel,
      h("div", { class: "panel-head" }, [h("h3", {}, "Serveur"), h("div", { style: "flex:1" }), h("span", { class: `state ${cls}` }, label)]),
      h("div", { class: "panel-body" }, [
        h("p", { class: "detail-title" }, `${placeName(srv)}${srv.map ? `, ${srv.map}` : ""}`),
        h("dl", { class: "kv" }, [
          h("dt", {}, "Joueurs"), h("dd", {}, srv.maxPlayers ? `${players.length} sur ${srv.maxPlayers}` : String(players.length)),
          h("dt", {}, "Phase"), h("dd", {}, srv.phase || "—"),
          h("dt", {}, "Ouvert depuis"), h("dd", {}, fmtDuration(srv.uptime || 0)),
          h("dt", {}, "FPS serveur"), h("dd", {}, srv.fps != null ? String(srv.fps) : "—"),
          h("dt", {}, "Mémoire"), h("dd", {}, srv.mem != null ? `${srv.mem} Mo` : "—"),
          h("dt", {}, "Temps de frame"), h("dd", {}, srv.hbMs != null ? `${srv.hbMs} ms` : "—"),
          h("dt", {}, "Réseau"), h("dd", {}, srv.netIn != null ? `${srv.netIn} ko/s reçus, ${srv.netOut ?? "?"} ko/s envoyés` : "—"),
          h("dt", {}, "Ping moyen"), h("dd", {}, srv.ping != null ? `${srv.ping} ms` : "—"),
          h("dt", {}, "Discord"), h("dd", { class: srv.discord?.d || srv.discord?.f ? "warn-text" : "" }, discordText(srv.discord)),
          h("dt", {}, "Version"), h("dd", {}, String(srv.placeVersion ?? "—")),
          h("dt", {}, "Dernier signal"), h("dd", {}, srv.hb ? `${timeOf(srv.hb)}` : "—"),
          srv.matchId ? h("dt", {}, "Match") : null, srv.matchId ? h("dd", { class: "id" }, srv.matchId) : null,
          h("dt", {}, "Identifiant"), h("dd", { class: "id" }, srv.jobId),
        ]),
        h("div", { class: "detail-actions" }, [
          joinUrl ? h("a", { class: "btn primary", href: joinUrl, target: "_blank", rel: "noopener" }, "Rejoindre ce Hub") : null,
          copyBtn,
          (() => { const b = h("button", { class: "btn" }, "Message"); b.addEventListener("click", () => messageDialog({ job: srv.jobId, label: `${placeName(srv)} (${shortId(srv.jobId)})` })); return b; })(),
          srv.stale ? null : (() => { const b = h("button", { class: "btn danger" }, "Vider"); b.addEventListener("click", () => drainDialog([srv])); return b; })(),
        ]),
        srv.kind !== "hub" ? h("div", { class: "soon" }, "Les serveurs de match sont privés : on ne peut pas les rejoindre. Vider un match en cours fait perdre la partie aux joueurs.") : null,
      ]),
      players.length
        ? h("table", {}, [
            h("thead", {}, h("tr", {}, ["Joueur", "Faction", "Niv.", "Équipe", "Ping", "Abo."].map((x) => h("th", {}, x)))),
            h("tbody", {}, players.map((p) => {
              const row = h("tr", { style: "cursor:pointer", title: "Ouvrir la fiche", tabindex: "0" }, [
                h("td", {}, p.n || `#${p.u}`),
                h("td", {}, factionText(p.f)),
                h("td", {}, p.l != null ? String(p.l) : ""),
                h("td", {}, p.t != null ? String(p.t) : ""),
                h("td", { style: p.p > 250 ? "color:var(--warn)" : "color:var(--dim)" }, p.p != null ? `${p.p} ms` : ""),
                h("td", {}, p.s ? p.s.replace("_sub", "") : ""),
              ]);
              row.addEventListener("click", () => openPlayer(p.u));
              row.addEventListener("keydown", (ev) => { if (ev.key === "Enter") openPlayer(p.u); });
              return row;
            })),
          ])
        : h("div", { class: "empty" }, "Serveur vide."),
    );
  }

  function renderEvents() {
    const events = [...(snap.events || [])].reverse();
    const seen = alerts.lastSeen();
    const notifBtn = notificationsAvailable() && Notification.permission === "default"
      ? (() => {
          const b = h("button", { class: "btn ghost" }, "Activer les notifications");
          b.title = "Une notification système à chaque crash, même si l'onglet est en arrière-plan";
          b.addEventListener("click", async () => { await Notification.requestPermission(); renderEvents(); });
          return b;
        })()
      : null;
    const w = snap.watcher || {};
    mount(eventsPanel,
      h("div", { class: "panel-head" }, [
        h("h3", {}, "Journal"),
        h("span", { class: "muted", title: w.lastError || "" },
          w.running ? (w.lastError ? "Veilleur en erreur" : `Veille toutes les ${w.interval || 20} s`) : "Veilleur arrêté (clé Open Cloud absente)"),
        w.analyticsError ? h("span", { class: "tag warn", title: w.analyticsError }, "Crashs Roblox indisponibles") : null,
        h("div", { style: "flex:1" }), notifBtn,
      ]),
      events.length
        ? h("div", { class: "events" }, events.slice(0, 120).map((e) => h("div", { class: `ev ${e.level} ${e.id > seen && e.level !== "info" ? "new" : ""}` }, [
            h("time", { datetime: new Date(e.at * 1000).toISOString(), title: fmtDate(e.at) }, timeOf(e.at)),
            h("div", { class: "ev-text" }, [e.text, e.server || e.jobId ? h("small", {}, [e.server || "", e.jobId ? ` ${shortId(e.jobId)}` : ""]) : null]),
          ])))
        : h("div", { class: "empty" }, "Rien à signaler. Crashs, démarrages et fermetures de serveurs apparaîtront ici."),
    );
    const last = (snap.events || []).at(-1);
    if (last) {
      alerts.markSeen(last.id);
      window.dispatchEvent(new Event("cc:alerts-seen"));
    }
  }

  let loading = false;
  const load = async (force = false) => {
    if (loading) return;
    loading = true;
    reloadBtn.disabled = true;
    const contractLoad = api.contracts(force).then((c) => {
      mount(issues, ...(c.issues || []).map((msg) => h("div", { class: "banner bad" }, msg)));
    }).catch((e) => mount(issues, h("div", { class: "banner bad" }, `Contrats illisibles : ${e.message}`)));
    try {
      [data, snap] = await Promise.all([api.live(force), api.liveEvents(0)]);
    } catch (e) {
      data = { servers: [], summary: {}, error: e.message };
    }
    if (ui.selected && !(data.servers || []).some((s) => s.jobId === ui.selected)) ui.selected = null;
    if (!ui.selected && data.servers?.length) ui.selected = data.servers[0].jobId;
    stamp.textContent = data.at ? `Lu à ${new Date(data.at * 1000).toLocaleTimeString("fr-FR")}` : "";
    renderPlaces(); renderList(); renderDetail(); renderEvents();
    await contractLoad;
    loading = false;
    reloadBtn.disabled = false;
  };
  reloadBtn.addEventListener("click", () => load(true));
  await load(false);

  const timer = setInterval(() => {
    if (!container.isConnected) return clearInterval(timer);
    if (ui.auto && !document.hidden) load(false);
  }, REFRESH_MS);
}

//  JOUEURS
export async function viewPlayers(root) {
  const input = h("input", { placeholder: "Nom d'utilisateur ou userId", style: "max-width:340px", "aria-label": "Joueur" });
  const btn = h("button", { class: "btn primary" }, "Ouvrir la fiche");
  const sheet = h("div");
  const roster = h("div", { class: "card" });
  const rosterTitle = h("h3", {}, "Joueurs connectés");
  const rosterStamp = h("span", { class: "muted" });
  const rosterError = h("div");
  const rosterRows = h("div", { style: "overflow-x:auto" });
  const refresh = h("button", { class: "btn" }, "Actualiser");
  mount(roster, h("div", { class: "row", style: "gap:12px;flex-wrap:wrap" }, [rosterTitle, refresh, rosterStamp]),
    h("p", { class: "muted" }, "HUB et matchs · actualisation toutes les 5 s. Clique sur un joueur pour ouvrir sa fiche."),
    rosterError, rosterRows);
  mount(root,
    h("div", { class: "toolbar" }, [h("h2", {}, "Joueurs")]),
    h("div", { class: "card" }, [
      h("div", { class: "row", style: "max-width:520px" }, [input, btn]),
      h("div", { class: "muted", style: "margin-top:8px" },
        "Recherche aussi un joueur hors ligne. Les données détaillées sont lues à l'ouverture de sa fiche."),
    ]),
    roster, sheet,
  );

  const go = async () => {
    const q = input.value.trim();
    if (!q) return;
    btn.disabled = true;
    try {
      const who = await api.playerSearch(q);
      await renderSheet(sheet, who.userId);
    } catch (e) {
      mount(sheet, h("div", { class: "banner bad" }, e.message));
    } finally {
      btn.disabled = false;
    }
  };
  btn.addEventListener("click", go);
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });

  let rosterLoading = false;
  const loadRoster = async (force = false) => {
    if (rosterLoading) return;
    rosterLoading = true;
    refresh.disabled = true;
    try {
      const result = await api.live(force);
      if (!roster.isConnected) return;
      // Un teleport peut laisser le joueur dans deux battements : retenir le plus recent.
      const byUser = new Map();
      for (const server of result.servers || []) {
        if (server.stale) continue;
        for (const player of server.players || []) {
          if (!player.u) continue;
          const previous = byUser.get(String(player.u));
          if (!previous || (server.hb || 0) > (previous.server.hb || 0)) {
            byUser.set(String(player.u), { player, server });
          }
        }
      }
      const rows = [...byUser.values()].sort((a, b) =>
        String(a.player.n || a.player.u).localeCompare(String(b.player.n || b.player.u), "fr"));
      rosterTitle.textContent = `Joueurs connectés (${rows.length})`;
      rosterStamp.textContent = result.at ? `Lu à ${new Date(result.at * 1000).toLocaleTimeString("fr-FR")}` : "";
      mount(rosterError);
      mount(rosterRows, rows.length ? h("table", {}, [
        h("thead", {}, h("tr", {}, ["Joueur", "Lieu", "Faction", "Niveau", "Dernier signal"].map((s) => h("th", {}, s)))),
        h("tbody", {}, rows.map(({ player: p, server: s }) => h("tr", {}, [
          h("td", {}, h("button", { class: "btn ghost", title: `Ouvrir la fiche · ${p.u}`,
            onclick: () => { input.value = String(p.u); go(); } }, p.n || String(p.u))),
          h("td", {}, [s.kind === "hub" ? "HUB" : (s.mode || "MATCH"),
            h("small", { class: "muted", style: "display:block" }, `${s.map || ""} ${shortId(s.jobId)}`.trim())]),
          h("td", {}, p.f || "—"), h("td", {}, p.l == null ? "—" : String(p.l)),
          h("td", { class: "muted" }, `${Math.max(0, Math.floor(Date.now() / 1000) - (s.hb || 0))} s`),
        ]))),
      ]) : h("div", { class: "empty" }, "Aucun joueur connecté signalé par les serveurs."));
    } catch (e) {
      mount(rosterError, h("div", { class: "banner bad" }, `Liste indisponible : ${e.message}. Les dernières données affichées peuvent être périmées.`));
    } finally {
      rosterLoading = false;
      refresh.disabled = false;
    }
  };
  refresh.addEventListener("click", () => loadRoster(true));
  loadRoster();
  const rosterTimer = setInterval(() => {
    if (!roster.isConnected) return clearInterval(rosterTimer);
    if (!document.hidden) loadRoster();
  }, REFRESH_MS);

  // Lien direct #players/<userId> (cartes de l'Accueil, journal) : ouvre la fiche.
  const fromHash = () => decodeURIComponent(location.hash.slice(1)).split("/")[1] || "";
  const onRoute = () => {
    if (!root.isConnected || !sheet.isConnected) { window.removeEventListener("cc:players-route", onRoute); return; }
    const uid = fromHash();
    if (uid) { input.value = uid; go(); }
  };
  window.addEventListener("cc:players-route", onRoute);

  const initial = pendingPlayer || fromHash();
  if (initial) {
    input.value = initial;
    pendingPlayer = null;
    go();
  } else {
    input.focus();
  }
}

function sectionError(sec) {
  return sec && !sec.ok ? h("div", { class: "banner bad" }, sec.error) : null;
}

function rawJson(label, value) {
  if (value == null) return null;
  return h("details", { style: "margin-top:10px" }, [
    h("summary", { class: "muted", style: "cursor:pointer" }, label),
    h("pre", { style: "white-space:pre-wrap;word-break:break-all;margin:8px 0 0" }, JSON.stringify(value, null, 2)),
  ]);
}

// onRemove(item) : ajoute un bouton « Retirer » par ligne (apercu avant toute ecriture).
function itemsTable(rows, onRemove = null) {
  if (!rows.length) return h("div", { class: "empty" }, "Vide.");
  return h("table", {}, [
    h("thead", {}, h("tr", {}, ["Emplacement", "Objet", "Qté", "Accessoires", "Contenu", onRemove ? "" : null].filter((x) => x != null).map((x) => h("th", {}, x)))),
    h("tbody", {}, rows.map(([where, it]) => h("tr", { title: `uid ${it.uid}` }, [
      h("td", { class: "muted" }, where),
      h("td", {}, [h("b", {}, String(it.label || it.id)), it.label !== it.id ? h("span", { class: "id" }, ` ${it.id}`) : null]),
      h("td", { class: "num" }, it.quantity != null ? String(it.quantity) : ""),
      h("td", { class: "muted" }, (it.mods || []).map((m) => `${m.slot} : ${m.id}`).join(", ")),
      h("td", { class: "muted" }, (it.contents || []).map((c) => c.label || c.id).join(", ")),
      onRemove ? h("td", { class: "num" }, (() => {
        const b = h("button", { class: "btn ghost", title: "Retirer cet objet (aperçu avant écriture)" }, "Retirer");
        b.addEventListener("click", () => onRemove(it));
        return b;
      })()) : null,
    ]))),
  ]);
}

async function renderSheet(sheet, userId, force = false) {
  mount(sheet, h("div", { class: "card muted" }, "Lecture de la fiche…"));
  const d = await api.player(userId, force);
  const S = d.sections || {};
  const id = S.identity?.data || {};
  const prof = S.profile?.data || null;
  const skills = S.skills?.data || null;
  const ban = S.ban?.ok ? S.ban.data : undefined;
  const presence = S.presence?.data || null;
  const subs = S.subscriptions?.data || [];
  const hp = S.honeypot?.data || null;
  const level = skills ? (skills.level ?? skills.Level) : null;

  const activeSubs = subs.filter((s) => s.record && (s.record.active ?? true));
  const where = presence
    ? (presence.kind === "hub" ? "En ligne au Hub" : `En match : ${presence.mode || ""}${presence.map ? `, ${presence.map}` : ""}`)
    : "Hors ligne";

  const tabBody = h("div");
  const tabs = [
    ["Résumé", () => summaryTab(d, prof, skills, subs, ban)],
    ["Inventaire", () => inventoryTab(userId, true, removeFrom("inventory"))],
    ["Stash", () => stashTab(userId, true, removeFrom("stash"))],
    ["Sécurité", () => securityTab(S)],
  ];
  const tabBar = h("div", { class: "seg", role: "tablist" });
  const tabBtns = tabs.map(([label, fn], i) => {
    const b = h("button", { class: i === 0 ? "on" : "", role: "tab" }, label);
    b.addEventListener("click", async () => {
      tabBtns.forEach((x) => x.classList.remove("on"));
      b.classList.add("on");
      mount(tabBody, h("div", { class: "muted" }, "Lecture…"));
      try { mount(tabBody, await fn()); }
      catch (e) { mount(tabBody, h("div", { class: "banner bad" }, e.message)); }
    });
    return b;
  });
  tabBar.append(...tabBtns);

  const refresh = h("button", { class: "btn" }, "Relire");
  const reload = () => renderSheet(sheet, userId, true).catch((e) => toast(e.message, "bad"));
  refresh.addEventListener("click", reload);
  const name = id.name || `#${userId}`;

  // ACTIONS (lot 3) : chacune ouvre une fenetre qui dit ce qui va se passer.
  const act = (label, fn, cls = "btn", title = "") => {
    const b = h("button", { class: cls, title }, label);
    b.addEventListener("click", fn);
    return b;
  };
  const prefill = (view) => {
    try { sessionStorage.setItem("cc.give.users", String(userId)); } catch { /* stockage indisponible */ }
    location.hash = `#${view}`;
  };
  const actions = h("div", { class: "sheet-actions" }, [
    presence ? act("Message", () => messageDialog({ userId, label: name })) : null,
    presence ? act("Expulser", () => kickDialog(userId, name), "btn danger") : null,
    ban?.active ? act("Lever le ban", () => unbanDialog(userId, name, reload))
      : act("Bannir", () => banDialog([userId], name, reload), "btn danger"),
    act("Modifier l'or", () => moneyDialog(userId, prof?.money, reload)),
    act("Don", () => prefill("give"), "btn", "Ouvre Dons avec ce joueur"),
    act("Modifications", () => backupsDialog(userId, reload), "btn ghost", "Modifications faites depuis le CC, annulables"),
  ]);
  const removeFrom = (where) => (it) => editFlow(userId, "remove_item", { where, uid: it.uid },
    `Retirer ${it.label || it.id}`, () => tabBtns[where === "stash" ? 2 : 1].click());

  mount(sheet,
    h("div", { class: "card" }, [
      h("div", { class: "toolbar", style: "margin-bottom:0" }, [
        h("div", { class: "who" }, [
          id.headshot ? h("img", { src: id.headshot, alt: "" }) : null,
          h("div", {}, [
            h("h2", {}, id.name || `#${userId}`),
            h("a", { href: id.profileUrl, target: "_blank", rel: "noopener", class: "muted" }, `Profil Roblox, userId ${userId}`),
          ]),
        ]),
        h("div", { class: "spacer" }),
        refresh,
      ]),
      h("div", { class: "badges" }, [
        tag(where, presence ? "ok" : ""),
        ban?.active ? tag(`Banni : ${ban.displayReason || "sans motif"}`, "bad") : null,
        hp ? tag(`${hp.hits || 0} appel(s) de piège`, "bad") : null,
        ...activeSubs.map((s) => tag(`Abonné ${s.label || s.id}`, "ok")),
      ]),
      h("div", { class: "stats" }, [
        h("div", { class: "stat" }, [h("div", { class: "stat-v" }, prof ? factionText(prof.faction) : "—"), h("div", { class: "stat-l" }, "Faction")]),
        h("div", { class: "stat" }, [h("div", { class: "stat-v" }, level != null ? String(level) : "—"), h("div", { class: "stat-l" }, "Niveau")]),
        h("div", { class: "stat" }, [h("div", { class: "stat-v" }, prof?.money != null ? Number(prof.money).toLocaleString("fr-FR") : "—"), h("div", { class: "stat-l" }, "Or")]),
        h("div", { class: "stat" }, [h("div", { class: "stat-v" }, prof?.lp != null ? String(prof.lp) : "—"), h("div", { class: "stat-l" }, "LP ranked")]),
      ]),
      !prof && S.profile?.ok ? h("div", { class: "banner", style: "margin-top:12px" }, `Aucun profil dans ${d.stores?.profile} : ce joueur n'a jamais joué sur cette version de données.`) : null,
      actions,
      h("div", { class: "muted", style: "margin-top:10px" }, `Lu à ${new Date(d.at * 1000).toLocaleTimeString("fr-FR")}, magasin ${d.stores?.profile || "?"}`),
    ]),
    h("div", { class: "card" }, [tabBar, h("div", { style: "margin-top:14px" }, tabBody)]),
  );
  mount(tabBody, await tabs[0][1]());
}

const SUB_STATES = {
  SUBSCRIBED_WILL_RENEW: "Actif, renouvellement automatique",
  SUBSCRIBED_WILL_NOT_RENEW: "Actif, sans renouvellement",
  SUBSCRIBED_RENEWAL_PAYMENT_PENDING: "Paiement du renouvellement en attente",
  EXPIRED: "Expiré",
};
const PROFILE_LABELS = {
  faction: "Faction", money: "Or", lp: "LP ranked", placementsPlayed: "Placements joués",
  specialization: "Spécialisation", factionLockedAt: "Faction choisie le", lastSeenAt: "Dernière connexion",
  hasFinishedTutorial: "Tutoriel terminé", defection: "Changement de camp en cours", market: "Marché noir",
};
function profileValue(key, value) {
  if (value === true) return "Oui";
  if (value === false || value == null) return key === "defection" ? "Non" : "—";
  if ((key === "lastSeenAt" || key === "factionLockedAt") && typeof value === "number") return fmtDate(value);
  if (key === "market" && typeof value === "object") {
    return `${value.listings ?? 0} annonce(s), ${value.mail ?? 0} courrier(s), ${value.receipts ?? 0} reçu(s)`;
  }
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

function summaryTab(d, prof, skills, subs, ban) {
  const S = d.sections;
  const subRows = subs.map((s) => h("tr", {}, [
    h("td", {}, s.label || s.id),
    h("td", {}, s.error ? tag("Illisible", "bad")
      : s.record ? tag(SUB_STATES[s.record.state] || s.record.state || "Abonné", s.record.state === "EXPIRED" ? "" : "ok")
      : h("span", { class: "muted" }, "Non abonné")),
    h("td", { class: "muted" }, s.error || (s.record?.nextRenewTime || s.record?.expireTime || "")),
  ]));
  return h("div", {}, [
    sectionError(S.profile), sectionError(S.skills), sectionError(S.subscriptions), sectionError(S.ban),
    h("div", { class: "grid2" }, [
      h("div", {}, [
        h("h3", {}, "Abonnements"),
        subs.length ? h("table", {}, h("tbody", {}, subRows))
          : h("div", { class: "muted" }, "Aucune offre d'abonnement connue : le contrat du HUB n'est pas encore publié."),
        h("h3", { style: "margin-top:18px" }, "Ban Roblox"),
        ban === undefined ? h("div", { class: "muted" }, "Non lu, voir l'erreur au-dessus.")
          : ban?.active
            ? h("dl", { class: "kv" }, [
                h("dt", {}, "Depuis"), h("dd", {}, ban.startTime || "?"),
                h("dt", {}, "Durée"), h("dd", {}, ban.duration || "Permanente"),
                h("dt", {}, "Motif affiché"), h("dd", {}, ban.displayReason || ""),
                h("dt", {}, "Motif privé"), h("dd", {}, ban.privateReason || ""),
              ])
            : h("div", { class: "muted" }, "Aucun ban actif."),
      ]),
      h("div", {}, [
        h("h3", {}, "Profil"),
        prof ? h("dl", { class: "kv" }, Object.entries(prof).filter(([k]) => k !== "raw").flatMap(([k, v]) =>
          [h("dt", {}, PROFILE_LABELS[k] || k), h("dd", {}, profileValue(k, v))]))
          : h("div", { class: "muted" }, "Pas de profil."),
      ]),
    ]),
    rawJson("Profil complet (JSON brut)", prof?.raw),
    rawJson("Compétences et XP (JSON brut)", skills),
    rawJson("Rachat EXFIL en attente", S.exfilClaim?.data),
    rawJson("Dette du marché noir", S.debt?.data),
  ]);
}

async function inventoryTab(userId, force, onRemove) {
  const inv = await api.playerInventory(userId, force);
  if (inv.empty) return h("div", { class: "empty" }, `Aucun inventaire sauvegardé dans ${inv.store}.`);
  const rows = [
    ...Object.entries(inv.equipped || {}).map(([slot, it]) => [`Équipé, ${slot}${slot === inv.active ? " (actif)" : ""}`, it]),
    ...(inv.pockets || []).map((it) => [`Poches ${it.x},${it.y}`, it]),
  ].filter(([, it]) => it);
  return h("div", {}, [itemsTable(rows, onRemove), h("div", { class: "muted", style: "margin-top:8px" }, `${rows.length} objet(s), magasin ${inv.store}`)]);
}

async function stashTab(userId, force, onRemove) {
  const st = await api.playerStash(userId, force);
  if (st.empty) return h("div", { class: "empty" }, `Aucun stash sauvegardé dans ${st.store}.`);
  const full = (st.tabs || []).filter((t) => t.items.length);
  return h("div", {}, [
    h("div", { class: "muted" }, `${st.unlockedTabs ?? "?"} onglet(s) débloqué(s), magasin ${st.store}`),
    ...full.map((t) => h("div", { style: "margin-top:14px" }, [
      h("h3", {}, `${t.name} (${t.items.length})`),
      itemsTable(t.items.map((it) => [`${it.x},${it.y}`, it]), onRemove),
    ])),
    full.length ? null : h("div", { class: "empty" }, "Stash vide."),
  ]);
}

function securityTab(S) {
  const hp = S.honeypot?.data;
  return h("div", {}, [
    sectionError(S.sanctions), sectionError(S.honeypot),
    h("h3", {}, "Pièges anti-triche"),
    hp ? h("div", {}, [
      h("dl", { class: "kv" }, [
        h("dt", {}, "Appels"), h("dd", {}, `${hp.hits || 0} sur ${hp.sessions || 0} session(s)${hp.admin ? ", admin en test" : ""}`),
        h("dt", {}, "Premier"), h("dd", {}, hp.firstAt ? fmtDate(hp.firstAt) : "?"),
        h("dt", {}, "Dernier"), h("dd", {}, hp.lastAt ? fmtDate(hp.lastAt) : "?"),
        h("dt", {}, "Pièges"), h("dd", {}, Object.entries(hp.traps || {}).map(([n, c]) => `${n} (${c})`).join(", ")),
      ]),
      rawJson("Échantillons d'arguments", hp.samples),
    ]) : h("div", { class: "muted" }, "Aucun piège déclenché."),
    h("h3", { style: "margin-top:18px" }, "Échelle automatique de l'anti-triche"),
    S.sanctions?.data ? rawJson("Enregistrement Sanctions", S.sanctions.data) : h("div", { class: "muted" }, "Aucune sanction enregistrée."),
  ]);
}
