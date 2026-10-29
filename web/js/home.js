//  home.js — Accueil : ce qu'il faut faire maintenant, et l'etat du jeu en un coup d'oeil.
//  Les cartes sont calculees par le serveur (core/cards.py) ; cette page les affiche et
//  passe chaque publication par un apercu avant d'ecrire quoi que ce soit.
import { api } from "./api.js";
import { h, mount, toast, fmtDuration, renderDiscordMarkdown } from "./ui.js";
import { notifyDialog } from "./notify.js";

const PRIO = {
  crit: ["Bloquant", "bad"], high: ["Important", "warn"], normal: ["À faire", ""],
  info: ["Pour info", ""], waiting: ["En attente", ""],
};

const rel = (ts) => {
  const d = Math.round(Date.now() / 1000 - ts);
  if (Math.abs(d) < 60) return "à l'instant";
  return d > 0 ? `il y a ${fmtDuration(d)}` : `dans ${fmtDuration(-d)}`;
};
const paris = (ts) => new Date(ts * 1000).toLocaleString("fr-FR",
  { weekday: "short", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Paris" });

function tomorrowNine() {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  d.setHours(9, 0, 0, 0);
  return Math.floor(d.getTime() / 1000);
}

// APERCU : montre exactement ce qui partira, puis publie sur confirmation.
function previewDialog(card, action, onDone) {
  const body = h("div", { class: "dlg-body" }, h("div", { class: "muted" }, "Préparation de l'aperçu…"));
  const publishBtn = h("button", { class: "btn primary", disabled: true }, "Publier");
  const cancel = h("button", { class: "btn" }, "Annuler");
  const dlg = h("div", { class: "dlg-back", role: "dialog", "aria-modal": "true", "aria-label": action.label }, [
    h("div", { class: "dlg" }, [
      h("div", { class: "dlg-head" }, [h("div", { class: "muted" }, card.title), h("h3", {}, action.label)]),
      body,
      h("div", { class: "dlg-foot" }, [h("span", { class: "muted" }, "Rien n'est envoyé avant ton clic."),
        h("div", { style: "flex:1" }), cancel, publishBtn]),
    ]),
  ]);
  const close = () => { dlg.remove(); document.removeEventListener("keydown", onKey); };
  const onKey = (e) => { if (e.key === "Escape") close(); };
  document.addEventListener("keydown", onKey);
  dlg.addEventListener("click", (e) => { if (e.target === dlg) close(); });
  cancel.addEventListener("click", close);
  document.body.append(dlg);
  cancel.focus();

  api.cardPreview(card.key, action.id).then((p) => {
    mount(body, ...p.messages.map((m) => h("div", { class: "dlg-msg" }, [
      h("div", { class: "muted" }, [`#${m.channel}`, m.ping ? `, ping ${m.ping === "everyone" ? "@everyone" : m.ping}` : ""]),
      h("div", { class: "discord-preview" }, h("div", { class: "dp-embed" }, [
        h("div", { class: "dp-title", text: m.title }),
        h("div", { class: "dp-body", html: renderDiscordMarkdown(m.body) }),
      ])),
    ])));
    publishBtn.disabled = false;
    publishBtn.focus();
  }).catch((e) => mount(body, h("div", { class: "banner bad", style: "margin:0" }, e.message)));

  publishBtn.addEventListener("click", async () => {
    publishBtn.disabled = true;
    publishBtn.textContent = "Publication…";
    try {
      const r = await api.cardAct(card.key, action.id);
      toast(r.ok ? "Publié." : "Envoi partiel ou refusé : voir le Journal.", r.ok ? "ok" : "bad");
      close();
      onDone(r);
    } catch (e) {
      toast(e.message, "bad");
      publishBtn.disabled = false;
      publishBtn.textContent = "Publier";
    }
  });
}

// DROIT A L'EFFACEMENT : apercu de chaque entree, puis confirmation en tapant l'identifiant.
function eraseDialog(card, action, refresh) {
  const uid = String(action.userId);
  const body = h("div", { class: "dlg-body" }, h("div", { class: "muted" }, "Lecture des magasins du joueur…"));
  const confirm = h("input", { type: "text", inputmode: "numeric", autocomplete: "off", "aria-label": "Identifiant du joueur" });
  const go = h("button", { class: "btn danger", disabled: true }, "Effacer définitivement");
  const cancel = h("button", { class: "btn" }, "Annuler");
  const dlg = h("div", { class: "dlg-back", role: "dialog", "aria-modal": "true", "aria-label": "Effacement" }, [
    h("div", { class: "dlg" }, [
      h("div", { class: "dlg-head" }, [h("div", { class: "muted" }, card.title), h("h3", {}, "Effacer les données du joueur")]),
      body,
      h("div", { class: "dlg-foot" }, [h("span", { class: "muted" }, "Irréversible."), h("div", { style: "flex:1" }), cancel, go]),
    ]),
  ]);
  const close = () => { dlg.remove(); document.removeEventListener("keydown", onKey); };
  const onKey = (e) => { if (e.key === "Escape") close(); };
  document.addEventListener("keydown", onKey);
  cancel.addEventListener("click", close);
  document.body.append(dlg);
  cancel.focus();
  let plan = null;
  const check = () => { go.disabled = !plan || confirm.value.trim() !== uid; };
  confirm.addEventListener("input", check);
  api.erasurePlan(uid, card.key).then((p) => {
    plan = p;
    mount(body,
      h("p", {}, [`${p.found} entrée(s) trouvée(s) chez Roblox`, p.unreadable ? `, ${p.unreadable} illisible(s) (permission manquante ?)` : "", ". "
        + "Toutes les entrées listées seront supprimées ; en base locale : " + p.local + "."]),
      h("div", { class: "dlg-scroll" }, h("table", {}, [
        h("thead", {}, h("tr", {}, ["Magasin", "Clé", "État"].map((x) => h("th", {}, x)))),
        h("tbody", {}, p.rows.map((r) => h("tr", {}, [
          h("td", {}, r.store), h("td", {}, h("code", {}, r.key)),
          h("td", {}, r.error ? h("span", { class: "tag bad", title: r.error }, "illisible")
            : r.exists ? h("span", { class: "tag warn" }, "présent") : h("span", { class: "muted" }, "absent")),
        ]))),
      ])),
      h("div", { class: "muted" }, p.notCovered),
      h("label", { class: "field" }, [h("span", {}, `Pour confirmer, tape l'identifiant du joueur : ${uid}`), confirm]));
    check();
    confirm.focus();
  }).catch((e) => mount(body, h("div", { class: "banner bad", style: "margin:0" }, e.message)));
  go.addEventListener("click", async () => {
    go.disabled = true;
    go.textContent = "Effacement…";
    try {
      const r = await api.erasureApply(plan.token, confirm.value.trim());
      toast(r.ok ? "Données effacées." : "Effacement partiel : voir le Journal.", r.ok ? "ok" : "bad");
      close();
      refresh(r);
    } catch (e) {
      toast(e.message, "bad");
      go.textContent = "Effacer définitivement";
      check();
    }
  });
}

// AUTOMATISATION : ce qui partira seul depuis cette carte, et quand.
function autoLines(c, refresh) {
  return c.actions.filter((a) => a.auto && !(a.auto.state === "done" || a.auto.state === "cancelled")).map((a) => {
    const st = a.auto;
    if (st.state === "failed") {
      return h("div", { class: "hc-auto bad" }, `Échec de l'envoi automatique « ${a.label} » : ${st.error || "erreur inconnue"}. À refaire à la main.`);
    }
    if (st.state === "pending") return h("div", { class: "hc-auto" }, `« ${a.label} » partira automatiquement (règle active).`);
    const when = new Date(st.due * 1000).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/Paris" });
    const stop = h("button", { class: "btn ghost sm" }, "Annuler l'envoi auto");
    stop.addEventListener("click", async () => {
      stop.disabled = true;
      try { refresh(await api.cancelAutomation(c.key, a.id)); toast("Envoi automatique annulé : l'action reste disponible à la main."); }
      catch (e) { toast(e.message, "bad"); stop.disabled = false; }
    });
    return h("div", { class: "hc-auto" }, [`« ${a.label} » part automatiquement à ${when}.`, stop]);
  });
}

// NOTIFICATION JOUEURS depuis une carte : meme fenetre que Diffusion > Notifications.
async function openNotify(card, action, refresh) {
  let entry = null;
  try { entry = (await api.notify()).catalogue.find((e) => e.key === action.notify) || null; } catch { /* apercu quand meme */ }
  notifyDialog({ key: action.notify, entry, params: action.params || {}, ref: action.ref, card: card.key, action: action.id,
    onDone: async () => { try { refresh(await api.home(true)); } catch { /* actualisation suivante */ } } });
}

function cardView(c, refresh) {
  const [prioLabel, prioCls] = PRIO[c.prio] || PRIO.normal;
  const setState = async (state, until) => {
    try { refresh(await api.cardState(c.key, state, until)); } catch (e) { toast(e.message, "bad"); }
  };
  const actions = c.actions.map((a) => {
    if (a.kind === "go") {
      return h("a", { class: "btn", href: a.href }, a.label);
    }
    const doneWord = a.kind === "notify" ? "envoyée" : "publié";
    const b = h("button", { class: `btn ${a.done ? "" : "primary"}`, title: a.done ? `Déjà ${doneWord} depuis cette carte` : "" },
      a.done ? `${a.label} (${doneWord})` : a.label);
    if (a.kind === "notify" && a.done) b.disabled = true;
    if (a.kind === "erase") b.classList.replace("primary", "danger");
    b.addEventListener("click", async () => {
      if (a.kind === "erase") return eraseDialog(c, a, refresh);
      if (a.kind === "publish") return previewDialog(c, a, refresh);
      if (a.kind === "notify") return openNotify(c, a, refresh);
      b.disabled = true;
      try { refresh(await api.cardAct(c.key, a.id)); toast("C'est noté."); } catch (e) { toast(e.message, "bad"); b.disabled = false; }
    });
    return b;
  });

  const later = h("details", { class: "later" }, [
    h("summary", { class: "btn ghost" }, "Plus tard"),
    h("div", { class: "later-menu" }, [
      ["Dans 1 heure", () => Math.floor(Date.now() / 1000) + 3600],
      ["Dans 4 heures", () => Math.floor(Date.now() / 1000) + 4 * 3600],
      ["Demain 9 h", tomorrowNine],
    ].map(([label, until]) => {
      const b = h("button", { class: "btn ghost" }, label);
      b.addEventListener("click", () => setState("snoozed", until()));
      return b;
    })),
  ]);
  const secondary = [
    c.noSnooze ? null : later,
    c.prio === "waiting" || c.noDismiss ? null : (() => { const b = h("button", { class: "btn ghost", title: "Fermer : c'est réglé" }, "Fait"); b.addEventListener("click", () => setState("done")); return b; })(),
    c.noDismiss ? null : (() => { const b = h("button", { class: "btn ghost", title: "Ne plus afficher cette carte" }, "Ignorer"); b.addEventListener("click", () => setState("dismissed")); return b; })(),
  ];

  const when = c.due ? `échéance ${rel(c.due)}` : c.at ? rel(c.at) : "";
  return h("article", { class: `hcard p-${c.prio}` }, [
    h("div", { class: "hc-top" }, [
      h("span", { class: `tag ${prioCls}` }, prioLabel),
      h("span", { class: "hc-cat" }, c.category),
      h("div", { style: "flex:1" }),
      when ? h("span", { class: "hc-when", title: (c.due || c.at) ? paris(c.due || c.at) : "" }, when) : null,
    ]),
    h("h3", { class: "hc-title" }, c.title),
    c.context ? h("p", { class: "hc-ctx", html: renderDiscordMarkdown(c.context) }) : null,
    c.where || c.why ? h("dl", { class: "kv hc-kv" }, [
      c.where ? h("dt", {}, "Où") : null, c.where ? h("dd", {}, c.where) : null,
      c.why ? h("dt", {}, "À quoi ça sert") : null, c.why ? h("dd", {}, c.why) : null,
    ]) : null,
    ...autoLines(c, refresh),
    h("div", { class: "hc-actions" }, [...actions, h("div", { style: "flex:1" }), ...secondary]),
  ]);
}

export async function viewHome(root) {
  const stamp = h("span", { class: "muted" });
  const reload = h("button", { class: "btn" }, "Actualiser");
  const strip = h("div", { class: "home-strip" });
  const list = h("div", { class: "home-list" });
  const waiting = h("div");
  mount(root,
    h("div", { class: "toolbar" }, [h("h2", {}, "Accueil"), h("div", { class: "spacer" }), stamp, reload]),
    strip, list, waiting);

  let timer = null;
  const render = (data, live) => {
    stamp.textContent = `Vérifié à ${new Date(data.at * 1000).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })}`;
    const s = data.season;
    const sum = live?.summary || {};
    const alerts = (live?.servers || []).filter((x) => x.stale || (typeof x.fps === "number" && x.fps < 30)).length;
    const tick = () => {
      const left = s.endsAt - Math.floor(Date.now() / 1000);
      mount(strip,
        h("a", { class: "hs", href: "#factionwar" }, [
          h("div", { class: "hs-l" }, `Saison ${s.label}`),
          h("div", { class: "hs-v" }, left > 0 ? fmtDuration(left) : "clôture en cours"),
          h("div", { class: "hs-s" }, `fin ${paris(s.endsAt)}, heure de Paris`),
        ]),
        h("a", { class: "hs", href: "#live" }, [
          h("div", { class: "hs-l" }, "En jeu"),
          h("div", { class: "hs-v" }, [String(sum.players ?? 0), h("small", {}, " joueurs")]),
          h("div", { class: "hs-s" }, `${sum.hubs ?? 0} Hub, ${sum.matches ?? 0} match(s)${alerts ? `, ${alerts} alerte(s)` : ""}`),
        ]),
        h("div", { class: "hs" }, [
          h("div", { class: "hs-l" }, "À faire"),
          h("div", { class: "hs-v" }, String(data.cards.length)),
          h("div", { class: "hs-s" }, [
            data.snoozed ? `${data.snoozed} repoussée(s)` : "rien de repoussé",
            data.waiting.length ? `, ${data.waiting.length} en attente` : "",
          ]),
        ]),
      );
    };
    tick();
    clearInterval(timer);
    timer = setInterval(() => (strip.isConnected ? tick() : clearInterval(timer)), 30000);

    mount(list, ...(data.cards.length
      ? data.cards.map((c) => cardView(c, refresh))
      : [h("div", { class: "home-empty" }, [
          h("h3", {}, "Rien à faire pour l'instant"),
          h("p", { class: "muted" }, "Fin de saison, versement ranked, triche, avis négatifs, tâches de configuration : "
            + "tout ce qui demande ton attention apparaîtra ici, avec l'action à faire."),
        ])]));
    mount(waiting, ...(data.waiting.length ? [
      h("details", { class: "home-waiting" }, [
        h("summary", {}, `En attente (${data.waiting.length}) : pas encore possible, le CC préviendra`),
        ...data.waiting.map((c) => cardView(c, refresh)),
      ]),
    ] : []));
    window.dispatchEvent(new CustomEvent("cc:home", { detail: data }));
  };

  let lastLive = null;
  async function refresh(data) {
    if (!root.isConnected) return;
    render(data, lastLive);
  }

  const load = async (force) => {
    try {
      const [data, live] = await Promise.all([api.home(force), api.live().catch(() => null)]);
      lastLive = live;
      render(data, live);
    } catch (e) {
      mount(list, h("div", { class: "banner bad" }, `Lecture impossible : ${e.message}`));
    }
  };
  reload.addEventListener("click", () => load(true).then(() => toast("Actualisé.")));
  await load(false);
}
