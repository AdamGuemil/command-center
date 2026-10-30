#!/usr/bin/env bash
# Met a jour le Command Center sur le serveur, avec retour arriere automatique.
#   A la main :     sudo -u deploy bash /opt/shroud-cc/deploy/deploy.sh
#   Depuis la CI :  ssh deploy@serveur   (cle limitee a ce script, voir docs/OPERATIONS.md)
#
# Etapes : code a jour (git pull --ff-only), image du dernier commit vert de main tiree de
# ghcr.io (si elle n'est pas accessible : construite sur place a partir du code), conteneur
# relance, puis /healthz attendu 60 s. Si le CC ne repond pas, l'image precedente est remise
# en place et le script echoue (la CI le montre en rouge).
#
# Tout est dans main() : bash lit alors le script en entier avant de l'executer, et le
# « git pull » qui remplace ce fichier pendant qu'il tourne ne peut pas le derouter.
set -euo pipefail

main() {
  local DIR IMAGE previous current
  DIR="$(cd "$(dirname "$0")/.." && pwd)"
  cd "$DIR"
  IMAGE="${CC_IMAGE:-ghcr.io/adamguemil/command-center:latest}"
  export CC_IMAGE="$IMAGE"

  log "Code : git pull"
  git pull --ff-only --quiet

  previous="$(docker image inspect --format '{{.Id}}' "$IMAGE" 2>/dev/null || true)"
  log "Image : $IMAGE"
  if ! docker compose pull --quiet cc 2>/dev/null; then
    log "Image ghcr.io inaccessible (paquet prive ?) : construction sur place, 2 a 5 minutes."
    log "Pour l'eviter : GitHub > Packages > command-center > Package settings > Public."
    docker compose build --pull cc
  fi
  current="$(docker image inspect --format '{{.Id}}' "$IMAGE")"
  if [ "$previous" = "$current" ] && [ -n "$(docker compose ps -q cc)" ]; then
    log "Deja a jour."
    docker compose up -d --remove-orphans >/dev/null       # Caddyfile ou compose modifies
    return 0
  fi

  log "Redemarrage"
  docker compose up -d --remove-orphans
  if healthy; then
    log "OK : le CC repond."
    docker image prune -f >/dev/null
    return 0
  fi

  log "Le CC ne repond pas : retour a l'image precedente"
  docker compose logs --tail 40 cc || true
  if [ -n "$previous" ]; then
    docker tag "$previous" "$IMAGE"
    docker compose up -d --remove-orphans
    if healthy; then log "Image precedente remise en place."; else log "L'image precedente ne repond pas non plus."; fi
  fi
  return 1
}

log() { printf '[deploy %s] %s\n' "$(date +%H:%M:%S)" "$*"; }

healthy() {
  for _ in $(seq 1 30); do
    if docker compose exec -T cc python -c \
      "import urllib.request,sys; sys.exit(0 if b'\"ok\":true' in urllib.request.urlopen('http://127.0.0.1:8787/healthz', timeout=3).read() else 1)" \
      >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  return 1
}

main "$@"
exit $?
