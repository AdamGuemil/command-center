//  actions.js — actions sur les joueurs et les serveurs (lot 3) : fenetres de confirmation,
//  suivi des commandes envoyees aux serveurs, modifications avec apercu avant/apres.
//  Rien n'est envoye sans un clic de confirmation dans une fenetre qui dit ce qui va se passer.
import { api } from "./api.js";
import { h, mount, toast } from "./ui.js";

// FENETRE GENERIQUE ---------------------------------------------------------------
// fields : noeuds du formulaire. onConfirm(close, setBusy) -> Promise ; une erreur levee
// est affichee dans la fenetre sans la fermer.
export function dialog({ title, subtitle = "", body = [], confirm = "Confirmer", danger = false, note = "", onConfirm }) {
  const err = h("div");
  const ok = h("button", { class: `btn ${danger ? "danger" : "primary"}` }, confirm);
  const cancel = h("button", { class: "btn" }, "Annuler");
  const content = h("div", { class: "dlg-body" }, body);
  const back = h("div", { class: "dlg-back", role: "dialog", "aria-modal": "true", "aria-label": title }, [
    h("div", { class: "dlg" }, [
      h("div", { class: "dlg-head" }, [subtitle ? h("div", { class: "muted" }, subtitle) : null, h("h3", {}, title)]),
      content, h("div", { style: "padding:0 18px" }, err),
      h("div", { class: "dlg-foot" }, [h("span", { class: "muted" }, note), h("div", { style: "flex:1" }), cancel, onConfirm ? ok : null]),
    ]),
  ]);
  const close = () => { back.remove(); document.removeEventListener("keydown", onKey); };
  const onKey = (e) => { if (e.key === "Escape") close(); };
  document.addEventListener("keydown", onKey);
  back.addEventListener("click", (e) => { if (e.target === back) close(); });
  cancel.addEventListener("click", close);
  ok.addEventListener("click", async () => {
    ok.disabled = true;
    const label = ok.textContent;
    ok.textContent = "En cours…";
    mount(err);
    try {
      await onConfirm(close, content);
    } catch (e) {
      mount(err, h("div", { class: "banner bad", style: "margin:8px 0 0" }, e.message));
      ok.disabled = false;
      ok.textContent = label;
    }
  });
  document.body.append(back);
  (back.querySelector("input, textarea, select") || cancel).focus();
  return { close, content, ok };
}

export const field = (label, input, hint = "") => h("div", { class: "field" }, [
  h("label", {}, label), input, hint ? h("div", { class: "muted", style: "font-size:12px;margin-top:4px" }, hint) : null,
]);

// SUIVI D'UNE COMMANDE : relit son etat toutes les 2 s, 45 s au plus.
export function trackCommand(cmd, el, onDone) {
  const started = Date.now();
  mount(el, h("div", { class: "muted" }, "Envoyée. En attente de la réponse du serveur…"));
  const tick = async () => {
    if (!el.isConnected) return;
    let s;
    try { s = await api.cmdStatus(cmd.id); } catch (e) { mount(el, h("div", { class: "banner bad" }, e.message)); return; }
    if (s.acks.length) {
      mount(el, ...s.acks.map((a) => h("div", { class: a.ok ? "banner ok" : "banner bad", style: "margin:4px 0" },
        `${a.ok ? "Fait" : "Refusé"} par le serveur ${a.place === "hub" ? "Hub" : a.place === "match" ? "de match" : ""} ${a.job || ""} : ${a.msg || ""}`)));
      if (s.done || Date.now() - started >= 45000) { onDone?.(s); return; }
    } else if (s.expired || Date.now() - started >= 45000) {
      mount(el, h("div", { class: "banner" }, "Commande envoyée, mais aucun accusé reçu. Elle a pu être exécutée en jeu."
        + (s.ackError ? ` Lecture des réponses : ${s.ackError}` : " Consulte le Journal Live avant de la renvoyer.")));
      return;
    } else if (s.ackError) {
      mount(el, h("div", { class: "banner" }, `Commande envoyée. Lecture des réponses indisponible : ${s.ackError}`));
    } else {
      mount(el, h("div", { class: "muted" }, "Envoyée. En attente de la réponse du serveur…"));
    }
    setTimeout(tick, 2000);
  };
  setTimeout(tick, 1500);
}

