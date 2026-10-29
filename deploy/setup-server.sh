#!/usr/bin/env bash
# Prepare un serveur neuf (Ubuntu 24.04 ou Debian 12) pour le Command Center.
# A lancer UNE fois :   curl -fsSL <url brute de ce fichier> | sudo bash
# Ensuite :             sudo bash /opt/shroud-cc/deploy/configure.sh   (.env, demarrage)
# Guide pas a pas (Oracle Cloud gratuit) : docs/HEBERGEMENT_ORACLE.md
# Relancable sans risque : chaque etape verifie ce qui existe deja.
#
# Ce que fait le script :
#   1. mises a jour de securite automatiques, pare-feu (22, 80, 443 seulement), swap si < 2 Go ;
#   2. Docker et son plugin compose (depot officiel Docker) ;
#   3. utilisateur « deploy » (membre du groupe docker) pour les mises a jour depuis GitHub ;
#   4. depot clone dans /opt/shroud-cc et .env cree (droits 600) a partir de .env.example ;
#   5. connexion SSH par mot de passe coupee, SEULEMENT si une cle SSH root existe deja.
set -euo pipefail

REPO="${CC_REPO:-https://github.com/AdamGuemil/command-center.git}"
DIR="${CC_DIR:-/opt/shroud-cc}"
say() { printf '\n\033[1;33m==> %s\033[0m\n' "$*"; }

[ "$(id -u)" = 0 ] || { echo "A lancer en root (sudo -i)."; exit 1; }
# shellcheck source=/dev/null
. /etc/os-release
case "$ID" in ubuntu|debian) ;; *) echo "Systeme non prevu : $ID (Ubuntu ou Debian attendu)."; exit 1;; esac

say "Paquets de base et mises a jour de securite automatiques"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -yq ca-certificates curl git ufw unattended-upgrades
dpkg-reconfigure -f noninteractive unattended-upgrades

say "Pare-feu : SSH, HTTP, HTTPS"
# Images Oracle Cloud : une regle iptables REJECT ferme tout sauf SSH. Installer ufw retire
# iptables-persistent (la regle ne revient plus au redemarrage) ; on la retire aussi tout de suite.
iptables -S INPUT 2>/dev/null | grep -- '-j REJECT' | sed 's/^-A /-D /' | while read -r rule; do
  # shellcheck disable=SC2086
  iptables $rule || true
done
ufw allow OpenSSH >/dev/null
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw allow 443/udp >/dev/null
ufw --force enable >/dev/null
ufw status | sed 's/^/   /'

if [ "$(free -m | awk '/^Mem:/{print $2}')" -lt 2000 ] && ! swapon --show | grep -q .; then
  say "Swap de 1 Go (moins de 2 Go de RAM)"
  fallocate -l 1G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

if ! command -v docker >/dev/null || ! docker compose version >/dev/null 2>&1; then
  say "Docker (depot officiel)"
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL "https://download.docker.com/linux/$ID/gpg" -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/$ID $VERSION_CODENAME stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -q
  apt-get install -yq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
systemctl enable --now docker >/dev/null
docker compose version | sed 's/^/   /'

say "Utilisateur deploy"
id deploy >/dev/null 2>&1 || useradd --create-home --shell /bin/bash deploy
usermod -aG docker deploy
install -d -m 700 -o deploy -g deploy /home/deploy/.ssh
touch /home/deploy/.ssh/authorized_keys
chown deploy:deploy /home/deploy/.ssh/authorized_keys && chmod 600 /home/deploy/.ssh/authorized_keys

say "Depot dans $DIR"
if [ -d "$DIR/.git" ]; then
  sudo -u deploy git -C "$DIR" pull --ff-only
else
  install -d -o deploy -g deploy "$DIR"
  sudo -u deploy git clone "$REPO" "$DIR"
fi
if [ ! -f "$DIR/.env" ]; then
  install -m 600 -o deploy -g deploy "$DIR/.env.example" "$DIR/.env"
fi

if [ -s /root/.ssh/authorized_keys ] || [ -s "/home/${SUDO_USER:-ubuntu}/.ssh/authorized_keys" ]; then
  say "SSH : connexion par mot de passe coupee (une cle SSH est installee)"
  printf 'PasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitRootLogin prohibit-password\n' \
    > /etc/ssh/sshd_config.d/10-shroud-cc.conf
  systemctl reload ssh 2>/dev/null || systemctl reload sshd
else
  say "SSH : aucune cle root trouvee, connexion par mot de passe laissee active"
  echo "   Ajoute ta cle publique dans /root/.ssh/authorized_keys puis relance ce script."
fi

cat <<EOF

========================================================================
 Serveur pret. Etape suivante (questions, puis demarrage du CC) :

     sudo bash $DIR/deploy/configure.sh
========================================================================
EOF
