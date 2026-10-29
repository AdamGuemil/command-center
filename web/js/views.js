//  views.js — les 7 panneaux du Command Center
import { api } from "./api.js";
import { h, mount, toast, fmtDuration, fmtDate, renderDiscordMarkdown, toHex, toDec, confirmAction }
  from "./ui.js";
import { banDialog, unbanDialog } from "./actions.js";

export const state = {
  status: null,
  channels: [],
  roles: [],
  templates: [],
  vars: [],
  draft: null,          // message en cours d'edition
};

//  1. COMPOSER
function blankDraft() {
  return { templateId: "", channelId: "", title: "", body: "", color: 5793266,
           footer: "", image: "", ping: "", publish: false };
}

export function viewCompose(root) {
  if (!state.draft) state.draft = blankDraft();
  const d = state.draft;

  // Salon par defaut : le premier #announcements trouve.
  if (!d.channelId && state.channels.length) {
    const pref = state.channels.find((c) => c.name === "announcements");
    d.channelId = (pref || state.channels[0]).id;
  }

  const preview = h("div", { class: "discord-preview" });
  const render = () => {
    const ping = d.ping === "everyone" ? "@everyone"
      : d.ping === "here" ? "@here"
      : d.ping ? "@role" : "";
    preview.innerHTML = "";
    if (ping) preview.append(h("div", { class: "dp-ping", text: ping }));
    const embed = h("div", { class: "dp-embed" });
    embed.style.borderLeftColor = toHex(d.color);
    if (d.title) embed.append(h("div", { class: "dp-title", text: d.title }));
    embed.append(h("div", { class: "dp-body", html: renderDiscordMarkdown(d.body) }));
    if (d.image) embed.append(h("img", { class: "dp-img", src: d.image }));
    if (d.footer) embed.append(h("div", { class: "dp-footer", text: d.footer }));
    preview.append(embed);
  };

  const bind = (key, el, transform = (v) => v) => {
    el.addEventListener("input", () => { d[key] = transform(el.value); render(); });
    return el;
  };

  // --- selecteurs ---
  const chanSel = h("select", {},
    state.channels.map((c) =>
      h("option", { value: c.id, selected: c.id === d.channelId ? "selected" : null },
        `#${c.name}${c.category ? `  ·  ${c.category}` : ""}`)));
  chanSel.addEventListener("change", () => { d.channelId = chanSel.value; });

  const tplSel = h("select", {}, [
    h("option", { value: "" }, "— modèle vierge —"),
    ...state.templates.map((t) =>
      h("option", { value: t.id, selected: t.id === d.templateId ? "selected" : null }, t.name)),
  ]);
  tplSel.addEventListener("change", () => {
    const t = state.templates.find((x) => x.id === tplSel.value);
    // Le salon est un choix INDEPENDANT du modele : repasser sur "modele
    // vierge" ne doit pas l'effacer, sinon l'envoi echoue sur "Aucun salon
    // selectionne" alors que la liste en affiche un.
    if (!t) { Object.assign(d, blankDraft(), { channelId: d.channelId }); }
    else {
      const ch = state.channels.find((c) => c.name === t.channel);
      Object.assign(d, {
        templateId: t.id, title: t.title, body: t.body, color: t.color,
        footer: t.footer || "", image: t.image || "", ping: t.ping || "",
        channelId: ch ? ch.id : d.channelId,
      });
    }
    // RECONSTRUCTION COMPLETE de la vue, plutot qu'un re-montage des memes
    // elements. Les champs sont crees a partir de `d` : les recreer garantit
    // qu'ils refletent l'etat, sans avoir a resynchroniser chaque champ un par
    // un -- ce qui se serait re-casse au premier champ ajoute.
    // C'est ce qui causait le bug : l'ecran montrait "@everyone" alors que
    // l'etat disait "aucun ping", et le message partait sans mention.
    viewCompose(root);
  });

  const pingSel = h("select", {}, [
    h("option", { value: "" }, "Aucun ping"),
    h("option", { value: "everyone" }, "@everyone"),
    h("option", { value: "here" }, "@here"),
    ...state.roles.map((r) => h("option", { value: r.id }, `@${r.name}`)),
  ]);
  pingSel.value = d.ping;
  pingSel.addEventListener("change", () => { d.ping = pingSel.value; render(); });

  const bodyArea = bind("body", h("textarea", {}, d.body));
  const titleInp = bind("title", h("input", { value: d.title, placeholder: "Titre de l'embed" }));
  const footInp = bind("footer", h("input", { value: d.footer, placeholder: "Pied de page (optionnel)" }));
  const imgInp = bind("image", h("input", { value: d.image, placeholder: "URL image (optionnel)" }));
  const colorInp = bind("color", h("input", { type: "color", value: toHex(d.color) }), toDec);

  // Insertion de variable au curseur : c'est ce qui rend les modeles reutilisables.
  const varChips = h("div", { class: "varlist" },
    state.vars.map((v) =>
      h("span", { class: "varchip", title: v.desc, onclick: () => {
        const pos = bodyArea.selectionStart ?? bodyArea.value.length;
        bodyArea.value = bodyArea.value.slice(0, pos) + v.key + bodyArea.value.slice(pos);
        d.body = bodyArea.value;
        bodyArea.focus();
        bodyArea.selectionStart = bodyArea.selectionEnd = pos + v.key.length;
        render();
      } }, v.key)));

  const sendBtn = h("button", { class: "btn primary" }, "Envoyer sur Discord");
  sendBtn.addEventListener("click", async () => {
    const chan = state.channels.find((c) => c.id === d.channelId);
    if (!confirmAction(`Envoyer dans #${chan ? chan.name : "?"} ?` +
        (d.ping ? `\n\nAvec un ping ${d.ping === "everyone" ? "@everyone" : "@" + d.ping} !` : ""))) return;
    sendBtn.disabled = true;
    sendBtn.textContent = "Envoi…";
    try {
      const r = await api.announce({ ...d, channelId: d.channelId });
      toast(`Publié dans #${r.channel}` + (r.published ? " (diffusé)" : ""), "ok");
    } catch (e) {
      toast(`${e.message}`, "bad");
    } finally {
      sendBtn.disabled = false;
      sendBtn.textContent = "Envoyer sur Discord";
    }
  });

  const previewBtn = h("button", { class: "btn" }, "Résoudre les variables");
  previewBtn.addEventListener("click", async () => {
    try {
      const r = await api.preview({ title: d.title, body: d.body, footer: d.footer });
      preview.innerHTML = "";
      const embed = h("div", { class: "dp-embed" });
      embed.style.borderLeftColor = toHex(d.color);
      if (r.title) embed.append(h("div", { class: "dp-title", text: r.title }));
      embed.append(h("div", { class: "dp-body", html: renderDiscordMarkdown(r.body) }));
      if (r.footer) embed.append(h("div", { class: "dp-footer", text: r.footer }));
      preview.append(embed);
      toast("Variables résolues avec les données réelles du jeu.");
    } catch (e) { toast(`${e.message}`, "bad"); }
  });

  const pubChk = h("input", { type: "checkbox", style: "width:auto" });
  pubChk.checked = d.publish;
  pubChk.addEventListener("change", () => { d.publish = pubChk.checked; });

  function buildCompose() {
    render();
    return [
      h("div", { class: "toolbar" }, [
        h("h2", {}, "Composer une annonce"),
        h("div", { class: "spacer" }),
        previewBtn, sendBtn,
      ]),
      h("div", { class: "grid2" }, [
        h("div", {}, [
          h("div", { class: "card" }, [
            h("div", { class: "row" }, [
              h("div", { class: "field" }, [h("label", {}, "Modèle"), tplSel]),
              h("div", { class: "field" }, [h("label", {}, "Salon"), chanSel]),
            ]),
            h("div", { class: "field" }, [h("label", {}, "Titre"), titleInp]),
            h("div", { class: "field" }, [h("label", {}, "Message (Markdown Discord)"), bodyArea]),
            h("div", { class: "muted" }, "Clique une variable pour l'insérer au curseur :"),
            varChips,
          ]),
          h("div", { class: "card" }, [
            h("div", { class: "row" }, [
              h("div", { class: "field" }, [h("label", {}, "Ping"), pingSel]),
              h("div", { class: "field" }, [h("label", {}, "Couleur"), colorInp]),
            ]),
            h("div", { class: "field" }, [h("label", {}, "Pied de page"), footInp]),
            h("div", { class: "field" }, [h("label", {}, "Image"), imgInp]),
            h("label", { style: "display:flex;gap:8px;align-items:center;text-transform:none" },
              [pubChk, "Diffuser aux serveurs abonnés (salon Annonces uniquement)"]),
          ]),
        ]),
        h("div", {}, [
          h("h3", {}, "Aperçu"),
          h("div", { class: "muted" },
            "Rendu fidèle. Les variables restent visibles tant que tu ne cliques pas « Résoudre »."),
          preview,
        ]),
      ]),
    ];
  }

  mount(root, ...buildCompose());
}

