//  arsenal.js — l'atelier d'armes
//  Reprend ce que faisait l'application `game-level/` : les stats de chaque
//  arme, et le SCORE calcule depuis ces stats.
//
//  Le NIVEAU et le PRIX restent manuels. Le score sert a l'audit de la
//  progression dans chaque classe ; il ne modifie aucun prix.
//
//  La page ecrit data/arsenal.json. La commande Studio applique les stats des
//  Tools ; le bloc Luau versionne les prix et les niveaux requis dans
//  ShopConfig. Aucun bouton de cette page ne publie l'economie sur Roblox.
//
//  Onglet HABITS : les tenues (haut + bas) suivent le meme chemin que les armes.
//  Une tenue a un prix, un niveau et une SOURCE ; seule `shop` s'achete, les autres
//  (starters, kits d'abonnement, Mercenary) partent dans NO_BUY. Le bloc Luau est
//  produit par le serveur (core/arsenal.py) pour qu'un test le compare au jeu.
import { api } from "./api.js";
import { h, mount, toast } from "./ui.js";

const S = {
  data: null,
  dirty: false,
  sort: "level",
  filter: "",
  cls: "",
  faction: "",
  boardFaction: "Rainor",
  dragging: null,
  savingLevel: false,
  showShopConfig: false,
  tab: "weapons",
  outfitFilter: "",
  outfitFaction: "",
  outfitSource: "",
  draggingOutfit: null,
  showOutfitShop: false,
};

// 1 stud ~ 0.28 m -- meme constante que core/arsenal.py (STUDS_TO_M). Affichage
// seul : la portee editable reste en studs, le metre n'est qu'une conversion
// live pour juger l'equilibrage sans faire le calcul de tete.
const STUDS_TO_M = 0.28;

const NUMS = [
  { k: "damage", label: "DGT", w: 62 },
  { k: "rpm", label: "RPM", w: 66 },
  { k: "rangeStuds", label: "PORTEE", w: 74 },
  { k: "pen", label: "PEN", w: 58 },
  { k: "stabH", label: "STAB H", w: 66 },
  { k: "stabV", label: "STAB V", w: 66 },
  { k: "poids", label: "POIDS", w: 62 },
  { k: "magCap", label: "CHARG.", w: 66 },
];

function classLabel(id) {
  const c = (S.data.classes || []).find((x) => x.id === id);
  return c ? c.label : id;
}

// Le score est recalcule EN DIRECT dans la page, avec la meme formule que le
// serveur : sans ca, il faudrait sauvegarder pour voir l'effet d'une stat.
function scoreOf(w) {
  const m = S.data.scoreModel;
  if (w.damage == null || w.damage === "") return null;
  const rpm = Number(w.rpm) || 0;
  const dps = (Number(w.damage) || 0) * rpm / 60;
  const s = (m.const || 0)
    + (m.damage || 0) * (Number(w.damage) || 0)
    + (m.dps || 0) * dps
    + (m.rangeStuds || 0) * (Number(w.rangeStuds) || 0)
    + (m.pen || 0) * (Number(w.pen) || 0)
    + (m.stabH || 0) * (Number(w.stabH) || 0)
    + (m.stabV || 0) * (Number(w.stabV) || 0)
    + (m.poids || 0) * (Number(w.poids) || 0);
  return Math.round(s * 10) / 10;
}

// Rang d'une arme DANS SA CLASSE, par score. C'est la seule comparaison qui ait
// un sens : un sniper et un SMG ne se comparent pas.
function ranks() {
  const by = {};
  for (const w of S.data.weapons) {
    if (!w.cls) continue;
    (by[w.cls] = by[w.cls] || []).push(w);
  }
  const out = new Map();
  for (const rows of Object.values(by)) {
    rows.slice().sort((a, b) => (scoreOf(a) || 0) - (scoreOf(b) || 0))
      .forEach((w, i) => out.set(w, { rank: i + 1, count: rows.length }));
  }
  return out;
}

function hideWeaponTooltip() {
  document.querySelector(".ars-hover-card")?.remove();
}

function statText(value, suffix = "") {
  if (value == null || value === "" || !Number.isFinite(Number(value))) return "—";
  return `${Number(value).toLocaleString("fr-FR")}${suffix}`;
}

function positionWeaponTooltip(event, tooltip) {
  const gap = 14;
  const margin = 8;
  const rect = tooltip.getBoundingClientRect();
  let left = event.clientX + gap;
  let top = event.clientY + gap;
  if (left + rect.width > window.innerWidth - margin) {
    left = event.clientX - rect.width - gap;
  }
  if (top + rect.height > window.innerHeight - margin) {
    top = event.clientY - rect.height - gap;
  }
  tooltip.style.left = `${Math.max(margin, left)}px`;
  tooltip.style.top = `${Math.max(margin, top)}px`;
}

