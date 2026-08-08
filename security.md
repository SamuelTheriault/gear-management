# Sécurité — Bonnes pratiques pour RégiStock

## Principe de base

Aucune information sensible (mot de passe, clé API, secret OAuth, credential de base de données) ne doit **jamais** se retrouver en clair dans :
- le code source,
- les fichiers markdown de documentation (`schema.md`, `architecture.md`, etc.),
- un commit Git,
- un message envoyé à Claude ou tout autre outil.

## 1. Gestion des secrets

- Toutes les valeurs sensibles (identifiants Google OAuth, mot de passe / connection string de la base de données, futures clés API) doivent être stockées dans des **variables d'environnement**, généralement via un fichier `.env` sur le serveur.
- Le fichier `.env` ne doit **jamais** être commité dans Git — ajouter `.env` au `.gitignore` dès la création du dépôt.
- En production (Railway), ces variables se configurent directement dans le dashboard Railway (onglet Variables du service) — pas de fichier `.env` sur un serveur à gérer. Même principe : jamais en dur dans le code ni dans un commit.
- Fournir un fichier `.env.example` (sans valeurs réelles) dans le dépôt pour documenter quelles variables sont attendues, ex. :
  ```
  DB_HOST=
  DB_USER=
  DB_PASSWORD=
  GOOGLE_CLIENT_ID=
  GOOGLE_CLIENT_SECRET=
  GOOGLE_MAPS_API_KEY=
  ```

## 2. Authentification (Google OAuth)