//  2. MODELES
export function viewTemplates(root, editingId) {
  // `editingId` : id du modele ouvert dans l'editeur, "" pour un nouveau,
  // null pour aucun. C'est ce qui permet d'editer EN PLACE plutot que de
  // devoir passer par le composeur.
  const editing = editingId != null
    ? (state.templates.find((t) => t.id === editingId) || {
        id: "", name: "", channel: "announcements", title: "", body: "",
        color: 5793266, footer: "", image: "", ping: "" })
    : null;

  const rows = state.templates.map((t, i) => h("tr", {}, [
    h("td", {}, h("strong", {}, t.name)),
    h("td", {}, h("span", { class: "tag" }, `#${t.channel}`)),
    h("td", { style: "color:var(--dim)" }, t.title),
    h("td", {}, t.ping ? h("span", { class: "tag" }, `@${t.ping}`) : ""),
    h("td", { style: "text-align:right;white-space:nowrap" }, [
      h("button", { class: "btn", onclick: () => {
        const ch = state.channels.find((c) => c.name === t.channel);
        state.draft = { templateId: t.id, channelId: ch ? ch.id : "", title: t.title,
          body: t.body, color: t.color, footer: t.footer || "", image: t.image || "",
          ping: t.ping || "", publish: false };
        document.querySelector('.nav-item[data-view="compose"]').click();
      } }, "Utiliser"),
      " ",
      h("button", { class: "btn", onclick: () => viewTemplates(root, t.id) }, "Modifier"),
      " ",
      // Duplication : le nouveau modele s'ouvre AUSSITOT dans l'editeur,
      // pre-rempli, pour n'avoir que 2-3 champs a retoucher.
      h("button", { class: "btn", onclick: async () => {
        const copy = { ...t, id: "", name: `${t.name} (copie)` };
        state.templates.push(copy);
        const r = await api.saveTemplates(state.templates);
        state.templates = r.templates;
        const created = state.templates[state.templates.length - 1];
        toast("Copie créée — modifie-la puis enregistre.");
        viewTemplates(root, created.id);
      } }, "⧉ Dupliquer"),
      " ",
      h("button", { class: "btn danger", onclick: async () => {
        if (!confirmAction(`Supprimer le modèle « ${t.name} » ?`)) return;
        state.templates.splice(i, 1);
        const r = await api.saveTemplates(state.templates);
        state.templates = r.templates;
        toast("Modèle supprimé.");
        viewTemplates(root, null);
      } }, "Supprimer"),
    ]),
  ]));

  let editor = null;
  if (editing) {
    const f = {
      name: h("input", { value: editing.name, placeholder: "Nom du modèle" }),
      channel: h("select", {}, state.channels.map((c) =>
        h("option", { value: c.name, selected: c.name === editing.channel ? "selected" : null },
          `#${c.name}`))),
      title: h("input", { value: editing.title }),
      body: h("textarea", {}, editing.body),
      footer: h("input", { value: editing.footer || "" }),
      image: h("input", { value: editing.image || "" }),
      color: h("input", { type: "color", value: toHex(editing.color) }),
      ping: h("select", {}, [
        h("option", { value: "" }, "Aucun ping"),
        h("option", { value: "everyone" }, "@everyone"),
        h("option", { value: "here" }, "@here"),
        ...state.roles.map((r) => h("option", { value: r.id }, `@${r.name}`)),
      ]),
    };
    f.ping.value = editing.ping || "";

    const saveBtn = h("button", { class: "btn primary" }, "Enregistrer");
    saveBtn.addEventListener("click", async () => {
      const name = f.name.value.trim();
      if (!name) return toast("Le modèle doit avoir un nom.", "bad");
      const payload = { id: editing.id, name, channel: f.channel.value,
        title: f.title.value, body: f.body.value, footer: f.footer.value,
        image: f.image.value, color: toDec(f.color.value), ping: f.ping.value };
      const idx = state.templates.findIndex((t) => t.id === editing.id && editing.id);
      if (idx >= 0) state.templates[idx] = payload; else state.templates.push(payload);
      const r = await api.saveTemplates(state.templates);
      state.templates = r.templates;
      toast("Modèle enregistré.");
      viewTemplates(root, null);
    });

    editor = h("div", { class: "card" }, [
      h("h3", {}, editing.id ? `Modifier « ${editing.name} »` : "Nouveau modèle"),
      h("div", { class: "row" }, [
        h("div", { class: "field" }, [h("label", {}, "Nom"), f.name]),
        h("div", { class: "field" }, [h("label", {}, "Salon"), f.channel]),
        h("div", { class: "field" }, [h("label", {}, "Ping"), f.ping]),
        h("div", { class: "field" }, [h("label", {}, "Couleur"), f.color]),
      ]),
      h("div", { class: "field" }, [h("label", {}, "Titre"), f.title]),
      h("div", { class: "field" }, [h("label", {}, "Message"), f.body]),
      h("div", { class: "row" }, [
        h("div", { class: "field" }, [h("label", {}, "Pied de page"), f.footer]),
        h("div", { class: "field" }, [h("label", {}, "Image (URL)"), f.image]),
      ]),
      h("div", { class: "muted" },
        "Variables disponibles : " + state.vars.map((v) => v.key).join(" · ")),
      h("div", { style: "display:flex;gap:8px;margin-top:10px" }, [
        saveBtn,
        h("button", { class: "btn", onclick: () => viewTemplates(root, null) }, "Annuler"),
      ]),
    ]);
  }

  mount(root,
    h("div", { class: "toolbar" }, [
      h("h2", {}, "Bibliothèque de modèles"),
      h("div", { class: "spacer" }),
      h("button", { class: "btn primary", onclick: () => viewTemplates(root, "") },
        "+ Nouveau modèle"),
    ]),
    h("div", { class: "muted" },
      "Les modèles sont partagés avec announce.py — un modèle créé ici est immédiatement utilisable en ligne de commande."),
    editor,
    h("div", { class: "card" },
      state.templates.length
        ? h("table", {}, [
            h("thead", {}, h("tr", {}, ["Nom", "Salon", "Titre", "Ping", ""].map((x) => h("th", {}, x)))),
            h("tbody", {}, rows),
          ])
        : h("div", { class: "empty" }, "Aucun modèle.")),
  );
}

//  3. PLANIFICATEUR
export async function viewSchedule(root) {
  const { schedule } = await api.schedule();

  const rows = schedule.map((s, i) => {
    const tpl = state.templates.find((t) => t.id === s.templateId);
    const due = s.at && new Date(s.at) <= new Date();
    return h("tr", {}, [
      h("td", {}, [s.at?.replace("T", " ") || "—", " ",
        due && !s.done ? h("span", { class: "tag bad" }, "à envoyer") : null]),
      h("td", {}, tpl ? tpl.name : h("span", { style: "color:var(--dim)" }, "modèle supprimé")),
      h("td", {}, h("span", { class: "tag" }, `#${s.channel || tpl?.channel || "?"}`)),
      h("td", { style: "color:var(--dim)" }, s.note || ""),
      h("td", {}, s.done ? h("span", { class: "tag ok" }, "envoyé") : ""),
      h("td", { style: "text-align:right;white-space:nowrap" }, [
        h("button", { class: "btn", onclick: async () => {
          if (!tpl) return toast("Modèle introuvable.", "bad");
          if (!confirmAction(`Envoyer « ${tpl.name} » maintenant ?`)) return;
          const ch = state.channels.find((c) => c.name === (s.channel || tpl.channel));
          try {
            await api.announce({ channelId: ch?.id, title: tpl.title, body: tpl.body,
              color: tpl.color, footer: tpl.footer, image: tpl.image,
              ping: s.ping || tpl.ping });
            schedule[i].done = true;
            await api.saveSchedule(schedule);
            toast("Envoyé.");
            viewSchedule(root);
          } catch (e) { toast(`${e.message}`, "bad"); }
        } }, "Envoyer"),
        " ",
        h("button", { class: "btn danger", onclick: async () => {
          schedule.splice(i, 1);
          await api.saveSchedule(schedule);
          viewSchedule(root);
        } }, "Supprimer"),
      ]),
    ]);
  });

  const atInp = h("input", { type: "datetime-local" });
  const tplSel = h("select", {}, state.templates.map((t) => h("option", { value: t.id }, t.name)));
  const noteInp = h("input", { placeholder: "Note (optionnel)" });
  const addBtn = h("button", { class: "btn primary" }, "+ Planifier");
  addBtn.addEventListener("click", async () => {
    if (!atInp.value) return toast("Choisis une date et une heure.", "bad");
    schedule.push({ id: "", at: atInp.value, templateId: tplSel.value,
      channel: "", ping: "", note: noteInp.value, done: false });
    await api.saveSchedule(schedule);
    toast("Planifié.");
    viewSchedule(root);
  });

  mount(root, 
    h("div", { class: "toolbar" }, [h("h2", {}, "Planificateur")]),
    h("div", { class: "banner" },
      "Rien ne s'envoie tout seul : ton PC n'est pas allumé en permanence, c'est voulu. " +
      "Cette file est ta check-list — ouvre le dashboard et clique « Envoyer » le moment venu. " +
      "Les entrées échues sont marquées en rouge."),
    h("div", { class: "card" },
      schedule.length
        ? h("table", {}, [
            h("thead", {}, h("tr", {}, ["Quand", "Modèle", "Salon", "Note", "État", ""].map((x) => h("th", {}, x)))),
            h("tbody", {}, rows),
          ])
        : h("div", { class: "empty" }, "Rien de planifié.")),
    h("div", { class: "card" }, [
      h("h3", {}, "Ajouter"),
      h("div", { class: "row" }, [
        h("div", { class: "field" }, [h("label", {}, "Date & heure"), atInp]),
        h("div", { class: "field" }, [h("label", {}, "Modèle"), tplSel]),
        h("div", { class: "field" }, [h("label", {}, "Note"), noteInp]),
        h("div", { style: "flex:0;display:flex;align-items:flex-end" }, addBtn),
      ]),
    ]),
  );
}

//  4. HISTORIQUE
// JOURNAL D'AUDIT : tout ce que le CC a fait (envois Discord, ecritures dans le jeu,
// cartes de l'Accueil), garde dans data/cc.db.
const JOURNAL_LABELS = {
  discord_send: "Envoi Discord", card_action: "Carte : action", card_state: "Carte : état",
  boost: "Boost", modes: "Modes", rewards: "Récompenses", give: "Don", wipe: "Wipe",
  ranked_pay: "Ranked", configs: "Configs live", maintenance_purge: "Purge des stash",
  settings: "Réglages", templates: "Modèles", schedule: "Planificateur", arsenal: "Arsenal",
  faction_announce: "Annonce aux factions", announce: "Annonce",
  login: "Connexion", login_denied: "Connexion refusée", webhook: "Webhook Roblox", erasure: "Effacement RTBF",
  automation: "Automatisation : réglage", automation_cancel: "Automatisation annulée", auto_failed: "Automatisation en échec",
  ban: "Ban", unban: "Débannissement", ban_wave: "Vague de bans", restart: "Redémarrage",
};
const JOURNAL_FILTERS = [["", "Tout"], ["discord_send", "Envois Discord"], ["game", "Écritures dans le jeu"], ["card", "Cartes"], ["access", "Accès"]];
const ACCESS_ACTIONS = new Set(["login", "login_denied", "automation", "automation_cancel"]);
const actorLabel = (a) => (!a || a === "local" ? "local" : a === "auto" ? "automatique" : a);
const GAME_ACTIONS = new Set(["boost", "modes", "rewards", "give", "wipe", "ranked_pay", "configs", "maintenance_purge"]);

