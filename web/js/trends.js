//  trends.js — ce que Roblox mesure sur l'experience (Analytics Open Cloud).
//  Lu a l'ouverture de l'ecran seulement, cache 5 min cote serveur. Aucun cout pour le jeu.
import { api } from "./api.js";
import { h, mount, toast } from "./ui.js";

const PERIODS = [[24, "24 h"], [24 * 7, "7 jours"], [24 * 28, "28 jours"]];
const COLORS = { Hub: "var(--accent)", Matchs: "var(--info)" };
const CYCLE = ["var(--accent)", "var(--info)", "var(--ok)", "var(--warn)", "var(--down)", "#a98bd6", "var(--dim)"];
let period = 24;

const fmtNum = (v) => (Math.abs(v) >= 100 ? Math.round(v).toLocaleString("fr-FR")
  : (Math.round(v * 10) / 10).toLocaleString("fr-FR"));

function colorFor(label, i) {
  return COLORS[label] || CYCLE[i % CYCLE.length];
}

function when(ts, long) {
  const d = new Date(ts * 1000);
  return long ? d.toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit" })
    : d.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
}

// Courbes multi-series en SVG : axe des temps commun, zero en bas, trois reperes.
function chart(series, unit) {
  const pts = series.flatMap((s) => s.points);
  if (!pts.length) return h("div", { class: "empty" }, "Aucune donnée sur la période.");
  const W = 600, H = 150, PAD = 4;
  const t0 = Math.min(...pts.map((p) => p[0])), t1 = Math.max(...pts.map((p) => p[0]));
  const max = Math.max(1e-9, ...pts.map((p) => p[1])) * 1.1;
  const x = (t) => PAD + ((t - t0) / Math.max(1, t1 - t0)) * (W - PAD * 2);
  const y = (v) => H - PAD - (v / max) * (H - PAD * 2);
  const grid = [0.25, 0.5, 0.75].map((f) => `<line x1="0" x2="${W}" y1="${y(max * f)}" y2="${y(max * f)}" stroke="var(--line-soft)" vector-effect="non-scaling-stroke"/>`).join("");
  const lines = series.map((s, i) => {
    const d = s.points.map((p, j) => `${j ? "L" : "M"}${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join("");
    return s.points.length === 1
      ? `<circle cx="${x(s.points[0][0])}" cy="${y(s.points[0][1])}" r="3" fill="${colorFor(s.label, i)}"/>`
      : `<path d="${d}" fill="none" stroke="${colorFor(s.label, i)}" stroke-width="1.6" vector-effect="non-scaling-stroke"/>`;
  }).join("");
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("preserveAspectRatio", "none");
  svg.setAttribute("style", "display:block;width:100%;height:150px");
  svg.setAttribute("role", "img");
  svg.innerHTML = grid + lines;
  const long = t1 - t0 > 2 * 86400;
  return h("div", {}, [
    h("div", { class: "legend", style: "justify-content:space-between;margin:0 0 4px" }, [
      h("span", {}, `max ${fmtNum(max / 1.1)}${unit ? " " + unit : ""}`), h("span", {}, ""),
    ]),
    svg,
    h("div", { class: "legend", style: "justify-content:space-between" }, [h("span", {}, when(t0, long)), h("span", {}, when(t1, long))]),
    h("div", { class: "legend", style: "flex-wrap:wrap;margin-top:8px" }, series.map((s, i) => {
      const last = s.points.at(-1);
      return h("span", {}, [h("i", { style: `background:${colorFor(s.label, i)}` }), `${s.label} `,
        h("b", { style: "color:var(--text)" }, last ? fmtNum(last[1]) : "—")]);
    })),
  ]);
}

function crashTotals(series) {
  const rows = series.map((s) => [s.label, s.points.reduce((a, p) => a + p[1], 0)])
    .filter(([, n]) => n > 0).sort((a, b) => b[1] - a[1]);
  if (!rows.length) return h("div", { class: "muted", style: "margin-top:8px" }, "Aucun crash serveur sur la période.");
  return h("table", { style: "margin-top:10px" }, [
    h("thead", {}, h("tr", {}, [h("th", {}, "Cause"), h("th", { class: "num" }, "Crashs")])),
    h("tbody", {}, rows.map(([cause, n]) => h("tr", {}, [h("td", {}, cause), h("td", { class: "num" }, fmtNum(n))]))),
  ]);
}

function explain(error) {
  if (/Analytics → Read/.test(error)) return "Ajoute « Analytics → Read » à la clé Open Cloud (Creator Hub, Open Cloud, API Keys).";
  if (/vide|empty|eligib|insufficient|not available/i.test(error)) return "Roblox ne publie ces mesures qu'à partir d'environ 100 joueurs actifs par jour.";
  return "";
}

export async function viewTrends(root) {
  const seg = h("div", { class: "seg", role: "group", "aria-label": "Période" });
  const reload = h("button", { class: "btn" }, "Relire");
  const stamp = h("span", { class: "muted" });
  const grid = h("div", { class: "grid2" });
  mount(root,
    h("div", { class: "toolbar" }, [h("h2", {}, "Tendances"), h("div", { class: "spacer" }), stamp, seg, reload]),
    h("div", { class: "muted", style: "margin:-6px 0 16px;max-width:78ch" },
      "Mesures de Roblox sur toute l'expérience, par place. Elles ne coûtent rien aux serveurs du jeu et existent même quand le Command Center est éteint. Le détail serveur par serveur est dans Live."),
    grid,
  );

  const renderSeg = () => seg.replaceChildren(...PERIODS.map(([hours, label]) => {
    const b = h("button", { class: period === hours ? "on" : "" }, label);
    b.addEventListener("click", () => { period = hours; renderSeg(); load(false); });
    return b;
  }));

  const load = async (force) => {
    mount(grid, h("div", { class: "card muted" }, "Lecture des mesures Roblox…"));
    try {
      const data = await api.trends(period, force);
      stamp.textContent = `Lu à ${new Date(data.at * 1000).toLocaleTimeString("fr-FR")}`;
      mount(grid, ...data.panels.map((p) => h("div", { class: "card", style: "margin:0" }, [
        h("h3", {}, p.title),
        p.error
          ? h("div", {}, [h("div", { class: "banner bad", style: "margin:0" }, p.error),
              explain(p.error) ? h("div", { class: "muted" }, explain(p.error)) : null])
          : chart(p.series, p.unit),
        p.id === "serverCrashes" && !p.error ? crashTotals(p.series) : null,
      ])));
    } catch (e) {
      mount(grid, h("div", { class: "banner bad" }, `Lecture impossible : ${e.message}`));
    }
  };
  reload.addEventListener("click", () => load(true).then(() => toast("Mesures relues.")));
  renderSeg();
  await load(false);
}
