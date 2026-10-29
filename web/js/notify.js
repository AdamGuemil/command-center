//  notify.js — Diffusion > Notifications : notifications Roblox hors du jeu (lot 4).
//  Les textes vivent dans le Creator Hub ; le CC garde leur Asset ID, calcule l'audience,
//  respecte la limite d'une notification par joueur et par jour, et n'envoie qu'apres un apercu.
import { api } from "./api.js";
import { h, mount, toast } from "./ui.js";
import { dialog, field } from "./actions.js";

const STATE = {
  running: ["En cours", "warn"], done: ["Terminée", "ok"], paused: ["En pause", "warn"],
  failed: ["Échec", "bad"], stopped: ["Arrêtée", ""],
};
const PARAM_LABEL = {
  event: "Nom de l'événement", hours: "Durée (heures)", version: "Version", headline: "Titre de la mise à jour",
};
const PARAM_HINT = {
  event: "Tel qu'il apparaîtra : « Double XP is live for 24h. »",
  headline: "Court, en anglais : le texte entier tient sur deux lignes de notification.",
};

const fmtDate = (ts) => new Date(ts * 1000).toLocaleString("fr-FR",
  { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });

function phone(text, game = "Shroud War") {
  return h("div", { class: "notif-prev", "aria-label": "Aperçu de la notification" }, [
    h("div", { class: "np-icon" }, "SW"),
    h("div", { class: "np-main" }, [
      h("div", { class: "np-title" }, game),
      h("div", { class: "np-text" }, text),
    ]),
    h("span", { class: "np-join" }, "Join"),
  ]);
}

// FENETRE D'ENVOI : apercu calcule par le serveur, puis envoi sur confirmation.
// opts : { key, entry (ligne du catalogue), params, ref, card, action, onDone }
export function notifyDialog({ key, entry, params = {}, ref = null, card = null, action = null, onDone }) {
  const inputs = {};
  const editable = entry?.input || [];
  const form = editable.map((p) => {
    const el = h("input", { value: params[p] ?? "", maxlength: p === "hours" ? "3" : "60",
      inputmode: p === "hours" ? "numeric" : "text", "aria-label": PARAM_LABEL[p] || p });
    inputs[p] = el;
    return field(PARAM_LABEL[p] || p, el, PARAM_HINT[p] || "");
  });
  const recompute = editable.length ? h("button", { class: "btn" }, "Recalculer l'audience") : null;
  const out = h("div", {}, h("div", { class: "muted" }, "Calcul de l'audience…"));
  let last = null;
  const current = () => {
    const p = { ...params };
    for (const [k, el] of Object.entries(inputs)) p[k] = el.value.trim();
    return p;
  };
  const d = dialog({
    title: entry ? `${entry.label} (${key})` : key,
    subtitle: card ? "Depuis l'Accueil" : "Notification Roblox",
    body: [...form, recompute, out],
    confirm: "Envoyer",
    note: "Une notification par joueur et par jour. Rien ne part avant ton clic.",
    onConfirm: async (close) => {
      if (!last || last.blockers.length) throw new Error("Rien à envoyer : voir l'aperçu.");
      const res = await api.notifySend({ key, params: current(), ref, card, action });
      toast(`Campagne lancée : ${res.toSend} joueur(s), suivi dans Diffusion > Notifications.`, "ok");
      close();
      onDone?.(res);
    },
  });
  d.ok.disabled = true;

  const load = async () => {
    d.ok.disabled = true;
    mount(out, h("div", { class: "muted" }, "Calcul de l'audience…"));
    try {
      const p = await api.notifyPreview({ key, params: current(), ref, card, action });
      last = p;
      const excluded = Object.entries(p.excluded || {});
      mount(out,
        phone(p.text),
        h("div", { class: "stats notif-stats" }, [
          stat("Audience", p.audience), stat("Déjà notifiés aujourd'hui", p.alreadyToday),
          stat("À envoyer", p.toSend), stat("Durée estimée", p.toSend ? `${Math.max(1, Math.ceil(p.minutes))} min` : "—"),
        ]),
        h("dl", { class: "kv" }, [
          h("dt", {}, "Ouvre au Hub"), h("dd", {}, entry?.screen || p.launch),
          h("dt", {}, "Sujet"), h("dd", {}, h("code", {}, p.ref)),
          ...excluded.flatMap(([why, n]) => [h("dt", {}, "Mis de côté"), h("dd", {}, `${n} joueur(s) : ${why}`)]),
        ]),
        ...p.notes.map((n) => h("div", { class: "banner info" }, n)),
        ...p.warnings.map((n) => h("div", { class: "banner warn" }, n)),
        ...p.blockers.map((n) => h("div", { class: "banner bad" }, n)),
        h("p", { class: "muted", style: "font-size:12px" },
          "Roblox ne livre qu'aux joueurs de 13 ans ou plus inscrits aux notifications de Shroud War, "
          + "et réduit la portée selon l'engagement : le nombre de joueurs touchés sera plus bas."));
      d.ok.disabled = p.blockers.length > 0;
      d.ok.textContent = p.toSend ? `Envoyer à ${p.toSend} joueur(s)` : "Envoyer";
    } catch (e) {
      last = null;
      mount(out, h("div", { class: "banner bad" }, e.message));
    }
  };
  recompute?.addEventListener("click", load);
  // Les champs vides (evenement, mise a jour) attendent la saisie ; sinon apercu immediat.
  if (editable.some((p) => !String(params[p] ?? "").trim())) {
    mount(out, h("div", { class: "muted" }, "Remplis les champs, puis « Recalculer l'audience »."));
  } else {
    load();
  }
  return d;
}