function journalDetail(e) {
  const d = e.detail;
  if (!d || typeof d !== "object") return String(d || "");
  if (e.action === "discord_send") return [d.title, d.error].filter(Boolean).join(" : ");
  if (e.action === "card_action") return [d.title, d.label || d.action].filter(Boolean).join(" : ");
  if (e.action === "card_state") {
    const st = { done: "faite", dismissed: "ignorée", open: "rouverte" }[d.state]
      || (d.state === "snoozed" && d.until ? `repoussée au ${fmtDate(d.until)}` : d.state);
    return [d.title, st].filter(Boolean).join(" : ");
  }
  return Object.entries(d).filter(([, v]) => v !== "" && v != null).slice(0, 6)
    .map(([k, v]) => `${k} ${typeof v === "object" ? JSON.stringify(v) : v}`).join(", ").slice(0, 220);
}

export async function viewHistory(root) {
  const { rows } = await api.journal(500);
  const seg = h("div", { class: "seg", role: "group", "aria-label": "Filtre" });
  const body = h("div", { class: "card" });
  let filter = "";
  const render = () => {
    seg.replaceChildren(...JOURNAL_FILTERS.map(([id, label]) => {
      const b = h("button", { class: filter === id ? "on" : "" }, label);
      b.addEventListener("click", () => { filter = id; render(); });
      return b;
    }));
    const shown = rows.filter((e) => !filter || (filter === "game" ? GAME_ACTIONS.has(e.action)
      : filter === "card" ? e.action.startsWith("card_") : filter === "access" ? ACCESS_ACTIONS.has(e.action)
      : e.action === filter));
    mount(body, shown.length
      ? h("table", {}, [
          h("thead", {}, h("tr", {}, ["Quand", "Qui", "Action", "Cible", "Détail", "État"].map((x) => h("th", {}, x)))),
          h("tbody", {}, shown.map((e) => h("tr", {}, [
            h("td", { style: "white-space:nowrap" }, fmtDate(e.at)),
            h("td", { class: "j-actor" }, actorLabel(e.actor)),
            h("td", {}, JOURNAL_LABELS[e.action] || e.action),
            h("td", {}, e.action === "discord_send" && e.target ? h("span", { class: "tag" }, `#${e.target}`)
              : e.action.startsWith("card_") ? h("a", { href: "#home" }, "Accueil") : (e.target || "—")),
            h("td", { style: "color:var(--dim)" }, journalDetail(e) || "—"),
            h("td", {}, e.ok ? h("span", { class: "tag ok" }, "OK") : h("span", { class: "tag bad" }, "échec")),
          ]))),
        ])
      : h("div", { class: "empty" }, "Rien dans le journal pour ce filtre."));
  };
  mount(root,
    h("div", { class: "toolbar" }, [h("h2", {}, "Journal"), h("div", { class: "spacer" }), seg]),
    h("div", { class: "muted", style: "margin:-6px 0 16px;max-width:78ch" },
      "Tout ce que le Command Center a fait : annonces Discord, écritures dans le jeu (boosts, modes, dons...) "
      + "et cartes de l'Accueil traitées. Utile pour ne pas poster deux fois et pour savoir qui a changé quoi."),
    body);
  render();
}

//  5. FACTION WAR
export async function viewFactionWar(root) {
  mount(root, h("div", { class: "empty" }, "Lecture des scores…"));
  let fw;
  try {
    fw = await api.factionWar();
  } catch (e) {
    mount(root, 
      h("div", { class: "toolbar" }, [h("h2", {}, "Faction War")]),
      h("div", { class: "banner bad" }, `Lecture impossible : ${e.message}`),
      h("div", { class: "muted" },
        "Le panneau a besoin d'une clé Open Cloud avec la permission « datastores: read » sur ton universe."),
    );
    return;
  }

  // Decalage d'affichage UNIQUEMENT : le numero reel sert de cle DataStore et
  // ne doit jamais changer (voir le Guide). On ne touche que le libelle.
  const settings = (await api.settings()).settings || {};
  const labelOffset = Number(settings.seasonLabelOffset || 0);
  const labelPrefix = settings.seasonLabelPrefix || "Semaine";

  const { Rusfor, Rainor } = fw.totals;
  const total = Rusfor + Rainor;
  const pctR = total ? (Rusfor / total) * 100 : 50;
  const localClose = new Date(fw.endsAt * 1000).toLocaleString(undefined, {
    weekday: "short", day: "2-digit", month: "2-digit",
    hour: "2-digit", minute: "2-digit", timeZoneName: "short",
  });

  const bar = h("div", { class: "fw-bar" }, [
    h("div", { class: "fw-seg fw-rusfor", style: `width:${pctR}%` }, Rusfor > 0 ? String(Rusfor) : ""),
    h("div", { class: "fw-seg fw-rainor", style: `width:${100 - pctR}%` }, Rainor > 0 ? String(Rainor) : ""),
  ]);

  const topTable = (faction, color) => {
    const rows = fw.tops[faction] || [];
    return h("div", { class: "card" }, [
      h("h3", { style: `color:${color}` }, `Top ${faction}`),
      rows.length
        ? h("table", {}, [
            h("thead", {}, h("tr", {}, ["#", "Joueur", "Points"].map((x) => h("th", {}, x)))),
            h("tbody", {}, rows.map((r) => h("tr", {}, [
              h("td", {}, String(r.rank)),
              h("td", {}, r.name),
              h("td", {}, String(r.points)),
            ]))),
          ])
        // Un classement inaccessible ne doit pas ressembler a un classement vide.
        : h("div", { class: "empty" },
            fw.topsError ? "Classement inaccessible (voir l'avertissement ci-dessus)."
                         : "Aucune contribution cette semaine."),
    ]);
  };

  // Annonce PAR FACTION : chaque camp recoit son propre message (victoire ou
  // defaite) dans son salon prive, avec son propre top.
  const facBtn = h("button", { class: "btn" }, "Annoncer aux 2 factions");
  facBtn.addEventListener("click", async () => {
    if (!confirmAction("Poster le résultat de saison dans le salon de CHAQUE faction ?\n\n" +
        "Le vainqueur reçoit un message de victoire, l'autre un message de défaite.")) return;
    try {
      const r = await api.announceFactions();
      const ok = r.results.filter((x) => x.sent).map((x) => x.faction);
      const ko = r.results.filter((x) => !x.sent);
      if (ko.length) {
        toast(`${ok.length}/2 envoyés — ${ko.map((x) => x.faction + " : " + x.reason).join(" · ")}`, "bad");
      } else {
        toast(`Annoncé aux 2 factions (vainqueur : ${r.winner || "égalité"}).`);
      }
    } catch (e) { toast(`${e.message}`, "bad"); }
  });

  const postBtn = h("button", { class: "btn primary" }, "Publier le classement");
  postBtn.addEventListener("click", async () => {
    const tpl = state.templates.find((t) => t.id === "factionwar");
    if (!tpl) return toast("Modèle « factionwar » introuvable.", "bad");
    const ch = state.channels.find((c) => c.name === tpl.channel);
    if (!ch) return toast(`Salon #${tpl.channel} introuvable.`, "bad");
    if (!confirmAction(`Publier le classement dans #${ch.name} ?`)) return;
    try {
      await api.announce({ channelId: ch.id, title: tpl.title, body: tpl.body,
        color: tpl.color, footer: tpl.footer, ping: tpl.ping });
      toast("Classement publié (variables résolues à l'envoi).");
    } catch (e) { toast(`${e.message}`, "bad"); }
  });

  mount(root, 
    h("div", { class: "toolbar" }, [
      h("h2", {}, "Faction War"),
      h("div", { class: "spacer" }),
      facBtn, postBtn,
    ]),
    h("div", { class: "card" }, [
      h("div", { class: "stats" }, [
        h("div", { class: "stat" }, [
          h("div", { class: "stat-v" }, `${labelPrefix} ${(fw.season ?? fw.week + 1) - labelOffset}`),
          h("div", { class: "stat-l" }, `Index technique ${fw.week}`),
        ]),
        h("div", { class: "stat" }, [
          h("div", { class: "stat-v" }, fmtDuration(fw.remaining)),
          h("div", { class: "stat-l" }, "Avant clôture"),
        ]),
        h("div", { class: "stat" }, [
          h("div", { class: "stat-v" }, localClose),
          h("div", { class: "stat-l" }, "Clôture dans votre fuseau"),
        ]),
        h("div", { class: "stat" }, [
          h("div", { class: "stat-v", style: `color:${fw.leader === "Rusfor" ? "var(--rusfor)" : fw.leader === "Rainor" ? "var(--rainor)" : "var(--dim)"}` },
            fw.leader || "Égalité"),
          h("div", { class: "stat-l" }, `En tête · écart ${fw.spread}`),
        ]),
      ]),
      bar,
      h("div", { class: "fw-meta" }, [
        h("span", { style: "color:var(--rusfor)" }, `Rusfor — ${Rusfor} pts`),
        h("span", { style: "color:var(--rainor)" }, `Rainor — ${Rainor} pts`),
      ]),
    ]),
    fw.topsError
      ? h("div", { class: "banner" },
          `Classements indisponibles : ${fw.topsError}`)
      : null,
    h("div", { class: "grid2" }, [topTable("Rusfor", "var(--rusfor)"), topTable("Rainor", "var(--rainor)")]),
    h("div", { class: "muted" },
      "Seuls EXFIL et OPERATIONS marquent des points (FactionWarConfig.scoring). " +
      "La semaine se clôture toute seule côté serveur, au premier joueur connecté après l'échéance."),
    (() => {
      const offInp = h("input", { type: "number", value: String(labelOffset), style: "max-width:140px" });
      const preInp = h("input", { value: labelPrefix, style: "max-width:180px" });
      const btn = h("button", { class: "btn primary" }, "Appliquer l'affichage");
      btn.addEventListener("click", async () => {
        await api.saveSettings({ seasonLabelOffset: +offInp.value,
                                 seasonLabelPrefix: preInp.value });
        toast("Libellé mis à jour (affichage uniquement).");
        viewFactionWar(root);
      });
      return h("div", { class: "card" }, [
        h("h3", {}, "Libellé de saison"),
        h("div", { class: "muted" },
          "L'époque du jeu est calée sur le 05/09/2026 à 18h00 (France) : la saison 1 tombe juste, décalage 0. " +
          "Ce réglage ne sert qu'à renuméroter l'affichage plus tard — il ne touche jamais au stockage."),
        h("div", { class: "row", style: "margin-top:10px" }, [
          h("div", { class: "field" }, [h("label", {}, "Préfixe"), preInp]),
          h("div", { class: "field" }, [h("label", {}, "Décalage"), offInp]),
          h("div", { style: "flex:0;display:flex;align-items:flex-end" }, btn),
        ]),
      ]);
    })(),
  );
}

