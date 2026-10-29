//  guide_content.js — sections du Guide ecrites a la main.
//  Une section par ecran ou par sujet. Regle : dire ce que fait chaque action, ce qui est
//  permanent, ce qui expire, et ou passe la donnee (detail technique : document Pipelines).
//  Les liens « #guide/<id>/<ancre> » ouvrent une section ou un document du Guide.

export const GROUPS = ["Prise en main", "Live", "Joueurs", "Saison", "Diffusion", "Réglages jeu", "Système", "Aide"];

export const SECTIONS = [
  {
    id: "demarrer", group: "Prise en main", title: "Démarrer et principes",
    summary: "Ce que fait le Command Center, ce qui est permanent, ce qui expire.",
    html: `
<p>Le Command Center est un serveur : sur ton PC, <code>python server.py</code> (ou <code>start.bat</code>), puis <code>http://127.0.0.1:8787</code> ; en ligne, l'adresse du serveur avec une connexion Discord (voir <a href="#guide/acces">Accès</a>). Il détient les secrets (clé Open Cloud, token du bot) ; la page web ne voit jamais un token et n'envoie que des intentions.</p>
<p>Trois règles expliquent tout le reste :</p>
<ul>
  <li><b>Ce que tu appliques vit dans le jeu.</b> Boosts, modes, récompenses et dons sont écrits dans les DataStores Roblox et y restent PC éteint. Les serveurs déjà ouverts sont prévenus par un message (<code>FW_Event</code>) et appliquent en moins d'une seconde.</li>
  <li><b>Le fichier du jeu est le filet de sécurité.</b> Les valeurs du code sont les valeurs par défaut ; le Command Center écrit des <i>surcharges</i>. Supprimer une surcharge revient aux valeurs d'origine : aucun état « cassé » n'est possible.</li>
  <li><b>La surveillance tient sans toi.</b> Un serveur du jeu, élu, signale dans <code>#ops-log</code> les serveurs qui plantent, même Command Center éteint. Le Command Center ajoute le détail (Live, journal, Tendances) tant qu'il tourne.</li>
</ul>
<table>
  <thead><tr><th>Action</th><th>Durée</th><th>Serveurs déjà lancés</th></tr></thead>
  <tbody>
    <tr><td>Boost</td><td><b>Expire</b> à la durée choisie</td><td>Immédiat</td></tr>
    <tr><td>Modes, récompenses, barème ranked</td><td><b>Permanent</b> jusqu'au prochain changement</td><td>Immédiat</td></tr>
    <tr><td>Don, wipe</td><td>Livré une fois (identifiant unique)</td><td>Immédiat ; un joueur absent le reçoit à son retour</td></tr>
    <tr><td>Configs live Roblox</td><td>Permanent, versionné par Roblox</td><td>5 à 15 min</td></tr>
    <tr><td>Économie ShopConfig</td><td>Versionnée avec les places</td><td>Au prochain serveur publié</td></tr>
    <tr><td>Live, Joueurs, Tendances, Sécurité</td><td>Lecture seule</td><td>Aucun effet</td></tr>
    <tr><td>Annonce Discord</td><td>Message posté, définitif</td><td>Aucun effet</td></tr>
    <tr><td>Modèles, planning, arsenal, tâches cochées</td><td>Local à ce PC (<code>data/</code>)</td><td>Aucun effet</td></tr>
  </tbody>
</table>
<p><b>Palette</b> : <kbd>Ctrl K</kbd> (ou Rechercher, en haut) pour aller à un écran, ouvrir un joueur (« fiche Pseudo ») ou lancer une action (« ban Pseudo », « kick Pseudo », message à tous, redémarrage).</p>
<p>Installation, clés et droits : <a href="#guide/readme">Installation et clés</a>. Chaque flux en détail : <a href="#guide/pipelines">Pipelines</a>.</p>`,
  },
  {
    id: "accueil", group: "Prise en main", title: "Accueil : ce qu'il faut faire maintenant",
    summary: "Les cartes à traiter, l'état du jeu et la fin de saison en un coup d'œil.",
    html: `
<p>L'Accueil est la page d'ouverture du Command Center. En haut : le temps restant avant la fin de la saison (heure de Paris), les joueurs en jeu et le nombre de cartes. En dessous : une <b>carte par chose qui demande ton attention</b>, la plus urgente en premier.</p>
<h4>Anatomie d'une carte</h4>
<ul>
  <li><b>Priorité</b> : Bloquant (rouge), Important (orange), À faire, Pour info.</li>
  <li><b>Titre</b> avec les vrais chiffres, et une ligne de contexte.</li>
  <li><b>Actions</b> : un bouton doré publie quelque chose. Il ouvre toujours un <b>aperçu</b> du message exact (salon, ping, texte avec les variables remplies) ; rien ne part avant « Publier ». Les autres boutons ouvrent le bon écran.</li>
  <li><b>Plus tard</b> (1 h, 4 h, demain 9 h), <b>Fait</b> (c'est réglé), <b>Ignorer</b> (ne plus afficher cette carte).</li>
</ul>
<p>Les boutons « Notifier… » n'apparaissent qu'une fois le texte correspondant créé dans le Creator Hub (voir <a href="#guide/notifications">Notifications joueurs</a>). Ils ouvrent l'aperçu de l'audience avant tout envoi.</p>
<p>Une carte se ferme seule quand toutes ses publications et notifications sont faites, ou quand sa situation disparaît (boost réannoncé, OPERATIONS refermé...). Chaque carte a une clé stable (par exemple <code>fw_result:w7</code>) : une fois traitée, elle ne revient pas.</p>
<h4>Les cartes</h4>
<table>
  <thead><tr><th>Quand</th><th>Carte</th><th>Action</th></tr></thead>
  <tbody>
    <tr><td>Clé Open Cloud refusée, Discord injoignable, contrat incohérent</td><td>Bloquant</td><td>Ouvrir Santé ou Live</td></tr>
    <tr><td>Dernières 24 h de la saison</td><td>Dernière ligne droite</td><td>Annoncer le versement ranked (préavis), notifier les absents</td></tr>
    <tr><td>Saison close</td><td>Saison N close : vainqueur et scores</td><td>Annoncer aux 2 factions, publier le résultat global, notifier les joueurs</td></tr>
    <tr><td>Saison échue mais pas encore close</td><td>Clôture en attente d'un serveur</td><td>Information</td></tr>
    <tr><td>Versement ranked créé</td><td>Ranked versé à N joueurs</td><td>Publier le Top 10, notifier le top ranked</td></tr>
    <tr><td>Pas de versement 30 min après la clôture</td><td>Versement ranked absent</td><td>Ouvrir Ranked</td></tr>
    <tr><td>Boost terminé</td><td>Boost X terminé</td><td>Annoncer la fin</td></tr>
    <tr><td>Boost ou OPERATIONS en cours</td><td>Prévenir les absents (Pour info)</td><td>Notification EVENT_LIVE</td></tr>
    <tr><td>Aucune relance depuis 7 jours</td><td>Relance hebdomadaire des inactifs (Pour info)</td><td>Notification COMEBACK</td></tr>
    <tr><td>OPERATIONS échu ou dans sa dernière heure</td><td>À refermer, ou dernière heure</td><td>Ouvrir Modes</td></tr>
    <tr><td>Plusieurs versions de place en ligne</td><td>Serveurs sur N versions</td><td>Voir les serveurs, annoncer une maintenance</td></tr>
    <tr><td>Piège anti-triche déclenché</td><td>Important</td><td>Ouvrir la fiche, voir Sécurité</td></tr>
    <tr><td>Anticheat ou sanction</td><td>Une carte par joueur et par jour</td><td>Ouvrir la fiche</td></tr>
    <tr><td>Avis d'1 ou 2 étoiles</td><td>Pour info</td><td>Ouvrir la fiche</td></tr>
    <tr><td>Rafale d'erreurs de script sur un serveur</td><td>N erreurs en 1 min dans un script</td><td>Voir les serveurs</td></tr>
    <tr><td>Annonce du planificateur échue</td><td>Annonce prévue</td><td>Ouvrir le planificateur</td></tr>
    <tr><td>Tâche manuelle (Creator Hub, Cloudflare...)</td><td>À faire, ou « En attente » si pas encore possible</td><td>Marquer comme fait</td></tr>
  </tbody>
</table>
<h4>D'où viennent les cartes</h4>
<p>Une partie est déduite de l'état du jeu, relu toutes les 30 s quand l'Accueil est ouvert : elle apparaît même si le jeu n'a rien signalé (par exemple une saison close pendant que le CC était éteint). L'autre partie vient des <b>événements du jeu</b> : les serveurs les déposent dans la file <code>CC_Events_V1</code> et le CC la relit toutes les 20 s. Un événement attend jusqu'à 2 jours que le CC le lise. Détail : <a href="#guide/pipelines/1-jeu-vers-command-center-lecture">Pipelines</a>.</p>
<p>La pastille de l'onglet Accueil compte les cartes ; elle est rouge s'il y en a d'importantes. Une nouvelle carte importante déclenche une notice et, si tu l'as autorisée, une notification système.</p>
<p><b>Automatique plus tard.</b> Pour l'instant, chaque carte attend ton clic. Le réglage « automatique » par règle viendra avec l'hébergement 24/7 (lot 6) ; wipe, ban et redémarrage ne seront jamais automatiques.</p>`,
  },
  {
    id: "reste", group: "Prise en main", title: "Tâches manuelles",
    summary: "Les réglages à faire hors du CC, et quand ils deviennent possibles.",
    html: `
<p>Les actions à faire hors du Command Center (Creator Hub, Cloudflare...) apparaissent comme des cartes de l'<a href="#guide/accueil">Accueil</a>, catégorie Configuration. Chaque tâche dit <b>où</b> agir et <b>à quoi ça sert</b>. Une tâche qui n'est pas encore possible est rangée dans « En attente », en bas de l'Accueil.</p>
<table>
  <thead><tr><th>État</th><th>Signification</th></tr></thead>
  <tbody>
    <tr><td>Important (« C'est le moment »)</td><td>La condition vient d'être remplie : notice et notification système une fois.</td></tr>
    <tr><td>À faire</td><td>Rien ne bloque.</td></tr>
    <tr><td>En attente</td><td>Pas encore possible ; le détail dit pourquoi et ce qui débloquera.</td></tr>
    <tr><td>Disparue</td><td>Cochée « Marquer comme fait », ou constatée automatiquement.</td></tr>
  </tbody>
</table>
<p>Les vérifications sont refaites toutes les 30 min (une requête Analytics). La liste complète, avec les tâches faites, reste lisible à l'adresse <a href="#todo">#todo</a>. Les coches sont gardées sur ce PC (<code>data/todo_state.json</code>).</p>
<p>Exemple : les alertes de performance Roblox sont refusées sous environ 100 joueurs actifs par jour. La tâche reste « En attente » avec le maximum des 7 derniers jours, et devient importante dès que le seuil est atteint.</p>`,
  },
  {
    id: "semaine", group: "Prise en main", title: "Semaine type : quoi faire et quand",
    summary: "Routine hebdomadaire, avant un lancement, erreurs à éviter.",
    html: `
<p>Tout est ancré sur une seule échéance : <b>la semaine de guerre bascule chaque samedi à 18h00</b> (heure française), depuis le samedi 05/09/2026.</p>
<p><i>Le calcul suit Europe/Paris : 18h00 reste 18h00 après les changements d'heure. Dans le jeu, l'échéance est formatée sur le client et chaque joueur voit donc l'heure correspondante dans son propre fuseau.</i></p>
<p>Le <b>Faction War et le Ranked se versent tous les deux automatiquement</b> à la bascule. Le LP ranked se conserve entre les saisons ; un wipe de version le remet à zéro.</p>

<h4>Avant un lancement ou une grosse mise à jour</h4>
<ol>
  <li><b>Santé</b> : les quatre lignes en vert, puis <b>Tester les permissions</b>. C'est le moment de corriger, pas le jour J.</li>
  <li><b>Reste à faire</b> : rien en « À faire » ni en « C'est le moment ».</li>
  <li><b>Composer</b>, modèle « Compte à rebours », vers <code>#announcements</code> avec <code>@everyone</code>. Épingle le message.</li>
  <li>Le jour J : modèle « Lancement », puis <b>Boosts</b> avec « Annoncer sur Discord » coché (par exemple XP ×2, Or ×1.5, 7 jours).</li>
  <li>Garde <b>Live</b> ouvert avec les notifications du navigateur activées : un crash pendant le pic de joueurs se voit dans la minute.</li>
</ol>

<h4>Cycle hebdomadaire — à répéter chaque semaine</h4>
<table>
  <thead><tr><th>Quand</th><th>Action dans le Command Center</th></tr></thead>
  <tbody>
    <tr><td><b>Vendredi</b></td><td>Ranked → <b>Annoncer le versement (24h)</b>. Indispensable : sans ce préavis, les joueurs inactifs ratent la fenêtre. La carte « Dernière ligne droite » propose aussi de <b>notifier les absents</b> (SEASON_ENDING).</td></tr>
    <tr><td><b>Samedi (après 18h00)</b></td><td>La guerre s'est clôturée seule. Composer → modèle <b>« Faction War — résultat de saison »</b> → annonce le vainqueur et les scores FINAUX.</td></tr>
    <tr><td><b>Samedi</b></td><td>Ranked → vérifie que le snapshot automatique apparaît, puis <b>publie le top 10</b>. Les cartes « Saison close » et « Ranked versé » proposent chacune leur notification joueurs.</td></tr>
    <tr><td><b>Samedi</b></td><td>Boosts → relance un boost de week-end si tu veux relancer l'activité.</td></tr>
    <tr><td><b>Chaque jour</b></td><td>Ouvrir l'<b>Accueil</b> : les cartes disent ce qui demande ton attention (crashs, triche, avis négatifs, tâches). Le reste est facultatif : Journal pour vérifier ce qui est parti, Tendances pour la santé du jeu sur la semaine.</td></tr>
  </tbody>
</table>
<p><b>Deux modèles Faction War, à ne pas confondre :</b></p>
<ul>
  <li><b>« Faction War — en cours »</b> (<code>{RUSFOR}</code>, <code>{RAINOR}</code>) lit la semaine <b>courante</b>. À publier <i>pendant</i> la semaine, pour entretenir la rivalité.</li>
  <li><b>« Faction War — résultat de saison »</b> (<code>{LAST_WINNER}</code>, <code>{LAST_RUSFOR}</code>…) lit l'<b>archive de la semaine close</b>. C'est celui-là qu'il faut après la bascule.</li>
</ul>
<p>Publier le modèle « en cours » après 18h00 annoncerait <b>0-0</b> : la nouvelle saison vient de démarrer, ses compteurs sont vides. Les scores de la semaine écoulée ne vivent plus que dans l'archive.</p>
<p>Le reste de l'ordre est <b>éditorial, pas technique</b> : les deux systèmes sont indépendants, publier une annonce ne change rien au versement ranked. On commence par la guerre (le récit collectif) avant les performances individuelles, simplement parce que ça se lit mieux.</p>
<p>Le ladder ranked <b>se conserve entre les saisons</b>, sauf wipe de version. Le snapshot de clôture enregistre simplement son top à cet instant pour les récompenses et le bilan ; la saison suivante continue avec les mêmes LP.</p>

<h4>Ponctuel, quand le besoin se présente</h4>
<ul>
  <li><b>Patch</b> — modèle <i>Patch notes</i> → <code>#patch-notes</code>, puis Diffusion, Notifications, <b>UPDATE</b> pour prévenir les joueurs des 30 derniers jours. Un patch rapide après le lancement est le meilleur signal de rétention.</li>
  <li><b>Maintenance</b> — modèle <i>Maintenance</i> avant une mise à jour serveur.</li>
  <li><b>Playtest</b> — quand tu veux du monde en file pour tester le matchmaking.</li>
  <li><b>Récompenses</b> — n'y touche qu'entre deux semaines, jamais en plein milieu (voir ci-dessous).</li>
</ul>

<h4>Ce qu'il ne faut pas faire</h4>
<ul>
  <li><b>Ne modifie pas les récompenses juste avant la bascule.</b> Le calcul se fait à la clôture : un changement à 17:55 s'appliquerait à une semaine déjà jouée sous d'autres règles.</li>
  <li><b>Ne verse pas le ranked deux fois de suite sans préavis.</b> Les joueurs non connectés entre les deux ne toucheront rien au second — c'est la règle anti-AFK.</li>
  <li><b>Ne retouche jamais l'époque</b> (<code>FactionWarConfig</code>) après le lancement : toutes les clés de stockage changeraient.</li>
  <li><b>N'oublie pas le préavis du vendredi.</b> C'est le seul garde-fou entre « récompense méritée » et « joueur frustré ».</li>
</ul>`,
  },
  {
    id: "live", group: "Live", title: "Live et alertes",
    summary: "Serveurs ouverts, joueurs, crashs, journal et notifications.",
    html: `
<p>Live montre chaque serveur ouvert, Hub et matchs, avec ses joueurs. Chaque serveur du jeu écrit son état toutes les 30 s, et lors des arrivées/départs (groupés, au plus une écriture toutes les 2 s), dans le registre <code>CC_Servers_V1</code> (MemoryStore) ; l'écran le relit toutes les 5 s tant qu'il est affiché (<b>Auto</b>), ou à la demande (<b>Pause</b>, <b>Relire maintenant</b>).</p>
<h4>Lire l'écran</h4>
<ul>
  <li><b>Bandeau du haut</b> : joueurs au Hub, en match par mode, et la courbe des 24 dernières heures (un point par minute, gardé par le Command Center).</li>
  <li><b>Liste</b> : filtres Tous, Hubs, Matchs, Alertes ; la recherche trouve un joueur, une map ou un identifiant. Les cases à cocher permettent de copier plusieurs identifiants. « Message » et « Vider » arrivent au lot 3.</li>
  <li><b>Détail d'un serveur</b> : FPS, mémoire, temps de frame, réseau, ping moyen, version, compteurs Discord, et ses joueurs (ping en orange au-dessus de 250 ms). Un clic sur un joueur ouvre sa fiche. « Rejoindre ce Hub » t'y envoie ; les serveurs de match sont privés.</li>
</ul>
<h4>Agir sur les serveurs</h4>
<ul>
  <li><b>Message</b> (détail d'un serveur, sélection, ou <b>Message à tous</b>) : bandeau STAFF chez les joueurs. La fenêtre affiche la réponse de chaque serveur.</li>
  <li><b>Vider</b> : bandeau avec compte à rebours, puis tous les joueurs du serveur sont renvoyés. Sur un match en cours, la partie est perdue.</li>
  <li><b>Redémarrer…</b> : redémarrage Roblox des serveurs, seulement ceux d'une ancienne version ou tous, tout de suite ou après un délai pendant lequel ils ne reçoivent plus de joueurs. Option : annonce de maintenance sur Discord et bandeau en jeu. Confirmation en recopiant REDEMARRER.</li>
</ul>
<h4>États d'un serveur</h4>
<table>
  <thead><tr><th>État</th><th>Signification</th></tr></thead>
  <tbody>
    <tr><td>En ligne</td><td>Signal reçu il y a moins de 75 s.</td></tr>
    <tr><td>Lent</td><td>FPS serveur sous 30 sur deux lectures de suite.</td></tr>
    <tr><td>Ne répond plus</td><td>Plus de signal depuis 75 s alors que le serveur n'a pas fermé proprement : crash ou gel. « Signalé par le jeu » indique que le veilleur du jeu a déjà prévenu <code>#ops-log</code>.</td></tr>
  </tbody>
</table>
<p>Une fermeture propre retire le serveur de la liste ; seul un crash ou un gel le laisse « muet ». Il disparaît seul après 5 min.</p>
<h4>Journal et notifications</h4>
<p>Le journal liste démarrages, fermetures, crashs, serveurs lents, versions de place mélangées, Hubs d'une version sans pont, crashs comptés par Roblox avec leur cause, et messages Discord perdus. La pastille rouge de Live compte les alertes non vues.</p>
<p><b>Activer les notifications</b> (bouton du journal) : un crash déclenche une notification système même si l'onglet est en arrière-plan.</p>
<h4>Qui prévient Discord</h4>
<p>Le veilleur élu du jeu signale un serveur muet dans <code>#ops-log</code>, CC éteint ou non. Le Command Center ne poste qu'en dernier recours, après 150 s sans signalement du jeu (cas du seul serveur ouvert qui tombe). Les tendances globales arrivent par les alertes Roblox dans <code>#roblox-alerts</code>. Un crash n'est jamais signalé deux fois. Tableau complet : <a href="#guide/pipelines/4-surveillance-et-alertes">Pipelines, surveillance et alertes</a>.</p>
<p><b>Compteur Discord</b> d'un serveur : messages envoyés, abandonnés par le limiteur (rafale d'un joueur ou d'un type de message) et refusés par Discord. Quotas : <a href="#guide/pipelines/5-limiteur-des-messages-discord-du-jeu">Pipelines, limiteur</a>.</p>`,
  },
  {
    id: "tendances", group: "Live", title: "Tendances",
    summary: "Ce que Roblox mesure : joueurs, crashs, FPS, mémoire, revenus.",
    html: `
<p>Les mesures de Roblox sur toute l'expérience, par place (Hub, Matchs) : pic de joueurs, crashs serveur par cause, FPS serveur, mémoire et CPU serveur, taux de crash client, requêtes DataStore, joueurs actifs par jour, revenus. Périodes : 24 h, 7 jours, 28 jours.</p>
<ul>
  <li><b>Coût nul pour le jeu</b> : Roblox les mesure lui-même. Le Command Center les lit à l'ouverture de l'écran, avec un cache de 5 min (<b>Relire</b> pour forcer).</li>
  <li><b>Live et Tendances se complètent</b> : Live dit quel serveur et quels joueurs ; Tendances dit combien et pourquoi (la cause d'un crash, par exemple <code>OutOfMemory</code>).</li>
  <li><b>Panneau en erreur « Analytics → Read »</b> : ajouter ce droit à la clé Open Cloud.</li>
  <li><b>Panneau vide ou « non éligible »</b> : Roblox ne publie les mesures de performance qu'à partir d'environ 100 joueurs actifs par jour.</li>
</ul>`,
  },
  {
    id: "joueurs", group: "Joueurs", title: "Joueurs : la fiche",
    summary: "Profil, abonnements, inventaire, stash, sanctions, pièges.",
    html: `
<p><b>Fiches</b> liste les joueurs connectés au HUB et dans les matchs, avec leur lieu, faction et niveau. La liste se rafraîchit toutes les 5 s ; les serveurs muets sont exclus et un joueur en téléport n’apparaît qu’une fois. Clique son nom pour ouvrir sa fiche, ou recherche un pseudo/userId, même hors ligne. Les données détaillées coûtent une douzaine de lectures à l’ouverture, avec un cache de 60 s.</p>
<ul>
  <li><b>Résumé</b> : où il joue en ce moment, faction, or, LP, niveau, abonnements, ban, sanctions, dette, extraction en attente, pièges déclenchés.</li>
  <li><b>Inventaire</b> et <b>Stash</b> : lus seulement au clic sur leur onglet, items décodés (accessoires, contenu des sacs).</li>
  <li><b>Sécurité</b> : le détail des pièges déclenchés par ce joueur.</li>
</ul>
<p>Chaque section échoue seule : un droit manquant affiche son erreur sans cacher le reste.</p>
<h4>Actions</h4>
<p>Chaque action ouvre une fenêtre qui dit ce qui va se passer ; rien ne part sans confirmation.</p>
<table>
  <thead><tr><th>Action</th><th>Ce qui se passe</th></tr></thead>
  <tbody>
    <tr><td>Message</td><td>Bandeau STAFF chez le joueur, s'il est en ligne.</td></tr>
    <tr><td>Expulser</td><td>Son serveur l'expulse avec le motif donné. Il peut revenir.</td></tr>
    <tr><td>Bannir, Lever le ban</td><td>Ban d'univers Roblox (HUB et matchs) : durée, motif affiché au joueur, motif privé, comptes alternatifs inclus ou non. Confirmation en recopiant BAN. Un joueur en ligne est expulsé aussitôt.</td></tr>
    <tr><td>Modifier l'or</td><td>Nouveau solde (valeur absolue), aperçu avant/après.</td></tr>
    <tr><td>Retirer (onglets Inventaire et Stash)</td><td>Retire un objet, avec le contenu de son sac s'il en a un. Aperçu avant/après.</td></tr>
    <tr><td>Don</td><td>Ouvre Dons avec ce joueur déjà en destinataire (or, XP, kits, objets, badges, titre, ou wipe).</td></tr>
    <tr><td>Modifications</td><td>Les modifications hors ligne faites depuis le CC, chacune annulable.</td></tr>
  </tbody>
</table>
<h4>Pourquoi une modification n'est jamais écrasée</h4>
<p>Le serveur où joue un joueur garde ses données en mémoire et les réécrit à sa prochaine sauvegarde : une écriture directe serait effacée. Donc :</p>
<ul>
  <li><b>Joueur en ligne</b> : la modification part en commande vers son serveur, qui l'applique et sauvegarde, puis répond « fait » ou « refusé » dans la fenêtre. Un objet porté ne peut pas être retiré en ligne : le jeu refuse, le message l'explique.</li>
  <li><b>Joueur hors ligne</b> : le CC pose un verrou de 60 s, vérifie deux fois qu'il est toujours absent, relit la donnée et vérifie que le jeu ne l'a pas changée depuis l'aperçu, puis écrit. S'il se connecte pendant ce temps, son serveur attend la fin du verrou avant de charger ses données. L'original est gardé dans <code>data/cc.db</code> pour l'annulation.</li>
  <li><b>Annuler</b> n'est possible que si le joueur n'a pas joué depuis : sinon l'annulation écraserait sa progression, le CC refuse.</li>
</ul>`,
  },
  {
    id: "securite", group: "Joueurs", title: "Sécurité : pièges anti-triche",
    summary: "Qui a appelé un remote leurre, et ce qu'il a envoyé.",
    html: `
<p>Le jeu contient des remotes leurres, crédibles, qu'aucun script légitime n'appelle. Un joueur qui en déclenche un passe forcément par un exécuteur : <b>pas de faux positif</b>. Le serveur ne fait rien de visible (pas de kick, pas d'effet) et répond un faux succès : le tricheur ne sait pas qu'il est repéré.</p>
<p>L'écran liste les joueurs pris, du plus récent au plus ancien, avec les pièges touchés, le nombre d'appels et les arguments envoyés. Un admin qui teste un piège est marqué comme tel. Le premier déclenchement d'une session part aussi dans <code>#ops-log</code>.</p>
<p><b>La sanction reste ta décision</b>. Rien n'est automatique : coche des joueurs puis <b>Bannir la sélection</b> pour une vague de bans (même motif, même durée, un résultat par joueur), ou ouvre le détail d'un joueur puis <b>Bannir</b> ou <b>Ouvrir la fiche</b>. En bas de l'écran : les joueurs actuellement bannis de l'univers, avec <b>Lever</b>.</p>
<p>Pourquoi bannir par vague plutôt qu'à chaque détection : un tricheur banni tout de suite sait quel outil l'a trahi. Une vague quelques jours plus tard ne dit rien de ce qui l'a fait repérer.</p>
<p><b>Ne jamais</b> appeler, réutiliser, renommer ou supprimer un piège : voir <a href="#guide/pieges">Pièges anti-triche</a>.</p>`,
  },
  {
    id: "factionwar", group: "Saison", title: "Faction War : semaines et scores",
    summary: "Calendrier, clés de stockage, clôture automatique.",
    html: `
<p>Rusfor contre Rainor. <b>Seuls EXFIL et OPERATIONS marquent des points</b> — DUALS est volontairement hors guerre. Chaque joueur marque pour <i>sa propre</i> faction, donc les équipes mixtes ne posent aucun problème.</p>
<p><b>La saison 1 commence le samedi 05/09/2026 à 18h00, heure française.</b> C'est l'époque du jeu (<code>FactionWarConfig</code>), et les semaines roulent donc du <b>samedi au samedi à 18h00</b>.</p>
<p>Le numéro est <i>calculé</i> par semaines civiles françaises depuis le 05/09/2026, affiché +1 pour que la première semaine soit la « saison 1 ». Il sert de <b>clé de stockage</b> (<code>s_0_Rusfor_0</code>, <code>archive_0</code>…).</p>
<p><b>Ne retouche plus l'époque après le lancement</b> : toutes les clés changeraient et les scores existants deviendraient inatteignables.</p>
<p><b>Avant le 05/09/2026 à 18h00</b>, le numéro est négatif et l'affichage montre « Season 0 » : c'est la pré-saison, volontairement visible plutôt que masquée.</p>
<p><b>Clôture :</b> automatique et <i>exactly-once</i>. Le premier serveur qui constate que la semaine est finie archive les scores et distribue les récompenses. Aucune tâche planifiée n'est nécessaire : même si personne n'est connecté à l'échéance exacte, la clôture se fait à la première connexion suivante.</p>
<p>Un match où <b>tous</b> les joueurs sont de la même faction ne fait pas monter le score global (garde anti-match miroir), mais la contribution personnelle compte quand même.</p>`,
  },
  {
    id: "ranked", group: "Saison", title: "Ranked : le ladder LP",
    summary: "Classement, anti-AFK, versement automatique.",
    html: `
<p>Classement individuel des DUALS, basé sur le LP (ELO). <b>Permanent entre les saisons.</b> Seul un changement de version des données (<code>DS_VERSION</code> dans <code>SharedConfig</code>) remet les LP et ce classement à zéro.</p>
<p>Alimenté à chaque fin de match par <code>RankedLadderService</code>, qui écrit le LP dans un OrderedDataStore. L'écriture est <b>absolue</b> (le LP courant, pas un delta) donc rejouable sans risque, et limitée à une fois par minute par joueur pour ménager le quota Roblox. Un flush forcé à la déconnexion garantit que la dernière valeur arrive.</p>
<p><b>C'est une vue dérivée, jamais une source de vérité.</b> Le vrai LP vit dans le profil du joueur. Si le classement se perdait, aucune donnée joueur ne serait affectée et il se reconstruirait au fil des matchs.</p>
<p><b>Il reste vide</b> tant qu'aucun match DUALS classé n'est terminé — c'est normal, pas un bug.</p>
<h4>Condition de présence — anti-AFK</h4>
<p><b>Un joueur doit s'être connecté entre deux versements pour toucher le second.</b> Le LP étant permanent et ne décroissant pas, sans cette règle quelqu'un resté top 10 puis absent trois mois reviendrait encaisser <i>tous</i> les versements accumulés.</p>
<p>Concrètement : à chaque connexion, l'horodatage est mémorisé. Un versement n'est accordé que si la connexion <i>précédente</i> est postérieure au versement d'avant. Les versements sautés sont marqués comme traités — ils ne reviendront pas.</p>
<p>Le <b>tout premier</b> versement n'est jamais filtré : on ne peut pas avoir raté un versement qui n'existait pas.</p>
<p><b>Préviens tes joueurs AVANT, pas pendant.</b> Le bouton <i>« Annoncer le versement (24h) »</i> publie un préavis avant la clôture automatique du samedi à 18h : les joueurs ont alors le temps de se connecter.</p>
<p>Le préavis utilise <code>{IN_24H}</code>, un horodatage Discord : chaque lecteur voit l'échéance <b>dans son propre fuseau et sa langue</b>, et le compte à rebours se met à jour tout seul.</p>
<p>Le <b>Faction War n'a pas besoin de cette règle</b> : ses récompenses dépendent des points marqués dans la semaine, donc un joueur inactif n'y a droit à rien de toute façon.</p>

<h4>Serveur vide, joueurs hors ligne</h4>
<p><b>Les récompenses modifiées</b> ne sont pas une livraison mais un <i>réglage</i> : elles attendent dans le DataStore et sont lues au démarrage du prochain serveur. Aucun joueur n'a besoin d'être connecté.</p>
<p><b>Le versement ranked</b> est paresseux comme la clôture Faction War : le premier serveur disponible crée le bordereau immuable, puis chacun le récupère à sa connexion.</p>
<p><b>La clôture de semaine</b>, elle, est <i>paresseuse</i> : si personne n'est connecté à l'échéance, elle se fait à la première connexion suivante. Au-delà de <b>2 semaines</b> (<code>MAX_LOOKBACK_WEEKS</code>), les récompenses non réclamées sont définitivement perdues.</p>
<p><b>Un boost</b> activé sans personne en ligne expire simplement sans avoir servi.</p>
<h4>Versement automatique</h4>
<p><b>Le snapshot part automatiquement à chaque fin de saison.</b> Le classement LP reste global et permanent ; seule sa photographie hebdomadaire est figée pour calculer les récompenses.</p>
<p>Le tableau d'aperçu montre qui recevrait quoi avec le ladder actuel. Le barème est éditable en avance et persiste dans le DataStore entre toutes les saisons ; les valeurs du code restent le filet de sécurité.</p>
<p><b>Impossible de verser deux fois.</b> L'identifiant dépend de la semaine et l'écriture est atomique : deux serveurs concurrents, un redémarrage ou un message répété produisent toujours le même bordereau.</p>
<p><b>Être hors ligne au moment précis de la clôture ne fait rien perdre.</b> Le modèle est un <i>pull</i> : un joueur éligible récupère son bordereau à son prochain passage au HUB.</p>
<p><b>Plusieurs bordereaux restent sûrs.</b> Les <b>8 derniers</b> sont conservés et parcourus dans l'ordre. La condition anti-AFK est appliquée à chacun ; ceux sautés pour inactivité sont marqués comme traités et ne reviennent pas.</p>
<p><b>Récapitulatif HUB :</b> un joueur actif voit le vainqueur, les scores, les ladders et ses récompenses en direct au HUB, à son retour de match, ou à sa connexion pendant la saison suivante. Après une saison complète supplémentaire, l'ancien bilan n'interrompt plus sa connexion.</p>`,
  },
  {
    id: "recompenses", group: "Saison", title: "Récompenses de fin de semaine",
    summary: "Calcul, modification, kits et badges.",
    html: `
<p>Versées <b>à la clôture de chaque semaine</b> de guerre, dans la boîte aux lettres du joueur. Le HUB tente automatiquement l'or, l'XP, les kits, badges et titres ; ce qui échoue reste dans le courrier et peut être réessayé.</p>
<p>Le calcul, dans l'ordre :</p>
<ol>
  <li><b>Palier de contribution</b> selon les points de la semaine : RECRUE (1+), SOLDAT (700+), VÉTÉRAN (2000+), HÉROS (5000+). Chaque palier donne de l'or, de l'XP et éventuellement un kit.</li>
  <li><b>Gagnante ou perdante</b> : les montants du tableau sont ceux de la faction <b>gagnante</b>. La perdante reçoit <code>ratio ×</code> l'or et l'XP, et son kit est <b>rétrogradé d'un palier</b>. Elle reçoit quand même quelque chose à tous les paliers — c'est ce qui la garde en jeu.</li>
  <li><b>Bonus de rang</b> : le top de sa <i>propre</i> faction reçoit un supplément (or, XP, titre). Il s'applique aux <b>deux</b> factions.</li>
</ol>
<p><b>Modifier :</b> onglet <i>Récompenses</i>. Tu édites, tu confirmes deux fois, c'est poussé à tous les serveurs immédiatement. <b>C'est permanent</b> jusqu'à ton prochain changement : ça survit aux redémarrages de serveur et à ton PC éteint.</p>
<p><b>Garde-fous :</b> plafonds durs à 50 000 or et 25 000 XP, appliqués <i>deux fois</i> — dans le dashboard pour t'expliquer précisément quel champ pose problème, et dans le jeu parce qu'un serveur ne doit jamais faire confiance à une valeur venue du réseau. Les bonus de rang sont retriés par rang croissant automatiquement, sinon le top 1 recevrait la récompense du top 10.</p>
<h4>Kits</h4>
<p>Le kit renseigné doit <b>exister dans <code>ShopConfig.KITS</code></b> côté jeu — le Command Center ne peut pas le vérifier, il ne lit pas le code Luau.</p>
<p>Si l'id est inconnu, le kit <b>reste au courrier</b> avec un avertissement dans l'Output serveur : corriger la config suffit à le livrer plus tard. (Avant, il disparaissait en silence.)</p>
<p>Ids existants : <code>kit_war_supply</code>, <code>kit_war_elite</code>, <code>operator_kit</code>, <code>elite_kit</code>, <code>warlord_kit</code>, <code>mercenary_kit</code>, <code>conscript_rainor</code>, <code>conscript_rusfor</code>. Pour en créer un nouveau, ajoute-le à <code>ShopConfig.KITS</code> (mets <code>hidden = true</code> pour qu'il n'apparaisse pas en boutique).</p>

<h4>Badges</h4>
<p>Un badge Roblox se crée <b>à la main dans le Creator Hub</b> — aucune API ne permet de le créer — et coûte <b>100 Robux</b> pièce. Le Command Center ne fait que l'<i>attribuer</i>.</p>
<p>Renseigne ses ids (séparés par des virgules, 5 maximum) dans la colonne <i>Badges</i>. Les badges du palier et ceux du bonus de rang <b>se cumulent</b>, doublons filtrés.</p>
<p>L'attribution a lieu à la réclamation du courrier. Elle est <b>idempotente</b> : Roblox ne donne jamais deux fois le même badge, et on vérifie la possession avant d'appeler pour ne pas gaspiller le quota. Si elle échoue (réseau, badge désactivé, badge hors de cette expérience), il <b>reste dans le courrier</b> pour être retenté — le courrier n'est pas considéré comme soldé tant qu'il reste un badge.</p>
<p><b>Le badge doit appartenir à cette expérience</b>, sinon Roblox refuse l'attribution.</p>
<p><b>Revenir en arrière :</b> « Revenir aux valeurs du jeu » supprime la surcharge ; le jeu reprend exactement les valeurs du fichier.</p>`,
  },
  {
    id: "boosts", group: "Réglages jeu", title: "Boosts : multiplicateurs XP, or, guerre",
    summary: "Effet immédiat, expiration automatique.",
    html: `
<p>Équivalent web de la commande <code>/boost</code> en jeu. Le Command Center écrit le boost dans le DataStore FactionWar versionné par <code>SharedConfig</code> (clé <code>event_override</code>) puis publie sur le topic <code>FW_Event</code> : les serveurs <b>déjà en partie</b> l'appliquent en moins d'une seconde, sans redémarrer.</p>
<p><b>Durée :</b> le boost <b>expire tout seul</b> à l'échéance choisie, tu n'as rien à faire. « Couper le boost » sert à l'interrompre avant terme.</p>
<p><b>Bornes :</b> multiplicateurs de ×1 à ×5, durée de 1 minute à 14 jours. Un boost entièrement à ×1 est refusé : il n'aurait aucun effet et masquerait un événement planifié.</p>
<p><b>Notifications en jeu :</b> les joueurs connectés reçoivent une bannière et un toast automatiquement — c'est le <i>jeu</i> qui le fait, pas le dashboard. La case « Annoncer sur Discord » ajoute en plus un message dans le salon d'annonces.</p>
<p><b>Si Discord échoue :</b> le boost reste appliqué. L'outil affiche « boost actif, mais l'annonce a échoué » — jamais l'inverse.</p>`,
  },
  {
    id: "dons", group: "Joueurs", title: "Dons et wipe",
    summary: "Or, XP, kits, items, badges, titre : à qui, et comment c'est livré.",
    html: `
<p>Le Command Center écrit un <b>bordereau</b> à identifiant unique dans le DataStore, puis prévient les serveurs. <code>GrantService</code> livre côté jeu.</p>
<table>
  <thead><tr><th>Audience</th><th>Livraison</th></tr></thead>
  <tbody>
    <tr><td>Joueurs (pseudos ou ids)</td><td>Boîte aux lettres : un joueur hors ligne le reçoit à son retour.</td></tr>
    <tr><td>Actifs cette semaine</td><td>Boîte aux lettres de tous les joueurs classés dans la guerre de la semaine.</td></tr>
    <tr><td>Tous les connectés</td><td>Appliqué tout de suite aux joueurs en ligne, sans boîte aux lettres.</td></tr>
  </tbody>
</table>
<ul>
  <li><b>Aperçu</b> avant l'envoi : qui reçoit quoi, pseudos résolus.</li>
  <li><b>Jamais deux fois</b> : rejouer le message ou relancer un serveur ne redonne rien, l'identifiant fait foi.</li>
  <li><b>Plafonds</b> : 50 000 or, 25 000 XP, 5 badges. Le jeu les réapplique : il ne fait jamais confiance à une valeur venue du réseau.</li>
  <li>Chaque don et chaque wipe laissent une trace dans <code>#ops-log</code>.</li>
</ul>
<p><b>Wipe</b> : vide l'inventaire, l'équipement et le stash des joueurs visés. Irréversible, jamais automatisable.</p>`,
  },
  {
    id: "modes", group: "Réglages jeu", title: "Modes de jeu",
    summary: "Ouvrir ou fermer une file, niveau minimum, événement OPERATIONS.",
    html: `
<p>Pour chaque mode : <b>ouvert</b> (sinon affiché « Soon ») et <b>niveau minimum</b> pour entrer dans la file. Écrit dans la clé <code>modes_config</code>, appliqué immédiatement aux serveurs ouverts et permanent jusqu'au prochain changement. <b>Revenir aux défauts</b> supprime la surcharge.</p>
<p><b>OPERATIONS</b> est un événement temporaire, fermé par défaut. L'ouvrir demande une durée : le bouton clignotant OPERATION apparaît sous PLAY jusqu'à l'échéance, puis se ferme seul. DOMINATION reste une file permanente séparée.</p>
<h4>Maintenance du stockage</h4>
<p>En bas de l'écran : purge du stash des joueurs absents depuis N mois. <b>Scanner</b> parcourt une page de joueurs à la fois et liste les candidats sans rien supprimer ; <b>Purger la sélection</b> ne supprime que les joueurs cochés. Irréversible, tracé dans <code>#ops-log</code>.</p>`,
  },
  {
    id: "configs", group: "Réglages jeu", title: "Configs live Roblox",
    summary: "Valeurs modifiables sans republier, via l'API Configs.",
    html: `
<p>Édite les configs live de l'expérience : lire la version publiée et le brouillon, modifier le brouillon, <b>publier</b>, restaurer une révision. La publication met 5 à 15 min à atteindre les joueurs et laisse une trace dans <code>#ops-log</code>.</p>
<p>L'API Configs est récente : en cas de refus, l'écran affiche le message exact de Roblox. Un 403 signifie que le droit correspondant manque à la clé.</p>`,
  },
  {
    id: "economie", group: "Réglages jeu", title: "Économie et Arsenal",
    summary: "Gains, prix, niveaux : configuration publiée avec les places.",
    html: `
<p><b>Ne pas confondre avec l'onglet Récompenses.</b> Récompenses règle la clôture hebdomadaire de Faction War. Les gains de modes, la quête quotidienne et les prix d'armes sont désormais définis en dur dans <code>ReplicatedStorage/Systems/Economy/ShopConfig.luau</code>.</p>
<h4>Barème livré</h4>
<table>
  <thead><tr><th>Source</th><th>Victoire</th><th>Défaite</th></tr></thead>
  <tbody>
    <tr><td>Duals</td><td>300</td><td>100</td></tr>
    <tr><td>Domination</td><td>400</td><td>150</td></tr>
    <tr><td>Exfil</td><td>550</td><td>75</td></tr>
    <tr><td>Operations</td><td>500</td><td>150</td></tr>
  </tbody>
</table>
<p>La quête <code>daily_kills</code> donne <b>1 000 gold</b>. Ce sont des montants de base : <code>CurrencyService</code> applique ensuite le bonus gold du joueur et l'éventuel boost actif.</p>
<h4>Modifier les valeurs</h4>
<ul>
  <li><b>Gains</b> : modifier <code>ShopConfig.DAILY_QUEST_REWARDS</code> ou <code>ShopConfig.MODE_REWARDS</code>.</li>
  <li><b>Prix</b> : modifier <code>ShopConfig.PRICES</code> directement, ou préparer les valeurs dans Arsenal puis utiliser <b>Générer ShopConfig</b>.</li>
  <li><b>Niveaux</b> : modifier <code>ShopConfig.LEVEL_REQ</code> ou utiliser la timeline Arsenal et son générateur.</li>
</ul>
<p><b>Aucune publication live :</b> le générateur produit seulement du code. Il faut synchroniser HUB/GAME et publier les places. Les serveurs déjà ouverts conservent leur version chargée au démarrage.</p>
<p><b>Habits :</b> l'onglet Habits de l'Arsenal règle prix, niveau (1 à 40) et source de chaque tenue. Seule la source « Shop » s'achète ; starters, kits d'abonnement et Mercenary partent dans <code>NO_BUY</code>. Reporter dans le jeu : <code>python claude_works/tools/outfit_shop.py --apply</code> puis <code>sync.py</code>.</p>
<p><b>Timeline Arsenal :</b> une arme peut être glissée vers un autre niveau ou une autre catégorie. Le dépôt est enregistré localement et le survol affiche score, rang et stats. Prix et niveau restent des choix manuels.</p>
<p>Documentation technique complète : <code>guides/GUIDE_ECONOMIE_ARSENAL.md</code>.</p>`,
  },
  {
    id: "annonces", group: "Diffusion", title: "Annonces, modèles et variables",
    summary: "Composer, modèles partagés, variables, planificateur.",
    html: `
<p><b>Composer</b> : l'aperçu montre exactement le rendu Discord. Rien n'est envoyé tant que tu ne cliques pas, et une confirmation rappelle le salon et le ping.</p>
<p><b>Modèles</b> : « Modifier » édite sur place ; « Dupliquer » crée une copie <i>déjà ouverte dans l'éditeur</i>, pour ne retoucher que 2-3 champs. Les modèles sont <b>partagés avec <code>announce.py</code></b> : un modèle créé ici est utilisable en ligne de commande dans la seconde.</p>
<p><b>Variables</b> : écris <code>{RUSFOR}</code> dans un modèle et il devient le vrai score <i>au moment de l'envoi</i>. C'est ce qui rend un modèle « classement » republiable chaque semaine sans jamais le rééditer. Clique une variable pour l'insérer au curseur ; « Résoudre les variables » montre le rendu réel avant d'envoyer.</p>
<p>Écris <code>&lt;#nom-du-salon&gt;</code> : c'est converti en vraie mention cliquable à l'envoi.</p>
<p><b>Planificateur</b> : c'est une <b>check-list</b>, pas un automate. Rien ne part tout seul, puisque ton PC n'est pas allumé en permanence. Une échéance dépassée devient une carte sur l'Accueil.</p>
<p><b>Journal</b> : tout ce que le CC a fait, gardé dans <code>data/cc.db</code> : annonces Discord, écritures dans le jeu (boosts, modes, récompenses, dons, wipe, configs, purge) et cartes traitées. Filtres par type. L'ancien <code>history.json</code> y est importé une fois.</p>`,
  },
  {
    id: "notifications", group: "Diffusion", title: "Notifications joueurs",
    summary: "Notifications Roblox hors du jeu : textes, audiences, limite d'une par jour.",
    html: `
<p>Une notification Roblox arrive sur le compte du joueur (site, appli), hors du jeu. Un clic sur « Join » le fait rejoindre Shroud War et ouvre directement le bon écran au Hub.</p>
<h4>Ce que Roblox impose</h4>
<ul>
  <li><b>Les textes se créent dans le Creator Hub</b> (Engagement, Notifications), 99 caractères au plus. Aucune API ne les crée : le CC garde seulement leur <b>Asset ID</b>.</li>
  <li><b>Une notification par joueur, par jour et par expérience.</b> Le CC tient un registre du jour (UTC) et saute les joueurs déjà notifiés.</li>
  <li>Seuls les joueurs de <b>13 ans ou plus inscrits</b> aux notifications de Shroud War les reçoivent (l'invitation s'affiche au Hub, <code>NotificationOptIn</code>). Roblox réduit aussi la portée selon l'engagement : le nombre réellement touché est plus bas que l'audience.</li>
  <li>L'expérience doit avoir au moins <b>100 visites</b>. Droit de clé : <b>User Notifications → Write</b>.</li>
</ul>
<h4>Le catalogue</h4>
<table>
  <thead><tr><th>#</th><th>Clé</th><th>Texte</th><th>Audience</th><th>Ouvre</th><th>Proposée par</th></tr></thead>
  <tbody>
    <tr><td>1</td><td style="white-space:nowrap"><code>RANKED_REWARD</code></td><td>You finished #{rank} in Ranked. Your {gold} gold is waiting.</td><td>Top du dernier versement ranked</td><td>Ranked</td><td>Carte « Ranked versé »</td></tr>
    <tr><td>2</td><td style="white-space:nowrap"><code>SEASON_RESULT</code></td><td>Season {season} is over: {faction} won. Claim your war rewards.</td><td>Contributeurs de la saison close</td><td>Faction War</td><td>Carte « Saison close »</td></tr>
    <tr><td>3</td><td style="white-space:nowrap"><code>EVENT_LIVE</code></td><td>{event} is live for {hours}h.</td><td>Absents depuis 2 à 14 jours</td><td>Jouer</td><td>Carte « Boost en cours » ou « OPERATIONS ouvert »</td></tr>
    <tr><td>4</td><td style="white-space:nowrap"><code>SEASON_ENDING</code></td><td>24h left in Season {season}. {faction} needs you.</td><td>Contributeurs de la semaine absents depuis 24 h, avec leur faction</td><td>Faction War</td><td>Carte « Dernière ligne droite »</td></tr>
    <tr><td>5</td><td style="white-space:nowrap"><code>UPDATE</code></td><td>Update {version} is out: {headline}</td><td>Venus dans les 30 derniers jours</td><td>Jouer</td><td>Manuel</td></tr>
    <tr><td>6</td><td style="white-space:nowrap"><code>COMEBACK</code></td><td>Your squad misses you. Your return bonus is waiting.</td><td>Absents depuis 7 à 30 jours, une fois par semaine au plus. À son retour, le joueur touche le bonus de retour (1 500 or, 500 XP)</td><td>Jouer</td><td>Carte hebdomadaire</td></tr>
  </tbody>
</table>
<p>Le numéro est la priorité. Comme un joueur n'en reçoit qu'une par jour, le CC garde la plus importante : le résultat de saison <b>met de côté</b> le top ranked tant que le ranked n'est pas versé, pour qu'il reçoive RANKED_REWARD juste après.</p>
<h4>Mise en place (une fois)</h4>
<ol>
  <li>Diffusion, <a href="#notify">Notifications</a> : « Copier le texte » de chaque ligne.</li>
  <li>Creator Hub, Shroud War, Engagement, Notifications, « Create a Notification String » : nom = la clé, texte = collé tel quel.</li>
  <li>Colonne Actions, « Copy Asset ID », puis colle-le dans le champ de la ligne et « Enregistrer les Asset IDs » (fichier local <code>data/notifications.json</code>).</li>
  <li>Ajoute <b>User Notifications → Write</b> à la clé Open Cloud, puis « Tester sur mon compte ». La tâche manuelle se coche seule au premier envoi réussi.</li>
</ol>
<h4>Envoyer</h4>
<p>Depuis une carte de l'Accueil ou « Préparer un envoi » : la fenêtre montre la notification telle qu'elle s'affichera, l'audience, les joueurs déjà notifiés aujourd'hui, ceux mis de côté et la durée. Rien ne part avant « Envoyer ». Un même sujet (saison, versement, boost, version) ne part qu'une fois.</p>
<p>L'envoi tourne en arrière-plan, environ 8 joueurs par seconde, une campagne à la fois ; « Arrêter » la coupe proprement. Une réponse 429 (joueur déjà notifié, ou limite de Roblox) compte comme servie ; une série de 429 met la campagne <b>en pause</b> : relance-la plus tard, les joueurs servis sont sautés. Un refus de droit ou de paramètres arrête tout de suite avec la cause.</p>
<h4>Côté jeu</h4>
<ul>
  <li><b>Index d'activité.</b> À chaque arrivée au Hub, <code>NotificationServer</code> écrit l'heure dans l'OrderedDataStore <code>CC_LastSeen_&lt;version&gt;</code> (au plus une fois par heure et par joueur sur un serveur). Le CC y choisit les absents par plage d'heures, sans lire un seul profil.</li>
  <li><b>Écran ouvert.</b> La notification porte <code>open=war</code>, <code>ranked</code>, <code>play</code> ou <code>crates</code>. Le Hub le lit à l'arrivée et <code>LaunchRouter</code> ouvre l'écran dès que le menu est prêt (après l'écran de démarrage ou le choix de faction), sauf si le joueur a déjà ouvert un écran.</li>
  <li><b>Bonus de retour.</b> Un joueur absent depuis 7 jours ou plus (jours UTC sans passage au Hub) touche à son arrivée un bonus dédié, 1 500 or et 500 XP, à la place du palier du jour 1 de la série de connexion, avec une bannière « Welcome back ». Réglage : <code>RetentionConfig.COMEBACK</code> ; <code>minDays</code> doit rester à 7 au plus, sinon la notification COMEBACK promettrait un bonus que certains ne toucheraient pas (contrôlé par <code>check.py</code>). Chaque bonus est journalisé dans les Analytics (événement <code>ComebackBonus</code>, valeur = jours d'absence).</li>
  <li>Le marché noir peut aussi envoyer sa propre notification (<code>MARKET_SOLD</code>) si son Asset ID est renseigné dans <code>ShopConfig</code> ; elle compte dans la même limite quotidienne.</li>
</ul>`,
  },
  {
    id: "automatisations", group: "Système", title: "Automatisations",
    summary: "Ce qui peut partir seul depuis une carte, quand, et comment l'arrêter.",
    html: `
<p>Par défaut, <b>rien ne part sans ton clic</b>. L'écran <a href="#automations">Automatisations</a> permet, règle par règle, de laisser une carte de l'Accueil publier seule ses annonces ou ses notifications.</p>
<h4>Les réglages d'une règle</h4>
<ul>
  <li><b>Manuel</b> : la carte attend ton clic (défaut).</li>
  <li><b>Avec délai</b> (0 à 120 min) : le départ est fixé à la première apparition de la carte, jamais repoussé. La carte affiche « part automatiquement à 18:15 » et un bouton <b>Annuler l'envoi auto</b> ; l'action reste alors disponible à la main.</li>
  <li><b>Immédiat</b> : dès la minute où la carte apparaît.</li>
  <li><b>Actions cochées</b> : seules celles-ci partent seules (par exemple le résultat global mais pas la notification).</li>
</ul>
<h4>Réglages communs</h4>
<ul>
  <li><b>Heures calmes</b> (heure de Paris) : rien ne part seul dans la plage ; l'envoi attend la fin.</li>
  <li><b>Tout en manuel</b> : coupe toutes les règles et annule ce qui était prévu.</li>
  <li><b>#ops-log</b> : un message à chaque envoi automatique, et à chaque échec.</li>
</ul>
<h4>Garde-fous</h4>
<ul>
  <li>Un envoi automatique suit exactement le chemin du clic : même contenu, même journal (auteur « automatique »), jamais deux fois.</li>
  <li>Un échec n'est <b>pas retenté</b> seul : la carte affiche l'erreur et propose l'action à la main.</li>
  <li><b>Jamais automatiques</b> : wipe, ban, redémarrage des serveurs, effacement RTBF, retrait d'objet ou d'or, dons.</li>
  <li>Le CC doit tourner pour que quelque chose parte seul : c'est l'intérêt de l'hébergement.</li>
</ul>`,
  },
  {
    id: "acces", group: "Système", title: "Accès, webhooks et effacement",
    summary: "Connexion Discord, rôles, webhooks Roblox, droit à l'effacement.",
    html: `
<h4>Connexion</h4>
<p>Sur ton PC (<code>python server.py</code>), pas de connexion : la console n'écoute que sur cette machine. En ligne, « Se connecter avec Discord » ; seul ton identifiant Discord est lu. Ton rôle dépend de la liste où figure cet identifiant dans le <code>.env</code> du serveur :</p>
<table>
  <thead><tr><th>Rôle</th><th>Peut</th></tr></thead>
  <tbody>
    <tr><td>Administrateur (<code>CC_ADMINS</code>)</td><td>Tout : dons, wipe, bans, effacement, automatisations, réglages du jeu.</td></tr>
    <tr><td>Modérateur (<code>CC_MODS</code>)</td><td>Tout lire, envoyer un message à un joueur ou un serveur, kicker, reporter ou ignorer une carte, voir les aperçus.</td></tr>
    <tr><td>Lecture (<code>CC_VIEWERS</code>)</td><td>Tout lire, voir les aperçus.</td></tr>
  </tbody>
</table>
<p>Retirer un identifiant et relancer coupe l'accès tout de suite. Un compte refusé voit son identifiant à l'écran : il suffit de l'ajouter. Le <a href="#history">Journal</a> indique qui a fait chaque action.</p>
<h4>Webhooks Roblox</h4>
<p>Roblox prévient le CC (adresse <code>/webhooks/roblox</code>, signée avec <code>ROBLOX_WEBHOOK_SECRET</code>) et chaque événement devient une carte :</p>
<ul>
  <li><b>Remboursement</b> : Roblox retire lui-même un pass ; pour un produit développeur (kit, or...), ce qui a été livré reste au joueur. Ouvre sa fiche et retire-le si besoin.</li>
  <li><b>Abonnement résilié</b> (info) ou <b>remboursé</b> (à vérifier) ; achats et renouvellements vont seulement au Journal.</li>
  <li><b>Droit à l'effacement</b> : obligation légale, 30 jours. La carte ne peut être ni ignorée ni marquée faite.</li>
</ul>
<h4>Effacer les données d'un joueur</h4>
<ol>
  <li>Carte « Droit à l'effacement », <b>Effacer les données…</b> : la fenêtre lit chaque magasin du joueur et dit ce qui existe (profil, compétences, inventaire, stash, sanctions, extraction, dettes, pièges, classements).</li>
  <li>Tape l'identifiant du joueur pour confirmer, puis <b>Effacer définitivement</b>.</li>
  <li>Le CC supprime aussi ce qu'il garde (liaison Discord, copies d'édition, registre des notifications, événements) et anonymise le Journal. La carte se ferme ; la trace de l'effacement reste, sans l'identifiant.</li>
</ol>
<p>Droits de clé nécessaires : Data Stores <b>Delete Entry</b> et Ordered Data Stores <b>Write</b>. Une entrée « illisible » dans l'aperçu signale un droit manquant.</p>`,
  },
  {
    id: "depannage", group: "Aide", title: "Dépannage",
    summary: "Les symptômes fréquents et leur cause.",
    html: `
<h4>Command Center</h4>
<ul>
  <li><b>« Le .env ne semble pas pris en compte »</b> : il est lu au démarrage. Relance le serveur après l'avoir modifié.</li>
  <li><b>Contenu périmé</b> : une deuxième instance refuse de démarrer et indique comment trouver la première. Si l'écran semble ancien, un ancien process tourne encore.</li>
  <li><b>Une action Roblox répond 403</b> : Santé, <b>Tester les permissions</b>. Chaque droit manquant y est nommé. Si tout est en 403, l'IP de ce PC n'est pas autorisée par la clé, ou la clé n'appartient pas au groupe.</li>
  <li><b>« Réservé aux administrateurs »</b> : ton rôle ne permet pas cette action (voir Accès).</li>
  <li><b>« Jeton de sécurité absent ou périmé »</b> : le serveur a redémarré ; recharge la page.</li>
  <li><b>Démarrage refusé</b> : le CC n'accepte pas d'écouter hors de cette machine sans connexion Discord configurée. Le message dit quelle variable manque.</li>
</ul>
<h4>Accueil</h4>
<ul>
  <li><b>Aucune carte venue du jeu</b> (triche, avis, versement) : la clé doit avoir « Memory Store : Queue Read et Discard » et « Sorted Map Write ». Santé, Tester les permissions. Le journal Live montre « jeu » à chaque événement reçu.</li>
  <li><b>Un test en Studio n'apparaît pas</b> : Roblox isole la mémoire MemoryStore de Studio de celle du jeu publié, donc les événements de Studio ne sortent pas. Les cartes déduites de l'état (saison close, boost, OPERATIONS) apparaissent quand même, car elles lisent les DataStores.</li>
  <li><b>« Version de données »</b> ou <b>« contrat incohérent »</b> : HUB et MATCH ne visent pas la même version. Publier les deux places.</li>
</ul>
<h4>Live et surveillance</h4>
<ul>
  <li><b>Live vide alors que des joueurs jouent</b> : les places publiées n'ont pas encore <code>CommandCenterBridge</code> (publier HUB et GAME), ou la clé n'a pas « Memory Store : Sorted Map Read ».</li>
  <li><b>Journal « Hub sans pont »</b> : un Hub tourne une ancienne version. Redémarrer les serveurs depuis le Creator Hub.</li>
  <li><b>Journal « versions mélangées »</b> : normal juste après une publication ; les anciens serveurs se ferment au fil des parties.</li>
  <li><b>Messages Discord perdus</b> (compteur orange d'un serveur) : un joueur ou un type de message a dépassé son quota. Regarder la sortie du serveur dans Studio ou les logs : un seul avertissement par minute résume les pertes par type.</li>
  <li><b>Tendances vides</b> : droit « Analytics → Read » absent, ou moins d'environ 100 joueurs actifs par jour.</li>
</ul>
<h4>Actions</h4>
<ul>
  <li><b>« Aucun serveur n'a répondu »</b> : le joueur s'est déconnecté, ou la réponse attend dans la file. Le journal Live affiche « Commande … faite » à son arrivée. Si rien n'arrive jamais : places pas encore publiées avec <code>CCCommands</code>.</li>
  <li><b>« Le jeu a modifié cette donnée depuis l'aperçu »</b> : normal si le joueur a joué entre-temps. Refais l'aperçu.</li>
  <li><b>« Verrou pris »</b> : une autre modification du même joueur est en cours, ou une précédente a été interrompue. Le verrou expire seul en 60 s.</li>
  <li><b>Ban refusé (403)</b> : droit « User Restrictions : Write » absent. <b>Redémarrage refusé</b> : « Universes : Write ».</li>
</ul>
<h4>Données et classements</h4>
<ul>
  <li><b>Classements vides avec un bandeau</b> : droit <b>Ordered Data Stores : Read</b> absent, un système séparé de Data Stores souvent oublié.</li>
  <li><b>Classement vide sans bandeau</b> : il est réellement vide, aucun match joué.</li>
  <li><b>Fiche joueur : une section en erreur</b> : le droit qu'elle utilise manque (Subscriptions, User Restrictions...). Le reste de la fiche reste valable.</li>
</ul>
<h4>Discord et notifications</h4>
<ul>
  <li><b>Discord refuse l'envoi</b> : sur le salon visé, le bot a besoin de Voir le salon, Envoyer des messages, Intégrer des liens, et Mentionner @everyone si tu pings.</li>
  <li><b>Le jeu ne poste plus dans Discord</b> : secret absent du Secrets Store (un avertissement par serveur), ou id du webhook absent de <code>ALLOWED_WEBHOOK_IDS</code> sur le Worker.</li>
  <li><b>Notification : campagne en échec (403)</b> : droit <code>User Notifications : Write</code> absent de la clé. Il n'est pas sondé par le test de permissions : utilise « Tester sur mon compte ».</li>
  <li><b>Notification : échec (400 ou 404)</b> : l'Asset ID ne correspond pas à un texte de Shroud War, ou les <code>{paramètres}</code> du texte créé dans le Creator Hub diffèrent de ceux affichés dans le CC (même orthographe, mêmes accolades).</li>
  <li><b>Notification envoyée mais jamais reçue</b> : normal pour un joueur de moins de 13 ans, non inscrit aux notifications, ou déjà notifié ce jour-là. Roblox réduit aussi la portée selon l'engagement.</li>
  <li><b>Audience « absents depuis… » vide</b> : l'index d'activité <code>CC_LastSeen</code> ne se remplit qu'après publication du Hub avec <code>NotificationServer</code>, à chaque arrivée d'un joueur.</li>
</ul>`,
  },
];