const stat = (label, value) => h("div", { class: "stat" }, [h("div", { class: "stat-l" }, label), h("div", { class: "stat-v" }, String(value))]);

function testDialog(entry, testUserId, reload) {
  const uid = h("input", { value: testUserId || "", inputmode: "numeric", placeholder: "ton userId Roblox" });
  const result = h("div");
  dialog({
    title: `Tester ${entry.key}`,
    subtitle: "Envoie le texte à un seul compte, avec des valeurs d'exemple",
    body: [
      phone(entry.text.replace(/\{(\w+)\}/g, (_, k) => ({ rank: "3", gold: "12,500", season: "12", faction: "Rainor",
        event: "Double XP", hours: "24", version: "0.9", headline: "New map and ranked rewards" })[k] || k)),
      field("Compte de test (userId)", uid, "Ce compte utilise sa notification du jour. Il doit avoir 13 ans ou plus "
        + "et avoir accepté les notifications de Shroud War (invitation en jeu au Hub)."),
      result,
    ],
    confirm: "Envoyer le test",
    onConfirm: async () => {
      const r = await api.notifyTest(entry.key, uid.value.trim());
      if (!r.ok) throw new Error(r.error);
      mount(result, h("div", { class: "banner ok" }, r.note));
      reload();
    },
  });
}

