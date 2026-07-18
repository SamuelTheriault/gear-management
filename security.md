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
  ```

## 2. Authentification (Google OAuth)

- Le `Client Secret` généré dans Google Cloud Console est une valeur sensible — même traitement que les autres secrets (variable d'environnement, jamais en dur).
- Les tokens de session utilisateur doivent être gérés **côté serveur** (session store ou cookie `httpOnly` + `secure`), jamais stockés dans le `localStorage` ou `sessionStorage` du navigateur — ces derniers sont accessibles par n'importe quel script si l'app a une faille XSS.
- Restreindre les URIs de redirection autorisées dans la config Google Cloud à ton domaine réel une fois en production.

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

## Résumé rapide

| Élément | Où ça va |
|---|---|
| Mot de passe base de données | Variable d'environnement (`.env`, non versionné) |
| Google Client ID / Secret | Variable d'environnement (`.env`, non versionné) |
| Tokens de session | Cookie `httpOnly` + `secure`, côté serveur |
| Fichiers markdown de doc (`schema.md`, etc.) | Aucune valeur sensible — structure et logique seulement |
