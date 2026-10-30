#!/usr/bin/env bash
# Configure et demarre le Command Center sur le serveur, par questions.
#   sudo bash /opt/shroud-cc/deploy/configure.sh
#
# 1. Reprend ton .env et tes donnees de PC s'ils ont ete copies dans /tmp (voir le guide) :
#      /tmp/cc.env      -> cles Roblox et Discord deja remplies sur ton PC
#      /tmp/cc-data/    -> dossier data du PC (cc.db, bot_data.json, notifications.json...)
# 2. Adresse publique : un domaine a toi, ou par defaut <ip>.sslip.io (gratuit, sans compte :
#    ce nom pointe tout seul vers l'IP du serveur ; Caddy y obtient le certificat HTTPS).
# 3. Ne demande que ce qui manque : application Discord (connexion), ton identifiant Discord.
# 4. Genere le secret des webhooks Roblox et la cle de deploiement GitHub, puis demarre.
# Relancable : une valeur deja remplie n'est plus demandee. Pour en changer une :
#   sudo nano /opt/shroud-cc/.env   puis   sudo bash /opt/shroud-cc/deploy/configure.sh
set -euo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENV="$DIR/.env"
[ "$(id -u)" = 0 ] || { echo "A lancer avec sudo : sudo bash $0"; exit 1; }
[ -f "$ENV" ] || install -m 600 -o deploy -g deploy "$DIR/.env.example" "$ENV"

say() { printf '\n\033[1;33m==> %s\033[0m\n' "$*"; }
get() { grep -E "^$1=" "$ENV" | tail -1 | cut -d= -f2- || true; }
set_var() {   # set_var CLE valeur : remplace ou ajoute, sans jamais afficher la valeur
  local key="$1" val="$2" tmp
  tmp="$(mktemp)"
  grep -vE "^$key=" "$ENV" > "$tmp" || true
  printf '%s=%s\n' "$key" "$val" >> "$tmp"
  cat "$tmp" > "$ENV" && rm -f "$tmp"
}
ask() {       # ask CLE "question" [secret] [defaut] [motif] : seulement si la valeur manque
  local key="$1" question="$2" secret="${3:-}" def="${4:-}" pattern="${5:-}" val
  [ -n "$(get "$key")" ] && return 0
  [ -n "$def" ] && question="$question [Entree : $def]"
  while true; do
    if [ -n "$secret" ]; then read -r -s -p "  $question : " val; echo; else read -r -p "  $question : " val; fi
    val="$(printf '%s' "${val:-$def}" | tr -d '[:space:]')"
    if [ -z "$val" ]; then echo "  (obligatoire)"; continue; fi
    if [ -n "$pattern" ] && ! [[ "$val" =~ $pattern ]]; then echo "  Format inattendu, recommence."; continue; fi
    break
  done
  set_var "$key" "$val"
}
IDS='^[0-9]{5,25}$'
ID_LIST='^[0-9]{5,25}(,[0-9]{5,25})*$'

# Refaire une reponse : sudo bash configure.sh --reset   (oublie les reponses de connexion)
if [ "${1:-}" = "--reset" ]; then
  for k in CC_DOMAIN CC_PUBLIC_URL DISCORD_CLIENT_ID DISCORD_CLIENT_SECRET CC_ADMINS; do set_var "$k" ""; done
  echo "  Reponses de connexion effacees : elles vont etre redemandees."
fi

# 1. Reprise du PC -----------------------------------------------------------------------
if [ -f /tmp/cc.env ]; then
  say "Reprise de ton .env de PC"
  tr -d '\r' < /tmp/cc.env | grep -E '^[A-Z_][A-Z0-9_]*=' | while IFS= read -r line; do
    key="${line%%=*}"
    case "$key" in CC_HOST|CC_PORT|CC_OPEN_BROWSER|CC_GAME_ROOT|CC_BOT|CC_WATCH|CC_JOBS|CC_DOMAIN|CC_PUBLIC_URL) continue;; esac
    [ -n "${line#*=}" ] && set_var "$key" "${line#*=}"
  done
  shred -u /tmp/cc.env 2>/dev/null || rm -f /tmp/cc.env
  echo "  Valeurs reprises ; le fichier copie a ete efface."
fi

# 2. Adresse publique -----------------------------------------------------------------
IP4="$(curl -fsS4 --max-time 5 https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}')"
if [ -z "$(get CC_DOMAIN)" ]; then
  say "Adresse de la console"
  echo "  Sans domaine a toi, garde la proposition : elle pointe deja vers ce serveur ($IP4)."
  ask CC_DOMAIN "Domaine" "" "${IP4//./-}.sslip.io"
fi
DOMAIN="$(get CC_DOMAIN)"
set_var CC_PUBLIC_URL "https://$DOMAIN"