//  5bis. RANKED (ladder LP permanent des DUALS)
export async function viewRanked(root) {
  mount(root, h("div", { class: "empty" }, "Lecture du classement…"));
  const plan = await api.rankedPreview();
  const rows = plan.rows || [];
  const tiers = plan.tiers || [];
  const medal = (r) => "#" + r;

  // --- bareme editable ---
  const tf = tiers.map((t) => ({
    maxRank: h("input", { type: "number", min: "1", value: String(t.maxRank) }),
    gold: h("input", { type: "number", min: "0", value: String(t.gold) }),
    xp: h("input", { type: "number", min: "0", value: String(t.xp) }),
    title: h("input", { value: t.title || "", placeholder: "S%d RANKED TOP 3" }),
    badges: h("input", { value: (t.badges || []).join(", "), placeholder: "ex: 123, 456" }),
  }));
  const saveTiersBtn = h("button", { class: "btn" }, "Enregistrer le barème");
  saveTiersBtn.addEventListener("click", async () => {
    try {
      await api.saveRankedTiers(tf.map((f) => ({
        maxRank: +f.maxRank.value, gold: +f.gold.value,
        xp: +f.xp.value, title: f.title.value.trim(),
        badges: f.badges.value })));
      toast("Barème enregistré.");
      viewRanked(root);
    } catch (e) { toast("" + e.message, "bad"); }
  });

  // Preavis : a publier ~24h AVANT de verser. L'avertissement anti-AFK dans
  // l'annonce du versement arriverait trop tard -- les joueurs inactifs
  // auraient deja rate la fenetre.
  const warnBtn = h("button", { class: "btn" }, "Annoncer le versement (24h)");
  warnBtn.addEventListener("click", async () => {
    const tpl = state.templates.find((t) => t.id === "ranked_incoming");
    if (!tpl) return toast("Modèle « ranked_incoming » introuvable.", "bad");
    const ch = state.channels.find((c) => c.name === tpl.channel);
    if (!ch) return toast(`Salon #${tpl.channel} introuvable.`, "bad");
    if (!confirmAction(`Publier le préavis dans #${ch.name} ?

` +
        "À faire ~24h AVANT la clôture automatique, pour laisser aux joueurs le temps de se connecter.")) return;
    try {
      await api.announce({ channelId: ch.id, title: tpl.title, body: tpl.body,
        color: tpl.color, footer: tpl.footer, ping: tpl.ping });
      toast("Préavis publié — verse dans ~24h.");
    } catch (e) { toast("" + e.message, "bad"); }
  });

  const postBtn = h("button", { class: "btn" }, "Publier le top 10");
  postBtn.addEventListener("click", async () => {
    const tpl = state.templates.find((t) => t.id === "ranked");
    if (!tpl) return toast("Modèle « ranked » introuvable.", "bad");
    const ch = state.channels.find((c) => c.name === tpl.channel);
    if (!ch) return toast(`Salon #${tpl.channel} introuvable.`, "bad");
    if (!confirmAction(`Publier le top 10 dans #${ch.name} ?`)) return;
    try {
      await api.announce({ channelId: ch.id, title: tpl.title, body: tpl.body,
        color: tpl.color, footer: tpl.footer, ping: tpl.ping });
      toast("Classement publié.");
    } catch (e) { toast("" + e.message, "bad"); }
  });

  const last = plan.lastPayout;

  mount(root,
    h("div", { class: "toolbar" }, [
      h("h2", {}, "Classement ranked (DUALS)"),
      h("div", { class: "spacer" }),
      warnBtn, postBtn,
    ]),
    h("div", { class: "muted" },
      "Ladder LP global et PERMANENT — il ne se réinitialise jamais. " +
      "Un snapshot récompensé est créé automatiquement à chaque clôture de saison."),
    h("div", { class: "banner" },
      "Clôture automatique le samedi à 18h (France). Publie le préavis ~24h avant : " +
      "un joueur inactif depuis la saison précédente ne recevra pas le nouveau versement."),
    plan.error ? h("div", { class: "banner" }, "" + plan.error) : null,
    last ? h("div", { class: "muted" },
      `Dernier versement : ${new Date(last.at * 1000).toLocaleString("fr-FR")} · ${last.count} joueur(s) · id ${last.id}`) : null,
    h("div", { class: "card" }, [
      h("h3", {}, "Aperçu de la prochaine clôture"),
      rows.length
        ? h("table", {}, [
            h("thead", {}, h("tr", {}, ["Rang", "Faction", "Joueur", "LP", "Or", "XP", "Titre"].map((x) => h("th", {}, x)))),
            h("tbody", {}, rows.map((r) => h("tr", {}, [
              h("td", {}, medal(r.rank)),
              h("td", {}, r.faction || "—"),
              h("td", {}, r.name),
              h("td", {}, String(r.lp)),
              h("td", {}, h("strong", {}, String(r.gold))),
              h("td", {}, String(r.xp)),
              h("td", { style: "color:var(--dim)" }, r.title || "—"),
            ]))),
          ])
        : h("div", { class: "empty" },
            plan.error
              ? "Classement inaccessible — corrige la permission ci-dessus."
              : "Aucun joueur classé. Le ladder se remplit au premier match DUALS terminé."),
      h("div", { class: "muted" },
        "Le snapshot et son bordereau sont immuables et exactement-once, même si plusieurs serveurs clôturent ensemble."),
    ]),
    h("div", { class: "card" }, [
      h("h3", {}, "Barème par rang"),
      h("div", { class: "muted" },
        "Persistant entre toutes les saisons. Le premier palier dont le rang max couvre le joueur s'applique."),
      h("table", {}, [
        h("thead", {}, h("tr", {}, ["Rang max", "Or", "XP", "Titre", "Badges"].map((x) => h("th", {}, x)))),
        h("tbody", {}, tf.map((f) => h("tr", {}, [
          h("td", {}, f.maxRank), h("td", {}, f.gold), h("td", {}, f.xp), h("td", {}, f.title),
          h("td", {}, f.badges),
        ]))),
      ]),
      h("div", { class: "muted" },
        "Badges : ids séparés par des virgules, 5 maximum. Le badge doit appartenir à cette expérience."),
      h("div", { style: "margin-top:12px" }, saveTiersBtn),
    ]),
  );
}

//  6. BOOSTS  (equivalent web de /boost en jeu)
export function viewBoost(root) {
  const b = state.status?.boost;
  const active = b && !b.expired;

  const xp = h("input", { type: "number", step: "0.1", min: "1", max: "5", value: "2" });
  const gold = h("input", { type: "number", step: "0.1", min: "1", max: "5", value: "1.5" });
  const war = h("input", { type: "number", step: "0.1", min: "1", max: "5", value: "1" });
  const mins = h("input", { type: "number", min: "1", max: "20160", value: "1440" });
  const name = h("input", { value: "LAUNCH WEEK", placeholder: "Nom du boost" });

  // Annonce Discord optionnelle. Cochee par defaut : quand on lance un boost,
  // on veut presque toujours que les joueurs le sachent.
  const annChk = h("input", { type: "checkbox", style: "width:auto" });
  annChk.checked = true;

  /** Un boost reussi mais une annonce ratee doit se voir comme tel, pas comme
   *  un echec global : le boost EST actif. */
  const reportDiscord = (r, okMsg) => {
    if (r.discord && r.discord.sent === false) {
      toast(`${okMsg} — mais l'annonce Discord a échoué : ${r.discord.reason}`, "bad");
    } else if (r.discord && r.discord.sent) {
      toast(`${okMsg} · annoncé dans #${r.discord.channel}`);
    } else {
      toast(okMsg);
    }
  };

  const applyBtn = h("button", { class: "btn primary" }, "Activer le boost");
  applyBtn.addEventListener("click", async () => {
    if (!confirmAction(`Activer « ${name.value} » sur TOUS les serveurs live ?` +
        (annChk.checked ? "\n\nUne annonce sera postée sur Discord." : ""))) return;
    applyBtn.disabled = true;
    try {
      const r = await api.boost({ xp: +xp.value, gold: +gold.value, war: +war.value,
        minutes: +mins.value, name: name.value, announce: annChk.checked });
      reportDiscord(r, "Boost actif — poussé aux serveurs en cours de partie.");
      state.status = await api.status();
      viewBoost(root);
    } catch (e) { toast(`${e.message}`, "bad"); applyBtn.disabled = false; }
  });

  const clearBtn = h("button", { class: "btn danger" }, "Couper le boost");
  clearBtn.addEventListener("click", async () => {
    if (!confirmAction("Couper le boost en cours ?")) return;
    try {
      const r = await api.boost({ action: "clear", announce: annChk.checked });
      reportDiscord(r, "Boost coupé.");
      state.status = await api.status();
      viewBoost(root);
    } catch (e) { toast(`${e.message}`, "bad"); }
  });

  const current = active
    ? h("div", { class: "card" }, [
        h("h3", {}, `Boost actif — ${b.name}`),
        h("div", { class: "stats" }, [
          h("div", { class: "stat" }, [h("div", { class: "stat-v" }, `×${b.xpMult}`), h("div", { class: "stat-l" }, "XP")]),
          h("div", { class: "stat" }, [h("div", { class: "stat-v" }, `×${b.goldMult}`), h("div", { class: "stat-l" }, "Or")]),
          h("div", { class: "stat" }, [h("div", { class: "stat-v" }, `×${b.factionPointMult}`), h("div", { class: "stat-l" }, "Guerre")]),
          h("div", { class: "stat" }, [h("div", { class: "stat-v" }, fmtDuration(b.remaining)), h("div", { class: "stat-l" }, "Restant")]),
        ]),
        clearBtn,
      ])
    : h("div", { class: "card" }, [
        h("h3", {}, "Aucun boost actif"),
        h("div", { class: "muted" }, b?.expired ? "Le dernier boost a expiré." : "Le jeu applique les événements planifiés."),
      ]);

  mount(root, 
    h("div", { class: "toolbar" }, [h("h2", {}, "Boosts en direct")]),
    h("div", { class: "muted" },
      "Équivalent web de la commande /boost. Écrit dans le DataStore FactionWar versionné du jeu puis publie sur " +
      "le topic FW_Event : les serveurs déjà lancés l'appliquent en moins d'une seconde."),
    state.status?.boostOk === false
      ? h("div", { class: "banner bad" }, `Open Cloud indisponible : ${state.status.boostError || "clé manquante"}`)
      : null,
    current,
    h("div", { class: "card" }, [
      h("h3", {}, "Nouveau boost"),
      h("div", { class: "row" }, [
        h("div", { class: "field" }, [h("label", {}, "XP ×"), xp]),
        h("div", { class: "field" }, [h("label", {}, "Or ×"), gold]),
        h("div", { class: "field" }, [h("label", {}, "Guerre ×"), war]),
        h("div", { class: "field" }, [h("label", {}, "Durée (min)"), mins]),
      ]),
      h("div", { class: "field" }, [h("label", {}, "Nom"), name]),
      h("label", { style: "display:flex;gap:8px;align-items:center;text-transform:none;margin-bottom:12px" },
        [annChk, "Annoncer sur Discord (modèle « Boost activé »)"]),
      h("div", { class: "muted" }, "Multiplicateurs bornés à ×5 et 14 jours, comme en jeu. Tout à ×1 est refusé (utilise « Couper »)."),
      h("div", { class: "muted" }, "Les joueurs déjà en partie sont notifiés automatiquement en jeu (bannière + toast)."),
      applyBtn,
    ]),
  );
}