// MESSAGE STAFF : a un joueur, un serveur, ou tout le monde.
export function messageDialog({ userId = null, job = null, jobs = null, label = "tous les serveurs" }) {
  const title = h("input", { value: "Staff", maxlength: "40" });
  const text = h("textarea", { rows: "3", maxlength: "240", placeholder: "Message affiché en bandeau en jeu (anglais conseillé)" });
  const status = h("div");
  dialog({
    title: "Envoyer un message en jeu", subtitle: label, confirm: "Envoyer",
    body: [field("Titre", title), field("Message", text, "Affiché comme les notifications du jeu, une seule à la fois."), status],
    note: "Bandeau STAFF, rien d'autre ne change.",
    onConfirm: async (close, content) => {
      if (!text.value.trim()) throw new Error("Écris un message.");
      for (const j of (jobs || [job])) {
        const r = await api.cmd({ op: "toast", userId, job: j, title: title.value, text: text.value });
        const line = h("div");
        status.append(line);
        trackCommand(r, line);
      }
      toast("Message envoyé.");
      content.querySelectorAll("input,textarea").forEach((x) => { x.disabled = true; });
    },
  });
}

export function kickDialog(userId, name) {
  const reason = h("input", { value: "Removed by a moderator.", maxlength: "200" });
  const status = h("div");
  dialog({
    title: `Expulser ${name}`, confirm: "Expulser", danger: true,
    body: [field("Motif affiché au joueur", reason), status],
    note: "Le joueur peut revenir. Pour l'empêcher, utilise Bannir.",
    onConfirm: async (close, content) => {
      const r = await api.cmd({ op: "kick", userId, reason: reason.value });
      trackCommand(r, status);
      content.querySelector("input").disabled = true;
    },
  });
}

const DURATIONS = [["1", "1 jour"], ["3", "3 jours"], ["7", "7 jours"], ["30", "30 jours"], ["", "Définitif"]];

export function banDialog(userIds, label, onDone) {
  const duration = h("select", {}, DURATIONS.map(([v, l]) => h("option", { value: v }, l)));
  duration.value = "7";
  const display = h("input", { maxlength: "400", placeholder: "Ex. Cheating (exploit detected)" });
  const priv = h("textarea", { rows: "2", maxlength: "1000", placeholder: "Pour le staff : preuves, contexte" });
  const alts = h("input", { type: "checkbox", checked: "checked" });
  const confirmName = h("input", { placeholder: "Recopie BAN pour confirmer" });
  const results = h("div");
  dialog({
    title: userIds.length > 1 ? `Bannir ${userIds.length} joueurs` : `Bannir ${label}`, confirm: "Bannir", danger: true,
    body: [
      field("Durée", duration),
      field("Motif affiché au joueur", display, "Roblox l'affiche quand il essaie de rejoindre (400 caractères au plus)."),
      field("Motif privé", priv),
      h("label", { class: "check" }, [alts, " Inclure ses comptes alternatifs (détection Roblox)"]),
      field("Confirmation", confirmName),
      results,
    ],
    note: "Ban d'univers Roblox : HUB et matchs. Un joueur en ligne est expulsé aussitôt.",
    onConfirm: async (close) => {
      if (confirmName.value.trim().toUpperCase() !== "BAN") throw new Error("Recopie BAN pour confirmer.");
      const body = { days: duration.value || null, displayReason: display.value, privateReason: priv.value, alts: alts.checked };
      if (userIds.length > 1) {
        const r = await api.banWave({ ...body, userIds });
        const bad = r.results.filter((x) => !x.ok);
        mount(results, h("div", { class: bad.length ? "banner bad" : "banner ok" },
          `${r.results.length - bad.length} banni(s)${bad.length ? `, ${bad.length} échec(s) : ${bad.map((x) => `${x.userId} (${x.error})`).join(", ")}` : ""}.`));
        if (!bad.length) { toast("Vague de bans appliquée."); close(); }
      } else {
        await api.ban({ ...body, userId: userIds[0] });
        toast("Joueur banni.");
        close();
      }
      onDone?.();
    },
  });
}

