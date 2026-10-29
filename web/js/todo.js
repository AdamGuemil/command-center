//  todo.js — Reste a faire : actions manuelles qui attendent le developpeur.
//  Le serveur verifie seul ce qui peut l'etre (droit Analytics, joueurs actifs, anciens
//  serveurs) et passe une tache a « C'est le moment » des qu'elle devient possible.
import { api } from "./api.js";
import { h, mount, toast } from "./ui.js";

const STATE = {
  ready: ["C'est le moment", "ok"],
  todo: ["À faire", "warn"],
  blocked: ["En attente", ""],
  done: ["Fait", "ok"],
};

function item(it, reload) {
  const [label, cls] = STATE[it.state] || [it.state, ""];
  const actions = [];
  if (!it.auto && it.state !== "done") {
    const b = h("button", { class: it.state === "ready" ? "btn primary" : "btn" }, "Marquer comme fait");
    b.addEventListener("click", async () => { await api.markTodo(it.id, true); toast("Tâche cochée."); reload(false); });
    actions.push(b);
  }
  if (!it.auto && it.state === "done") {
    const b = h("button", { class: "btn ghost" }, "Rouvrir");
    b.addEventListener("click", async () => { await api.markTodo(it.id, false); reload(false); });
    actions.push(b);
  }
  return h("div", { class: `card todo ${it.state}` }, [
    h("div", { class: "todo-head" }, [
      h("span", { class: `tag ${cls}` }, label),
      h("h3", {}, it.title),
      h("div", { style: "flex:1" }),
      it.auto ? h("span", { class: "soon" }, "Vérifié automatiquement") : null,
      ...actions,
    ]),
    it.detail ? h("p", { class: it.state === "blocked" ? "muted" : "" }, it.detail) : null,
    it.state !== "done" ? h("dl", { class: "kv" }, [
      h("dt", {}, "Où"), h("dd", {}, it.where),
      h("dt", {}, "À quoi ça sert"), h("dd", {}, it.why),
    ]) : null,
  ]);
}

export async function viewTodo(root) {
  const list = h("div");
  const stamp = h("span", { class: "muted" });
  const recheck = h("button", { class: "btn" }, "Revérifier");
  mount(root,
    h("div", { class: "toolbar" }, [h("h2", {}, "Reste à faire"), h("div", { class: "spacer" }), stamp, recheck]),
    h("div", { class: "muted", style: "margin:-6px 0 16px;max-width:78ch" },
      "Les actions qui se font à la main, hors du Command Center. Quand une condition se vérifie "
      + "(droit de clé, nombre de joueurs, anciens serveurs), le CC la contrôle toutes les 30 min "
      + "et prévient quand la tâche devient possible."),
    list,
  );
  const load = async (force) => {
    try {
      const data = await api.todo(force);
      stamp.textContent = data.at ? `Vérifié à ${new Date(data.at * 1000).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })}` : "";
      mount(list, ...data.items.map((it) => item(it, load)));
      window.dispatchEvent(new CustomEvent("cc:todo", { detail: data }));
    } catch (e) {
      mount(list, h("div", { class: "banner bad" }, `Lecture impossible : ${e.message}`));
    }
  };
  recheck.addEventListener("click", () => load(true).then(() => toast("Revérifié.")));
  await load(false);
}
