//  md.js — rendu Markdown minimal et sur pour les documents du depot (ecran Guide).
//  Couvre ce que les docs utilisent : titres, paragraphes, listes (imbriquees, cases a
//  cocher), tableaux, blocs de code, citations, separateurs, code en ligne, gras,
//  italique, liens. Tout le texte est echappe AVANT la mise en forme : un document ne
//  peut pas injecter de HTML dans la page.

const esc = (s) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

/** Identifiant d'ancre a la GitHub : minuscules, accents gardes, espaces en tirets. */
export function slug(text) {
  return text.toLowerCase().replace(/[`*_~[\]()]/g, "").replace(/[^\p{L}\p{N}\s-]/gu, "")
    .trim().replace(/\s/g, "-");
}

// opts.link(href) -> { href, attrs } : laisse l'appelant router les liens internes.
function inline(text, opts) {
  const codes = [];
  let s = esc(text).replace(/`([^`]+)`/g, (_, c) => `\u0000${codes.push(c) - 1}\u0000`);
  s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_, label, href) => {
    const target = opts.link ? opts.link(href.replace(/&amp;/g, "&")) : { href };
    if (!target) return `<span class="md-file" title="${href}">${label}</span>`;
    const ext = /^https?:/.test(target.href);
    return `<a href="${esc(target.href)}"${target.attrs || ""}${ext ? ' target="_blank" rel="noopener"' : ""}>${label}</a>`;
  });
  s = s.replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
    .replace(/(^|[^*\w])\*([^*\s][^*]*)\*(?!\w)/g, "$1<i>$2</i>");
  return s.replace(/\u0000(\d+)\u0000/g, (_, i) => `<code>${codes[i]}</code>`);
}

const isTableSep = (l) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(l);
const cells = (l) => l.trim().replace(/^\|/, "").replace(/\|$/, "").split(/(?<!\\)\|/).map((c) => c.trim());
const listRe = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/;

/**
 * Markdown -> { html, headings: [{ level, text, id }] }.
 * Les blocs ```mermaid sont rendus en <pre class="mermaid"> pour un rendu eventuel.
 */
export function renderMarkdown(src, opts = {}) {
  const lines = src.replace(/\t/g, "    ").split("\n");
  const out = [];
  const headings = [];
  const used = new Map();
  let i = 0;

  const para = [];
  const flush = () => {
    if (para.length) out.push(`<p>${inline(para.join(" "), opts)}</p>`);
    para.length = 0;
  };

  while (i < lines.length) {
    const line = lines[i];

    // Bloc de code
    const fence = line.match(/^\s*```\s*([\w-]*)/);
    if (fence) {
      flush();
      const body = [];
      i++;
      while (i < lines.length && !/^\s*```/.test(lines[i])) body.push(lines[i++]);
      i++;
      const lang = fence[1];
      out.push(lang === "mermaid"
        ? `<pre class="mermaid">${esc(body.join("\n"))}</pre>`
        : `<pre class="code"><code>${esc(body.join("\n"))}</code></pre>`);
      continue;
    }

    if (!line.trim()) { flush(); i++; continue; }

    // Titre
    const hd = line.match(/^(#{1,6})\s+(.*?)\s*#*$/);
    if (hd) {
      flush();
      const level = hd[1].length;
      const text = hd[2];
      let id = slug(text);
      const n = used.get(id) || 0;
      used.set(id, n + 1);
      if (n) id = `${id}-${n}`;
      headings.push({ level, text: text.replace(/[`*]/g, ""), id });
      out.push(`<h${level} id="${opts.idPrefix || ""}${id}">${inline(text, opts)}</h${level}>`);
      i++;
      continue;
    }

    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { flush(); out.push("<hr>"); i++; continue; }

    // Tableau : ligne d'en-tete suivie d'un separateur
    if (line.includes("|") && i + 1 < lines.length && isTableSep(lines[i + 1])) {
      flush();
      const head = cells(line);
      i += 2;
      const rows = [];
      while (i < lines.length && lines[i].includes("|") && lines[i].trim()) rows.push(cells(lines[i++]));
      out.push(`<div class="md-table"><table><thead><tr>${head.map((c) => `<th>${inline(c, opts)}</th>`).join("")}</tr></thead><tbody>${
        rows.map((r) => `<tr>${head.map((_, k) => `<td>${inline(r[k] || "", opts)}</td>`).join("")}</tr>`).join("")
      }</tbody></table></div>`);
      continue;
    }

    // Citation
    if (/^\s*>/.test(line)) {
      flush();
      const body = [];
      while (i < lines.length && /^\s*>/.test(lines[i])) body.push(lines[i++].replace(/^\s*>\s?/, ""));
      out.push(`<blockquote>${renderMarkdown(body.join("\n"), { ...opts, idPrefix: "q-" }).html}</blockquote>`);
      continue;
    }

    // Liste (imbriquee par indentation ; les lignes de suite indentees continuent l'element)
    if (listRe.test(line)) {
      flush();
      const stack = [];   // { indent, tag }
      let html = "";
      let open = false;   // un <li> est ouvert au niveau courant
      while (i < lines.length) {
        const l = lines[i];
        const m = l.match(listRe);
        if (m) {
          const indent = m[1].length;
          const tag = /\d/.test(m[2]) ? "ol" : "ul";
          while (stack.length && indent < stack.at(-1).indent) {
            html += `</li></${stack.pop().tag}>`;
          }
          if (!stack.length || indent > stack.at(-1).indent) {
            stack.push({ indent, tag });
            html += `<${tag}>`;
          } else if (open) {
            html += "</li>";
          }
          let text = m[3];
          const box = text.match(/^\[([ xX])\]\s+(.*)$/);
          if (box) {
            const done = box[1] !== " ";
            text = box[2];
            html += `<li class="task${done ? " done" : ""}"><span class="box" aria-label="${done ? "fait" : "à faire"}"></span>${inline(text, opts)}`;
          } else {
            html += `<li>${inline(text, opts)}`;
          }
          open = true;
          i++;
        } else if (l.trim() && /^\s{2,}/.test(l) && open) {
          html += ` ${inline(l.trim(), opts)}`;
          i++;
        } else if (!l.trim() && i + 1 < lines.length && listRe.test(lines[i + 1]) && /^\s+/.test(lines[i + 1])) {
          i++;  // ligne vide entre deux sous-elements
        } else {
          break;
        }
      }
      while (stack.length) html += `</li></${stack.pop().tag}>`;
      out.push(html);
      continue;
    }

    para.push(line.trim());
    i++;
  }
  flush();
  return { html: out.join("\n"), headings };
}

// Mermaid n'est charge que si un document en contient, depuis un CDN fige. Hors ligne,
// le schema reste lisible en texte.
let mermaidReady = null;
export async function renderDiagrams(root) {
  const blocks = root.querySelectorAll("pre.mermaid");
  if (!blocks.length) return;
  try {
    mermaidReady ??= import("https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.esm.min.mjs")
      .then((m) => {
        m.default.initialize({
          startOnLoad: false, theme: "base", securityLevel: "strict",
          flowchart: { useMaxWidth: false, padding: 12 },
          themeVariables: {
            background: "#1e232a", primaryColor: "#242a32", primaryBorderColor: "#c9a24b",
            primaryTextColor: "#e3e6ea", lineColor: "#8c95a1", secondaryColor: "#1e232a",
            tertiaryColor: "#171b20", clusterBkg: "#171b20", clusterBorder: "#2c333c",
            fontFamily: "Barlow, system-ui, sans-serif", fontSize: "14px",
          },
        });
        return m.default;
      });
    const mermaid = await mermaidReady;
    await mermaid.run({ nodes: [...blocks] });
  } catch {
    blocks.forEach((b) => b.classList.add("mermaid-off"));
  }
}
