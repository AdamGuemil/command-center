# Mettre le Command Center en ligne gratuitement (Oracle Cloud)

Ce guide met la console en ligne, allumée en permanence, sur un serveur gratuit d'Oracle
Cloud. À la fin, tu ouvres `https://<adresse>` depuis ton téléphone, tu te connectes avec
Discord, et une fin de saison produit ses cartes même quand ton PC est éteint.

**Durée** : environ 45 minutes, une seule fois.
**Coût** : 0 €. Oracle demande une carte bancaire pour vérifier ton identité, mais ne prélève
rien tant que tu restes dans l'offre gratuite (« Always Free »).
**Il te faut** : ton PC Windows, ta carte bancaire, ton compte Discord et le Creator Hub.

Tout ce qui est technique est fait par deux scripts. Tu copies quelques commandes et tu
réponds à quelques questions.

---

## 1. Pousser la dernière version sur GitHub

Le serveur télécharge le code depuis GitHub : il doit être à jour.

1. Copie le fichier `ci.yml` reçu dans `.github\workflows\` (remplace l'ancien).
2. Dans le dossier du CC :
   ```
   git add -A
   git commit -m "Hebergement Oracle"
   git push
   ```

## 2. Créer le compte Oracle Cloud

1. Va sur <https://www.oracle.com/cloud/free/> > **Start for free**.
2. Remplis le formulaire. **Home Region** : choisis **France Central (Paris)** ou **Germany
   Central (Frankfurt)**. Ce choix est **définitif** : le serveur gratuit sera créé dans cette
   région.
3. Vérification de la carte : Oracle bloque une petite somme puis la rend. Les cartes
   prépayées sont refusées. Si ta carte est refusée, essaie-en une autre.
4. Attends l'e-mail « Your account is ready ». Ça prend de quelques minutes à une heure.
5. **Sécurité des dépenses** (conseillé) : menu ☰ > *Billing & Cost Management* > *Budgets*
   > *Create Budget*, montant **1 €**, alerte à 100 % avec ton e-mail. Tu seras prévenu si
   quelque chose devenait payant.

## 3. Créer ta clé SSH (sur ton PC)

La clé SSH remplace le mot de passe pour te connecter au serveur. Ouvre **PowerShell** :

```powershell
ssh-keygen -t ed25519
```
Appuie trois fois sur Entrée. Puis copie la partie publique (elle peut être partagée sans
risque) :
```powershell
Get-Content $HOME\.ssh\id_ed25519.pub | Set-Clipboard
```

## 4. Créer le serveur

Dans la console Oracle : menu ☰ > **Compute** > **Instances** > **Create instance**.

1. **Name** : `shroud-cc`.
2. **Image and shape** > **Edit** :
   - **Change image** > **Ubuntu** > **Canonical Ubuntu 24.04** > *Select image*.
   - **Change shape** > **Ampere** > `VM.Standard.A1.Flex`, **1 OCPU** et **6 GB** >
     *Select shape*. Si Oracle répond « Out of capacity » à la création, reviens ici et prends
     **Specialty and previous generation** > `VM.Standard.E2.1.Micro`. Les deux portent
     l'étiquette *Always Free-eligible* et suffisent largement.
3. **Networking** : laisse *Create new virtual cloud network* et *Create new public subnet*,
   et vérifie que **Assign a public IPv4 address** est coché.
4. **Add SSH keys** > **Paste public keys** > colle (Ctrl+V) ce que tu as copié à l'étape 3.
5. **Create**. Attends l'état **Running** (1 à 2 minutes), puis note l'**IP publique**
   (*Public IP address*) affichée sur la page. Dans la suite, remplace `<IP>` par elle.

## 5. Ouvrir le site au public (ports 80 et 443)

Par défaut, Oracle n'autorise que la connexion SSH. Sur la page de l'instance :

1. Clique sur le lien du **Subnet** (onglet *Networking* ou section *Primary VNIC*).
2. Onglet **Security** (ou *Security Lists*) > **Default Security List for …**.
3. **Add Ingress Rules** :
   - *Source CIDR* : `0.0.0.0/0`
   - *IP Protocol* : `TCP`
   - *Destination Port Range* : `80,443`
4. **Add Ingress Rules** pour valider.

## 6. Installer le serveur

Dans PowerShell, connecte-toi au serveur (réponds `yes` à la première question) :
```powershell
ssh ubuntu@<IP>
```
Puis lance l'installation (3 à 5 minutes) :
```bash
curl -fsSL https://raw.githubusercontent.com/AdamGuemil/command-center/main/deploy/setup-server.sh | sudo bash
```
Le script installe Docker, le pare-feu, les mises à jour de sécurité automatiques, et
télécharge le CC. Laisse cette fenêtre ouverte.

## 7. Envoyer ton .env et tes données au serveur

**Ferme d'abord le CC sur ton PC** (Ctrl+C dans sa fenêtre), pour que sa base soit copiée
proprement. Ouvre une **deuxième** fenêtre PowerShell :
```powershell
cd $HOME\Desktop\rob\shroud-command-center\shroud-command-center
scp .env ubuntu@<IP>:/tmp/cc.env
scp -r data ubuntu@<IP>:/tmp/cc-data
```
Tes clés Roblox et Discord, ton journal, tes réglages de notifications et la configuration du
bot partent ainsi vers le serveur, sans rien retaper. Le fichier copié est effacé du dossier
`/tmp` du serveur dès qu'il est lu.

## 8. Préparer la connexion Discord

Le serveur aura l'adresse `https://<IP avec des tirets>.sslip.io`. Par exemple, l'IP
`141.145.10.20` donne `https://141-145-10-20.sslip.io`. Ce nom gratuit pointe tout seul vers
ton serveur : pas de domaine à acheter.

