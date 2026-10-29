// Relais Roblox -> Discord (Cloudflare Worker « hf-webhook-proxy »).
//
// POURQUOI : Discord refuse les requetes venues directement des serveurs Roblox.
// Le jeu (DiscordFeed.luau) poste donc ici, sur /api/webhooks/<id>/<token>, et ce
// Worker les transmet a discord.com.
//
// GARDE : seuls les webhooks dont l'id figure dans la variable ALLOWED_WEBHOOK_IDS
// (ids separes par des virgules, reglee dans Cloudflare > Worker > Settings >
// Variables and Secrets) sont relayes. Sans elle, ce Worker serait un relais ouvert
// vers n'importe quel webhook Discord du monde, a ton nom et sur ton quota.
//
// Deploiement : coller ce fichier dans l'editeur du Worker, puis « Deploy ».

const WEBHOOK_PATH = /^\/api\/webhooks\/(\d{17,20})\/([A-Za-z0-9_-]{20,100})\/?$/;
const MAX_BODY = 16_000; // un embed Discord complet tient tres largement dedans

export default {
  async fetch(request, env) {
    if (request.method !== "POST") {
      return new Response("Method Not Allowed", { status: 405 });
    }

    const match = new URL(request.url).pathname.match(WEBHOOK_PATH);
    if (!match) {
      return new Response("Not Found", { status: 404 });
    }
    const [, id, token] = match;

    const allowed = String(env.ALLOWED_WEBHOOK_IDS || "")
      .split(",").map((s) => s.trim()).filter(Boolean);
    if (!allowed.includes(id)) {
      return new Response("Forbidden", { status: 403 });
    }

    const body = await request.text();
    if (body.length > MAX_BODY) {
      return new Response("Payload Too Large", { status: 413 });
    }

    const upstream = await fetch(`https://discord.com/api/webhooks/${id}/${token}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
    });
    // On renvoie le statut Discord tel quel : un 404 (webhook supprime) ou un 429
    // (limite de debit) doit apparaitre dans les warn du serveur Roblox.
    return new Response(upstream.status === 204 ? null : await upstream.text(), {
      status: upstream.status,
      headers: { "Content-Type": "application/json" },
    });
  },
};