function showWeaponTooltip(w, event) {
  hideWeaponTooltip();
  const score = scoreOf(w);
  const rank = ranks().get(w);
  const dps = w.damage && w.rpm
    ? Math.round(Number(w.damage) * Number(w.rpm) / 60 * 10) / 10
    : null;
  const rangeM = w.rangeStuds
    ? Math.round(Number(w.rangeStuds) * STUDS_TO_M * 10) / 10
    : null;
  const stats = [
    ["Dégâts", statText(w.damage)],
    ["Cadence", statText(w.rpm, " RPM")],
    ["DPS", statText(dps)],
    ["Portée", w.rangeStuds == null ? "—" : `${statText(w.rangeStuds, " studs")} · ${statText(rangeM, " m")}`],
    ["Pénétration", statText(w.pen)],
    ["Stabilité H", statText(w.stabH)],
    ["Stabilité V", statText(w.stabV)],
    ["Poids", statText(w.poids)],
    ["Chargeur", statText(w.magCap)],
  ];
  const tooltip = h("div", { class: "ars-hover-card", role: "tooltip" }, [
    h("div", { class: "ars-hover-head" }, [
      h("div", {}, [
        h("strong", {}, w.name),
        h("small", {}, `${classLabel(w.cls)} · ${w.faction} · niveau ${w.level ?? "—"}`),
      ]),
      h("div", { class: "ars-hover-score" }, [
        h("small", {}, "SCORE"),
        h("strong", {}, score == null ? "—" : String(score)),
        h("span", {}, rank ? `rang ${rank.rank}/${rank.count}` : "sans rang"),
      ]),
    ]),
    h("div", { class: "ars-hover-stats" }, stats.map(([label, value]) =>
      h("div", { class: "ars-hover-stat" }, [h("span", {}, label), h("b", {}, value)]))),
    h("div", { class: "ars-hover-foot" },
      `Prix ${statText(w.price, " gold")} · niveau ${statText(w.level)}`),
  ]);
  document.body.append(tooltip);
  positionWeaponTooltip(event, tooltip);
}

function markDirty() {
  S.dirty = true;
  const b = document.getElementById("ars-save");
  if (b) { b.classList.add("primary"); b.textContent = "Enregistrer *"; }
}

function cell(w, key, opts = {}) {
  const inp = h("input", {
    class: "ars-in" + (opts.mono ? " mono" : ""),
    type: opts.type || "number",
    value: w[key] == null ? "" : w[key],
    style: opts.width ? `width:${opts.width}px` : "",
    disabled: opts.disabled ? "disabled" : null,
  });
  inp.addEventListener("input", () => {
    const v = inp.value.trim();
    w[key] = v === "" ? null : (opts.type === "text" ? v : Number(v));
    markDirty();
    if (opts.rerender) render();
  });
  return inp;
}

function select(w, key, options, labels) {
  const sel = h("select", { class: "ars-in" },
    options.map((o) => h("option", { value: o, selected: w[key] === o ? "selected" : null },
      labels ? labels(o) : o)));
  sel.addEventListener("change", () => {
    w[key] = sel.value;
    markDirty();
    render();
  });
  return sel;
}

function rowsToShow() {
  let rows = S.data.weapons.slice();
  if (S.cls) rows = rows.filter((w) => w.cls === S.cls);
  if (S.faction) rows = rows.filter((w) => w.faction === S.faction);
  if (S.filter) {
    const q = S.filter.toLowerCase();
    rows = rows.filter((w) => (w.name || "").toLowerCase().includes(q));
  }
  const key = S.sort;
  rows.sort((a, b) => {
    if (key === "name") return String(a.name).localeCompare(String(b.name));
    if (key === "cls") return String(a.cls).localeCompare(String(b.cls))
      || (a.level || 0) - (b.level || 0);
    const va = key === "score" ? (scoreOf(a) || 0) : (a[key] || 0);
    const vb = key === "score" ? (scoreOf(b) || 0) : (b[key] || 0);
    return va - vb;
  });
  return rows;
}

function arsenalPayload() {
  return {
    scoreModel: S.data.scoreModel,
    levelMax: S.data.levelMax,
    weapons: S.data.weapons,
    outfits: S.data.outfits,
  };
}

function highestWeaponLevel() {
  return Math.max(1, ...S.data.weapons.map((w) => Number(w.level) || 0));
}

function luauString(value) {
  return `"${String(value ?? "")
    .replace(/\\/g, "\\\\")
    .replace(/"/g, '\\"')
    .replace(/\r/g, "\\r")
    .replace(/\n/g, "\\n")}"`;
}

function shopConfigExport() {
  const issues = [];
  const names = new Set();
  const weapons = S.data.weapons.slice().sort((a, b) =>
    String(a.name || "").localeCompare(String(b.name || ""), "fr", { sensitivity: "base" }));

  for (const w of weapons) {
    const name = String(w.name || "").trim();
    if (!name) issues.push("Une arme n’a pas de nom.");
    else if (names.has(name)) issues.push(`Nom dupliqué : ${name}.`);
    names.add(name);

    for (const [key, label] of [["price", "prix"], ["level", "niveau"]]) {
      if (w[key] == null || w[key] === "" || !Number.isFinite(Number(w[key]))) {
        issues.push(`${name || "Arme sans nom"} : ${label} manquant.`);
      }
    }
  }

  const rows = (key) => weapons.map((w) =>
    `\t[${luauString(String(w.name || "").trim())}] = ${Math.trunc(Number(w[key]))},`).join("\n");
  const levelMax = Math.max(30, Number(S.data.levelMax) || 30, highestWeaponLevel());
  const code = `-- Généré depuis Command Center > Arsenal.
-- Colle ce bloc APRES la table ShopConfig.LEVEL_REQ.
-- Lors du prochain export, remplace tout ce qui se trouve entre les deux balises.
-- COMMAND_CENTER_WEAPON_SHOP_BEGIN

ShopConfig.AUTO_LEVEL_MAX = ${Math.trunc(levelMax)}

for weaponName, price in pairs({
${rows("price")}
}) do
\tShopConfig.PRICES[weaponName] = price
end

for weaponName, requiredLevel in pairs({
${rows("level")}
}) do
\tShopConfig.LEVEL_REQ[weaponName] = requiredLevel
end

-- COMMAND_CENTER_WEAPON_SHOP_END`;

  return { code, issues };
}

