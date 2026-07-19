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
- Setup requis : projet Google Cloud, credentials OAuth, intégration frontend + backend (quelques heures de dev). ✅ Fait (2026-07-18).
- **Librairies** : `django-allauth` (gère l'échange OAuth avec Google) + `dj-rest-auth`
  (expose des endpoints DRF — utilisateur courant, logout — pour le frontend Vue).
- **Flux retenu** : flux "classique" côté serveur, pas de token/JWT ni de Google
  Identity Services côté client. Le frontend redirige le navigateur vers
  `/accounts/google/login/` ; Google redirige vers le callback allauth
  (`/accounts/google/login/callback/`, URI enregistrée telle quelle dans Google
  Cloud pour le domaine local et Railway) ; allauth crée une session Django
  (cookie), consommée ensuite par le frontend via `/api/auth/user/` et
  `/api/auth/logout/` (dj-rest-auth), avec `CORS_ALLOW_CREDENTIALS=True`.
- **Accès restreint côté Google** : le projet Google Cloud reste en mode
  "Testing" — seuls les comptes ajoutés comme "test users" peuvent compléter le
  flux OAuth. Première barrière d'accès, avant même la logique applicative.
- **Provisioning du compte applicatif** : au premier login Google réussi d'un
  compte, un signal (`allauth.account.signals.user_logged_in`, branché dans
  `backend/inventory/signals.py`) crée automatiquement l'`inventory.User`
  correspondant (email/nom depuis le profil Google), avec `role='viewer'` par
  défaut. Samuel promeut ensuite manuellement certains comptes en `role='admin'`
  via `/admin/`. Le lien technique entre `inventory.User` et le
  `django.contrib.auth.User` créé par allauth se fait via le champ nullable
  `users.django_user_id` (voir `schema.md`) — ce lien est distinct du
  superutilisateur Django (`/admin/login/`), qui n'est pas concerné par ce flux.

## 4. Logique centrale — Détection de conflits

C'est le cœur fonctionnel de l'application (implémenté dans `backend/inventory/conflicts.py`, exposé via les serializers DRF `ShowMaterialSerializer`/`ShowTechnicianSerializer`). Deux types de conflits à valider :

### a) Conflits de matériel
Quand un matériel est assigné à un spectacle (`show_materials`), le système calcule la **fenêtre effective** :
```
fenêtre = [start_datetime - buffer_before, end_datetime + buffer_after]
```
Le système vérifie que cette fenêtre ne chevauche aucune autre fenêtre existante pour le **même matériel** (ou un parent/enfant lié, recherché récursivement dans la hiérarchie) sur un autre spectacle.

**Quantité et capacité partagée (décision du 2026-07-19)** : pour du matériel possédé en plusieurs exemplaires identiques (`materials.quantity`, ex. 20 rallonges électriques), la règle ci-dessus n'est plus binaire pour le matériel exact demandé — c'est une capacité partagée. `get_material_conflicts` additionne les `quantity` déjà assignées sur des fenêtres qui chevauchent celle du nouveau spectacle, et ne bloque que si le total dépasserait `materials.quantity`. Deux mécanismes coexistent :
- Matériel parent/enfant (hiérarchie kit) : reste vérifié en mode binaire — ces matériels doivent obligatoirement rester à `quantity = 1` (voir `MaterialSerializer.validate()`), la notion de capacité partagée n'a de sens que pour un matériel autonome.
- Matériel exact (même `material_id`) : capacité partagée comme décrit ci-dessus. Un matériel « normal » à `quantity = 1` retombe naturellement sur le comportement binaire d'origine (toute assignation existante qui chevauche épuise déjà la seule unité disponible).

Demander plus de `quantity` que ce qui est possédé au total (`materials.quantity`) est rejeté d'emblée par `ShowMaterialSerializer.validate()`, **avant même** de regarder les chevauchements — et ce cas précis n'est pas overridable par `force` (erreur de données, pas un arbitrage de planning). Un dépassement dû à un chevauchement réel, lui, reste bloquant avec possibilité de forcer via `force: true`, comme les autres conflits.

### b) Conflits de techniciens
Même logique : un technicien ne peut pas être assigné (`show_technicians`) à deux spectacles dont les fenêtres effectives se chevauchent.

### c) Conflits de déplacement (décision du 2026-07-18)
Un technicien assigné à un `transport` (livraison/ramassage, fenêtre = `[scheduled_datetime, scheduled_datetime + estimated_duration_minutes]`) est vérifié contre **les deux** types d'engagement à la fois : ses autres `transports`, ET ses assignations `show_technicians`. Concrètement : un technicien ne peut pas être en train de livrer du matériel au moment où il est censé être sur un spectacle (et vice-versa) — `get_technician_conflicts` (assignation à un show) et `get_transport_conflicts` (assignation à un transport) croisent désormais l'une contre l'autre (voir `conflicts.py`, `_technician_commitments`). Cette vérification ne bénéficie PAS de l'exemption d'entreposage (point suivant) : un déplacement est toujours un vrai engagement de temps pour le technicien qui le fait, contrairement au matériel qui dort en entrepôt.

### Comportement bloquant + override (décision du 2026-07-17)
Si chevauchement détecté → l'API refuse l'assignation (`400`) et retourne le détail des conflits. Ajouter `"force": true` dans la requête force l'assignation malgré le conflit. `GET /api/shows/{id}/conflicts/` liste les chevauchements actuellement en place sur un spectacle (utile pour repérer après coup les assignations faites avec `force: true`).

### Exemption d'entreposage (décision du 2026-07-18)
Un `venue` peut être marqué `is_storage = true` (un entrepôt, pas un vrai lieu de spectacle). Un `show` rattaché à un tel `venue` (convention : `event_type = 'storage'`) est **entièrement ignoré** par la détection de conflit **matériel** : assigner du matériel à un entrepôt ne bloque jamais, et une assignation existante à un entrepôt ne compte jamais comme conflit pour un vrai spectacle ailleurs — le matériel rangé est considéré disponible. Cette exemption ne s'applique qu'au matériel ; un technicien assigné à un `show` d'entrepôt (ex. pour de l'inventaire) reste soumis à la détection normale, puisque ça représente un vrai engagement de temps pour lui.

