//  guide.js — documentation embarquee : sections ecrites pour l'app (guide_content.js)
//  et documents du depot (PIPELINES.md, guide des pieges, plan, README) lus a l'ouverture.
//  Adresse d'une page : #guide/<id> ou #guide/<id>/<ancre> (lien direct, partageable).
import { api } from "./api.js";
import { h, mount } from "./ui.js";
import { GROUPS, SECTIONS } from "./guide_content.js";
import { renderMarkdown, renderDiagrams, slug } from "./md.js";

const LAST_KEY = "cc.guide.last";
const DOC_FILES = {
  "PIPELINES.md": "pipelines", "GUIDE_PIEGES.md": "pieges",
  "PLAN_COMMAND_CENTER.md": "plan", "README.md": "readme", "OPERATIONS.md": "readme",
  "ARCHITECTURE.md": "architecture",
};

let docs = null;          // [{ id, title, summary, file, updatedAt, markdown }]
let docsError = null;
let index = null;         // entrees de recherche

const norm = (s) => s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
const fmtDay = (ts) => new Date(ts * 1000).toLocaleString("fr-FR",
  { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });

function readLast() { try { return localStorage.getItem(LAST_KEY) || ""; } catch { return ""; } }
function writeLast(v) { try { localStorage.setItem(LAST_KEY, v); } catch { /* stockage indisponible */ } }

function route() {
  const [, id = "", anchor = ""] = decodeURIComponent(location.hash.slice(1)).split("/");
  return { id, anchor };
}

// Pages dans l'ordre du sommaire : prise en main, documents techniques, puis les ecrans.
const DOC_GROUP = "Documents techniques";
const NAV_GROUPS = [GROUPS[0], DOC_GROUP, ...GROUPS.slice(1)];
function pages() {
  const list = SECTIONS.map((s) => ({ kind: "section", ...s }))
    .concat((docs || []).map((d) => ({ kind: "doc", group: DOC_GROUP, ...d })));
  return NAV_GROUPS.flatMap((g) => list.filter((p) => p.group === g));
}

function mdLink(docId) {
  return (href) => {
    if (href.startsWith("#")) return { href: `#guide/${docId}/${href.slice(1)}` };
    if (/^https?:/.test(href)) return { href };
    const [path, anchor] = href.split("#");
    const target = DOC_FILES[path.split("/").pop()];
    if (target) return { href: `#guide/${target}${anchor ? `/${anchor}` : ""}` };
    return null;  // fichier du depot sans page : affiche comme un nom de fichier
  };
}

// Ancre des titres <h4> des sections ecrites a la main.
function sectionBody(section) {
  const body = h("div", { class: "guide-body", html: section.html });
  const headings = [];
  body.querySelectorAll("h4").forEach((el) => {
    el.id = `s-${slug(el.textContent)}`;
    headings.push({ level: 4, text: el.textContent, id: el.id.slice(2) });
  });
  return { body, headings, prefix: "s-" };
}

function docBody(doc) {
  const { html, headings } = renderMarkdown(doc.markdown, { link: mdLink(doc.id), idPrefix: "d-" });
  const body = h("div", { class: "guide-body md", html });
  body.querySelector("h1")?.remove();   // le titre est deja dans l'en-tete de page
  return { body, headings: headings.filter((x) => x.level > 1 && x.level < 4), prefix: "d-" };
}