async function copyShopConfig(text, textarea) {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
    } else {
      textarea.focus();
      textarea.select();
      if (!document.execCommand("copy")) throw new Error("Copie refusée");
    }
    toast("Bloc ShopConfig copié.");
  } catch (_) {
    textarea.focus();
    textarea.select();
    toast("Copie automatique impossible : le texte est sélectionné, fais Ctrl+C.", "bad");
  }
}

function shopConfigGenerator() {
  if (!S.showShopConfig) return null;

  const generated = shopConfigExport();
  const textarea = h("textarea", {
    class: "ars-shop-code",
    readonly: "readonly",
    spellcheck: "false",
    "aria-label": "Code ShopConfig généré",
  }, generated.code);

  const copy = h("button", {
    class: "btn primary",
    disabled: S.dirty || generated.issues.length ? "disabled" : null,
  }, "Copier le bloc");
  copy.addEventListener("click", () => copyShopConfig(generated.code, textarea));

  return h("div", { id: "ars-shop-generator", class: "card ars-shop-generator" }, [
    h("div", { class: "ars-shop-generator-head" }, [
      h("div", {}, [
        h("h3", {}, "Générateur ShopConfig"),
        h("p", { class: "muted" },
          `${S.data.weapons.length} prix + ${S.data.weapons.length} niveaux · `
          + "bloc à coller après ShopConfig.LEVEL_REQ."),
      ]),
      copy,
    ]),
    S.dirty ? h("div", { class: "banner" },
      "Enregistre d’abord l’Arsenal pour générer exactement les valeurs présentes dans data/arsenal.json.") : null,
    generated.issues.length ? h("div", { class: "banner bad" },
      generated.issues.slice(0, 8).join(" ")) : null,
    textarea,
  ]);
}

async function moveWeapon(w, level, classId) {
  const classChanged = w.cls !== classId;
  if (S.savingLevel || (!classChanged && Number(w.level) === level)) return;
  const previous = { level: w.level, cls: w.cls, levelMax: S.data.levelMax };
  const saveEverything = S.dirty || classChanged;
  w.level = level;
  w.cls = classId;
  S.data.levelMax = Math.max(30, Number(S.data.levelMax) || 30, level);
  S.savingLevel = true;
  hideWeaponTooltip();
  render();
  try {
    S.data = saveEverything
      ? await api.saveArsenal(arsenalPayload())
      : await api.setArsenalLevel(w.name, level);
    S.dirty = false;
    const destination = `${classLabel(classId)}, niveau ${level}`;
    toast(classChanged
      ? `${w.name} → ${destination}. Arsenal enregistré.`
      : `${w.name} → niveau ${level}. Arsenal enregistré.`);
  } catch (e) {
    w.level = previous.level;
    w.cls = previous.cls;
    S.data.levelMax = previous.levelMax;
    toast(e.message, "bad");
  } finally {
    S.dragging = null;
    S.savingLevel = false;
    render();
  }
}

async function setLevelMax(value) {
  const minimum = Math.max(30, highestWeaponLevel());
  const next = Math.max(minimum, Math.min(200, Math.trunc(Number(value) || minimum)));
  if (next === S.data.levelMax) return;
  const previous = S.data.levelMax;
  S.data.levelMax = next;
  S.savingLevel = true;
  render();
  try {
    S.data = await api.saveArsenal(arsenalPayload());
    S.dirty = false;
    toast(`Timeline prolongée jusqu’au niveau ${next}.`);
  } catch (e) {
    S.data.levelMax = previous;
    toast(e.message, "bad");
  } finally {
    S.savingLevel = false;
    render();
  }
}