### Buffers
Par défaut, 1h avant et 1h après chaque événement (répétition ou représentation), pour couvrir le transport et l'installation/désinstallation du matériel. Configurable par spectacle si besoin — et depuis le 2026-07-18, ce "par défaut" lui-même est configurable globalement via `settings.default_buffer_before_minutes`/`default_buffer_after_minutes` (voir section 4bis), plutôt que codé en dur.

## 4bis. Réglages globaux (`settings`, décision du 2026-07-18)

Table singleton (une seule ligne, voir `schema.md` section 10) exposée en lecture/écriture sur `GET`/`PATCH /api/settings/` (`SettingsView`, pas de liste ni de création — toujours la même ligne, créée automatiquement avec des valeurs par défaut si absente). Objectif : donner à une future page de réglages du frontend Vue le contrôle sur des valeurs jusqu'ici codées en dur, sans redéploiement backend.

- `default_buffer_before_minutes`/`default_buffer_after_minutes` : valeur proposée à la création d'un `Show` — lue dynamiquement par un callable Django (`models._default_buffer_before_minutes` etc.), pas une constante Python.
- `default_transport_duration_minutes` : idem pour `Transport.estimated_duration_minutes`, utilisé seulement si l'estimation automatique Google Routes (section 4ter) échoue ou n'est pas configurée.
- `date_format`/`time_format` : préférences d'affichage pour le frontend (pas encore consommées, le frontend n'étant pas branché — mais déjà en place côté API).

## 4ter. Calcul du temps de trajet (Google Routes API, décision du 2026-07-18)