//  6b. GIVE  (cadeaux admin : or/XP/kits/items a des joueurs)
export function viewGive(root) {
  // Audience
  const audience = h("select", {}, [
    h("option", { value: "users" }, "Joueurs (pseudos/ids)"),
    h("option", { value: "online" }, "Tous les connectés"),
    h("option", { value: "active" }, "Actifs cette semaine"),
  ]);
  const users = h("input", { placeholder: "@pseudo1, @pseudo2, 123456…" });
  // Ouvert depuis une fiche joueur (bouton Don) : destinataire deja rempli.
  let prefilled = "";
  try { prefilled = sessionStorage.getItem("cc.give.users") || ""; sessionStorage.removeItem("cc.give.users"); } catch { /* stockage indisponible */ }
  users.value = prefilled;
  const usersField = h("div", { class: "field" }, [
    h("label", {}, "Destinataires"),
    users,
    h("div", { class: "muted", style: "margin-top:4px" },
      "Nom d'UTILISATEUR (@pseudo), pas le nom affiché. Ou colle directement l'userId. "
      + "Clique « Aperçu » pour vérifier qui est ciblé avant d'envoyer."),
  ]);

  const gold = h("input", { type: "number", min: "0", max: "50000", value: "0" });
  const xp = h("input", { type: "number", min: "0", max: "25000", value: "0" });
  const kits = h("input", { placeholder: "kit_war_supply, …" });
  const items = h("input", { placeholder: "AK74, Medkit, …" });
  const title = h("input", { placeholder: "(titre optionnel)" });
  const badges = h("input", { placeholder: "ids de badge, séparés par des virgules" });

  const previewBox = h("div", { class: "muted" }, "Renseigne un cadeau puis « Aperçu ».");

  const toggleUsers = () => { usersField.style.display = audience.value === "users" ? "" : "none"; };
  audience.addEventListener("change", toggleUsers);
  toggleUsers();

  const payload = () => ({
    audience: audience.value,
    users: users.value,
    gold: +gold.value, xp: +xp.value,
    kits: kits.value, items: items.value,
    title: title.value, badges: badges.value,
  });

  const previewBtn = h("button", { class: "btn" }, "Aperçu");
  previewBtn.addEventListener("click", async () => {
    previewBox.textContent = "Calcul…";
    try {
      const r = await api.givePreview(payload());
      if (!r.ok) { previewBox.textContent = `${r.error}`; return; }
      const rw = r.reward || {};
      const parts = [];
      if (rw.gold) parts.push(`${rw.gold} or`);
      if (rw.xp) parts.push(`${rw.xp} XP`);
      if (rw.kits?.length) parts.push(`kits: ${rw.kits.join(", ")}`);
      if (rw.items?.length) parts.push(`items: ${rw.items.join(", ")}`);
      if (rw.badges?.length) parts.push(`badges: ${rw.badges.join(", ")}`);
      if (rw.title) parts.push(`titre « ${rw.title} »`);
      const who = r.targetCount != null ? `${r.targetCount} joueur(s)` : "tous les connectés (à l'envoi)";
      previewBox.replaceChildren(
        h("div", {}, `${who} : ${parts.join(" · ")}`),
        r.resolved?.length
          ? h("div", { style: "margin-top:4px" }, "Ciblés : " + r.resolved.map((u) => `${u.name} (#${u.userId})`).join(", "))
          : null,
        r.unresolved?.length ? h("div", { class: "tag bad" }, `introuvables : ${r.unresolved.join(", ")}`) : null,
        r.hubNote ? h("div", { class: "muted" }, `${r.hubNote}`) : null,
        r.note ? h("div", { class: "muted" }, r.note) : null,
      );
    } catch (e) { previewBox.textContent = `${e.message}`; }
  });

  const sendBtn = h("button", { class: "btn primary" }, "Envoyer le cadeau");
  sendBtn.addEventListener("click", async () => {
    if (!confirmAction("Envoyer ce cadeau ? Il sera distribué en jeu (idempotent : "
        + "renvoyer ne double pas).")) return;
    sendBtn.disabled = true;
    try {
      const r = await api.give(payload());
      if (!r.ok) { toast(`${r.error}`, "bad"); sendBtn.disabled = false; return; }
      const who = r.targetCount != null ? `${r.targetCount} joueur(s)` : "les connectés";
      toast(`Cadeau envoyé à ${who}.`);
      if (r.unresolved?.length) toast(`Introuvables ignorés : ${r.unresolved.join(", ")}`, "bad");
    } catch (e) { toast(`${e.message}`, "bad"); }
    sendBtn.disabled = false;
  });

  mount(root,
    h("div", { class: "toolbar" }, [h("h2", {}, "Give — cadeaux admin")]),
    h("div", { class: "muted" },
      "Or / XP / kits / items / badges / titre à un ou plusieurs joueurs. Même mécanique "
      + "idempotente que les versements ranked : bordereau immuable + publish FW_Event. "
      + "Les hors-ligne le reçoivent à leur retour ; « en ligne » est immédiat."),
    state.status?.boostOk === false
      ? h("div", { class: "banner bad" }, `Open Cloud indisponible : ${state.status.boostError || "clé manquante"}`)
      : null,
    h("div", { class: "card" }, [
      h("h3", {}, "Destinataires"),
      h("div", { class: "field" }, [h("label", {}, "Audience"), audience]),
      usersField,
    ]),
    h("div", { class: "card" }, [
      h("h3", {}, "Cadeau"),
      h("div", { class: "row" }, [
        h("div", { class: "field" }, [h("label", {}, "Or"), gold]),
        h("div", { class: "field" }, [h("label", {}, "XP"), xp]),
      ]),
      h("div", { class: "field" }, [h("label", {}, "Kits (ids)"), kits]),
      h("div", { class: "field" }, [h("label", {}, "Items"), items]),
      h("div", { class: "row" }, [
        h("div", { class: "field" }, [h("label", {}, "Titre"), title]),
        h("div", { class: "field" }, [h("label", {}, "Badges"), badges]),
      ]),
      h("div", { class: "muted" }, "Plafonds : 50 000 or, 25 000 XP, 5 badges (mêmes bornes qu'en jeu). "
        + "Items/kits : réclamés au HUB uniquement (en raid ils seraient effacés)."),
      h("div", { style: "display:flex;gap:8px" }, [previewBtn, sendBtn]),
      previewBox,
    ]),
    // -- WIPE (destructif) --
    (function () {
      const wUsers = h("input", { placeholder: "Pseudo1, Pseudo2, 123456…" });
  wUsers.value = prefilled;
      const wAud = h("select", {}, [
        h("option", { value: "users" }, "Joueurs (liste)"),
        h("option", { value: "online" }, "Tous les connectés (au Hub)"),
      ]);
      const wUsersField = h("div", { class: "field" }, [h("label", {}, "Cibles"), wUsers]);
      const toggleW = () => { wUsersField.style.display = wAud.value === "users" ? "" : "none"; };
      wAud.addEventListener("change", toggleW); toggleW();

      const wipeBtn = h("button", { class: "btn danger" }, "WIPE (inventaire + stash + équipé)");
      wipeBtn.addEventListener("click", async () => {
        const aud = wAud.value;
        const conf = aud === "online"
          ? "WIPER tous les joueurs connectés au Hub ? DESTRUCTIF et irréversible."
          : `WIPER « ${wUsers.value} » ? DESTRUCTIF et irréversible.`;
        if (!confirmAction(conf)) return;
        wipeBtn.disabled = true;
        try {
          const r = await api.wipe({ audience: aud, users: wUsers.value });
          if (!r.ok) toast("" + r.error, "bad");
          else {
            const who = r.targetCount != null ? `${r.targetCount} joueur(s)` : "les connectés";
            toast(`Wipe envoyé pour ${who}.`);
            if (r.unresolved?.length) toast(`Introuvables : ${r.unresolved.join(", ")}`, "bad");
          }
        } catch (e) { toast("" + e.message, "bad"); }
        wipeBtn.disabled = false;
      });

      return h("div", { class: "card" }, [
        h("h3", { style: "color:var(--danger,#e74c3c)" }, "Wipe joueur (destructif)"),
        h("div", { class: "muted" }, "Vide l'inventaire courant, l'équipé ET le stash. Idempotent "
          + "et offline-safe (un joueur en raid est wipé à son retour au Hub). Irréversible."),
        h("div", { class: "field" }, [h("label", {}, "Audience"), wAud]),
        wUsersField,
        wipeBtn,
      ]);
    })(),
  );
}