function progressionBoard() {
  const faction = S.boardFaction;
  const maxLevel = Math.max(30, Number(S.data.levelMax) || 30, highestWeaponLevel());
  const levels = Array.from({ length: maxLevel }, (_, i) => i + 1);
  const accessible = S.data.weapons.filter((w) =>
    w.faction === "Neutral" || w.faction === faction);
  // Même une catégorie vide reste visible : chaque cellule doit pouvoir servir
  // de destination à une arme venant d'une autre ligne.
  const classes = S.data.classes;
  const counts = new Map(levels.map((level) => [
    level,
    accessible.filter((w) => Number(w.level) === level).length,
  ]));

  const factionSel = h("select", { class: "ars-board-select" },
    ["Rainor", "Rusfor"].map((f) => h("option",
      { value: f, selected: faction === f ? "selected" : null },
      `${f} · ${f === "Rainor" ? "West" : "East"}`)));
  factionSel.addEventListener("change", () => {
    S.boardFaction = factionSel.value;
    render();
  });

  const maxInput = h("input", {
    class: "ars-level-max mono",
    type: "number",
    min: "30",
    max: "200",
    value: maxLevel,
    disabled: S.savingLevel ? "disabled" : null,
  });
  maxInput.addEventListener("change", () => setLevelMax(maxInput.value));

  const extend = h("button", {
    class: "btn",
    disabled: S.savingLevel ? "disabled" : null,
  }, "+5 niveaux");
  extend.addEventListener("click", () => setLevelMax(maxLevel + 5));

  const header = h("tr", {}, [
    h("th", { class: "ars-level-class ars-level-corner" }, "Catégorie"),
    ...levels.map((level) => h("th", { class: "ars-level-head" }, [
      h("span", {}, `Niv. ${level}`),
      h("small", { class: (counts.get(level) || 0) > 2 ? "hot" : "" },
        `${counts.get(level) || 0} arme${counts.get(level) === 1 ? "" : "s"}`),
    ])),
  ]);

  const body = classes.map((classInfo) => {
    const cells = levels.map((level) => {
      const inCell = accessible
        .filter((w) => w.cls === classInfo.id && Number(w.level) === level)
        .sort((a, b) => (scoreOf(a) || 0) - (scoreOf(b) || 0));
      const td = h("td", { class: "ars-level-cell" }, inCell.map((w) => {
        const chip = h("div", {
          class: `ars-unlock ${String(w.faction).toLowerCase()}`,
          draggable: S.savingLevel ? null : "true",
          "aria-label": `${w.name}, score ${scoreOf(w) ?? "indisponible"}`,
        }, w.name);
        chip.addEventListener("mouseenter", (event) => showWeaponTooltip(w, event));
        chip.addEventListener("mousemove", (event) => {
          const tooltip = document.querySelector(".ars-hover-card");
          if (tooltip) positionWeaponTooltip(event, tooltip);
        });
        chip.addEventListener("mouseleave", hideWeaponTooltip);
        chip.addEventListener("dragstart", (event) => {
          hideWeaponTooltip();
          S.dragging = w;
          chip.classList.add("dragging");
          event.dataTransfer.effectAllowed = "move";
          event.dataTransfer.setData("text/plain", w.name);
        });
        chip.addEventListener("dragend", () => {
          S.dragging = null;
          chip.classList.remove("dragging");
          document.querySelectorAll(".ars-level-cell.over")
            .forEach((el) => el.classList.remove("over"));
        });
        return chip;
      }));
      td.addEventListener("dragover", (event) => {
        if (!S.dragging || S.savingLevel) return;
        event.preventDefault();
        event.dataTransfer.dropEffect = "move";
        td.classList.add("over");
      });
      td.addEventListener("dragleave", () => td.classList.remove("over"));
      td.addEventListener("drop", (event) => {
        event.preventDefault();
        td.classList.remove("over");
        if (!S.dragging || S.savingLevel) return;
        moveWeapon(S.dragging, level, classInfo.id);
      });
      return td;
    });
    return h("tr", {}, [
      h("th", { class: "ars-level-class" }, classInfo.label),
      ...cells,
    ]);
  });

  return h("div", { class: "card ars-progression" }, [
    h("div", { class: "ars-progression-head" }, [
      h("div", {}, [
        h("h3", {}, "Progression des déblocages"),
        h("p", { class: "muted" },
          "Glisse une arme vers n’importe quelle catégorie et niveau : les deux sont enregistrés immédiatement. Survole une arme pour voir son score et ses stats."),
      ]),
      h("div", { class: "ars-progression-controls" }, [
        h("label", {}, [h("span", {}, "Shop"), factionSel]),
        h("label", {}, [h("span", {}, "Niveau max"), maxInput]),
        extend,
      ]),
    ]),
    h("div", { class: "ars-level-wrap" },
      h("table", { class: "ars-level-table" }, [
        h("thead", {}, header),
        h("tbody", {}, body),
      ])),
    h("div", { class: "ars-level-legend" }, [
      h("span", { class: "ars-dot neutral" }, "Neutral"),
      h("span", { class: "ars-dot rainor" }, "Rainor"),
      h("span", { class: "ars-dot rusfor" }, "Rusfor"),
    ]),
  ]);
}

