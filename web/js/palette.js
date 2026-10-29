//  palette.js — palette de commandes (Ctrl+K) : aller a un ecran, ouvrir un joueur,
//  lancer une action. Les actions ouvrent leur fenetre habituelle : rien ne part sans
//  confirmation.
import { api } from "./api.js";
import { h, mount, toast } from "./ui.js";
import { banDialog, kickDialog, messageDialog, restartDialog } from "./actions.js";

function screens() {
  return [...document.querySelectorAll(".nav-item")].map((el) => ({
    label: el.textContent.trim().replace(/\d+$/, ""), hint: "Écran", run: () => { location.hash = `#${el.dataset.view}`; },
  }));
}

async function withPlayer(query, fn) {
  try {
    const who = await api.playerSearch(query);
    fn(who.userId, who.name || query);
  } catch (e) {
    toast(e.message, "bad");
  }
}

function commandsFor(text) {
  const q = text.trim();
  const out = [];
  const m = q.match(/^(\S+)\s+(.+)$/);
  const verb = (m ? m[1] : q).toLowerCase();
  const arg = m ? m[2].trim() : "";
  if (arg && ["joueur", "fiche", "player"].includes(verb)) {
    out.push({ label: `Ouvrir la fiche de ${arg}`, hint: "Joueur", run: () => { location.hash = `#players/${encodeURIComponent(arg)}`; } });
  }
  if (arg && ["ban", "bannir"].includes(verb)) {
    out.push({ label: `Bannir ${arg}`, hint: "Action", run: () => withPlayer(arg, (id, name) => banDialog([id], name)) });
  }
  if (arg && ["kick", "expulser"].includes(verb)) {
    out.push({ label: `Expulser ${arg}`, hint: "Action", run: () => withPlayer(arg, (id, name) => kickDialog(id, name)) });
  }
  if (q && !m && !/\s/.test(q) && q.length >= 3) {
    out.push({ label: `Ouvrir la fiche de ${q}`, hint: "Joueur", run: () => { location.hash = `#players/${encodeURIComponent(q)}`; } });
  }
  out.push(
    { label: "Message à tous les joueurs", hint: "Action", run: () => messageDialog({ label: "Tous les joueurs connectés" }) },
    { label: "Redémarrer les serveurs", hint: "Action", run: () => restartDialog() },
  );
  return out;
}

const norm = (s) => s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");

export function openPalette() {
  if (document.querySelector(".palette")) return;
  const input = h("input", { class: "palette-input", placeholder: "Écran, joueur (fiche Pseudo), ban Pseudo, kick Pseudo…", "aria-label": "Commande" });
  const list = h("div", { class: "palette-list", role: "listbox" });
  const back = h("div", { class: "dlg-back palette", role: "dialog", "aria-modal": "true", "aria-label": "Palette de commandes" },
    h("div", { class: "dlg palette-box" }, [input, list, h("div", { class: "palette-foot muted" }, "Entrée pour lancer, flèches pour choisir, Échap pour fermer")]));
  let items = [], sel = 0;
  const close = () => back.remove();
  const render = () => {
    const q = norm(input.value.trim());
    const nav = screens().filter((s) => !q || norm(s.label).includes(q));
    items = [...nav.slice(0, 6), ...commandsFor(input.value)].slice(0, 10);
    sel = Math.min(sel, items.length - 1);
    mount(list, ...items.map((it, i) => {
      const row = h("div", { class: `palette-item${i === sel ? " on" : ""}`, role: "option" }, [h("span", {}, it.label), h("span", { class: "muted" }, it.hint)]);
      row.addEventListener("mousemove", () => { if (sel !== i) { sel = i; render(); } });
      row.addEventListener("click", () => { close(); it.run(); });
      return row;
    }));
  };
  input.addEventListener("input", () => { sel = 0; render(); });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Escape") close();
    else if (e.key === "ArrowDown") { sel = Math.min(items.length - 1, sel + 1); render(); e.preventDefault(); }
    else if (e.key === "ArrowUp") { sel = Math.max(0, sel - 1); render(); e.preventDefault(); }
    else if (e.key === "Enter" && items[sel]) { const it = items[sel]; close(); it.run(); }
  });
  back.addEventListener("click", (e) => { if (e.target === back) close(); });
  document.body.append(back);
  render();
  input.focus();
}

export function installPalette() {
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      openPalette();
    }
  });
}