<https://discord.com/developers/applications> > ton application (celle du bot) > **OAuth2** :

1. **Redirects** > **Add Redirect** :
   `https://<IP avec des tirets>.sslip.io/auth/callback` > **Save Changes**.
2. Copie le **Client ID**. Tu colleras le **Client Secret** (*Reset Secret*) à l'étape
   suivante, quand le script le demande.

## 9. Configurer et démarrer

Retourne dans la fenêtre connectée au serveur :
```bash
sudo bash /opt/shroud-cc/deploy/configure.sh
```
Le script reprend ton `.env` et ne pose que ce qui manque :
- **Domaine** : appuie sur Entrée pour garder l'adresse sslip.io proposée.
- **Client ID** et **Client Secret** de l'étape 8. Le secret ne s'affiche pas quand tu le
  colles (clic droit pour coller), c'est normal.
- **Identifiant Discord administrateur** : le tien. Dans Discord : *Paramètres* > *Avancés* >
  *Mode développeur*, puis clic droit sur ton nom > *Copier l'identifiant*.

Ensuite il construit et démarre la console (2 à 5 minutes). Il affiche enfin l'adresse, le
**secret des webhooks** et les **3 valeurs pour GitHub**. Garde cette fenêtre ouverte pour
les étapes 10 et 11.

## 10. Vérifier et finir

1. Ouvre l'adresse sur ton PC puis sur ton téléphone > **Se connecter avec Discord**. La
   première visite peut prendre quelques secondes, le temps d'obtenir le certificat HTTPS.
2. **Creator Hub** > Open Cloud > API Keys > ta clé > *Accepted IP Addresses* : remplace
   `0.0.0.0/0` par `<IP>/32`. La clé ne fonctionnera plus que depuis ton serveur.
3. **Creator Hub** > Shroud War (profil du groupe) > **Webhooks** > *Create Webhook* :
   - URL et **Secret** affichés par le script ;
   - déclencheurs *Transaction Refunded*, *Subscription* et *Right to Erasure*.

   **Test Response** doit faire apparaître la carte « Webhook Roblox reçu » sur l'Accueil.