function table() {
  const rk = ranks();
  const head = h("tr", {}, [
    h("th", { class: "ars-th" }, "Arme"),
    h("th", { class: "ars-th" }, "Classe"),
    h("th", { class: "ars-th" }, "Camp"),
    h("th", { class: "ars-th" }, "Rarete"),
    ...NUMS.flatMap((n) => n.k === "rangeStuds"
      ? [h("th", { class: "ars-th num" }, n.label), h("th", { class: "ars-th num calc" }, "M")]
      : [h("th", { class: "ars-th num" }, n.label)]),
    h("th", { class: "ars-th num calc" }, "DPS"),
    h("th", { class: "ars-th num calc" }, "SCORE"),
    h("th", { class: "ars-th num calc" }, "RANG"),
    h("th", { class: "ars-th num edit" }, "PRIX"),
    h("th", { class: "ars-th num edit" }, "NIVEAU"),
    h("th", { class: "ars-th" }, ""),
  ]);

  const body = rowsToShow().map((w) => {
    const sc = scoreOf(w);
    const r = rk.get(w);
    const dps = (w.damage && w.rpm) ? Math.round(w.damage * w.rpm / 60 * 10) / 10 : null;
    const rangeM = w.rangeStuds ? Math.round(w.rangeStuds * STUDS_TO_M * 10) / 10 : null;
    const del = h("button", { class: "btn tiny danger" }, "×");
    del.addEventListener("click", () => {
      S.data.weapons.splice(S.data.weapons.indexOf(w), 1);
      markDirty(); render();
    });
    return h("tr", { class: "ars-tr" }, [
      h("td", {}, cell(w, "name", { type: "text", width: 150 })),
      h("td", {}, select(w, "cls", S.data.classes.map((c) => c.id), classLabel)),
      h("td", {}, select(w, "faction", S.data.factions)),
      h("td", {}, select(w, "rarity", S.data.rarities)),
      ...NUMS.flatMap((n) => n.k === "rangeStuds"
        ? [h("td", {}, cell(w, n.k, { width: n.w, rerender: true })),
           h("td", { class: "num calc" }, rangeM == null ? "—" : String(rangeM))]
        : [h("td", {}, cell(w, n.k, { width: n.w, rerender: true }))]),
      h("td", { class: "num calc" }, dps == null ? "—" : String(dps)),
      h("td", { class: "num calc strong" }, sc == null ? "—" : String(sc)),
      h("td", { class: "num calc" }, r ? `${r.rank}/${r.count}` : "—"),
      h("td", { class: "edit" }, cell(w, "price", { width: 84, mono: true })),
      h("td", { class: "edit" }, cell(w, "level", { width: 64, mono: true })),
      h("td", {}, del),
    ]);
  });

  return h("div", { class: "ars-wrap" },
    h("table", { class: "ars-table" }, [h("thead", {}, head), h("tbody", {}, body)]));
}

function scorePanel() {
  const m = S.data.scoreModel;
  const fields = Object.keys(m).map((k) => {
    const inp = h("input", { class: "ars-in mono", type: "number", step: "0.0001", value: m[k] });
    inp.addEventListener("input", () => { m[k] = Number(inp.value) || 0; markDirty(); render(); });
    return h("label", { class: "ars-coef" }, [h("span", {}, k), inp]);
  });
  return h("div", { class: "card" }, [
    h("h3", {}, "Modele de score"),
    h("p", { class: "muted" },
      "Score = somme pondérée des stats. Il sert à comparer les armes au sein "
      + "de leur classe et à auditer la progression. Prix et niveau restent manuels."),
    h("div", { class: "ars-coefs" }, fields),
  ]);
}

function alertPanel() {
  const list = S.data.alerts || [];
  if (!list.length) {
    return h("div", { class: "card" }, [
      h("h3", {}, "Coherence"),
      h("div", { class: "banner ok" }, "Aucune alerte."),
    ]);
  }
  const LABEL = { missing: "Manque", dup: "Doublon", inversion: "Inversion" };
  return h("div", { class: "card" }, [
    h("h3", {}, `Coherence — ${list.length} alerte(s)`),
    h("p", { class: "muted" },
      "Des AVERTISSEMENTS, pas des corrections : une arme volontairement chere "
      + "et faible est un choix legitime. Recalcule a l'enregistrement."),
    h("div", { class: "ars-alerts" }, list.slice(0, 60).map((a) =>
      h("div", { class: "ars-alert " + a.kind }, [
        h("span", { class: "ars-tag" }, LABEL[a.kind] || a.kind),
        h("strong", {}, a.name),
        h("span", { class: "muted" },
          (a.cls ? ` ${classLabel(a.cls)} · ${a.faction} — ` : " — ") + a.text),
      ]))),
  ]);
}

// ---------------------------------------------------------------------------
//  HABITS
// ---------------------------------------------------------------------------

const OUTFIT_ALERT_LABEL = {
  missing: "Manque", dup: "Doublon", inversion: "Inversion", level: "Niveau",
};

function tabSwitch() {
  const tab = (id, label) => {
    const b = h("button", { class: "ars-tab" + (S.tab === id ? " on" : "") }, label);
    b.addEventListener("click", () => {
      if (S.tab === id) return;
      S.tab = id;
      render();
    });
    return b;
  };
  return h("div", { class: "ars-tabs" }, [tab("weapons", "Armes"), tab("outfits", "Habits")]);
}

function sourceLabel(id) {
  const s = (S.data.outfitSources || []).find((x) => x.id === id);
  return s ? s.label : id;
}

function outfitRows() {
  let rows = S.data.outfits.slice();
  if (S.outfitFaction) rows = rows.filter((o) => o.faction === S.outfitFaction);
  if (S.outfitSource) rows = rows.filter((o) => o.source === S.outfitSource);
  if (S.outfitFilter) {
    const q = S.outfitFilter.toLowerCase();
    rows = rows.filter((o) => [o.id, o.label, o.topName, o.bottomName, o.topTemplate, o.bottomTemplate]
      .some((v) => String(v || "").toLowerCase().includes(q)));
  }
  const rank = (o) => (o.source === "shop" ? 0 : 1);
  rows.sort((a, b) => rank(a) - rank(b)
    || String(a.faction).localeCompare(String(b.faction))
    || (a.level ?? 999) - (b.level ?? 999)
    || String(a.id).localeCompare(String(b.id)));
  return rows;
}

