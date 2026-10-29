//  automations.js — Système > Automatisations
//  Chaque regle dit ce qui peut partir seul depuis une carte de l'Accueil. Tout est manuel
//  par defaut ; le serveur (core/automations.py) refuse toute action destructrice.
import { api, me } from "./api.js";
import { h, mount, toast, fmtDate } from "./ui.js";

const MODES = [["manual", "Manuel"], ["delay", "Avec délai"], ["auto", "Immédiat"]];
const STATES = { planned: ["prévue", ""], done: ["partie", "ok"], failed: ["échec", "bad"], cancelled: ["annulée", ""] };
const NEVER = ["Wipe", "Ban et vague de bans", "Redémarrage des serveurs", "Effacement RTBF", "Retrait d'objet ou d'or",
  "Dons"];

function seg(value, onPick, disabled) {
  const box = h("div", { class: "seg", role: "radiogroup", "aria-label": "Mode" });
  const draw = (v) => box.replaceChildren(...MODES.map(([id, label]) => {
    const b = h("button", { class: v === id ? "on" : "", role: "radio", "aria-checked": String(v === id), disabled }, label);
    b.addEventListener("click", () => { draw(id); onPick(id); });
    return b;
  }));
  draw(value);
  return box;
}

function ruleCard(rule, maxDelay, canEdit, onSaved) {
  const cfg = { ...rule.config, actions: [...rule.config.actions] };
  const delay = h("input", { type: "number", min: "0", max: String(maxDelay), value: String(cfg.delay), disabled: !canEdit,
    "aria-label": "Délai en minutes", style: "width:90px" });
  const delayRow = h("div", { class: "auto-delay" }, [delay, h("span", { class: "muted" }, "min après l'apparition de la carte")]);
  const save = h("button", { class: "btn primary", disabled: true }, "Enregistrer");
  const dirty = () => { save.disabled = !canEdit; };
  const showDelay = () => { delayRow.style.display = cfg.mode === "delay" ? "" : "none"; };
  const modes = seg(cfg.mode, (m) => { cfg.mode = m; showDelay(); dirty(); }, !canEdit);
  delay.addEventListener("input", dirty);
  const checks = Object.entries(rule.actions).map(([id, label]) => {
    const cb = h("input", { type: "checkbox", disabled: !canEdit });
    cb.checked = cfg.actions.includes(id);
    cb.addEventListener("change", () => {
      cfg.actions = cb.checked ? [...new Set([...cfg.actions, id])] : cfg.actions.filter((x) => x !== id);
      dirty();
    });
    return h("label", { class: "check" }, [cb, label]);
  });
  save.addEventListener("click", async () => {
    save.disabled = true;
    try {
      onSaved(await api.saveAutomation(rule.id, { mode: cfg.mode, delay: Number(delay.value), actions: cfg.actions }));
      toast(cfg.mode === "manual" ? "Règle repassée en manuel." : "Règle enregistrée.");
    } catch (e) { toast(e.message, "bad"); save.disabled = false; }
  });
  showDelay();
  const by = rule.config._by ? `Modifiée par ${rule.config._by}, ${fmtDate(rule.config._at)}` : "Jamais modifiée";
  return h("section", { class: `card auto-rule ${cfg.mode === "manual" ? "" : "on"}` }, [
    h("div", { class: "auto-head" }, [
      h("div", {}, [h("h3", {}, rule.label), h("div", { class: "muted" }, `Carte : ${rule.when}`)]),
      h("div", { style: "flex:1" }), modes,
    ]),
    delayRow,
    h("div", { class: "auto-actions" }, checks),
    h("div", { class: "auto-foot" }, [h("span", { class: "muted" }, by), h("div", { style: "flex:1" }), save]),
  ]);
}