//  6d. MODES  (disponibilite UP + niveau min, via DataStore)
export async function viewModes(root) {
  mount(root, h("div", { class: "empty" }, "Chargement…"));
  const data = await api.modes();
  const vals = data.values || {};
  const labels = data.labels || {};
  const ids = data.modeIds || Object.keys(vals);

  const rows = {};
  const cards = ids.map((id) => {
    const v = vals[id] || { up: true, minLevel: 0 };
    const up = h("input", { type: "checkbox", style: "width:auto" });
    up.checked = id === "operations"
      ? v.up !== false && Number(v.endsAt || 0) > Math.floor(Date.now() / 1000)
      : v.up !== false;
    const lvl = h("input", { type: "number", min: "0", max: "1000", value: String(v.minLevel || 0),
      style: "width:90px" });
    const remainingHours = Math.max(1, Math.ceil((Number(v.endsAt || 0) - Date.now() / 1000) / 3600));
    const duration = id === "operations"
      ? h("input", { type: "number", min: "1", max: "336", value: String(remainingHours), style: "width:90px" })
      : null;
    rows[id] = { up, lvl, duration };
    return h("div", { class: "card" }, [
      h("h3", {}, labels[id] || id),
      h("label", { style: "display:flex;gap:8px;align-items:center;text-transform:none;margin-bottom:8px" },
        [up, id === "operations"
          ? "Événement actif (décoché par défaut)"
          : "Disponible (décoché = « Soon », mode masqué/bloqué)"]),
      h("div", { class: "field" }, [h("label", {}, "Niveau minimum pour lancer"), lvl]),
      duration ? h("div", { class: "field" }, [h("label", {}, "Durée à partir de l'activation (heures)"), duration]) : null,
    ]);
  });

  const payload = () => {
    const out = {};
    for (const id of ids) {
      out[id] = { up: rows[id].up.checked, minLevel: +rows[id].lvl.value };
      if (id === "operations") {
        out[id].endsAt = rows[id].up.checked
          ? Math.floor(Date.now() / 1000) + Math.max(1, +rows[id].duration.value || 1) * 3600
          : 0;
      }
    }
    return out;
  };

  const saveBtn = h("button", { class: "btn primary" }, "Appliquer");
  saveBtn.addEventListener("click", async () => {
    if (!confirmAction("Appliquer la disponibilité des modes ? Poussé aux serveurs en cours.")) return;
    saveBtn.disabled = true;
    try {
      const r = await api.saveModes(payload());
      if (!r.ok) toast("" + r.error, "bad");
      else toast("Modes mis à jour — poussés aux serveurs.");
    } catch (e) { toast("" + e.message, "bad"); }
    saveBtn.disabled = false;
  });

  const resetBtn = h("button", { class: "btn danger" }, "Revenir aux défauts");
  resetBtn.addEventListener("click", async () => {
    if (!confirmAction("Revenir aux valeurs par défaut (Domination active, Operations désactivé) ?")) return;
    try { await api.resetModes(); toast("Réinitialisé."); viewModes(root); }
    catch (e) { toast("" + e.message, "bad"); }
  });

  mount(root,
    h("div", { class: "toolbar" }, [h("h2", {}, "Modes de jeu")]),
    h("div", { class: "muted" },
      "Active/désactive chaque mode et fixe son niveau minimum. Operations est un événement minuté : "
      + "son bouton clignotant n'apparaît sous PLAY que pendant la durée choisie. Un mode désactivé "
      + "s'affiche « Soon » dans le menu et n'est plus composé. Écrit dans le DataStore FactionWar versionné "
      + "puis publié sur FW_Event (comme les boosts) — pas besoin du scope ConfigService."),
    data.error ? h("div", { class: "banner bad" }, data.error) : null,
    ...cards,
    h("div", { style: "display:flex;gap:8px" }, [saveBtn, resetBtn]),
    maintenanceCard(),
  );
}

// -- Maintenance : purge des stash inactifs (dans le panneau Modes) --
function maintenanceCard() {
  const months = h("input", { type: "number", min: "1", max: "60", value: "3", style: "width:80px" });
  const maxKeys = h("input", { type: "number", min: "1", max: "100", value: "100", style: "width:80px" });
  const out = h("div", { class: "muted" }, "Scanne une page de stash et liste les inactifs.");
  let cursor = null;
  let selected = new Set();

  const renderList = (res) => {
    selected = new Set((res.candidates || []).map((c) => c.userId));
    const rows = (res.candidates || []).map((c) =>
      h("label", { style: "display:flex;gap:8px;align-items:center;text-transform:none" }, [
        (() => { const cb = h("input", { type: "checkbox", style: "width:auto" }); cb.checked = true;
          cb.addEventListener("change", () => { if (cb.checked) selected.add(c.userId); else selected.delete(c.userId); });
          return cb; })(),
        h("span", {}, `${c.name} (#${c.userId}) — inactif ${c.daysInactive} j`),
      ]));
    out.replaceChildren(
      h("div", {}, `${res.scanned} clé(s) scannée(s), ${(res.candidates || []).length} candidat(s). `
        + (res.cursor ? "Page suivante disponible." : "Fin de liste.")),
      ...rows);
  };

  const scanBtn = h("button", { class: "btn" }, "Scanner");
  scanBtn.addEventListener("click", async () => {
    scanBtn.disabled = true; cursor = null;
    try {
      const r = await api.maintScan({ months: +months.value, cursor: null, maxKeys: +maxKeys.value });
      if (!r.ok) toast("" + (r.error || "scan"), "bad"); else { cursor = r.cursor; renderList(r); }
    } catch (e) { toast("" + e.message, "bad"); }
    scanBtn.disabled = false;
  });
  const moreBtn = h("button", { class: "btn" }, "Page suivante");
  moreBtn.addEventListener("click", async () => {
    if (!cursor) return toast("Pas de page suivante.", "bad");
    try {
      const r = await api.maintScan({ months: +months.value, cursor, maxKeys: +maxKeys.value });
      if (!r.ok) toast("" + (r.error || "scan"), "bad"); else { cursor = r.cursor; renderList(r); }
    } catch (e) { toast("" + e.message, "bad"); }
  });
  const purgeBtn = h("button", { class: "btn danger" }, "Purger la sélection");
  purgeBtn.addEventListener("click", async () => {
    const ids = [...selected];
    if (ids.length === 0) return toast("Aucun stash sélectionné.", "bad");
    if (!confirmAction(`Supprimer DÉFINITIVEMENT ${ids.length} stash inactif(s) ?`)) return;
    purgeBtn.disabled = true;
    try {
      const r = await api.maintPurge(ids);
      toast(`${r.deleted} stash supprimé(s)` + (r.failed?.length ? `, ${r.failed.length} échec(s)` : "") + ".");
    } catch (e) { toast("" + e.message, "bad"); }
    purgeBtn.disabled = false;
  });

  return h("div", { class: "card" }, [
    h("h3", {}, "Purge des stash inactifs"),
    h("div", { class: "muted" }, "Supprime le stash des joueurs sans connexion depuis N mois. "
      + "Scan borné (une page à la fois) + suppression sur sélection explicite. Irréversible."),
    h("div", { class: "row" }, [
      h("div", { class: "field" }, [h("label", {}, "Inactif depuis (mois)"), months]),
      h("div", { class: "field" }, [h("label", {}, "Clés par page"), maxKeys]),
    ]),
    h("div", { style: "display:flex;gap:8px" }, [scanBtn, moreBtn, purgeBtn]),
    out,
  ]);
}

//  6c. CONFIGS  (ConfigService live via Open Cloud)
export async function viewConfigs(root) {
  mount(root, h("div", { class: "empty" }, "Chargement des configs…"));
  const data = await api.configs();

  if (!data.ok) {
    mount(root,
      h("div", { class: "toolbar" }, [h("h2", {}, "Configs live")]),
      h("div", { class: "banner bad" }, data.error || "Configs indisponibles."),
      h("div", { class: "muted" },
        "L'API Configs (create.roblox.com/docs/production/configs) est récente. "
        + "Vérifie le scope Open Cloud « Configs » et qu'au moins une config existe "
        + "dans Creator Hub > Configs."));
    return;
  }

  const draftJson = JSON.stringify(data.draft || data.published || {}, null, 2);
  const editor = h("textarea",
    { style: "width:100%;min-height:260px;font-family:monospace;font-size:13px", spellcheck: "false" },
    draftJson);

  const saveBtn = h("button", { class: "btn" }, "Enregistrer le brouillon");
  saveBtn.addEventListener("click", async () => {
    let values;
    try { values = JSON.parse(editor.value); }
    catch (e) { return toast("JSON invalide : " + e.message, "bad"); }
    saveBtn.disabled = true;
    try {
      const r = await api.configsOverwrite(values);
      if (!r.ok) toast("" + r.error, "bad");
      else toast("Brouillon enregistré (non encore publié).");
    } catch (e) { toast("" + e.message, "bad"); }
    saveBtn.disabled = false;
  });

  const pubBtn = h("button", { class: "btn primary" }, "Publier en production");
  pubBtn.addEventListener("click", async () => {
    if (!confirmAction("Publier le brouillon ? Propagation 5–15 min côté joueurs.")) return;
    pubBtn.disabled = true;
    try {
      const r = await api.configsPublish();
      if (!r.ok) toast("" + r.error, "bad");
      else toast("Publié. Propagation en cours (5–15 min).");
    } catch (e) { toast("" + e.message, "bad"); }
    pubBtn.disabled = false;
  });

  mount(root,
    h("div", { class: "toolbar" }, [h("h2", {}, "Configs live")]),
    h("div", { class: "muted" },
      "Valeurs modifiables sans republier l'expérience (kill-switches de modes, "
      + "durées, seuils…). Le jeu les lit via ConfigBridge, PAR-DESSUS les valeurs "
      + "Luau qui restent le filet de sécurité. La publication met 5–15 min à "
      + "atteindre les joueurs — c'est pourquoi les boosts restent sur MessagingService."),
    data.draftError
      ? h("div", { class: "muted" }, "Pas de brouillon distinct : édition à partir du publié.")
      : null,
    h("div", { class: "card" }, [
      h("h3", {}, `Brouillon — repository « ${data.repo} »`),
      editor,
      h("div", { style: "display:flex;gap:8px;margin-top:8px" }, [saveBtn, pubBtn]),
    ]),
    h("div", { class: "card" }, [
      h("h3", {}, "Publié (en ligne)"),
      h("pre", { style: "overflow:auto;max-height:200px;font-size:12px" },
        JSON.stringify(data.published || {}, null, 2)),
    ]),
  );
}

