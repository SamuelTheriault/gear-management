# Architecture technique — RégiStock

## 1. Vue d'ensemble

Application web interne pour la gestion de l'inventaire de matériel de production, l'assignation de matériel et de techniciens aux spectacles, et la détection automatique de conflits d'horaire. Usage strictement interne (pas de portail vendor, pas de communication externe intégrée).

## 2. Stack technique confirmée

| Couche | Technologie | Justification |
|---|---|---|
| Base de données | MySQL 8.0 (confirmé disponible chez Ionos) | MariaDB 10 aussi disponible en alternative compatible; PostgreSQL non inclus dans le forfait actuel |
| Backend / API | Python (Django) + Django REST Framework | Node.js écarté : l'hébergement web standard Ionos ne supporte pas de runtime Node.js en production (build-time seulement, pour du statique). Django est nativement supporté (offre Python Hosting Ionos). Gère la logique métier et la détection de conflits |
| Frontend | Vue 3 (Vite) | Choisi plutôt que React pour la simplicité de maintenance en solo, hors développement à temps plein |
| Authentification | Google OAuth 2.0 | Plus simple et plus robuste qu'un login maison ; délègue la sécurité des mots de passe à Google |
| Hébergement | Railway (PaaS) | Ionos écarté : l'hébergement web standard ne fait tourner Python qu'en CGI (confirmé via `info.py`), impraticable pour un vrai process Django/Gunicorn persistant. Railway offre déploiement Git automatique et MySQL managé sans gestion serveur (alternative envisagée : VPS Ionos avec gestion manuelle Nginx/Gunicorn/MySQL, écartée pour éviter la charge d'administration système) |

## 3. Authentification

- Login via compte Google (OAuth 2.0) — pas de gestion de mots de passe custom.
- Rôles : `admin` (accès complet), `viewer` (lecture seule) — extensible si besoin plus tard.
- Setup requis : projet Google Cloud, credentials OAuth, intégration frontend + backend (quelques heures de dev).

## 4. Logique centrale — Détection de conflits

C'est le cœur fonctionnel de l'application. Deux types de conflits à valider :

### a) Conflits de matériel
Quand un matériel est assigné à un spectacle (`show_materials`), le système calcule la **fenêtre effective** :
```
fenêtre = [start_datetime - buffer_before, end_datetime + buffer_after]
```
Le système vérifie que cette fenêtre ne chevauche aucune autre fenêtre existante pour le **même matériel** (ou un parent/enfant lié) sur un autre spectacle. Si chevauchement → conflit signalé, l'assignation est bloquée ou avertie.

### b) Conflits de techniciens
Même logique : un technicien ne peut pas être assigné (`show_technicians`) à deux spectacles dont les fenêtres effectives se chevauchent.

### Buffers
Par défaut, 1h avant et 1h après chaque événement (répétition ou représentation), pour couvrir le transport et l'installation/désinstallation du matériel. Configurable par spectacle si besoin.

## 5. Workflows principaux

### Workflow 1 — Créer une fiche spectacle
1. Créer le spectacle (`shows`) : titre, lieu (`venue_id`), type (répétition/représentation), horaires.
2. Le système calcule automatiquement la fenêtre effective (horaire + buffers).
3. Depuis la fiche, sélectionner le matériel requis dans l'inventaire.
4. Le système valide en temps réel s'il y a conflit avec une autre fiche.
5. Si matériel loué spécifiquement pour ce spectacle, cocher `is_rental` et indiquer le `rental_vendor`.
6. Assigner les techniciens requis — même validation de conflit.

### Workflow 2 — Sortir les listes de matériel par technicien ou par département
1. Depuis une fiche spectacle (ou globalement), générer une liste filtrée par technicien assigné.
2. Chaque technicien reçoit/consulte uniquement son propre matériel et son horaire pour le spectacle concerné.
3. Le matériel étant aussi rattaché à un département responsable (`department_id`), on peut aussi générer une liste par département — utile pour savoir qui doit apporter quoi sur le lieu du spectacle, indépendamment de l'assignation technicien.

### Workflow 3 — Suivi des besoins de location
1. Lors de l'assignation de matériel à un spectacle, si le matériel n'existe pas encore dans l'inventaire ou doit être loué, l'ajouter comme entrée dans `materials` avec `ownership_status = rental` (ou simplement cocher `is_rental` dans `show_materials` si le matériel de base existe déjà mais que cette instance-là est louée).
2. Les démarches de location (contact vendor, confirmation, etc.) se font **hors application**, par courriel. Un futur module d'automatisation (Claude / scripts) pourra pré-remplir ces courriels à partir des données du spectacle — **hors scope actuel**, prévu comme étape future.

## 6. Explicitement hors scope (validé avec Samuel)

- Portail ou module de communication bidirectionnelle avec les vendors (reste par courriel).
- Table de tâches ou de notes de suivi dans l'app.
- Historique des changements d'assignation (seules les données actuelles sont conservées).
- Budget de location (prévu comme étape future, une fois le système de base en place).

## 7. Étapes futures (non incluses dans la V1)

- Génération automatisée de courriels de demande de location (via Claude ou script), pré-remplis avec les infos du spectacle.
- Module de budget de location attaché aux spectacles.
- Rôles utilisateurs plus granulaires si l'équipe grandit.