Samuel a demandé si géolocaliser les lieux pour calculer automatiquement les temps de trajet valait la peine. Réponse : oui à ce volume d'usage, le coût n'est pas un frein (l'API Google Routes offre 10 000 requêtes gratuites/mois pour le tier "Essentials" — largement suffisant), mais ça demande un compte Google Cloud avec facturation activée et une clé API à gérer comme un secret.

- `venues.latitude`/`longitude` (nullables, saisie manuelle — pas de géocodage automatique d'adresse pour l'instant) permettent de localiser un lieu.
- `inventory/maps.py` (`estimate_travel_minutes`) appelle l'API Google Routes ("Compute Routes" — un trajet simple, cohérent avec le fait qu'un `Transport` a toujours une origine et une destination uniques) pour estimer la durée du trajet entre deux venues.
- `TransportSerializer` appelle cette fonction automatiquement à la création d'un `Transport`, seulement si le client n'a pas fourni `estimated_duration_minutes` explicitement et que les deux venues ont des coordonnées. Le résultat est utilisé directement, y compris pour la détection de conflit du technicien assigné.
- Dégradation silencieuse à chaque étape : pas de clé API configurée, coordonnées manquantes, erreur réseau/quota → retombe sur `settings.default_transport_duration_minutes`, jamais d'erreur ni de blocage.
- **Étapes manuelles restantes côté Samuel** (voir aussi `inventory/maps.py` et `security.md`) : créer/choisir un projet Google Cloud, activer la facturation, activer "Routes API", créer une clé API restreinte à cette API, puis l'ajouter comme `GOOGLE_MAPS_API_KEY` dans les Variables Railway (et `backend/.env` en local, voir `.env.example`). Tant que ce n'est pas fait, l'app fonctionne normalement, juste sans l'auto-estimation.

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
4. Chaque département a une couleur d'identification (`departments.color`) réglable, exposée dans l'API via `department_color` sur le matériel et les assignations show/matériel (voir `schema.md`, section 3) — le frontend (une fois branché) l'utilisera pour coder visuellement les listes et plannings par département.

### Workflow 3 — Suivi des besoins de location
1. Lors de l'assignation de matériel à un spectacle, si le matériel n'existe pas encore dans l'inventaire ou doit être loué, l'ajouter comme entrée dans `materials` avec `ownership_status = rental` (ou simplement cocher `is_rental` dans `show_materials` si le matériel de base existe déjà mais que cette instance-là est louée).
2. Les démarches de location (contact vendor, confirmation, etc.) se font **hors application**, par courriel. Un futur module d'automatisation (Claude / scripts) pourra pré-remplir ces courriels à partir des données du spectacle — **hors scope actuel**, prévu comme étape future.

### Workflow 4 — Tracer le passage en entreposage
1. Créer (une fois) un `venue` avec `is_storage = true` pour chaque entrepôt physique.
2. Créer un `show` sur ce venue (convention : `event_type = 'storage'`) pour la période où le matériel y est rangé, puis y assigner le matériel via `show_materials` — comme pour un vrai spectacle, mais sans jamais déclencher de conflit (voir section 4).

### Workflow 5 — Planifier une livraison ou un ramassage
1. Depuis la fiche spectacle, créer un `transport` : type (livraison/ramassage), lieu de départ, lieu d'arrivée, heure prévue. La durée estimée peut être laissée vide : si les deux lieux ont des coordonnées GPS, elle est calculée automatiquement (Google Routes) ; sinon elle prend la valeur par défaut des réglages.
2. Assigner (ou laisser vide pour l'instant) le technicien qui s'en charge — le système valide en temps réel qu'il n'est pas déjà engagé (spectacle ou autre déplacement) sur cette fenêtre.
3. `GET /api/shows/{id}/conflicts/` inclut les déplacements dans les conflits techniciens listés, aux côtés des assignations `show_technicians`.

### Workflow 6 — Ajuster les réglages globaux
1. `GET /api/settings/` pour consulter les valeurs actuelles (buffers par défaut, durée de transport par défaut, format de date/heure).
2. `PATCH /api/settings/` avec les champs à changer — s'applique immédiatement aux prochaines fiches créées (pas de redéploiement, pas d'effet rétroactif sur les fiches existantes).

## 6. Explicitement hors scope (validé avec Samuel)

- Portail ou module de communication bidirectionnelle avec les vendors (reste par courriel).
- Table de tâches ou de notes de suivi dans l'app.
- Historique des changements d'assignation (seules les données actuelles sont conservées).
- Budget de location (prévu comme étape future, une fois le système de base en place).

## 7. Étapes futures (non incluses dans la V1)

- Génération automatisée de courriels de demande de location (via Claude ou script), pré-remplis avec les infos du spectacle.
- Module de budget de location attaché aux spectacles.
- Rôles utilisateurs plus granulaires si l'équipe grandit.