# 3. Ce qui manque ----------------------------------------------------------------------
say "Jeu et bot (deja remplis si ton .env de PC a ete repris)"
ask ROBLOX_UNIVERSE_ID "Universe ID Roblox" "" "" "$IDS"
ask ROBLOX_PLACE_ID "Place ID du HUB" "" "" "$IDS"
ask ROBLOX_OPENCLOUD_KEY "Cle Open Cloud" secret
ask DISCORD_BOT_TOKEN "Token du bot Discord" secret
ask DISCORD_GUILD_ID "ID du serveur Discord" "" "" "$IDS"

say "Connexion a la console (Discord Developer Portal > ton application > OAuth2)"
echo "  Ajoute d'abord dans « Redirects » exactement :  https://$DOMAIN/auth/callback"
ask DISCORD_CLIENT_ID "Client ID" "" "" "$IDS"
ask DISCORD_CLIENT_SECRET "Client Secret" secret
echo "  Ton identifiant Discord : Parametres > Avances > Mode developpeur, puis clic droit"
echo "  sur ton nom > Copier l'identifiant. Plusieurs : separes par des virgules."
ask CC_ADMINS "Identifiant(s) Discord administrateur" "" "" "$ID_LIST"
set_var CC_BOT 1                                  # le bot Discord tourne ici, plus sur le PC
if [ -z "$(get ROBLOX_WEBHOOK_SECRET)" ]; then
  set_var ROBLOX_WEBHOOK_SECRET "$(openssl rand -hex 32)"
fi
chown deploy:deploy "$ENV" && chmod 600 "$ENV"

# 4. Demarrage ----------------------------------------------------------------------------
say "Construction et demarrage (2 a 5 minutes la premiere fois)"
cd "$DIR"
sudo -u deploy docker compose up -d --build
if [ -d /tmp/cc-data ]; then
  say "Reprise des donnees du PC"
  sudo -u deploy docker compose stop cc
  cid="$(sudo -u deploy docker compose ps -aq cc)"
  for f in /tmp/cc-data/*; do
    [ -f "$f" ] || continue
    case "$(basename "$f")" in *.db|*.json) ;; *) continue;; esac
    chown 1000:1000 "$f"                       # utilisateur « cc » du conteneur
    docker cp -a "$f" "$cid:/app/data/$(basename "$f")" && echo "  $(basename "$f")"
  done
  rm -rf /tmp/cc-data
  sudo -u deploy docker compose start cc
fi

ok=""
for _ in $(seq 1 30); do
  if sudo -u deploy docker compose exec -T cc python -c \
    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/healthz', timeout=3)" >/dev/null 2>&1; then
    ok=1; break
  fi
  sleep 2
done
if [ -z "$ok" ]; then
  echo "Le CC ne repond pas. Dernieres lignes :"
  sudo -u deploy docker compose logs --tail 30 cc
  exit 1
fi

# 5. Cle de deploiement GitHub (une fois) ----------------------------------------------
AUTH="${CC_DEPLOY_HOME:-/home/deploy}/.ssh/authorized_keys"
DEPLOY_KEY=""
if ! grep -q 'deploy/deploy.sh' "$AUTH" 2>/dev/null; then
  tmpk="$(mktemp -d)"
  ssh-keygen -q -t ed25519 -N "" -C github-deploy -f "$tmpk/k"
  printf 'command="bash %s/deploy/deploy.sh",no-port-forwarding,no-X11-forwarding,no-agent-forwarding,no-pty %s\n' \
    "$DIR" "$(cat "$tmpk/k.pub")" >> "$AUTH"
  chown deploy:deploy "$AUTH"
  DEPLOY_KEY="$(cat "$tmpk/k")"
  rm -rf "$tmpk"
fi
HOSTKEY="$(awk '{print $1" "$2}' "${CC_HOSTKEY:-/etc/ssh/ssh_host_ed25519_key.pub}" 2>/dev/null || true)"

cat <<EOF

========================================================================
 Le Command Center tourne :  https://$DOMAIN
 (le certificat HTTPS est obtenu a la premiere visite, quelques secondes)

 A FAIRE MAINTENANT
 1. Ouvre l'adresse, « Se connecter avec Discord ».
 2. Creator Hub > Open Cloud > ta cle > Accepted IP Addresses : $IP4/32
 3. Creator Hub > Webhooks : URL https://$DOMAIN/webhooks/roblox
    Secret :  $(get ROBLOX_WEBHOOK_SECRET)
 4. Sur ton PC, dans le .env : CC_BOT=0 et CC_WATCH=0 (une seule console active).
EOF
if [ -n "$DEPLOY_KEY" ]; then
cat <<EOF

 MISES A JOUR AUTOMATIQUES (GitHub > depot > Settings > Secrets and variables > Actions)
   Variables > New :  DEPLOY_HOST          = $IP4
   Secrets   > New :  DEPLOY_KNOWN_HOSTS   = $IP4 $HOSTKEY
   Secrets   > New :  DEPLOY_SSH_KEY       = tout le bloc ci-dessous, lignes BEGIN et END comprises

$DEPLOY_KEY

 Cette cle ne peut QUE lancer le deploiement. Elle n'est gardee nulle part sur ce
 serveur : si tu la perds, supprime sa ligne dans $AUTH et relance ce script.
EOF
fi
echo "========================================================================"