export function unbanDialog(userId, name, onDone) {
  dialog({
    title: `Lever le ban de ${name}`, confirm: "Lever le ban",
    body: [h("p", {}, "Le joueur pourra de nouveau rejoindre le jeu. Ses comptes alternatifs aussi.")],
    onConfirm: async (close) => { await api.unban(userId); toast("Ban levé."); close(); onDone?.(); },
  });
}

// MODIFICATION D'UN JOUEUR : apercu, puis commande (en ligne) ou ecriture sous verrou.
export async function editFlow(userId, op, params, label, onDone) {
  let p;
  try {
    p = await api.editPlan({ userId, op, params });
  } catch (e) {
    toast(e.message, "bad");
    return;
  }
  const status = h("div");
  const pathText = p.path === "online"
    ? `Joueur en ligne (${p.online.kind === "hub" ? "Hub" : `match ${p.online.mode || ""}`}) : la modification part vers son serveur, qui l'applique et sauvegarde.`
    : "Joueur hors ligne : écriture directe sous verrou. S'il se connecte pendant ce temps, son serveur attend la fin (60 s au plus).";
  dialog({
    title: label, subtitle: `userId ${userId}`, confirm: "Appliquer", danger: op === "remove_item",
    body: [
      h("table", {}, h("tbody", {}, [
        h("tr", {}, [h("td", { class: "muted" }, "Avant"), h("td", {}, p.change.before)]),
        h("tr", {}, [h("td", { class: "muted" }, "Après"), h("td", {}, h("b", {}, p.change.after))]),
        h("tr", {}, [h("td", { class: "muted" }, "Donnée"), h("td", { class: "id" }, `${p.store} / ${p.key}`)]),
      ])),
      h("p", { class: "muted" }, pathText),
      status,
    ],
    note: p.path === "online" ? "" : "Une copie de l'original est gardée : annulable depuis la fiche.",
    onConfirm: async (close) => {
      if (p.path === "online") {
        const r = await api.cmd({ op, userId, ...params });
        trackCommand(r, status, () => onDone?.());
      } else {
        mount(status, h("div", { class: "muted" }, "Verrou posé, vérification que le joueur reste hors ligne (5 s)…"));
        await api.editApply(p.token);
        toast("Modification enregistrée.");
        close();
        onDone?.();
      }
    },
  });
}

export function moneyDialog(userId, current, onDone) {
  const amount = h("input", { type: "number", min: "0", step: "1", value: current ?? 0 });
  dialog({
    title: "Modifier l'or", subtitle: `userId ${userId}`, confirm: "Voir l'aperçu",
    body: [field("Nouveau solde", amount, "Valeur absolue. Pour ajouter un bonus, préfère Dons : il passe par la boîte aux lettres.")],
    onConfirm: async (close) => {
      const v = Number(amount.value);
      if (!Number.isFinite(v) || v < 0) throw new Error("Montant invalide.");
      close();
      await editFlow(userId, "set_money", { amount: Math.floor(v) }, "Modifier l'or", onDone);
    },
  });
}

export function backupsDialog(userId, onDone) {
  const body = h("div", {}, h("div", { class: "muted" }, "Lecture…"));
  const d = dialog({ title: "Modifications faites depuis le CC", subtitle: `userId ${userId}`, body: [body] });
  const OPS = { remove_item: "Objet retiré", set_money: "Or modifié" };
  api.edits(userId).then((r) => {
    mount(body, r.backups.length ? h("table", {}, [
      h("thead", {}, h("tr", {}, ["Quand", "Modification", "Détail", ""].map((x) => h("th", {}, x)))),
      h("tbody", {}, r.backups.map((b) => {
        const undo = h("button", { class: "btn ghost", disabled: b.undoneAt ? "disabled" : null }, b.undoneAt ? "Annulée" : "Annuler");
        undo.addEventListener("click", async () => {
          undo.disabled = true;
          undo.textContent = "Annulation…";
          try { await api.editUndo(b.id); toast("Modification annulée."); d.close(); onDone?.(); }
          catch (e) { toast(e.message, "bad"); undo.disabled = false; undo.textContent = "Annuler"; }
        });
        return h("tr", {}, [
          h("td", {}, new Date(b.at * 1000).toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })),
          h("td", {}, OPS[b.op] || b.op),
          h("td", { class: "muted" }, b.op === "set_money" ? `${b.params.amount} or` : `${b.params.where} ${b.params.uid}`),
          h("td", {}, undo),
        ]);
      })),
    ]) : h("div", { class: "muted" }, "Aucune modification hors ligne pour ce joueur. Les modifications faites en ligne passent par son serveur et sont dans le Journal."));
  }).catch((e) => mount(body, h("div", { class: "banner bad" }, e.message)));
}