function globalCard(g, canEdit, onSaved) {
  const allManual = h("input", { type: "checkbox", disabled: !canEdit });
  allManual.checked = g.allManual;
  const opsLog = h("input", { type: "checkbox", disabled: !canEdit });
  opsLog.checked = g.opsLog;
  const start = h("input", { type: "time", value: g.quietStart, disabled: !canEdit, "aria-label": "Début des heures calmes" });
  const end = h("input", { type: "time", value: g.quietEnd, disabled: !canEdit, "aria-label": "Fin des heures calmes" });
  const save = h("button", { class: "btn primary", disabled: !canEdit }, "Enregistrer");
  save.addEventListener("click", async () => {
    save.disabled = true;
    try {
      onSaved(await api.saveAutomation("_global", { allManual: allManual.checked, opsLog: opsLog.checked,
        quietStart: start.value, quietEnd: end.value }));
      toast(allManual.checked ? "Tout est en manuel : rien ne partira seul." : "Réglages enregistrés.");
    } catch (e) { toast(e.message, "bad"); }
    save.disabled = !canEdit;
  });
  return h("section", { class: `card ${g.allManual ? "auto-off" : ""}` }, [
    h("h3", {}, "Réglages communs"),
    h("label", { class: "check" }, [allManual, h("span", {}, [h("b", {}, "Tout en manuel"),
      h("span", { class: "muted" }, " : coupe toutes les règles et annule ce qui était prévu.")])]),
    h("div", { class: "auto-quiet" }, [h("span", {}, "Heures calmes (Paris) : rien ne part seul de"), start,
      h("span", {}, "à"), end, h("span", { class: "muted" }, "l'envoi attend la fin de la plage.")]),
    h("label", { class: "check" }, [opsLog, "Prévenir dans #ops-log à chaque envoi automatique"]),
    h("div", { class: "auto-foot" }, [h("div", { style: "flex:1" }), save]),
  ]);
}

export async function viewAutomations(root) {
  const [data, who] = await Promise.all([api.automations(), me()]);
  const canEdit = Boolean(who?.permissions?.admin);
  const render = (d) => {
    const runs = d.runs || [];
    mount(root,
      h("div", { class: "toolbar" }, [h("h2", {}, "Automatisations")]),
      h("p", { class: "muted", style: "margin:-6px 0 16px;max-width:80ch" },
        "Par défaut, rien ne part sans ton clic. Une règle fait partir seule les publications cochées d'une carte de "
        + "l'Accueil, avec le même aperçu et le même journal qu'à la main (auteur « automatique »). Avec un délai, la "
        + "carte affiche l'heure de départ et un bouton pour annuler. Un échec n'est jamais retenté seul : la carte le "
        + "repropose à la main."),
      canEdit ? null : h("div", { class: "banner info" }, "Lecture seule : seuls les administrateurs changent ces règles."),
      globalCard(d.global, canEdit, render),
      ...d.rules.map((r) => ruleCard(r, d.maxDelay, canEdit && !d.global.allManual, render)),
      h("section", { class: "card" }, [
        h("h3", {}, "Jamais automatique"),
        h("p", { class: "muted" }, "Ces actions demandent toujours un humain, une confirmation et laissent une trace : "
          + NEVER.join(", ") + "."),
      ]),
      h("section", { class: "card" }, [
        h("h3", {}, "Derniers envois automatiques"),
        runs.length ? h("table", {}, [
          h("thead", {}, h("tr", {}, ["Carte", "Action", "État", "Quand", "Erreur"].map((x) => h("th", {}, x)))),
          h("tbody", {}, runs.map((r) => {
            const [label, cls] = STATES[r.state] || [r.state, ""];
            return h("tr", {}, [h("td", {}, r.card), h("td", {}, r.action), h("td", {}, h("span", { class: `tag ${cls}` }, label)),
              h("td", { style: "white-space:nowrap" }, fmtDate(r.done_at || r.due)), h("td", { class: "muted" }, r.error || "")]);
          })),
        ]) : h("div", { class: "muted" }, "Aucun pour l'instant."),
      ]));
  };
  render(data);
}
