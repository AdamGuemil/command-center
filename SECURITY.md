# Security

## Reporting

Please report vulnerabilities privately through GitHub's **Report a vulnerability** button
(Security tab) rather than in a public issue. You should get an answer within a week.

## How secrets are handled

- The Open Cloud key and the Discord bot token live only in environment variables or a local
  `.env` file, which is ignored by Git. They are never sent to the browser: the web UI sends
  intentions to the local server, which makes the API calls.
- The game's Discord webhooks are not in this repository: they live in the experience's
  Secrets Store and go through a Cloudflare Worker that only relays an allow-list of webhook
  ids (`tools/cloudflare/webhook-proxy.js`).
- Local data (`data/cc.db`, journals, notification asset ids) is ignored by Git.

## Current limits

- **No authentication yet.** The server binds to `127.0.0.1` by default and must not be
  exposed to a network. The Docker Compose file publishes the port on localhost only. Hosted
  access with Discord OAuth, roles, CSRF protection and rate limits is planned (lot 6).
- Destructive actions (ban, server restart, item removal, offline edits) always require an
  explicit confirmation in the UI, and some require typing a word. They will never be
  automatable.
- An Open Cloud key should be restricted to the experience it serves and, once hosted, to
  the server's IP address.

## If a secret leaks

- Open Cloud key: delete it in the Creator Hub and create a new one.
- Discord bot token: reset it in the Developer Portal.
- Discord webhook: create a new one, update the Roblox secret and the Worker allow-list,
  then delete the old webhook.