//  7. SANTE
export function viewHealth(root) {
  const s = state.status || {};
  const line = (label, ok, detail) => h("tr", {}, [
    h("td", {}, label),
    h("td", {}, ok ? h("span", { class: "tag ok" }, "OK") : h("span", { class: "tag bad" }, "KO")),
    h("td", { style: "color:var(--dim)" }, detail || ""),
  ]);

  const rb = s.roblox || {};
  const dc = s.discord || {};

  mount(root, 
    h("div", { class: "toolbar" }, [h("h2", {}, "Santé du système")]),
    s.missing?.length
      ? h("div", { class: "banner" },
          `Non configuré : ${s.missing.join(", ")} — copie .env.example vers .env et remplis ces valeurs.`)
      : null,
    h("div", { class: "card" }, h("table", {}, [
      h("thead", {}, h("tr", {}, ["Composant", "État", "Détail"].map((x) => h("th", {}, x)))),
      h("tbody", {}, [
        line("Bot Discord", dc.ok, dc.ok ? `${dc.bot} · ${dc.guild}` : dc.error),
        line("Membres Discord", dc.ok, dc.ok ? `${dc.members} membres · ${dc.online} en ligne` : ""),
        line("Experience Roblox", rb.ok, rb.ok ? `${rb.name} · ${rb.playing} en jeu · ${rb.visits} visites` : rb.reason),
        line("Open Cloud (boosts)", s.boostOk !== false, s.boostOk === false ? s.boostError : "DataStore + MessagingService joignables"),
      ]),
    ])),
    permissionsCard(),
    h("div", { class: "card" }, [
      h("h3", {}, "Configuration"),
      h("table", {}, h("tbody", {}, Object.entries(s.config || {}).map(([k, v]) =>
        h("tr", {}, [h("td", { style: "color:var(--dim)" }, k), h("td", {}, String(v || "—"))])))),
    ]),
  );
}

// Une ligne par droit de la cle Open Cloud. Lance a la demande : la sonde ecrit puis
// supprime une cle `cc_probe` et publie sur un topic sans abonne (~10 appels).
function permissionsCard() {
  const body = h("div", { class: "muted" },
    "Vérifie chaque droit de ROBLOX_OPENCLOUD_KEY sur l'univers, un par un.");
  const btn = h("button", { class: "btn primary" }, "Tester les permissions");
  const TAG = { ok: ["ok", "OK"], bad: ["bad", "MANQUANT"], skip: ["", "non testé"] };
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    body.replaceChildren(h("div", { class: "muted" }, "Test en cours…"));
    try {
      const r = await api.permissions();
      if (r.error) {
        body.replaceChildren(h("div", { class: "banner bad" }, r.error));
        return;
      }
      const bad = r.rows.filter((x) => x.state === "bad").length;
      body.replaceChildren(
        h("div", { class: `banner ${bad ? "bad" : ""}` }, bad
          ? `${bad} droit(s) manquant(s) sur l'univers ${r.universeId}. Corrige la clé dans le Creator Hub, puis reteste (aucun redémarrage nécessaire si la clé ne change pas).`
          : `Tous les droits testables sont accordés sur l'univers ${r.universeId}.`),
        h("table", {}, [
          h("thead", {}, h("tr", {}, ["Système", "Opération", "Sert à", "État", "Quoi faire"].map((x) => h("th", {}, x)))),
          h("tbody", {}, r.rows.map((x) => {
            const [cls, label] = TAG[x.state] || TAG.skip;
            return h("tr", {}, [
              h("td", {}, x.system),
              h("td", {}, x.operation),
              h("td", { style: "color:var(--dim)" }, x.use),
              h("td", {}, h("span", { class: `tag ${cls}`, title: x.detail || "" },
                x.status && x.state === "bad" ? `${label} (${x.status})` : label)),
              h("td", { style: "color:var(--dim)" }, x.state === "bad" ? x.hint : (x.state === "skip" ? x.detail : "")),
            ]);
          })),
        ]),
      );
    } catch (e) {
      body.replaceChildren(h("div", { class: "banner bad" }, `Test impossible : ${e.message}`));
    } finally {
      btn.disabled = false;
    }
  });
  return h("div", { class: "card" }, [
    h("div", { class: "toolbar" }, [h("h3", {}, "Permissions Open Cloud"), h("div", { class: "spacer" }), btn]),
    body,
  ]);
}

//  SECURITE : pieges anti-triche (claude_works/guides/GUIDE_PIEGES.md)
// Liste lue a l'ouverture de l'espace ; le detail d'un joueur au clic sur sa ligne.
export async function viewSecurity(root) {
  mount(root, h("div", { class: "empty" }, "Lecture des pièges…"));
  let list;
  try {
    list = await api.honeypots(50);
  } catch (e) {
    mount(root,
      h("div", { class: "toolbar" }, [h("h2", {}, "Sécurité")]),
      h("div", { class: "banner bad" }, `Lecture impossible : ${e.message}`));
    return;
  }

  const detail = h("div", { class: "card" },
    h("div", { class: "muted" }, "Clique un joueur pour voir ce qu'il a tenté."));

  const showDetail = async (row) => {
    detail.replaceChildren(h("div", { class: "muted" }, `Lecture de ${row.name}…`));
    try {
      const d = await api.honeypot(row.userId);
      const rec = d.record;
      if (!rec) {
        detail.replaceChildren(h("div", { class: "muted" }, "Aucun enregistrement détaillé (écriture encore en cours ?)."));
        return;
      }
      const traps = Object.entries(rec.traps || {}).sort((a, b) => b[1] - a[1]);
      detail.replaceChildren(
        h("div", { class: "toolbar" }, [
          h("h3", {}, d.name),
          h("a", { href: `https://www.roblox.com/users/${d.userId}/profile`, target: "_blank",
            rel: "noopener", class: "muted" }, `userId ${d.userId}`),
          rec.admin ? h("span", { class: "tag" }, "admin (test ?)") : null,
        ]),
        h("div", { class: "stats" }, [
          h("div", { class: "stat" }, [h("div", { class: "stat-v" }, String(rec.hits || 0)), h("div", { class: "stat-l" }, "Appels")]),
          h("div", { class: "stat" }, [h("div", { class: "stat-v" }, String(rec.sessions || 0)), h("div", { class: "stat-l" }, "Sessions")]),
          h("div", { class: "stat" }, [h("div", { class: "stat-v" }, rec.firstAt ? fmtDate(rec.firstAt) : "—"), h("div", { class: "stat-l" }, "Premier")]),
          h("div", { class: "stat" }, [h("div", { class: "stat-v" }, rec.lastAt ? fmtDate(rec.lastAt) : "—"), h("div", { class: "stat-l" }, "Dernier")]),
        ]),
        h("h3", {}, "Pièges déclenchés"),
        h("table", {}, h("tbody", {}, traps.map(([name, n]) =>
          h("tr", {}, [h("td", {}, h("code", {}, name)), h("td", {}, String(n))])))),
        h("h3", {}, "Derniers appels"),
        h("table", {}, [
          h("thead", {}, h("tr", {}, ["Quand", "Piège", "Arguments", "Serveur"].map((x) => h("th", {}, x)))),
          h("tbody", {}, (rec.samples || []).map((s) => h("tr", {}, [
            h("td", {}, s.at ? fmtDate(s.at) : "—"),
            h("td", {}, h("code", {}, s.trap || "?")),
            h("td", { style: "word-break:break-all" }, h("code", {}, s.args || "")),
            h("td", { style: "color:var(--dim)" }, `${s.studio ? "Studio · " : ""}${s.placeId || "?"} · ${(s.jobId || "").slice(0, 8)}`),
          ]))),
        ]),
        h("div", { class: "row", style: "margin-top:12px;gap:8px" }, [
          h("a", { class: "btn", href: `#players/${d.userId}` }, "Ouvrir la fiche"),
          (() => { const b = h("button", { class: "btn danger" }, "Bannir"); b.addEventListener("click", () => banDialog([d.userId], d.name, () => viewSecurity(root))); return b; })(),
        ]),
      );
    } catch (e) {
      detail.replaceChildren(h("div", { class: "banner bad" }, `Détail illisible : ${e.message}`));
    }
  };

  const rows = list.rows || [];
  // VAGUE DE BANS : on coche, on bannit tout le monde en une fois (meme motif, meme duree).
  const picked = new Set();
  const waveBtn = h("button", { class: "btn danger", disabled: true }, "Bannir la sélection");
  const updateWave = () => {
    waveBtn.disabled = !picked.size;
    waveBtn.textContent = picked.size ? `Bannir la sélection (${picked.size})` : "Bannir la sélection";
  };
  waveBtn.addEventListener("click", () => banDialog([...picked], `${picked.size} joueur(s)`, () => viewSecurity(root)));
  const bansBox = h("div", { class: "card" }, h("div", { class: "muted" }, "Lecture des bans…"));
  api.bans().then((r) => {
    mount(bansBox, h("h3", {}, `Bannis de l'univers (${r.bans.length}${r.more ? "+" : ""})`),
      r.bans.length ? h("table", {}, [
        h("thead", {}, h("tr", {}, ["Joueur", "Depuis", "Durée", "Motif affiché", ""].map((x) => h("th", {}, x)))),
        h("tbody", {}, r.bans.map((x) => h("tr", {}, [
          h("td", {}, h("a", { href: `#players/${x.userId}` }, x.name || `#${x.userId}`)),
          h("td", { style: "color:var(--dim)" }, x.start ? new Date(x.start).toLocaleDateString("fr-FR") : "—"),
          h("td", {}, x.duration ? `${Math.round(parseInt(x.duration, 10) / 86400)} j` : "Définitif"),
          h("td", { style: "color:var(--dim)" }, x.displayReason || ""),
          h("td", { class: "num" }, (() => { const b = h("button", { class: "btn ghost" }, "Lever"); b.addEventListener("click", () => unbanDialog(x.userId, x.name || x.userId, () => viewSecurity(root))); return b; })()),
        ]))),
      ]) : h("div", { class: "muted" }, "Aucun ban actif."));
  }).catch((e) => mount(bansBox, h("div", { class: "banner bad" }, `Bans illisibles : ${e.message}. Droit « User Restrictions : Read » ?`)));

  mount(root,
    h("div", { class: "toolbar" }, [h("h2", {}, "Sécurité : pièges anti-triche"), h("div", { class: "spacer" }), waveBtn]),
    list.error ? h("div", { class: "banner bad" }, `Classement inaccessible : ${list.error}`) : null,
    h("div", { class: "muted" },
      "Joueurs ayant appelé un remote leurre, du plus récent au plus ancien. Aucun script du jeu n'appelle ces remotes : chaque ligne est un exécuteur ou une injection."),
    h("div", { class: "grid2" }, [
      h("div", { class: "card" }, rows.length
        ? h("table", {}, [
            h("thead", {}, h("tr", {}, ["", "Joueur", "Dernier appel"].map((x) => h("th", {}, x)))),
            h("tbody", {}, rows.map((r) => {
              const box = h("input", { type: "checkbox", "aria-label": `Sélectionner ${r.name}` });
              box.addEventListener("click", (e) => e.stopPropagation());
              box.addEventListener("change", () => { box.checked ? picked.add(r.userId) : picked.delete(r.userId); updateWave(); });
              const tr = h("tr", { style: "cursor:pointer" }, [
                h("td", { style: "width:28px" }, box),
                h("td", {}, r.name),
                h("td", { style: "color:var(--dim)" }, fmtDate(r.lastAt)),
              ]);
              tr.addEventListener("click", () => showDetail(r));
              return tr;
            })),
          ])
        : h("div", { class: "empty" }, list.error ? "—" : "Aucun joueur piégé pour l'instant.")),
      detail,
    ]),
    bansBox,
  );
}