function catalogueRow(entry, ids, testUserId, reload) {
  const input = h("input", { value: entry.messageId || "", placeholder: "Asset ID copié du Creator Hub",
    "aria-label": `Asset ID ${entry.key}`, spellcheck: "false" });
  ids[entry.key] = input;
  const copy = h("button", { class: "btn ghost", title: "Copier le texte à coller dans le Creator Hub" }, "Copier le texte");
  copy.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(entry.text); toast("Texte copié."); } catch { toast("Copie refusée par le navigateur.", "bad"); }
  });
  const test = h("button", { class: "btn", disabled: !entry.messageId }, "Tester sur mon compte");
  test.addEventListener("click", () => testDialog(entry, testUserId, reload));
  const send = h("button", { class: "btn primary", disabled: !entry.messageId }, "Préparer un envoi");
  send.addEventListener("click", () => notifyDialog({ key: entry.key, entry, onDone: reload }));
  return h("div", { class: `card notif-row${entry.messageId ? "" : " missing"}` }, [
    h("div", { class: "notif-head" }, [
      h("span", { class: "tag" }, `#${entry.priority}`),
      h("h3", {}, entry.label),
      h("code", { class: "muted" }, entry.key),
      h("div", { style: "flex:1" }),
      entry.messageId ? h("span", { class: "tag ok" }, "Prêt") : h("span", { class: "tag warn" }, "Asset ID manquant"),
    ]),
    h("div", { class: "notif-text" }, [h("code", {}, entry.text), h("span", { class: "muted" }, `${entry.length}/99`), copy]),
    h("dl", { class: "kv" }, [
      h("dt", {}, "Paramètres"), h("dd", { class: "notif-params" }, entry.params.length ? entry.params.map((p) => h("code", {}, `{${p}}`)) : "aucun"),
      h("dt", {}, "Ouvre au Hub"), h("dd", {}, `${entry.screen} (${entry.launch})`),
      h("dt", {}, "Audience"), h("dd", {}, entry.audience),
      h("dt", {}, "Quand"), h("dd", {}, entry.trigger),
    ]),
    h("div", { class: "notif-actions" }, [field("Asset ID", input), test, send]),
  ]);
}

function campaignsTable(rows) {
  if (!rows.length) return h("div", { class: "empty" }, "Aucune notification envoyée pour l'instant.");
  return h("div", { style: "overflow-x:auto" }, h("table", {}, [
    h("thead", {}, h("tr", {}, ["Quand", "Notification", "Sujet", "Envoyées", "Déjà servis", "Échecs", "État"].map((x) => h("th", {}, x)))),
    h("tbody", {}, rows.map((c) => {
      const [label, cls] = STATE[c.state] || [c.state, ""];
      return h("tr", {}, [
        h("td", { style: "white-space:nowrap" }, fmtDate(c.at)),
        h("td", {}, c.label),
        h("td", {}, h("code", {}, c.ref || "—")),
        h("td", {}, `${c.sent} / ${c.total}`),
        h("td", {}, String(c.skipped + c.throttled)),
        h("td", {}, String(c.failed)),
        h("td", {}, [h("span", { class: `tag ${cls}` }, label), c.error ? h("div", { class: "muted", style: "font-size:12px;max-width:42ch" }, c.error) : null]),
      ]);
    })),
  ]));
}

