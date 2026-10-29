# Exploitation : installation, clés, panneaux

Guide d'exploitation du Command Center, en français. La présentation générale est dans le
[README](../README.md) ; chaque flux de données (source, transport, destination, rythme,
coût, comportement en panne) est décrit en tableaux dans [PIPELINES.md](PIPELINES.md).

Le CC vise les DataStores de la version de données du jeu (`SharedConfig.DS_VERSION`, par
exemple `SW_DEV_1`). Il la lit dans le dépôt du jeu si `CC_GAME_ROOT` le désigne, sinon dans
`CC_DATASTORE_VERSION`. Le contrat publié par chaque place (`CC_Contract`) signale tout écart
dans Santé et Live.

---

## Démarrage

```powershell
copy .env.example .env      # puis remplis .env
python server.py            # ou double-clic sur start.bat
```

Sans aucune clé : `CC_DEMO=1 python server.py` (ou `docker compose up`) lance le faux univers
de démonstration, avec ses données dans `data/demo/`.

Le dashboard s'ouvre sur <http://127.0.0.1:8787>.

**Aucune dépendance à installer** pour le dashboard : tout passe par la
bibliothèque standard de Python. (`discord.py` n'est utile que pour
`tools/setup_discord.py`, à lancer une seule fois, et à `bot.py`.)

Il ne tourne **que pendant que tu l'utilises** — `Ctrl+C` et plus rien ne
tourne. Pas d'hébergement 24/7.

---

## Ce qu'il y a dedans