//  8. RECOMPENSES  (surcharge validee, plafonds stricts)
export async function viewRewards(root) {
  mount(root, h("div", { class: "empty" }, "Lecture des récompenses…"));
  const data = await api.rewards();
  const v = data.values || data.defaults;
  const TIERS = { 1: "RECRUE", 2: "SOLDAT", 3: "VETERAN", 4: "HÉROS" };

  const rw = {}, rb = [];
  for (const t of ["1", "2", "3", "4"]) {
    const row = (v.rewards && v.rewards[t]) || {};
    rw[t] = {
      gold: h("input", { type: "number", min: "0", max: String(data.maxGold), value: String(row.gold ?? 0) }),
      xp:   h("input", { type: "number", min: "0", max: String(data.maxXP),  value: String(row.xp ?? 0) }),
      kit:  h("input", { value: row.kit || "", placeholder: "aucun" }),
      badges: h("input", { value: (row.badges || []).join(", "), placeholder: "ex: 123, 456" }),
    };
  }
  for (const b of (v.rankBonuses || [])) {
    rb.push({
      maxRank: h("input", { type: "number", min: "1", value: String(b.maxRank) }),
      gold:    h("input", { type: "number", min: "0", max: String(data.maxGold), value: String(b.gold) }),
      xp:      h("input", { type: "number", min: "0", max: String(data.maxXP),  value: String(b.xp) }),
      title:   h("input", { value: b.title || "", placeholder: "S%d TITRE" }),
      badges:  h("input", { value: (b.badges || []).join(", "), placeholder: "ex: 123" }),
    });
  }
  const ratioInp = h("input", { type: "number", step: "0.05", min: "0", max: "1",
                                value: String(v.loserRatio ?? 0.4) });

  const collect = () => ({
    rewards: Object.fromEntries(Object.entries(rw).map(([t, f]) =>
      [t, { gold: +f.gold.value, xp: +f.xp.value, kit: f.kit.value.trim(),
            badges: f.badges.value }])),
    rankBonuses: rb.map((f) => ({ maxRank: +f.maxRank.value, gold: +f.gold.value,
                                  xp: +f.xp.value, title: f.title.value.trim(),
                                  badges: f.badges.value })),
    loserRatio: +ratioInp.value,
  });

  // Indicateur de modification non enregistree. Sans lui, on tape une valeur,
  // on annule une confirmation, et rien ne dit que la saisie n'est pas partie.
  const dirtyFlag = h("div", { class: "banner", style: "display:none" },
    "Modifications NON enregistrées — clique « Appliquer en jeu » (2 confirmations).");
  const markDirty = () => { dirtyFlag.style.display = "block"; };
  [...Object.values(rw).flatMap((f) => Object.values(f)),
   ...rb.flatMap((f) => Object.values(f)), ratioInp]
    .forEach((el) => el.addEventListener("input", markDirty));

  const saveBtn = h("button", { class: "btn primary" }, "Appliquer en jeu");
  saveBtn.addEventListener("click", async () => {
    // Double confirmation : ceci change ce que les joueurs recevront reellement.
    if (!confirmAction("Appliquer ces récompenses à TOUS les serveurs ?\n\n" +
      "Elles seront utilisées à la prochaine clôture de semaine.")) return;
    if (!confirmAction("Dernière confirmation : les joueurs recevront ces montants.")) return;
    saveBtn.disabled = true;
    try {
      await api.saveRewards({ values: collect() });
      toast("Récompenses appliquées et poussées aux serveurs.");
      viewRewards(root);
    } catch (e) { toast(`${e.message}`, "bad"); saveBtn.disabled = false; }
  });

  const resetBtn = h("button", { class: "btn danger" }, "↺ Revenir aux valeurs du jeu");
  resetBtn.addEventListener("click", async () => {
    if (!confirmAction("Supprimer la surcharge et revenir aux valeurs de FactionWarConfig.luau ?")) return;
    try {
      await api.resetRewards();
      toast("Surcharge supprimée — valeurs par défaut rétablies.");
      viewRewards(root);
    } catch (e) { toast(`${e.message}`, "bad"); }
  });

  mount(root,
    h("div", { class: "toolbar" }, [
      h("h2", {}, "Récompenses de fin de semaine"),
      h("div", { class: "spacer" }),
      data.overridden ? resetBtn : null,
      saveBtn,
    ]),
    data.error ? h("div", { class: "banner" }, `${data.error}`) : null,
    dirtyFlag,
    h("div", { class: data.overridden ? "banner" : "muted" },
      data.overridden
        ? "Une surcharge est ACTIVE : ces valeurs remplacent celles du fichier du jeu."
        : "Valeurs par défaut du jeu (FactionWarConfig.luau). Aucune surcharge active."),
    h("div", { class: "card" }, [
      h("h3", {}, "Par palier de contribution"),
      h("div", { class: "muted" },
        `Base de la faction GAGNANTE. La perdante reçoit ce ratio ×, et son kit est rétrogradé d'un palier. Plafonds : ${data.maxGold} or, ${data.maxXP} XP.`),
      h("table", {}, [
        h("thead", {}, h("tr", {}, ["Palier", "Or", "XP", "Kit", "Badges"].map((x) => h("th", {}, x)))),
        h("tbody", {}, ["1", "2", "3", "4"].map((t) => h("tr", {}, [
          h("td", {}, h("strong", {}, TIERS[t])),
          h("td", {}, rw[t].gold), h("td", {}, rw[t].xp), h("td", {}, rw[t].kit),
          h("td", {}, rw[t].badges),
        ]))),
      ]),
      h("div", { class: "field", style: "max-width:260px;margin-top:14px" },
        [h("label", {}, "Ratio faction perdante (0–1)"), ratioInp]),
      h("div", { class: "muted" },
        "Le kit doit exister dans ShopConfig.KITS, sinon il ne sera pas livré. " +
        "Ids valides : kit_war_supply · kit_war_elite · operator_kit · elite_kit · " +
        "warlord_kit · mercenary_kit · conscript_rainor · conscript_rusfor · " +
        "kit_war_supply · kit_war_elite. Laisser vide = aucun kit."),
    ]),
    h("div", { class: "card" }, [
      h("h3", {}, "Bonus de rang (top de sa propre faction)"),
      h("div", { class: "muted" },
        "Appliqué aux DEUX factions. %d dans le titre est remplacé par le numéro de saison."),
      h("table", {}, [
        h("thead", {}, h("tr", {}, ["Rang max", "Or", "XP", "Titre", "Badges"].map((x) => h("th", {}, x)))),
        h("tbody", {}, rb.map((f) => h("tr", {}, [
          h("td", {}, f.maxRank), h("td", {}, f.gold), h("td", {}, f.xp), h("td", {}, f.title),
          h("td", {}, f.badges),
        ]))),
      ]),
      h("div", { class: "muted" },
        "Badges : ids séparés par des virgules, 5 maximum. Un badge se crée à la main dans le Creator Hub (100 Robux) et doit appartenir à cette expérience."),
    ]),
  );
}