function outfitTitle(o) {
  const price = o.price == null ? "—" : `${Number(o.price).toLocaleString("fr-FR")} gold`;
  return `${o.id} ${o.label}\n${o.topName} / ${o.bottomName}\n${price} · niveau ${o.level ?? "—"}`;
}

async function moveOutfit(o, level) {
  if (S.savingLevel || Number(o.level) === level) return;
  const previous = o.level;
  const saveEverything = S.dirty;
  o.level = level;
  S.savingLevel = true;
  render();
  try {
    S.data = saveEverything
      ? await api.saveArsenal(arsenalPayload())
      : await api.setOutfitLevel(o.id, level);
    S.dirty = false;
    toast(`${o.id} ${o.label} → niveau ${level}. Arsenal enregistré.`);
  } catch (e) {
    o.level = previous;
    toast(e.message, "bad");
  } finally {
    S.draggingOutfit = null;
    S.savingLevel = false;
    render();
  }
}

// Une ligne par camp : les deux echelles de progression se lisent cote a cote.
function outfitBoard() {
  const maxLevel = Math.max(30, Number(S.data.levelMax) || 30);
  const levels = Array.from({ length: maxLevel }, (_, i) => i + 1);
  const sold = S.data.outfits.filter((o) => o.source === "shop");
  const lines = [
    { faction: "Rainor", label: "Rainor · West" },
    { faction: "Rusfor", label: "Rusfor · East" },
    { faction: "Neutral", label: "Neutre" },
  ].filter((l) => l.faction !== "Neutral" || sold.some((o) => o.faction === "Neutral"));
  const count = (level) => sold.filter((o) => Number(o.level) === level).length;

  const header = h("tr", {}, [
    h("th", { class: "ars-level-class ars-level-corner" }, "Camp"),
    ...levels.map((level) => h("th", { class: "ars-level-head" }, [
      h("span", {}, `Niv. ${level}`),
      h("small", {}, `${count(level)} tenue${count(level) === 1 ? "" : "s"}`),
    ])),
  ]);

  const body = lines.map((line) => h("tr", {}, [
    h("th", { class: "ars-level-class" }, line.label),
    ...levels.map((level) => {
      const inCell = sold.filter((o) => o.faction === line.faction && Number(o.level) === level)
        .sort((a, b) => (a.price || 0) - (b.price || 0));
      const td = h("td", { class: "ars-level-cell" }, inCell.map((o) => {
        const chip = h("div", {
          class: `ars-unlock ${String(o.faction).toLowerCase()}`,
          draggable: S.savingLevel ? null : "true",
          title: outfitTitle(o),
        }, `${o.label} · ${o.price == null ? "?" : Number(o.price).toLocaleString("fr-FR")}`);
        chip.addEventListener("dragstart", (event) => {
          S.draggingOutfit = o;
          chip.classList.add("dragging");
          event.dataTransfer.effectAllowed = "move";
          event.dataTransfer.setData("text/plain", o.id);
        });
        chip.addEventListener("dragend", () => {
          S.draggingOutfit = null;
          chip.classList.remove("dragging");
          document.querySelectorAll(".ars-level-cell.over")
            .forEach((el) => el.classList.remove("over"));
        });
        return chip;
      }));
      td.addEventListener("dragover", (event) => {
        if (!S.draggingOutfit || S.savingLevel) return;
        event.preventDefault();
        event.dataTransfer.dropEffect = "move";
        td.classList.add("over");
      });
      td.addEventListener("dragleave", () => td.classList.remove("over"));
      td.addEventListener("drop", (event) => {
        event.preventDefault();
        td.classList.remove("over");
        if (!S.draggingOutfit || S.savingLevel) return;
        moveOutfit(S.draggingOutfit, level);
      });
      return td;
    }),
  ]));

  return h("div", { class: "card ars-progression" }, [
    h("div", { class: "ars-progression-head" }, [
      h("div", {}, [
        h("h3", {}, "Progression des tenues vendues"),
        h("p", { class: "muted" },
          `Glisse une tenue vers un niveau (1 à ${maxLevel}) : il est enregistré immédiatement. `
          + "Le prix se règle dans le tableau ; les tenues de kit n'ont pas de niveau."),
      ]),
    ]),
    h("div", { class: "ars-level-wrap" },
      h("table", { class: "ars-level-table" }, [h("thead", {}, header), h("tbody", {}, body)])),
    h("div", { class: "ars-level-legend" }, [
      h("span", { class: "ars-dot neutral" }, "Neutral"),
      h("span", { class: "ars-dot rainor" }, "Rainor"),
      h("span", { class: "ars-dot rusfor" }, "Rusfor"),
    ]),
  ]);
}