4. Sur ton PC, dans le `.env` du CC : `CC_BOT=0` et ajoute `CC_WATCH=0`. Sinon deux bots
   répondent et les alertes arrivent en double. Le CC du PC reste utile pour l'Arsenal.

## 11. Mises à jour automatiques

À chaque `git push` sur `main`, GitHub teste puis met le serveur à jour tout seul. Si la
nouvelle version ne répond pas, le serveur revient à la précédente.

1. **Rendre l'image publique**. Après ton premier push, GitHub > ton profil > *Packages* >
   `command-center` > *Package settings* > *Change visibility* > **Public**. Le code est déjà
   public, et l'image ne contient aucun secret.
2. GitHub > dépôt `command-center` > *Settings* > *Secrets and variables* > *Actions* :
   - onglet **Variables** > *New repository variable* : `DEPLOY_HOST` ;
   - onglet **Secrets** > *New repository secret* : `DEPLOY_KNOWN_HOSTS`, puis
     `DEPLOY_SSH_KEY` (tout le bloc, lignes `BEGIN` et `END` comprises).

   Les valeurs sont celles affichées par le script. La clé ne peut **que** lancer une mise à
   jour du CC, rien d'autre sur le serveur.

C'est fini. Tu peux fermer les fenêtres PowerShell.

---

## Si quelque chose coince

| Symptôme | Cause et solution |
|---|---|
| « Out of capacity » à la création | Plus de place en Ampere dans ta région : prends `VM.Standard.E2.1.Micro` (étape 4), ou réessaie plus tard. |
| `ssh` : « Permission denied (publickey) » | La clé collée à l'étape 4 n'est pas celle de ce PC. Recrée l'instance avec la bonne clé (étape 3). |
| La page ne s'ouvre pas du tout | Ports 80 et 443 pas ouverts : refais l'étape 5. |
| « Démarrage refusé » ou page d'erreur | Relance `sudo bash /opt/shroud-cc/deploy/configure.sh`. Le message dit ce qui manque. |
| Le navigateur signale un certificat invalide après 2 minutes | L'autorité de certification refuse l'adresse sslip.io (trop de demandes ce jour-là). Prends un nom gratuit sur <https://www.duckdns.org> (connexion avec GitHub, sous-domaine pointé sur `<IP>`), mets-le dans `CC_DOMAIN` et `CC_PUBLIC_URL` du `.env` et dans *Redirects* chez Discord, puis `sudo -u deploy docker compose up -d`. |
| Discord : « Invalid OAuth2 redirect_uri » | L'adresse de l'étape 8 doit être exactement celle du site, avec `https://` et `/auth/callback`. |
| « Ton compte Discord n'a pas accès » | Ton identifiant n'est pas dans `CC_ADMINS` : `sudo nano /opt/shroud-cc/.env`, corrige, puis relance `configure.sh`. |
| Voir ce que fait le CC | `cd /opt/shroud-cc && sudo docker compose logs --tail 50 cc` |
| Changer un réglage | `sudo nano /opt/shroud-cc/.env` (Ctrl+O pour enregistrer, Ctrl+X pour quitter), puis `cd /opt/shroud-cc && sudo -u deploy docker compose up -d` |

**Instance inactive.** Oracle peut arrêter un serveur gratuit qu'il juge inutilisé (moins de
20 % de processeur et de réseau pendant 7 jours ; pour Ampere, la mémoire compte aussi). Il
prévient par e-mail avant. Si ça arrive : console Oracle > ton instance > **Start**, la console
redémarre avec ses données. Pour ne plus jamais être concerné, tu peux passer le compte en
*Pay As You Go* (*Billing* > *Upgrade*). Ce qui est « Always Free » reste gratuit, et le
budget de 1 € de l'étape 2 te protège.
