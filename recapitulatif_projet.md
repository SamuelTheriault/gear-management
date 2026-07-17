# Récapitulatif — Application de gestion de matériel

## Objectif du projet

Application web interne pour gérer l'inventaire de matériel de production (son, éclairage, rigging, mobilier, etc.), l'assigner aux spectacles et répétitions selon leurs horaires, assigner les techniciens, et détecter automatiquement les conflits d'utilisation — matériel comme techniciens.

## Ce que l'application fait (V1)

- **Inventaire de matériel** : chaque item a un nom, une description, une catégorie (type d'usage), un statut (propriété ou location générale), un lieu d'entreposage, un département responsable (voir ci-dessous), et peut être organisé en hiérarchie parent/enfant (ex. "Kit Audio" → "Micro sans fil", "Ampli", "Haut-parleurs").
- **Départements (`departments`)** : table avec nom du département et contact responsable, associée à chaque matériel — permet de savoir qui doit apporter quoi sur le lieu du spectacle.
- **Lieux (`venues`)** : table dédiée pour centraliser adresses et contacts des salles/sites, référencée par les spectacles et le matériel.
- **Fiches spectacles (`shows`)** : titre, lieu, type (répétition/représentation), horaires. Une fenêtre effective d'utilisation est calculée automatiquement en ajoutant 1h avant et 1h après (buffers configurables) pour couvrir le transport et l'installation.
- **Assignation de matériel** (`show_materials`) : associer du matériel de l'inventaire à un spectacle, avec possibilité d'indiquer si ce matériel est loué spécifiquement pour ce spectacle (`is_rental` + `rental_vendor`).
- **Techniciens** (`technicians`) et leur assignation aux spectacles (`show_technicians`).
- **Détection de conflits** : le système vérifie automatiquement, pour le matériel comme pour les techniciens, qu'il n'y a pas de chevauchement entre les fenêtres effectives de deux spectacles différents.
- **Listes par technicien** : possibilité de sortir une liste de matériel et d'horaire propre à chaque technicien, utile sur le terrain.
- **Authentification** : login via Google OAuth (pas de gestion de mot de passe custom), avec rôles admin / viewer.

## Ce qui a été volontairement exclu de la V1

| Exclu | Raison |
|---|---|
| Module de communication bidirectionnelle avec les vendors | Géré par courriel, hors app — pourra être automatisé plus tard via Claude |
| Table de tâches / notes internes | Gérées dans un autre outil |
| Historique des changements d'assignation | Seules les données actuelles sont utiles pour Samuel |
| Dates de location générales sur le matériel | La location est toujours ponctuelle et liée à un spectacle précis, pas une propriété générale du matériel |
| Budget de location | Prévu comme étape future, une fois la base en place |

## Stack technique confirmée

- **Base de données** : MySQL 8.0 (confirmé chez Ionos; MariaDB 10 aussi disponible en alternative compatible)
- **Backend** : Python/Django + Django REST Framework — Node.js écarté car l'hébergement web standard Ionos ne supporte pas de runtime Node.js en production (seulement build-time pour du statique, ou via un Cloud Server séparé)
- **Frontend** : Vue 3 (Vite) — choisi pour la simplicité de maintenance en solo plutôt que React
- **Authentification** : Google OAuth 2.0
- **Hébergement** : Railway (PaaS — déploiement Git, MySQL managé) — remplace Ionos pour l'app, après avoir confirmé que l'hébergement web standard Ionos ne fait tourner Python qu'en CGI (voir `info.py`), impraticable pour Django en production. Ionos reste possible pour d'autres usages (domaine, email) si besoin.

## Tables principales

`users` · `venues` · `departments` · `materials` (avec hiérarchie parent/enfant + catégorie + département responsable) · `shows` · `show_materials` · `technicians` · `show_technicians`

Détails complets des champs → voir `schema.md`.

## Prochaines étapes suggérées

1. ~~Base de données confirmée : MySQL 8.0.~~ ✅
2. ~~Stack backend/frontend confirmée (Django + Vue).~~ ✅ (2026-07-16)
3. ~~Structure de repo initiale (backend Django + frontend Vue scaffoldés, Git init).~~ ✅ (2026-07-16)
4. ~~Hébergement confirmé : Railway (Ionos écarté pour l'app, CGI seulement).~~ ✅ (2026-07-17)
5. Créer le compte/projet Railway, connecter le repo Git, provisionner MySQL managé.
6. Mettre en place le projet Google Cloud pour l'OAuth.
7. Modèles Django + migrations pour les 8 tables de `schema.md`.
8. Squelette API (endpoints) + logique de détection de conflits.

## Fichiers produits

- `schema.md` — structure complète de la base de données
- `architecture.md` — overview technique, logique de conflits, workflows
- `agents_tools.md` — outils/agents par phase (planification, développement, tests, review, documentation)
- `recapitulatif_projet.md` — ce document