function outfitTable() {
  const head = h("tr", {}, [
    ...["Id", "Tenue", "Camp", "Source", "Rareté"].map((t) => h("th", { class: "ars-th" }, t)),
    h("th", { class: "ars-th num edit" }, "PRIX"),
    h("th", { class: "ars-th num edit" }, "NIVEAU"),
    ...["Haut · gabarit Studio", "Haut · _ItemName", "Bas · gabarit Studio", "Bas · _ItemName"]
      .map((t) => h("th", { class: "ars-th" }, t)),
    h("th", { class: "ars-th" }, ""),
  ]);
  const body = outfitRows().map((o) => {
    const sold = o.source === "shop";
    const del = h("button", { class: "btn tiny danger" }, "×");
    del.addEventListener("click", () => {
      S.data.outfits.splice(S.data.outfits.indexOf(o), 1);
      markDirty(); render();
    });
    return h("tr", { class: "ars-tr" + (sold ? "" : " ars-locked") }, [
      h("td", {}, cell(o, "id", { type: "text", width: 54, mono: true })),
      h("td", {}, cell(o, "label", { type: "text", width: 130 })),
      h("td", {}, select(o, "faction", S.data.factions)),
      h("td", {}, select(o, "source", (S.data.outfitSources || []).map((s) => s.id), sourceLabel)),
      h("td", {}, select(o, "rarity", S.data.rarities)),
      h("td", { class: "edit" }, cell(o, "price", { width: 84, mono: true })),
      h("td", { class: "edit" }, cell(o, "level", { width: 64, mono: true, disabled: !sold })),
      h("td", {}, cell(o, "topTemplate", { type: "text", width: 200, mono: true })),
      h("td", {}, cell(o, "topName", { type: "text", width: 200 })),
      h("td", {}, cell(o, "bottomTemplate", { type: "text", width: 200, mono: true })),
      h("td", {}, cell(o, "bottomName", { type: "text", width: 200 })),
      h("td", {}, del),
    ]);
  });
  return h("div", { class: "ars-wrap" },
    h("table", { class: "ars-table" }, [h("thead", {}, head), h("tbody", {}, body)]));
}

function outfitAlertPanel() {
  const list = S.data.outfitAlerts || [];
  if (!list.length) {
    return h("div", { class: "card" }, [
      h("h3", {}, "Cohérence des habits"),
      h("div", { class: "banner ok" }, "Aucune alerte."),
    ]);
  }
  return h("div", { class: "card" }, [
    h("h3", {}, `Cohérence des habits — ${list.length} alerte(s)`),
    h("p", { class: "muted" },
      "Manque, Doublon et Niveau bloquent la copie du bloc ShopConfig ; une Inversion "
      + "(tenue moins chère qu'une tenue débloquée avant) n'est qu'un avertissement."),
    h("div", { class: "ars-alerts" }, list.slice(0, 60).map((a) =>
      h("div", { class: "ars-alert " + (a.kind === "level" ? "missing" : a.kind) }, [
        h("span", { class: "ars-tag" }, OUTFIT_ALERT_LABEL[a.kind] || a.kind),
        h("strong", {}, a.name),
        h("span", { class: "muted" }, ` ${a.faction ? a.faction + " — " : "— "}${a.text}`),
      ]))),
  ]);
}

function outfitShopGenerator() {
  if (!S.showOutfitShop) return null;
  const block = S.data.outfitShop || { code: "", issues: [] };
  const textarea = h("textarea", {
    class: "ars-shop-code",
    readonly: "readonly",
    spellcheck: "false",
    "aria-label": "Bloc ShopConfig des habits",
  }, block.code);
  const copy = h("button", {
    class: "btn primary",
    disabled: S.dirty || block.issues.length ? "disabled" : null,
  }, "Copier le bloc");
  copy.addEventListener("click", () => copyShopConfig(block.code, textarea));
  return h("div", { id: "ars-outfit-generator", class: "card ars-shop-generator" }, [
    h("div", { class: "ars-shop-generator-head" }, [
      h("div", {}, [
        h("h3", {}, "Générateur ShopConfig · habits"),
        h("p", { class: "muted" },
          "Colle ce bloc entre les balises COMMAND_CENTER_OUTFIT_SHOP de ShopConfig, ou lance "
          + "python claude_works/tools/outfit_shop.py --apply (puis sync.py pour GAME)."),
      ]),
      copy,
    ]),
    S.dirty ? h("div", { class: "banner" },
      "Enregistre d’abord l’Arsenal pour générer exactement les valeurs présentes dans data/arsenal.json.") : null,
    block.issues.length ? h("div", { class: "banner bad" }, block.issues.slice(0, 8).join(" · ")) : null,
    textarea,
  ]);
}