// INDEX DE RECHERCHE : un morceau par titre, pour pointer au bon endroit.
function buildIndex() {
  const out = [];
  for (const s of SECTIONS) {
    const tmp = document.createElement("div");
    tmp.innerHTML = s.html;
    let cur = { page: s, anchor: "", heading: "", text: "" };
    out.push(cur);
    for (const node of tmp.childNodes) {
      if (node.nodeName === "H4") {
        cur = { page: s, anchor: slug(node.textContent), heading: node.textContent, text: "" };
        out.push(cur);
      } else {
        cur.text += ` ${node.textContent}`;
      }
    }
  }
  for (const d of docs || []) {
    let cur = { page: { kind: "doc", ...d }, anchor: "", heading: "", text: "" };
    out.push(cur);
    const used = new Map();
    for (const line of d.markdown.split("\n")) {
      const m = line.match(/^(#{1,6})\s+(.*?)\s*#*$/);
      if (m) {
        let id = slug(m[2]);
        const n = used.get(id) || 0;
        used.set(id, n + 1);
        if (n) id = `${id}-${n}`;
        cur = { page: { kind: "doc", ...d }, anchor: m[1].length > 1 ? id : "", heading: m[2].replace(/[`*]/g, ""), text: "" };
        out.push(cur);
      } else if (!/^\s*\|?[\s:|-]*$/.test(line) && !/^\s*```/.test(line)) {
        cur.text += ` ${line.replace(/[`*|#>]/g, " ")}`;
      }
    }
  }
  for (const e of out) {
    e.text = e.text.replace(/\s+/g, " ").trim();
    e.hay = norm(`${e.page.title} ${e.heading} ${e.text}`);
  }
  return out;
}

function search(query) {
  const terms = norm(query).split(/\s+/).filter((t) => t.length > 1);
  if (!terms.length) return [];
  index ??= buildIndex();
  const hits = [];
  for (const e of index) {
    if (!terms.every((t) => e.hay.includes(t))) continue;
    const head = norm(`${e.page.title} ${e.heading}`);
    const score = terms.reduce((n, t) => n + (head.includes(t) ? 10 : 0)
      + Math.min(5, e.hay.split(t).length - 1), 0);
    hits.push({ e, score });
  }
  return hits.sort((a, b) => b.score - a.score).slice(0, 40).map((x) => x.e);
}

function highlight(text, query) {
  const terms = norm(query).split(/\s+/).filter((t) => t.length > 1);
  const low = norm(text);
  let at = Math.min(...terms.map((t) => { const i = low.indexOf(t); return i < 0 ? Infinity : i; }));
  if (!Number.isFinite(at)) at = 0;
  const start = Math.max(0, at - 70);
  const slice = (start ? "…" : "") + text.slice(start, start + 220) + (text.length > start + 220 ? "…" : "");
  const frag = document.createDocumentFragment();
  const lowSlice = norm(slice);
  let pos = 0;
  const marks = [];
  for (const t of terms) {
    let i = lowSlice.indexOf(t);
    while (i >= 0) { marks.push([i, i + t.length]); i = lowSlice.indexOf(t, i + t.length); }
  }
  marks.sort((a, b) => a[0] - b[0]);
  for (const [a, b] of marks) {
    if (a < pos) continue;
    frag.append(slice.slice(pos, a), h("mark", {}, slice.slice(a, b)));
    pos = b;
  }
  frag.append(slice.slice(pos));
  return frag;
}

export async function viewGuide(root) {
  const input = h("input", { type: "search", class: "guide-search", placeholder: "Rechercher dans le guide et les documents",
    "aria-label": "Rechercher dans le guide", autocomplete: "off" });
  const nav = h("nav", { class: "guide-nav", "aria-label": "Sommaire du guide" });
  // Petit ecran : le sommaire se replie derriere un bouton.
  const navToggle = h("button", { class: "btn guide-nav-toggle", "aria-expanded": "false" }, "Sommaire");
  navToggle.addEventListener("click", () => {
    const openNow = nav.classList.toggle("open");
    navToggle.setAttribute("aria-expanded", String(openNow));
  });
  const main = h("article", { class: "guide-main" });
  const toc = h("aside", { class: "guide-toc", "aria-label": "Sur cette page" });
  const layout = h("div", { class: "guide" }, [nav, main, toc]);

  mount(root,
    h("div", { class: "toolbar" }, [h("h2", {}, "Guide"), h("div", { class: "spacer" }),
      h("span", { class: "muted guide-kbd" }, ["Touche ", h("kbd", {}, "/"), " pour chercher"]), input]),
    navToggle,
    layout,
  );

  if (!docs) {
    try { docs = (await api.docs()).docs; docsError = null; } catch (e) { docs = []; docsError = e.message; }
    index = null;
  }

  let current = null;

  const renderNav = () => {
    const groups = NAV_GROUPS;
    const all = pages();
    mount(nav, ...groups.map((g) => {
      const items = all.filter((p) => p.group === g);
      if (!items.length && !(g === DOC_GROUP && docsError)) return null;
      return h("div", { class: "gn-group" }, [
        h("div", { class: "gn-label" }, g),
        ...items.map((p) => {
          const a = h("a", { href: `#guide/${p.id}`, class: `gn-item${current?.id === p.id ? " on" : ""}`,
            "aria-current": current?.id === p.id ? "page" : null }, [
            h("span", {}, p.title),
            p.kind === "doc" ? h("span", { class: "gn-file" }, p.file) : null,
          ]);
          return a;
        }),
        g === DOC_GROUP && docsError ? h("div", { class: "gn-err" }, `Lecture impossible : ${docsError}`) : null,
      ]);
    }));
  };

  const scrollTo = (prefix, anchor) => {
    const el = anchor && main.querySelector(`#${CSS.escape(prefix + anchor)}`);
    if (el) {
      el.scrollIntoView({ block: "start" });
      el.classList.add("flash");
      setTimeout(() => el.classList.remove("flash"), 1600);
    } else {
      (root.closest(".main") || document.scrollingElement)?.scrollTo({ top: 0 });
    }
  };

  const open = (id, anchor = "", push = true) => {
    const all = pages();
    const page = all.find((p) => p.id === id) || all.find((p) => p.id === readLast()) || all[0];
    current = page;
    writeLast(page.id);
    nav.classList.remove("open");
    navToggle.setAttribute("aria-expanded", "false");
    if (push) history.replaceState(null, "", `#guide/${page.id}${anchor ? `/${anchor}` : ""}`);
    input.value = "";

    const { body, headings, prefix } = page.kind === "doc" ? docBody(page) : sectionBody(page);
    const i = all.indexOf(page);
    const prev = all[i - 1], next = all[i + 1];
    const pager = h("div", { class: "guide-pager" }, [
      prev ? h("a", { href: `#guide/${prev.id}`, class: "gp prev" }, [h("span", {}, "Précédent"), h("b", {}, prev.title)]) : h("span"),
      next ? h("a", { href: `#guide/${next.id}`, class: "gp next" }, [h("span", {}, "Suivant"), h("b", {}, next.title)]) : h("span"),
    ]);
    // Documents : tableaux larges, le sommaire passe en tete de page et libere la colonne de droite.
    const isDoc = page.kind === "doc";
    layout.classList.toggle("doc-mode", isDoc);
    const docToc = isDoc && headings.length > 1
      ? h("details", { class: "doc-toc" }, [
          h("summary", {}, `Sur cette page (${headings.filter((x) => x.level === 2).length || headings.length} parties)`),
          h("div", { class: "doc-toc-list" }, headings.map((x) =>
            h("a", { href: `#guide/${page.id}/${x.id}`, class: `gt-item l${x.level}` }, x.text))),
        ])
      : null;
    mount(main,
      h("div", { class: "guide-eyebrow" }, page.group),
      h("h1", { class: "guide-title" }, page.title),
      page.kind === "doc"
        ? h("p", { class: "guide-meta" }, [`${page.summary} `, h("span", { class: "muted" }, `${page.file}, mis à jour le ${fmtDay(page.updatedAt)}.`)])
        : h("p", { class: "guide-meta" }, page.summary),
      docToc,
      body,
      pager,
    );
    mount(toc, ...(!isDoc && headings.length > 1 ? [
      h("div", { class: "gt-label" }, "Sur cette page"),
      ...headings.map((x) => h("a", { href: `#guide/${page.id}/${x.id}`, class: `gt-item l${x.level}` }, x.text)),
    ] : []));
    renderNav();
    renderDiagrams(body);
    scrollTo(prefix, anchor);
    if (!isDoc) spy(prefix, headings);
    else observer?.disconnect();
  };

  // Sur cette page : le titre en cours de lecture est mis en avant pendant le defilement.
  let observer = null;
  const spy = (prefix, headings) => {
    observer?.disconnect();
    if (headings.length < 2 || typeof IntersectionObserver === "undefined") return;
    const links = new Map([...toc.querySelectorAll(".gt-item")].map((a) => [a.getAttribute("href").split("/").pop(), a]));
    observer = new IntersectionObserver((entries) => {
      const visible = entries.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
      if (!visible) return;
      links.forEach((a) => a.classList.remove("on"));
      links.get(visible.target.id.slice(prefix.length))?.classList.add("on");
    }, { root: root.closest(".main"), rootMargin: "0px 0px -70% 0px" });
    headings.forEach((x) => { const el = main.querySelector(`#${CSS.escape(prefix + x.id)}`); if (el) observer.observe(el); });
  };

  const showResults = (query) => {
    const hits = search(query);
    current = null;
    renderNav();
    mount(toc);
    layout.classList.remove("doc-mode");
    mount(main,
      h("div", { class: "guide-eyebrow" }, "Recherche"),
      h("h1", { class: "guide-title" }, hits.length ? `${hits.length}${hits.length === 40 ? "+" : ""} résultat(s)` : "Aucun résultat"),
      hits.length ? null : h("p", { class: "guide-meta" }, "Essaie un autre mot : un écran (Live, Boosts), un terme (crash, LP, webhook) ou un nom de fichier."),
      h("div", { class: "guide-results" }, hits.map((e) => h("a", {
        href: `#guide/${e.page.id}${e.anchor ? `/${e.anchor}` : ""}`, class: "gr",
      }, [
        h("div", { class: "gr-path" }, [e.page.title, e.heading ? ` › ${e.heading}` : ""]),
        h("div", { class: "gr-text" }, highlight(e.text || e.heading || e.page.summary || "", query)),
      ]))),
    );
  };

  // Navigation interne : liens du sommaire, du pager, des documents et des resultats.
  root.addEventListener("click", (ev) => {
    const a = ev.target.closest("a[href^='#guide']");
    if (!a) return;
    ev.preventDefault();
    const [, id = "", anchor = ""] = decodeURIComponent(a.getAttribute("href").slice(1)).split("/");
    if (current && id === current.id && anchor) {
      history.replaceState(null, "", `#guide/${id}/${anchor}`);
      scrollTo(current.kind === "doc" ? "d-" : "s-", anchor);
    } else {
      open(id, anchor);
    }
  });

  let timer;
  input.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(() => (input.value.trim().length > 1 ? showResults(input.value) : open(current?.id || readLast())), 120);
  });
  input.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") { input.value = ""; open(readLast()); }
    if (ev.key === "Enter") main.querySelector(".gr")?.click();
  });
  const onKey = (ev) => {
    if (!root.isConnected) { document.removeEventListener("keydown", onKey); return; }
    if (ev.key === "/" && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName || "")) {
      ev.preventDefault();
      input.focus();
    }
  };
  document.addEventListener("keydown", onKey);
  const onRoute = () => {
    if (!root.isConnected || !main.isConnected) { window.removeEventListener("cc:guide-route", onRoute); return; }
    const r = route();
    open(r.id, r.anchor, false);
  };
  window.addEventListener("cc:guide-route", onRoute);

  const r = route();
  open(r.id, r.anchor, false);
}