// SERVEURS : vider, redemarrer.
export function drainDialog(servers) {
  const delay = h("input", { type: "number", min: "5", max: "300", value: "30" });
  const text = h("input", { maxlength: "200", value: "This server is closing for an update." });
  const status = h("div");
  dialog({
    title: servers.length > 1 ? `Vider ${servers.length} serveurs` : "Vider ce serveur", confirm: "Vider", danger: true,
    body: [field("Délai avant la fermeture (s)", delay), field("Message affiché", text), status],
    note: "Les joueurs voient un bandeau, puis sont renvoyés. Sur un match en cours, la partie est perdue.",
    onConfirm: async (close, content) => {
      for (const s of servers) {
        const r = await api.cmd({ op: "drain", job: s.jobId, delay: Number(delay.value), text: text.value });
        const line = h("div");
        status.append(line);
        trackCommand(r, line);
      }
      content.querySelectorAll("input").forEach((x) => { x.disabled = true; });
    },
  });
}

export function restartDialog() {
  const scope = h("select", {}, [
    h("option", { value: "old" }, "Seulement les serveurs d'une ancienne version"),
    h("option", { value: "all" }, "Tous les serveurs"),
  ]);
  const bleed = h("select", {}, [["0", "Tout de suite"], ["5", "Dans 5 minutes"], ["10", "Dans 10 minutes"], ["30", "Dans 30 minutes"]]
    .map(([v, l]) => h("option", { value: v }, l)));
  bleed.value = "10";
  const announce = h("input", { type: "checkbox", checked: "checked" });
  const toastAll = h("input", { type: "checkbox", checked: "checked" });
  const confirmText = h("input", { placeholder: "Recopie REDEMARRER pour confirmer" });
  dialog({
    title: "Redémarrer les serveurs", confirm: "Redémarrer", danger: true,
    body: [
      field("Serveurs", scope, "« Ancienne version » ne fait rien si aucune nouvelle version n'a été publiée."),
      field("Fermeture", bleed, "Avec un délai, les serveurs ne reçoivent plus de joueurs puis ferment à l'échéance : les parties en cours peuvent finir."),
      h("label", { class: "check" }, [announce, " Annoncer la maintenance sur Discord (modèle « Maintenance »)"]),
      h("label", { class: "check" }, [toastAll, " Prévenir les joueurs en jeu par un bandeau"]),
      field("Confirmation", confirmText),
    ],
    note: "Open Cloud, redémarrage des serveurs de l'univers.",
    onConfirm: async (close) => {
      if (confirmText.value.trim().toUpperCase() !== "REDEMARRER") throw new Error("Recopie REDEMARRER pour confirmer.");
      const minutes = Number(bleed.value);
      if (toastAll.checked) {
        await api.cmd({ op: "toast", job: "*", title: "Update", urgent: true,
          text: minutes ? `Servers restart for an update in ${minutes} minutes.` : "Servers restart for an update now." });
      }
      const r = await api.restart({ allVersions: scope.value === "all", bleedMinutes: minutes, announce: announce.checked });
      toast(r.announce && r.announce.sent === false ? `Redémarrage demandé. Annonce Discord échouée : ${r.announce.reason}` : "Redémarrage demandé.",
        r.announce && r.announce.sent === false ? "bad" : "ok");
      close();
    },
  });
}