- Le `Client Secret` généré dans Google Cloud Console est une valeur sensible — même traitement que les autres secrets (variable d'environnement, jamais en dur).
- Les tokens de session utilisateur doivent être gérés **côté serveur** (session store ou cookie `httpOnly` + `secure`), jamais stockés dans le `localStorage` ou `sessionStorage` du navigateur — ces derniers sont accessibles par n'importe quel script si l'app a une faille XSS.
- Restreindre les URIs de redirection autorisées dans la config Google Cloud à ton domaine réel une fois en production.

## 2bis. Clé API Google Routes (calcul de trajet, 2026-07-18)

- Clé distincte du `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` de l'OAuth — même principe : variable d'environnement (`GOOGLE_MAPS_API_KEY`), jamais en dur, jamais dans un fichier markdown ou un commit.
- La restreindre dans Google Cloud Console à "Routes API" uniquement (pas d'accès aux autres API Google Maps), pour limiter les dégâts si la clé fuit malgré tout.
- Si la variable est absente ou vide, `inventory/maps.py` désactive simplement l'estimation automatique (pas d'erreur, pas de crash) — donc pas de pression à la configurer dans l'urgence.

## 3. Base de données

- Utiliser des identifiants distincts pour l'environnement de développement/local et pour la production sur Railway.
- Le compte utilisé par l'application ne devrait avoir que les permissions nécessaires (lecture/écriture sur les tables du projet), pas un accès administrateur complet au service MySQL managé.
- Le MySQL managé Railway n'est accessible que via son réseau interne/URL de connexion fournie — pas d'exposition publique par défaut, à vérifier dans les paramètres du service.

## 4. Transport

- HTTPS obligatoire en production — Railway fournit un certificat SSL/TLS automatique sur son domaine par défaut (et sur un domaine custom si tu en ajoutes un).
- Aucune donnée sensible (identifiants, tokens) ne doit transiter en clair (HTTP simple).

## 5. Dépôt de code

- Dépôt Git privé (pas public), même si le projet est interne.
- Avant chaque commit, vérifier qu'aucun secret n'a été inclus par erreur (ex. copier-coller d'une clé API dans un fichier de config versionné).
- Si un secret est accidentellement commité, il faut le considérer comme compromis et le régénérer (changer le mot de passe / régénérer la clé), pas seulement le supprimer du fichier.

## 6. Liens publics de rapport (`report_shares`, 2026-08-08)

**C'est la seule porte de l'API qui s'ouvre sans authentification.** Tout le reste est derrière `IsAuthenticated` + `HasProjectAccess` (voir `permissions.py`). Cette section décrit pourquoi cette exception existe et ce qui la borne.

### Le modèle de menace, énoncé franchement

Le jeton d'URL **est** l'authentification. Qui détient le lien lit la feuille. C'est un choix assumé, pas un oubli : le scénario réel est une feuille papier qui circule sur un quai de déchargement, scannée par un technicien pigiste ou le directeur technique d'une salle partenaire. Exiger un mot de passe rendrait le code QR inutile, et un compte par personne est hors de question pour des gens qui interviennent trois jours sur une production.

Ce qu'on protège en échange :

1. **Entropie.** 16 octets tirés de `secrets` (jamais `random`) — 128 bits, 22 caractères URL-safe. L'énumération est sans objet, et connaître des jetons déjà émis n'aide pas à en deviner d'autres.
2. **Portée d'un seul objet.** Un lien expose UNE tournée, UN spectacle, UN technicien ou UNE journée — jamais le projet entier, jamais une liste. Un lien qui fuite expose une feuille, pas la production.
3. **Révocable et expirable.** `revoked_at` coupe l'accès immédiatement ; `expires_at` (optionnel) le fait expirer seul.
4. **Lecture seule.** Les vues publiques n'exposent aucune écriture. Un lien qui fuite ne peut rien modifier.
5. **404 uniforme.** Jeton inconnu, révoqué ou expiré : même réponse, même message. Distinguer les cas transformerait la vue en oracle confirmant qu'un jeton a existé.
6. **Non indexable.** En-tête `X-Robots-Tag: noindex, nofollow, noarchive` sur chaque réponse, plus un `robots.txt` qui interdit `/p/` et `/api/`. Ceci ne PROTÈGE rien — un robot malveillant l'ignore — c'est une mesure d'hygiène contre l'indexation accidentelle d'un lien collé dans un courriel ou un canal public.
7. **Non mise en cache.** `Cache-Control: no-store` : le contenu doit être à jour (c'est la promesse du QR) et ne doit pas rester dans le cache d'un proxy partagé ou d'un téléphone prêté. `Referrer-Policy: no-referrer` évite que l'URL secrète parte dans l'en-tête `Referer` d'un lien externe.
8. **Limite de débit.** `DEFAULT_THROTTLE_RATES['public-report']` (défaut `120/hour` par IP, réglable via `PUBLIC_REPORT_THROTTLE`). Volontairement généreux : une équipe entière derrière le wifi d'une salle partage une seule IP publique. Le but n'est pas de rationner l'usage légitime mais de rendre coûteuse une énumération automatisée — que l'entropie rend de toute façon vaine.

### Ce que ça implique pour Samuel

- **Un lien de partage se traite comme un document confidentiel**, pas comme une URL anodine. Une feuille de tournée porte des adresses de quai, des noms et des numéros de téléphone de contacts en salle.
- **Révoquer coupe aussi les copies papier.** Toutes les feuilles déjà imprimées avec ce code QR cessent de fonctionner, y compris celles qui circulent légitimement. C'est voulu — c'est ce qui rend la révocation utile — mais ça se décide, ça ne se clique pas distraitement. L'interface demande une confirmation explicite pour cette raison.
- **Les liens révoqués restent listés** dans Réglages → Liens de partage, avec leur compteur de consultations : c'est la trace de ce qui a circulé, à consulter justement quand on soupçonne une fuite.

### Règles pour toute vue ajoutée dans `public_views.py`

Lecture seule ; un jeton = un objet, aucun paramètre qui élargirait la portée ; 404 uniforme ; en-têtes de protection via `_harden()` ; throttle. Ces cinq règles sont répétées en tête du module — les enfreindre est ce qui transformerait une exception étroite en fuite de données.

### Variable d'environnement

`PUBLIC_BASE_URL` (ex. `https://gear-management-production.up.railway.app`) — origine utilisée pour construire l'URL encodée dans les codes QR. Ce n'est pas un secret, mais c'est une valeur **critique** : sans elle, l'URL est déduite de la requête courante, ce qui suffit tant qu'un PDF sort d'un cycle requête/réponse, et devient faux dès qu'une tâche planifiée s'en mêle. Un QR erroné imprimé en quarante exemplaires ne se rattrape pas.

## Résumé rapide

| Élément | Où ça va |
|---|---|
| Mot de passe base de données | Variable d'environnement (`.env`, non versionné) |
| Google Client ID / Secret (OAuth) | Variable d'environnement (`.env`, non versionné) |
| Clé API Google Routes (`GOOGLE_MAPS_API_KEY`) | Variable d'environnement (`.env`, non versionné), restreinte à "Routes API" dans Google Cloud |
| Tokens de session | Cookie `httpOnly` + `secure`, côté serveur |
| Jetons de partage public (`report_shares.token`) | Générés par `secrets`, jamais choisis ni modifiables par l'API. À traiter comme un document confidentiel : qui a le lien lit la feuille |
| `PUBLIC_BASE_URL` | Variable d'environnement Railway — pas un secret, mais critique : une valeur fausse grave une mauvaise adresse dans les codes QR imprimés |
| Fichiers markdown de doc (`schema.md`, etc.) | Aucune valeur sensible — structure et logique seulement |
