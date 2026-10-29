//  ui.js — helpers partages par toutes les vues

/** Cree un element. `props` accepte class, html, text, onclick, et attributs. */
export function h(tag, props = {}, children = []) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "html") el.innerHTML = v;
    else if (k === "text") el.textContent = v;
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v);
  }
  for (const c of [].concat(children)) {
    if (c == null) continue;
    el.append(c instanceof Node ? c : document.createTextNode(c));
  }
  return el;
}

/**
 * Remplace le contenu de `root` en ignorant les enfants nuls.
 *
 * A UTILISER PARTOUT au lieu de root.replaceChildren(...) : cette derniere
 * convertit `null` en noeud texte "null", donc un bloc conditionnel du type
 * `condition ? h(...) : null` affichait litteralement « null » a l'ecran.
 */
export function mount(root, ...children) {
  root.replaceChildren(...children.flat().filter((c) => c != null && c !== false));
}

export function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

let toastTimer;
export function toast(message, kind = "ok") {
  const el = document.getElementById("toast");
  el.textContent = message;
  el.className = `toast show ${kind}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.className = "toast"), kind === "bad" ? 6500 : 3200);
}

export function fmtDuration(seconds) {
  seconds = Math.max(0, Math.floor(seconds || 0));
  const d = Math.floor(seconds / 86400);
  const hrs = Math.floor((seconds % 86400) / 3600);
  const min = Math.floor((seconds % 3600) / 60);
  if (d) return `${d}j ${String(hrs).padStart(2, "0")}h`;
  if (hrs) return `${hrs}h ${String(min).padStart(2, "0")}m`;
  return `${min}m`;
}

export function fmtDate(ts) {
  return new Date(ts * 1000).toLocaleString("fr-FR",
    { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

/**
 * Rendu Markdown minimal, fidele a ce que Discord affiche reellement :
 * gras, italique, code, barre, et mentions de salon. Le but est de voir le
 * message tel qu'il sortira, pas de reimplementer Markdown.
 */
export function renderDiscordMarkdown(text) {
  let out = escapeHtml(text);
  out = out.replace(/```([\s\S]*?)```/g, "<code>$1</code>");
  out = out.replace(/`([^`\n]+)`/g, "<code>$1</code>");
  out = out.replace(/\*\*\*([^*]+)\*\*\*/g, "<strong><em>$1</em></strong>");
  out = out.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  out = out.replace(/\*([^*\n]+)\*/g, "<em>$1</em>");
  out = out.replace(/__([^_]+)__/g, "<u>$1</u>");
  out = out.replace(/~~([^~]+)~~/g, "<s>$1</s>");
  out = out.replace(/&lt;#([A-Za-z0-9_\-]+)&gt;/g, '<span class="mention">#$1</span>');
  out = out.replace(/&lt;@&amp;(\d+)&gt;/g, '<span class="mention">@role</span>');
  out = out.replace(/(https?:\/\/[^\s]+)/g, '<span style="color:#00a8fc">$1</span>');
  return out;
}

/** Convertit une couleur decimale Discord en #rrggbb, et l'inverse. */
export const toHex = (dec) => "#" + Number(dec || 0).toString(16).padStart(6, "0");
export const toDec = (hex) => parseInt(String(hex).replace("#", ""), 16) || 0;

export function confirmAction(message) {
  return window.confirm(message);
}