function renderOutfits() {
  const root = document.getElementById("main");
  const search = h("input", { placeholder: "Chercher une tenue…", value: S.outfitFilter,
    style: "width:200px" });
  search.addEventListener("input", () => { S.outfitFilter = search.value; renderOutfits(); });

  const factionSel = h("select", {}, [
    h("option", { value: "" }, "Toutes les factions"),
    ...S.data.factions.map((f) => h("option",
      { value: f, selected: S.outfitFaction === f ? "selected" : null }, f)),
  ]);
  factionSel.addEventListener("change", () => { S.outfitFaction = factionSel.value; renderOutfits(); });

  const sourceSel = h("select", {}, [
    h("option", { value: "" }, "Toutes les sources"),
    ...(S.data.outfitSources || []).map((s) => h("option",
      { value: s.id, selected: S.outfitSource === s.id ? "selected" : null }, s.label)),
  ]);
  sourceSel.addEventListener("change", () => { S.outfitSource = sourceSel.value; renderOutfits(); });

  const add = h("button", { class: "btn" }, "+ Habit");
  add.addEventListener("click", () => {
    S.data.outfits.unshift({ id: `X${String(S.data.outfits.length + 1).padStart(2, "0")}`,
      label: "Nouvelle tenue", faction: "Neutral", rarity: "Common", source: "shop",
      price: null, level: null, note: "",
      topTemplate: "", topName: "", bottomTemplate: "", bottomName: "" });
    markDirty(); renderOutfits();
  });

  const save = h("button", { id: "ars-save", class: "btn" + (S.dirty ? " primary" : "") },
    S.dirty ? "Enregistrer *" : "Enregistrer");
  save.addEventListener("click", async () => {
    save.disabled = true;
    try {
      S.data = await api.saveArsenal(arsenalPayload());
      S.dirty = false;
      toast("Arsenal enregistre.");
    } catch (e) {
      toast(e.message, "bad");
    } finally {
      save.disabled = false;
      renderOutfits();
    }
  });

  const shopExport = h("button", { id: "ars-outfit-export", class: "btn" },
    S.showOutfitShop ? "Fermer ShopConfig" : "Générer ShopConfig");
  shopExport.addEventListener("click", () => {
    S.showOutfitShop = !S.showOutfitShop;
    renderOutfits();
    if (S.showOutfitShop) {
      document.getElementById("ars-outfit-generator")
        ?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  });

  const total = S.data.outfits.length;
  const sold = S.data.outfits.filter((o) => o.source === "shop").length;
  mount(root,
    h("div", { class: "toolbar" }, [
      h("h2", {}, "Arsenal"),
      tabSwitch(),
      h("div", { class: "spacer" }),
      search, factionSel, sourceSel, add, save, shopExport,
    ]),
    h("div", { class: "muted", style: "margin:-6px 0 12px" },
      `${total} tenues · ${sold} vendues · ${total - sold} de kit (NO_BUY) · ShopConfig = source du jeu`),
    outfitBoard(),
    outfitShopGenerator(),
    outfitTable(),
    h("div", { style: "margin-top:16px" }, outfitAlertPanel()),
  );
}

function render() {
  if (S.tab === "outfits") return renderOutfits();
  hideWeaponTooltip();
  const root = document.getElementById("main");
  const search = h("input", { placeholder: "Chercher une arme…", value: S.filter,
    style: "width:200px" });
  search.addEventListener("input", () => { S.filter = search.value; render(); });

  const clsSel = h("select", {}, [
    h("option", { value: "" }, "Toutes les classes"),
    ...S.data.classes.map((c) => h("option",
      { value: c.id, selected: S.cls === c.id ? "selected" : null }, c.label)),
  ]);
  clsSel.addEventListener("change", () => { S.cls = clsSel.value; render(); });

  const factionSel = h("select", {}, [
    h("option", { value: "" }, "Toutes les factions"),
    ...S.data.factions.map((f) => h("option",
      { value: f, selected: S.faction === f ? "selected" : null }, f)),
  ]);
  factionSel.addEventListener("change", () => { S.faction = factionSel.value; render(); });

  const sortSel = h("select", {}, [
    ["level", "Trier par niveau"], ["score", "Trier par score"],
    ["price", "Trier par prix"], ["cls", "Trier par classe"], ["name", "Trier par nom"],
  ].map(([v, l]) => h("option", { value: v, selected: S.sort === v ? "selected" : null }, l)));
  sortSel.addEventListener("change", () => { S.sort = sortSel.value; render(); });

  const add = h("button", { class: "btn" }, "+ Arme");
  add.addEventListener("click", () => {
    S.data.weapons.unshift({ name: "Nouvelle arme", cls: "ar", faction: "Neutral",
      rarity: "Common", price: null, level: null });
    markDirty(); render();
  });

  const save = h("button", { id: "ars-save", class: "btn" + (S.dirty ? " primary" : "") },
    S.dirty ? "Enregistrer *" : "Enregistrer");
  save.addEventListener("click", async () => {
    save.disabled = true;
    try {
      const res = await api.saveArsenal(arsenalPayload());
      S.data = res;
      S.dirty = false;
      toast("Arsenal enregistre.");
    } catch (e) {
      toast(e.message, "bad");
    } finally {
      save.disabled = false;
      render();
    }
  });

  const shopExport = h("button", { id: "ars-shop-export", class: "btn" },
    S.showShopConfig ? "Fermer ShopConfig" : "Générer ShopConfig");
  shopExport.addEventListener("click", () => {
    S.showShopConfig = !S.showShopConfig;
    render();
    if (S.showShopConfig) {
      document.getElementById("ars-shop-generator")
        ?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  });

  mount(root,
    h("div", { class: "toolbar" }, [
      h("h2", {}, "Arsenal"),
      tabSwitch(),
      h("div", { class: "spacer" }),
      search, clsSel, factionSel, sortSel, add, save, shopExport,
    ]),
    h("div", { class: "muted", style: "margin:-6px 0 12px" },
      `${S.data.weapons.length} armes · prix versionnés · ShopConfig = source du jeu`),
    progressionBoard(),
    shopConfigGenerator(),
    table(),
    h("div", { class: "grid2", style: "margin-top:16px" }, [scorePanel(), alertPanel()]),
  );
}

export async function viewArsenal(root) {
  S.data = await api.arsenal();
  S.data.levelMax = Math.max(30, Number(S.data.levelMax) || 30, highestWeaponLevel());
  S.data.outfits = S.data.outfits || [];
  S.dirty = false;
  render(root);
}