| Panneau | À quoi ça sert |
|---|---|
| ✍️ **Composer** | Rédiger une annonce avec aperçu Discord fidèle, variables dynamiques, ping, couleur, image |
| 📚 **Modèles** | Créer/éditer tes propres modèles, partagés avec `announce.py` |
| 🗓️ **Planificateur** | File d'annonces à venir, avec marquage des échéances |
| 🔔 **Notifications** | Notifications Roblox hors du jeu (6 textes : ranked, résultat et fin de saison, événement, mise à jour, retour des inactifs). Asset IDs du Creator Hub, test sur ton compte, aperçu de l'audience, une par joueur et par jour, écran ouvert au Hub ([PIPELINES.md](PIPELINES.md#vers-les-joueurs--notifications-roblox)) |
| 📜 **Journal** | Tout ce que le CC a fait (envois Discord, écritures dans le jeu, cartes traitées), dans `data/cc.db` |
| 🏠 **Accueil** | Page d'ouverture : une carte par chose à faire (saison close, ranked, triche, pièges, avis négatifs, boost fini, OPERATIONS, versions, tâches manuelles), avec aperçu avant toute publication, et le temps restant de la saison |
| 📡 **Live** | Serveurs ouverts (Hubs, matchs), mode, map, phase, joueurs, FPS, version ; rafraîchi toutes les 5 s tant que l'onglet est ouvert |
| 📈 **Tendances** | Mesures de Roblox (Analytics) par place : pic de joueurs, crashs serveur par cause, FPS, mémoire et CPU serveur, crashs client, DataStore, joueurs actifs, revenus. Coût nul pour le jeu |
| 🧑 **Joueurs** | Liste des joueurs connectés au HUB et en match, actualisée toutes les 5 s ; fiche au clic (profil, or, LP, abonnements, ban, inventaire et stash décodés, pièges, sanctions) et actions : message, expulsion, ban, or, retrait d'objet, don, annulation. Une modification n'est jamais écrasée par le serveur du joueur ([PIPELINES.md](PIPELINES.md#2-command-center-vers-le-jeu-écriture)) |
| 🍯 **Sécurité** | Joueurs ayant déclenché un piège anti-triche, avec les arguments envoyés, vagues de bans et liste des bannis (guide des pièges dans le dépôt du jeu, affiché dans l'écran Guide si `CC_GAME_ROOT` est réglé) |
| ⚔️ **Faction War** | Scores live des 2 factions, top contributeurs, publication en 1 clic |
| ⚡ **Boosts** | Équivalent web de `/boost` : XP/or/guerre poussés aux serveurs live |
| 🎮 **Modes** | Disponibilité live des files et fenêtre temporaire de l'événement OPERATIONS |
| 🔫 **Arsenal** | Stats, prix et niveaux locaux, audit de progression et export ShopConfig des armes et des habits (onglet **Habits**) |
| 📖 **Guide** | Une page par écran (ce que fait chaque bouton, ce qui est permanent, ce qui expire), et les documents du dépôt lus en direct : `PIPELINES.md`, guide des pièges, plan, ce README. Recherche (touche `/`), liens directs `#guide/<page>/<ancre>` |
| 🩺 **Santé** | État de chaque connexion, avec le détail exact de ce qui manque |

Dans **Modes**, OPERATIONS est désactivé par défaut. Son activation demande une durée : le
dashboard écrit `up=true` et un `endsAt` Unix futur. Le bouton clignotant OPERATION apparaît
alors sous PLAY jusqu'à l'échéance ; la file est aléatoire. Le reset remet l'événement à
`up=false`, `endsAt=0`. DOMINATION reste une file permanente séparée.

---

## Pourquoi un serveur local plutôt qu'une page statique

Le token du bot et la clé Open Cloud ne doivent **jamais** arriver dans le
navigateur : une page web ne peut pas garder un secret. Ici la page n'envoie
que des intentions (« poste ce message »), et le serveur local détient les
secrets et fait les appels. **Le navigateur ne voit jamais un token.**

---

## Variables dynamiques

Écris `{RUSFOR}` dans un modèle : il devient le vrai score au moment de
l'envoi. C'est ce qui rend les annonces **modulaires** — un seul modèle
« classement » republiable chaque semaine sans jamais le rééditer.

`{GAME_URL}` `{GAME_NAME}` `{DISCORD_INVITE}` `{PLAYING}` `{VISITS}`
`{FAVORITES}` `{WEEK}` `{RUSFOR}` `{RAINOR}` `{LEADER}` `{SPREAD}`
`{REMAINING}` `{DATE}`

Les variables coûteuses (Faction War = 8 lectures DataStore) ne sont résolues
que si le texte les utilise réellement.

---

## Comment le pont avec le jeu fonctionne

`EventService.luau` écoute exactement deux canaux pour les boosts :

1. DataStore `SharedConfig.dsName("FactionWar")`, clé `event_override` — lu au démarrage serveur
2. MessagingService topic `FW_Event` — poussé aux serveurs déjà lancés

Open Cloud expose ces deux canaux en HTTP. Le dashboard écrit dans le premier
puis publie sur le second : **exactement ce que fait `/boost` en jeu**, même
donnée, même effet, sans être connecté. Sans le `publish`, un serveur en cours
mettrait jusqu'à 5 min à voir le boost.

Les scores Faction War sont écrits en 4 shards par faction (pour éviter la
contention entre serveurs) : le panneau additionne les 8 clés, comme
`readShardTotals()` côté Luau.

> La version des DataStores vient de `SharedConfig.luau` dans le dépôt du jeu (`CC_GAME_ROOT`)
> ou de `CC_DATASTORE_VERSION`. Les autres contrats (clé, topic, epoch, nombre de shards)
> restent alignés avec `EventService.luau` et `FactionWarConfig.luau` ; le dépôt du jeu les
> vérifie avec ses propres tests de contrat.

---

## Ligne de commande

```powershell
python announce.py --list                  # modèles + variables
python announce.py launch --dry-run        # prévisualiser sans envoyer
python announce.py launch --ping everyone
python announce.py factionwar              # publie le classement en direct
python announce.py patch --title "v0.4.1" --body "- Fix HUD DUALS"
```

Même moteur que le dashboard, mêmes modèles. Envoi en ~300 ms (REST pur, pas
de connexion gateway).

---

## Comment le CC voit le jeu en direct

Chaque serveur (HUB et MATCH) lance `ServerStorage/Core/CommandCenterBridge` :

- au démarrage, il publie le **contrat** de sa place dans le DataStore non versionné
  `CC_Contract` (clé `place_<PlaceId>`) : version des données, magasins, offres. Le CC
  s'en sert pour lire les bons magasins et signale un HUB et un MATCH qui divergent ;
- toutes les 30 s, et lors des arrivées/départs (au plus une écriture toutes les 2 s), il écrit son état dans la SortedMap MemoryStore `CC_Servers_V1`
  (expiration 300 s, « muet » après 75 s sans battement). L'onglet Live la lit via Open Cloud : pas d'endpoint public, et un
  serveur planté disparaît seul.

Le contrat est retenté après 60 s si sa publication échoue. Live relit les alertes à chaque actualisation ; un contrat absent ou illisible reste en cache 10 s, un contrat présent 5 min. « Relire maintenant » force aussi cette lecture.

La fiche joueur lit les magasins du contrat du HUB, à la demande seulement (cache 60 s).

Le lecteur des accusés accepte les réponses Roblox `queueItems`/`id` et le format documenté `items`/`readId`. Il enregistre les événements avant de les retirer de la file. Une erreur de lecture apparaît dans le suivi de commande ; un accusé absent ne signifie pas que le message n’a pas été affiché en jeu.

**Qui détecte quoi, et qui prévient Discord** (aucune alerte en double) :

| Source | Voit | Prévient Discord |
|---|---|---|
| Veilleur élu dans le jeu (`CommandCenterBridge`, un seul serveur de l'univers, bail MemoryStore) | un serveur précis devenu muet, avec ses joueurs | oui, et marque l'entrée `crashReportedAt` ; marche CC éteint |
| Analytics Roblox (`core/analytics.py`, lu toutes les 5 min) | les crashs serveur par place et par **cause** | non : journal du CC et écran Tendances |
| Alertes de performance Roblox (Creator Hub, Configure → Alerts) | tendances globales : FPS, mémoire, crash client, chute de joueurs | oui, par le webhook « Custom alerts » ; marche CC éteint ; environ 100 joueurs actifs par jour requis |
| Veilleur du CC (`core/watch.py`) | tout ce qui précède, dans Live | seulement en dernier recours, 150 s sans veilleur du jeu |

Coût côté jeu : par serveur, une écriture MemoryStore et une tentative de bail toutes les
30 s, avec une écriture supplémentaire lors des arrivées/départs, groupée et limitée à une toutes les 2 s ; pour le seul élu, une lecture du registre toutes les 30 s. `DiscordFeed` limite les
messages **par joueur et par type** (un tricheur en rafale ne vide que son propre quota),
avec un plafond large de 60 par minute et par salon et une pause sur refus 429 de Discord :
HttpService (500 requêtes par minute et par serveur) n'est jamais saturé. Détail dans
[PIPELINES.md](PIPELINES.md#5-limiteur-des-messages-discord-du-jeu).

**Veilleur live** (`core/watch.py`) : tant que le CC tourne, il relit le registre toutes
les 20 s et en déduit des événements : serveur démarré, fermé proprement (son entrée est
retirée à la fermeture), **crash ou gel** (entrée toujours là mais plus de battement depuis
75 s), lag (FPS serveur sous 30), versions de place mélangées, Hub sans pont (listé par
Roblox mais absent du registre). Les crashs partent aussi dans `#ops-log`, et en
notification navigateur si tu l'as activée dans Live. Journal et courbe des joueurs sur
24 h : `data/live_events.json`, `data/live_timeline.json`.

**Bus d'événements** (`ServerStorage/Core/CCEvents` côté jeu, `core/events.py` côté CC) :
fin de saison, versement ranked, sanctions, anticheat, pièges et avis négatifs sont déposés
par le jeu dans la file MemoryStore `CC_Events_V1` et attendent jusqu'à 2 jours que le CC
les lise. Le CC les relit à chaque passage du veilleur et en fait des cartes sur l'Accueil.
Le jeu cesse de déposer au-delà de 40 événements non lus : la mémoire MemoryStore, partagée
avec le matchmaking, ne peut pas déborder. Les crashs survenus CC éteint restent signalés
par le veilleur élu du jeu dans `#ops-log`.

## Clés à créer

**Discord** — Developer Portal > ton application > Bot > *Reset Token*.
Permissions sur le salon visé : Voir le salon, Envoyer des messages, Intégrer
des liens, et Mentionner @everyone si tu pings.

**Roblox Open Cloud** — Creator Hub, **profil du groupe** propriétaire de Shroud War
sélectionné en haut à gauche > Open Cloud > API Keys > *Create API Key*. Pour chaque
système, choisir ton expérience (son univers) :

| Système | Opérations | Sert à |
|---|---|---|
| Data Stores | Read Entry, Create Entry, Update Entry, Delete Entry, List Entry Keys | boosts, modes, give, barèmes, maintenance, modifications de joueur hors ligne |
| Ordered Data Stores | Read | classements Faction War et ranked, index d'activité des notifications |
| Messaging Service | Publish | pousser aux serveurs ouverts |
| Memory Store | Sorted Map Read, Write ; Queue Read, Discard | serveurs live, événements, verrous d'édition (lots 1-3) |
| Subscriptions | Read | abonnement d'un joueur dans sa fiche (lot 1) |
| Analytics | Read | écran Tendances et crashs serveur avec leur cause |
| User Restrictions | Read, Write | fiche (ban), bans et vagues de bans |
| Universes | Write | bouton Redémarrer de Live |
| User Notifications | Write | notifications joueurs (droit utilisateur, dans une section séparée de la page) |

*Accepted IP Addresses* : `0.0.0.0/0` tant que le CC tourne sur ce PC (IP domestique
variable) ; à restreindre à l'IP du serveur une fois hébergé. Coller la clé dans `.env`
(`ROBLOX_OPENCLOUD_KEY=`), relancer le CC, puis **Santé > Tester les permissions** :
chaque droit manquant y est nommé. Notifications et redémarrage ne sont pas sondés
(leur seul test serait l'action elle-même) : pour les notifications, utilise
**Notifications > Tester sur mon compte**.

> `UNIVERSE_ID` n'est pas le `PLACE_ID`. Creator Hub > ton experience > `...` >
> *Copy Universe ID*.

**Webhooks Discord du jeu** — les `<id>/<token>` vivent dans le Secrets Store de
l'expérience (`discord_match_results`, `discord_live_leaderboard`, `discord_level_ups`,
`discord_ops_log`, restreints au domaine du Worker Cloudflare), jamais dans le
code. Le Worker [`tools/cloudflare/webhook-proxy.js`](../tools/cloudflare/webhook-proxy.js) ne relaie
que les ids listés dans sa variable `ALLOWED_WEBHOOK_IDS`.

---

## Sécurité

- `.env` est dans `.gitignore` — les secrets ne quittent pas ta machine.
- Le serveur n'écoute que sur `127.0.0.1` : rien n'est exposé au réseau.
- Ne partage jamais ce dossier avec un `.env` dedans.
- Si un token fuite : Reset Token (Discord) / supprime la clé (Creator Hub).
- Un webhook Discord ne se régénère pas : en créer un nouveau, mettre à jour le secret
  Roblox et `ALLOWED_WEBHOOK_IDS`, puis supprimer l'ancien.

---

## Fichiers

La carte du dépôt est dans le [README](../README.md#repository-layout).

---

## 🔫 Arsenal

Les armes, leurs stats, leur score, leur prix et leur niveau — dans l'onglet
**Arsenal**. Ces données vivaient dans une seconde application (`game-level/`) :
deux outils pour un seul jeu, c'était deux endroits où chercher et deux occasions
de diverger.

Le **niveau reste manuel**. Le prix peut être écrit à la main ou recalculé depuis
l'onglet **Économie** avec le modèle permanent : base quadratique du niveau,
coefficient de catégorie, percentile de stats dans la catégorie, facteur
d'utilité par arme, puis multiplicateur global. La rareté et la faction ne
modifient jamais le prix. Les colonnes éditables sont en **or**.

La timeline affiche tous les niveaux sur une seule longueur. Une arme se déplace
par glisser-déposer vers n'importe quel niveau **et n'importe quelle catégorie** ;
les deux valeurs sont immédiatement écrites dans `data/arsenal.json`. Un survol
affiche sa fiche (score, rang et stats). Le plafond visuel commence à 30 et peut
être prolongé par pas de 5, par exemple jusqu'à 35 pour une future arme.

**Le score reste calculé** depuis les stats, avec le même modèle linéaire
(éditable en bas de page). Il situe une arme dans sa classe et devient un facteur
de percentile compris entre les bornes du panneau Économie uniquement quand un
recalcul est demandé. Les colonnes calculées sont en **bleu**.

Le panneau **Cohérence** liste les avertissements : arme sans prix ou sans
niveau, deux armes d'une même classe au même niveau pour un camp, et les
**inversions** (une arme au score plus bas débloquée avant une plus forte). Ce
sont des avertissements, jamais des corrections — une arme volontairement chère
et faible est un choix légitime. C'est le même esprit que `/shopaudit` en jeu.

Les classes sont celles du jeu (`ShopConfig.WEAPON_CLASSES` : `ar`, `br`,
`carbine`, `smg`, `lmg`, `dmr`, `sniper`, `shotgun`, `pistol`,
`mpistol`…), pas des libellés propres à l'outil : un seul vocabulaire.

`ShopConfig` est la source de vérité publiée. La commande Studio
`tools/studio/sync_arsenal_from_command_center.luau` relit l'API locale et applique
les stats, classes et factions aux Tools. Le bouton **Générer ShopConfig** produit
un bloc Luau contenant les prix, les niveaux requis et `AUTO_LEVEL_MAX`. Ce bloc
se copie-colle après la table `ShopConfig.LEVEL_REQ`, sans supprimer les prix des
chargeurs, équipements ou cosmétiques déjà présents.

### 👕 Habits

L'onglet **Habits** de l'Arsenal gère les 33 tenues (haut + bas) comme les armes : une timeline
par camp (glisser une tenue vendue vers un niveau de 1 à 40, enregistré aussitôt), un tableau
(prix, **source**, rareté, gabarits Studio et `_ItemName`), un panneau de cohérence et un
générateur ShopConfig. Seule la source `shop` s'achète ; starters, kits d'abonnement et Mercenary
partent dans `ShopConfig.NO_BUY`.

Report dans le jeu (dépôt du jeu) : `python claude_works/tools/outfit_shop.py --apply` (ou **Copier le bloc**
entre les balises `COMMAND_CENTER_OUTFIT_SHOP`), puis `sync.py` pour GAME. Les attributs des
items (`_ItemName`, `Faction`, `Rarity`) s'appliquent avec
`tools/studio/sync_outfits_from_command_center.command.luau`.

## 💰 Économie publiée

Les gains par mode, la quête quotidienne et les prix du Shop vivent en dur dans
`ReplicatedStorage/Systems/Economy/ShopConfig.luau`. Le Command Center ne possède plus d'onglet,
de route API ni de publication live pour l'économie. Une modification demande de
synchroniser HUB/GAME puis de publier les places ; les serveurs déjà ouverts
gardent les valeurs chargées au démarrage.

Le contrat complet, les valeurs livrées, la procédure Studio et les tests sont documentés dans
`guides/GUIDE_ECONOMIE_ARSENAL.md`, dans le dépôt du jeu.


## Vérifications

`pytest` lance les tests Python (cartes, ordonnanceur de notifications, commandes,
modifications hors ligne, mode démo...), `ruff check .` et `mypy` le style et les types.
Le test navigateur `node tests/e2e/browser_live.cjs` utilise Playwright (`NODE_PATH` si
nécessaire ; sur Windows avec Edge, `PLAYWRIGHT_CHANNEL=msedge`). Il simule les API : aucun
message ni changement de données n'est envoyé au jeu. La CI GitHub lance le tout, plus un
démarrage du conteneur en mode démo.