export async function viewNotify(root) {
  const head = h("div");
  const list = h("div");
  const history = h("div", { class: "card" });
  const ids = {};
  const testId = h("input", { inputmode: "numeric", placeholder: "ton userId", "aria-label": "Compte de test" });
  const save = h("button", { class: "btn primary" }, "Enregistrer les Asset IDs");
  let timer = null;

  const load = async () => {
    let data;
    try { data = await api.notify(); } catch (e) { mount(list, h("div", { class: "banner bad" }, e.message)); return; }
    if (!root.isConnected) return;
    const ready = data.catalogue.filter((c) => c.messageId).length;
    const today = Object.values(data.today.byKey).reduce((a, b) => a + b, 0);
    const running = data.campaigns.find((c) => c.id === data.running);
    testId.value = data.testUserId || testId.value;
    const stop = h("button", { class: "btn danger" }, "Arrêter");
    stop.addEventListener("click", async () => { try { await api.notifyStop(); toast("Arrêt demandé."); } catch (e) { toast(e.message, "bad"); } });
    mount(head,
      h("div", { class: "home-strip" }, [
        h("div", { class: "hs" }, [h("div", { class: "hs-l" }, "Textes prêts"), h("div", { class: "hs-v" }, `${ready}/${data.catalogue.length}`),
          h("div", { class: "hs-s" }, ready < data.catalogue.length ? "à créer dans le Creator Hub" : "catalogue complet")]),
        h("div", { class: "hs" }, [h("div", { class: "hs-l" }, "Aujourd'hui (UTC)"), h("div", { class: "hs-v" }, [String(today), h("small", {}, " joueurs")]),
          h("div", { class: "hs-s" }, "déjà notifiés : ils ne recevront plus rien avant demain")]),
        h("div", { class: "hs" }, [h("div", { class: "hs-l" }, "Campagne"),
          h("div", { class: "hs-v" }, running ? `${running.sent + running.skipped + running.throttled + running.failed}/${running.total}` : "aucune"),
          running ? h("div", { class: "hs-s" }, [`${running.label} en cours `, stop]) : h("div", { class: "hs-s" }, "rien en cours")]),
      ]),
      ready < data.catalogue.length ? h("details", { class: "card notif-setup", open: ready === 0 }, [
        h("summary", {}, "Mise en place (une fois)"),
        h("ol", {}, [
          h("li", {}, ["Creator Hub, Shroud War, ", h("b", {}, "Engagement > Notifications"), ", « Create a Notification String »."]),
          h("li", {}, "Nom : la clé ci-dessous (visible de toi seul). Texte : bouton « Copier le texte » de la ligne, à coller tel quel. Les {paramètres} doivent rester identiques."),
          h("li", {}, "Une fois créé : colonne Actions, « Copy Asset ID », puis colle-le dans le champ Asset ID de la ligne et enregistre."),
          h("li", {}, ["Clé Open Cloud : ajoute ", h("b", {}, "User Notifications > Write"), " (droits utilisateur, séparés de ceux de l'expérience)."]),
          h("li", {}, "« Tester sur mon compte » : la notification arrive sur ton compte Roblox si tu as accepté les notifications de Shroud War."),
        ]),
        h("p", { class: "muted" }, "Roblox exige au moins 100 visites sur l'expérience. Le jeu remplit l'index d'activité "
          + `(${data.activityStore}) à chaque arrivée au Hub, une fois cette version publiée : les audiences « absents depuis… » en dépendent.`),
      ]) : null,
    );
    mount(list, ...data.catalogue.map((e) => catalogueRow(e, ids, data.testUserId, load)),
      h("div", { class: "card notif-foot" }, [
        field("Compte de test (userId)", testId, "Utilisé par « Tester sur mon compte »."),
        h("div", { style: "flex:1" }), save,
      ]),
      h("p", { class: "muted", style: "font-size:12px" },
        "Le jeu peut aussi envoyer MARKET_SOLD (vente au marché noir à un vendeur hors ligne, BlackMarketService) si "
        + "ShopConfig.MARKET_SOLD_NOTIFICATION_ID est renseigné ; elle compte dans la même limite d'une par jour, sans passer par ce registre."));
    mount(history, h("h3", {}, "Envois"), campaignsTable(data.campaigns));
    clearTimeout(timer);
    if (running) timer = setTimeout(() => root.isConnected && load(), 3000);
  };

  save.addEventListener("click", async () => {
    save.disabled = true;
    try {
      await api.notifySaveConfig(Object.fromEntries(Object.entries(ids).map(([k, el]) => [k, el.value.trim()])), testId.value.trim());
      toast("Asset IDs enregistrés.", "ok");
      await load();
    } catch (e) { toast(e.message, "bad"); } finally { save.disabled = false; }
  });

  mount(root,
    h("div", { class: "toolbar" }, [h("h2", {}, "Notifications joueurs"), h("div", { class: "spacer" })]),
    h("div", { class: "muted", style: "margin:-6px 0 16px;max-width:82ch" },
      "Notifications Roblox reçues hors du jeu (site, appli). Une par joueur et par jour au plus : le CC garde la "
      + "plus importante (ordre ci-dessous) et saute les joueurs déjà notifiés. Les cartes de l'Accueil proposent "
      + "chaque envoi au bon moment ; cet écran sert à la mise en place, aux tests et aux envois manuels."),
    head, list, history);
  await load();
}
