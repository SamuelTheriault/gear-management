# Récapitulatif — RégiStock (application de gestion de matériel)

## Objectif du projet

Application web interne pour gérer l'inventaire de matériel de production (son, éclairage, rigging, mobilier, etc.), l'assigner aux spectacles et répétitions selon leurs horaires, assigner les techniciens, et détecter automatiquement les conflits d'utilisation — matériel comme techniciens.

## Ce que l'application fait (V1)

- **Inventaire de matériel** : chaque item a un nom, une description, une catégorie (type d'usage), un statut (propriété ou location générale), un lieu d'entreposage, un département responsable (voir ci-dessous), une quantité totale possédée (`quantity`, défaut 1 — permet du matériel identique en plusieurs exemplaires, ex. 20 rallonges électriques, sans créer un item par unité), et peut être organisé en hiérarchie parent/enfant (ex. "Kit Audio" → "Micro sans fil", "Ampli", "Haut-parleurs") — un matériel en hiérarchie doit rester à `quantity = 1`.
- **Départements (`departments`)** : table avec nom du département, contact responsable, et une couleur d'identification (`color`, code hex #RRGGBB) — associée à chaque matériel, permet de savoir qui doit apporter quoi sur le lieu du spectacle. La couleur est reflétée dans les sous-sections où le département apparaît (matériel, assignations show/matériel) via `department_color` dans l'API, pour un code couleur cohérent dans tout le planning une fois le frontend branché.
- **Lieux (`venues`)** : table dédiée pour centraliser adresses et contacts des salles/sites, référencée par les spectacles et le matériel. Un lieu peut être marqué `is_storage` (entrepôt) — voir note dédiée plus bas. Coordonnées GPS optionnelles (`latitude`/`longitude`) pour le calcul automatique de temps de trajet — voir note "Google Maps".
- **Fiches spectacles (`shows`)** : titre, lieu, type (répétition/représentation), horaires. Une fenêtre effective d'utilisation est calculée automatiquement en ajoutant 1h avant et 1h après (buffers configurables) pour couvrir le transport et l'installation.
- **Assignation de matériel** (`show_materials`) : associer du matériel de l'inventaire à un spectacle, avec une quantité (`quantity`, défaut 1 — ex. assigner 5 des 20 rallonges en inventaire) et possibilité d'indiquer si ce matériel est loué spécifiquement pour ce spectacle (`is_rental` + `rental_vendor`).
- **Techniciens** (`technicians`) et leur assignation aux spectacles (`show_technicians`).
- **Déplacements (`transports`)** : livraison/ramassage de matériel entre deux lieux pour un spectacle donné, avec heure prévue, durée estimée et technicien assigné — voir note dédiée plus bas.
- **Détection de conflits** : le système vérifie automatiquement, pour le matériel comme pour les techniciens, qu'il n'y a pas de chevauchement entre les fenêtres effectives de deux spectacles différents — et, depuis l'ajout de `transports`, qu'un technicien n'est pas sur un spectacle en même temps qu'il fait un déplacement.
- **Listes par technicien** : possibilité de sortir une liste de matériel et d'horaire propre à chaque technicien, utile sur le terrain.
- **Authentification** : login via Google OAuth (pas de gestion de mot de passe custom), avec rôles admin / viewer.
- **Réglages globaux (`settings`)** : buffers par défaut, durée de transport par défaut, format d'affichage des dates/heures — ajustables via l'API sans redéploiement, en prévision d'une page de réglages côté frontend. Voir note dédiée plus bas.
- **Productions (`projects`)** : Samuel travaille en parallèle sur plusieurs productions sans rien en commun (compagnies de danse, musées, biennales) — `venues`, `materials`, `technicians` et `shows` sont isolés par production, `departments` et `settings` restent communs à toutes. Bascule d'une production à l'autre entièrement côté frontend (à venir), sans recharger/exporter de fichier. Voir note dédiée plus bas.
- **Duplication de projet** (`POST /api/projects/{id}/duplicate/`) : démarrer une nouvelle édition d'un mandat (ex. Furies 2027 après Furies 2026) en copiant lieux/matériel/techniciens de l'édition précédente, sans copier ni spectacles ni assignations — le calendrier repart vierge. Voir note dédiée plus bas.

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

`users` · `venues` · `departments` · `materials` (avec hiérarchie parent/enfant + catégorie + département responsable) · `shows` · `show_materials` · `technicians` · `show_technicians` · `transports` (ajoutée le 2026-07-18) · `settings` (singleton, ajoutée le 2026-07-18) · `projects` (ajoutée le 2026-07-19 — isole `venues`/`materials`/`technicians`/`shows`) · `transport_materials` (liaison transport↔matériel, ajoutée le 2026-07-24 — alimente le module de cohérence des emplacements)

Détails complets des champs → voir `schema.md`.

## Prochaines étapes suggérées

1. ~~Base de données confirmée : MySQL 8.0.~~ ✅
2. ~~Stack backend/frontend confirmée (Django + Vue).~~ ✅ (2026-07-16)
3. ~~Structure de repo initiale (backend Django + frontend Vue scaffoldés, Git init).~~ ✅ (2026-07-16)
4. ~~Hébergement confirmé : Railway (Ionos écarté pour l'app, CGI seulement).~~ ✅ (2026-07-17)
5. ~~Compte/projet Railway créé, repo connecté, MySQL managé provisionné, déploiement fonctionnel (Django + Gunicorn + WhiteNoise, `/admin/login/` accessible en HTTPS).~~ ✅ (2026-07-18) — domaine : `gear-management-production.up.railway.app`
6. ~~Créer un superutilisateur Django pour valider l'accès admin.~~ ✅ (2026-07-18) — validé local (venv) et Railway (`railway run`).
7. ~~Mettre en place le projet Google Cloud pour l'OAuth + intégration Django.~~ ✅ (2026-07-18) — voir note ci-dessous
8. ~~Modèles Django + migrations pour les 8 tables de `schema.md`.~~ ✅ (2026-07-17) — voir note ci-dessous
9. ~~Squelette API (endpoints) + logique de détection de conflits.~~ ✅ (2026-07-17) — voir note ci-dessous
10. ~~Couleur d'identification par département (`Department.color`).~~ ✅ (2026-07-18) — voir note ci-dessous
11. ~~Quantité de matériel (`Material.quantity` / `ShowMaterial.quantity`).~~ ✅ (2026-07-19) — voir note ci-dessous
12. ~~Matériel désactivable (`Material.is_active`).~~ ✅ (2026-07-19) — voir note ci-dessous
13. ~~Isolation par projet (`Project`) pour travailler sur plusieurs productions en parallèle.~~ ✅ (2026-07-19) — voir note ci-dessous
14. ~~Duplication de projet (`POST /api/projects/{id}/duplicate/`) pour démarrer une nouvelle édition d'un mandat.~~ ✅ (2026-07-19) — voir note ci-dessous
15. ~~Code court par lieu (`Venue.code`).~~ ✅ (2026-07-19) — voir note ci-dessous

### Notes de déploiement (piège à retenir)

Railway ne supporte pas la phase `release:` du `Procfile` (style Heroku) — `collectstatic`
et `migrate` doivent tourner dans la commande `web:` elle-même (voir `backend/Procfile`),
sinon les fichiers statiques et les migrations ne s'appliquent jamais en production.

### Note sur le modèle `User` (étape 8, lien complété à l'étape 7)

Le modèle `inventory.User` (table `users`, champs email/name/role/created_at) est un
modèle applicatif distinct du superutilisateur Django (`django.contrib.auth.models.User`)
qui sert à `/admin/login/`. Ce dernier reste inchangé. Depuis l'étape 7, `inventory.User`
porte un champ `django_user` (nullable) qui le relie au compte Django créé par
django-allauth lors du premier login Google réussi — voir `architecture.md` section 3
et `schema.md` pour le détail. Le provisioning (création automatique, rôle `viewer` par
défaut) est géré par un signal (`backend/inventory/signals.py`), couvert par 4 tests
unitaires.

### Note sur l'étape 7 (Google Cloud OAuth)

- Librairies : `django-allauth` + `dj-rest-auth`, flux "classique" côté serveur
  (session cookie Django, pas de JWT/token) — détail complet dans `architecture.md`
  section 3.
- Projet Google Cloud en mode "Testing" (liste de test users = première barrière
  d'accès, pas de vérification Google requise pour un usage interne).
- Revue de code faite (`code-reviewer`) : tests verts (19/19), flake8 propre, aucun
  secret en dur. Deux corrections apportées suite à la revue : `DEBUG` par défaut
  passé à `False` (au lieu de `True`) pour ne pas affaiblir silencieusement
  `SESSION_COOKIE_SECURE`/`CSRF_COOKIE_SECURE` si la variable Railway est oubliée, et
  documentation du flux OAuth ajoutée dans `architecture.md` (référence qui manquait
  depuis `schema.md`).
- **Pas encore testé de bout en bout dans un vrai navigateur** — ça se fera à l'étape
  10, en même temps que le branchement du bouton de login côté Vue.

### Note sur la logique de conflits (étape 9)

- API DRF complète (`/api/<ressource>/`) pour les 8 modèles, montée dans
  `config/urls.py`. Authentification : `IsAuthenticated` (défaut DRF), testable
  dès maintenant via la session admin existante (`/api-auth/login/`) — pas
  besoin d'attendre l'OAuth Google pour commencer à utiliser l'API.
- Détection de conflits (`inventory/conflicts.py`) : fenêtre effective
  (buffers), hiérarchie parent/enfant du matériel (récursive), chevauchement
  strict (deux fenêtres qui se touchent pile à la limite ne sont pas en
  conflit).
- Comportement choisi avec Samuel (2026-07-17) : **bloquant avec override**.
  L'API refuse (400) une assignation (`show-materials`, `show-technicians`) en
  conflit, et retourne le détail des conflits. Ajouter `"force": true` dans la
  requête force l'assignation malgré le conflit.
- `GET /api/shows/{id}/conflicts/` liste les chevauchements actuellement en
  place sur un spectacle (utile pour repérer après coup les assignations
  faites avec `force: true`).
- 15 tests unitaires (`inventory/tests.py`) couvrent la logique de conflit et
  le comportement bloquant/override de l'API — tous passent.

### Note sur l'entreposage (2026-07-18)

- Besoin exprimé par Samuel : un emplacement d'entreposage (entrepôt), où le
  matériel est "disponible" et ne doit jamais entrer en conflit avec les
  autres lieux/spectacles.
- Décision (parmi 3 options proposées) : réutiliser `Show`/`show_materials`
  tel quel plutôt que créer une nouvelle table. Ajout d'un champ
  `Venue.is_storage` (booléen) ; convention `event_type = 'storage'` sur
  `Show` pour l'étiquette (voir `schema.md` section 2 et 5).
- Effet sur `conflicts.py` : un `Show` dont le `venue.is_storage = true` est
  totalement ignoré par la détection de conflit **matériel**, dans les deux
  sens (assigner à l'entrepôt ne bloque jamais ; une assignation existante à
  l'entrepôt ne bloque jamais un vrai spectacle ailleurs). Les techniciens
  restent soumis à la détection normale même sur un `Show` d'entrepôt (voir
  `architecture.md` section 4).
- 8 nouveaux tests (4 sur l'exemption d'entreposage + non-régression sur les
  conflits réels) — suite complète à 23 tests, tous passent.
- **Bug pré-existant découvert et corrigé au passage** : `requirements.txt`
  ne listait pas `requests`/`PyJWT`/`cryptography`, requis dès le démarrage
  de Django par le provider Google de `django-allauth`
  (`SocialAccountConfig.ready()` importe le provider même sans requête réelle).
  Sans ce correctif, tout déploiement Railway aurait planté immédiatement
  (`ModuleNotFoundError`) — à vérifier au prochain déploiement.

### Note sur les déplacements (2026-07-18)

- Besoin exprimé par Samuel : savoir quand le matériel est livré/ramassé vers
  un lieu de spectacle, et quel technicien s'en charge — rien de tout ça
  n'existait dans les 8 tables initiales.
- Décision (parmi 3 options proposées) : nouvelle table dédiée `transports`
  (show, type livraison/ramassage, lieu de départ, lieu d'arrivée, heure
  prévue, durée estimée, technicien nullable) plutôt que des champs sur `Show`
  ou que de traiter un déplacement comme un `Show` à part entière — voir
  `schema.md` section 9.
- Un technicien assigné à un `transport` est désormais croisé, dans les deux
  sens, avec ses assignations `show_technicians` : impossible de le mettre sur
  un spectacle ET un déplacement qui se chevauchent (voir `conflicts.py`,
  `_technician_commitments`, et `architecture.md` section 4c). Comportement
  bloquant + `force: true`, identique aux autres assignations.
- Pas d'exemption d'entreposage ici : contrairement au matériel qui dort en
  entrepôt, un déplacement est toujours un vrai engagement de temps pour le
  technicien qui le fait.
- 8 nouveaux tests (logique + API) — suite complète à 31 tests, tous passent.
  flake8 propre.

### Note sur les réglages globaux et le calcul de trajet (2026-07-18)

- Samuel a demandé (1) une page de réglages pour ajuster des variables comme
  les buffers par défaut et le format des dates, et (2) si géolocaliser les
  lieux pour calculer automatiquement les temps de trajet valait la peine.
- **Réglages** : nouvelle table singleton `settings` (une seule ligne,
  forcée par le modèle) — `default_buffer_before_minutes`,
  `default_buffer_after_minutes`, `default_transport_duration_minutes`,
  `date_format`, `time_format` (champs choisis par Samuel parmi une liste
  proposée ; "langue de l'interface" a été proposée mais pas retenue).
  Exposée sur `GET`/`PATCH /api/settings/`. Les valeurs par défaut de `Show`
  et `Transport` sont maintenant lues dynamiquement depuis cette table
  (callables Django) plutôt que codées en dur à 60 minutes — voir
  `architecture.md` section 4bis. La vraie "page" de réglages viendra avec le
  frontend Vue (pas encore branché) ; le backend est prêt dès maintenant.
- **Calcul de trajet** : recommandation donnée avec chiffres à l'appui —
  l'API Google Routes ("Compute Routes", un trajet simple) offre 10 000
  requêtes gratuites/mois, largement suffisant à ce volume d'usage ; le vrai
  coût est la mise en place (compte Google Cloud + facturation + clé API),
  pas l'argent. Samuel a choisi d'implémenter maintenant plutôt que la
  version "coordonnées seulement, sans appel API".
  - `venues.latitude`/`longitude` (saisie manuelle, pas de géocodage
    automatique d'adresse pour l'instant).
  - `inventory/maps.py` appelle l'API et retourne `None` silencieusement
    (avec un log) si la clé API est absente, les coordonnées manquantes, ou
    l'appel en échec — fallback sur `settings.default_transport_duration_minutes`.
  - `TransportSerializer` appelle cette estimation automatiquement à la
    création, seulement si le client ne fournit pas `estimated_duration_minutes`.
  - **Étapes manuelles restantes côté Samuel, à faire avant que ça
    fonctionne réellement** : créer/choisir un projet Google Cloud, activer
    la facturation (carte enregistrée, mais le tier gratuit couvre l'usage
    prévu), activer "Routes API", créer une clé API restreinte à cette API,
    puis l'ajouter comme `GOOGLE_MAPS_API_KEY` dans les Variables Railway (et
    `backend/.env` en local — voir `.env.example`). Tant que ce n'est pas
    fait, l'app fonctionne normalement, juste sans l'auto-estimation.
- **Bug de config découvert et corrigé au passage** : `backend/.env.example`
  existait déjà mais ne documentait pas encore `GOOGLE_MAPS_API_KEY` — ajouté,
  ainsi que la section correspondante dans `security.md`.
- 17 nouveaux tests (`inventory/test_settings_and_maps.py` — singleton,
  defaults dynamiques, service maps mocké, auto-estimation, endpoint
  settings) — suite complète à 48 tests, tous passent. flake8 propre.

### Note sur la couleur d'identification par département (étape 10)

- Besoin exprimé par Samuel : associer une couleur à chaque département
  depuis les réglages, pour repérer visuellement le matériel/les
  assignations par département dans l'app une fois le frontend branché.
- `Department.color` (hex `#RRGGBB`, validé par regex, défaut `#64748B`) —
  reflétée en lecture seule via `department_color` sur `MaterialSerializer`
  et `ShowMaterialSerializer`, sans requête supplémentaire côté frontend.
  Aperçu visuel ajouté dans l'admin Django (pastille de couleur).
- Revue de code faite : lint propre, validation confirmée à la fois côté
  modèle (`full_clean`) et côté API (DRF propage automatiquement le
  validator du modèle) — testé en conditions réelles (POST invalide → 400
  avec message français). Suggestion non bloquante notée : ajouter un test
  automatisé pour ce rejet côté API (actuellement vérifié manuellement,
  seul le rejet côté modèle est couvert par la suite de tests).
- Développée en parallèle de l'étape 7bis (OAuth) et de l'ajout
  entreposage/transports/réglages — fusionnée avec `main` après coup,
  conflits limités à des imports/emplacements de code (aucune divergence
  fonctionnelle réelle).

### Note sur la quantité de matériel (étape 11, 2026-07-19)

- Besoin exprimé par Samuel : du matériel identique possédé en plusieurs
  exemplaires (ex. 20 rallonges électriques) sans avoir à créer un item par
  unité physique pour pouvoir en assigner une partie (ex. 5) à un spectacle.
- Décision (options proposées et validées avec Samuel) : `Material.quantity`
  (quantité totale possédée, défaut 1) et `ShowMaterial.quantity` (quantité
  assignée à ce spectacle, défaut 1) — plutôt que de dupliquer des items.
  Un matériel qui participe à une hiérarchie kit (parent/enfant) doit rester
  à `quantity = 1` : un kit reste une unité conceptuelle unique, la capacité
  partagée n'a de sens que pour du matériel autonome. Un dépassement de
  capacité dû à un chevauchement d'horaire reste bloquant avec possibilité de
  forcer via `force: true`, cohérent avec les autres conflits.
- Effet sur `conflicts.py` (`get_material_conflicts`) : la vérification pour
  le matériel exact demandé est passée d'un chevauchement binaire à une
  capacité partagée (somme des quantités déjà assignées sur des fenêtres qui
  chevauchent, comparée à `Material.quantity`) — voir `architecture.md`
  section 4a. La propagation binaire parent/enfant reste inchangée.
- Demander plus que `Material.quantity` au total (même sans aucun
  chevauchement) est rejeté d'emblée par `ShowMaterialSerializer.validate()`
  et n'est **pas** overridable par `force` — erreur de données, pas un
  arbitrage de planning.
- 13 nouveaux tests (capacité, hiérarchie, API, non-régression du
  comportement binaire pour `quantity = 1`) — suite complète à 70 tests, tous
  passent. flake8 propre.

### Note sur le matériel désactivable (étape 12, 2026-07-19)

- Besoin exprimé par Samuel, après avoir exploré puis abandonné une piste
  plus complexe (un lieu "Magasin" immuable + suivi automatique du lieu
  actuel du matériel — jugée trop compliquée pour la valeur ajoutée) : juste
  pouvoir désactiver un matériel qu'il n'utilise plus (ex. un vieux rideau)
  sans le supprimer, pour ne plus l'avoir dans son inventaire courant.
- `Material.is_active` (booléen, défaut `true`). `GET /api/materials/` ne
  retourne que le matériel actif par défaut ; `?include_inactive=true` pour
  tout revoir. La consultation par id (`GET /api/materials/{id}/`) reste
  toujours accessible peu importe le statut, pour ne pas casser l'affichage
  des assignations existantes qui référencent un matériel entretemps
  désactivé.
- Admin Django : colonne + filtre `is_active`, actions groupées "Activer"/
  "Désactiver" sur plusieurs items à la fois.
- Confirmé au passage avec Samuel : la protection contre le double-usage
  reste entièrement basée sur le calendrier (fenêtres effectives des
  `shows`, voir `architecture.md` section 4) — ce point n'est pas affecté
  par `is_active`, qui ne fait que masquer de l'affichage, sans toucher à la
  détection de conflits.
- 4 nouveaux tests — suite complète à 74 tests, tous passent. flake8 propre.

### Note sur l'isolation par projet (étape 13, 2026-07-19)

- Besoin exprimé par Samuel : pouvoir travailler sur différents projets (des
  productions n'ayant rien en commun entre elles — différentes compagnies de
  danse, musées, biennales comme CINARS/Parcours Danse/Furies) et basculer de
  l'un à l'autre sans avoir à charger/sauvegarder un fichier à chaque fois.
- Clarifié avec Samuel avant de toucher au schéma (changement structurant
  touchant presque toutes les tables) : un « projet » = une production
  précise (pas une compagnie/client au sens large) ; seuls les `departments`
  restent communs à tous les projets (Samuel a explicitement choisi de NE PAS
  partager le matériel ni les techniciens entre projets, malgré la tentation
  évidente pour son propre inventoire personnel) ; pas de vue « tous projets
  confondus » pour l'instant ; aucune vraie donnée n'existait encore en prod,
  donc migration directe sans backfill.
- Nouveau modèle `Project` (nom, client, statut actif/archivé, dates, notes) —
  singleton non requis, autant de projets que nécessaire. `venue`, `material`,
  `technician` et `show` portent chacun un FK `project` obligatoire
  (`on_delete=PROTECT`) — voir `schema.md` section 11 et `architecture.md`
  section 4quater.
- Validation bloquante ajoutée aux serializers concernés (`_same_project()`)
  pour empêcher tout mélange entre deux projets : matériel/technicien d'un
  autre projet assigné à un spectacle, lieu d'un autre projet sur un
  spectacle ou un déplacement, matériel parent ou lieu d'entreposage d'un
  autre projet.
- Filtrage optionnel `?project=<id>` ajouté aux listes concernées
  (`ProjectFilteredMixin`) — pas obligatoire pour ne pas casser l'accès API
  brut, mais prévu pour être systématiquement utilisé par le frontend une
  fois branché.
- Suppression d'un projet bloquée tant qu'il lui reste des données
  (`PROTECT`) — la voie normale pour retirer une production terminée est de
  l'archiver (`status='archived'`), pas de la supprimer.
- Développée sur une branche dédiée (`feature/production-scoping`), après
  avoir d'abord fait merger deux petites branches en attente
  (`feature/department-colors`, `feature/material-quantity`) pour partir
  d'une base propre — recommandation faite et suivie avant de commencer un
  changement aussi structurant.
- 13 nouveaux tests (isolation, filtrage, blocage cross-projet, département
  resté global, suppression protégée) — suite complète à 87 tests, tous
  passent. flake8 propre.

### Note sur la duplication de projet (étape 14, 2026-07-19)

- Besoin exprimé par Samuel : pouvoir copier un projet vers un nouveau projet
  pour démarrer une nouvelle édition d'un mandat (ex. une nouvelle année de
  Furies), sans repartir de zéro sur le matériel/les lieux/les techniciens,
  mais SANS traîner le calendrier de l'édition précédente.
- Vérification faite avant de coder (demandée par Samuel) : sur les 11
  modèles de l'app, seuls `Venue`, `Material` et `Technician` sont scopés par
  projet en plus de `Show` — `Department`/`Settings`/`User` sont globaux (rien
  à copier), et `ShowMaterial`/`ShowTechnician`/`Transport` sont des
  assignations rattachées à `Show`, explicitement exclues. La liste proposée
  par Samuel (matériel, lieux, techniciens) était donc déjà complète.
- Décision sur les champs du nouveau projet (clarifiée avec Samuel) :
  `client_name` repris du projet source par défaut (surchargeable) — une
  nouvelle édition, c'est généralement le même client. `notes`,
  `start_date`/`end_date` et `status` repartent à leurs valeurs par défaut
  (`status='active'`), quel que soit l'état du projet source — spécifiques à
  chaque édition, jamais hérités.
- `POST /api/projects/{id}/duplicate/` (`inventory/duplication.py`) : copie
  atomique (tout ou rien) des lieux, du matériel (hiérarchie parent/enfant
  remappée vers les nouvelles lignes créées, pas vers celles du projet
  source) et des techniciens vers un nouveau `Project`. `department` sur le
  matériel copié n'est jamais remappé : référentiel commun à tous les
  projets, la copie pointe vers la même ligne que l'original. Réponse :
  `{'project': {...}, 'copied': {'venues': n, 'materials': n, 'technicians': n}}`
  pour confirmation immédiate du volume copié.
- Le projet source n'est jamais modifié par l'opération.
- 11 nouveaux tests (`inventory/tests.py`, `ProjectDuplicationTests` —
  décompte, hiérarchie remappée, venue remappée, département non dupliqué,
  aucune assignation copiée, projet source intact, nom obligatoire) — suite
  complète à 98 tests, tous passent. flake8 propre.

### Note sur le code court par lieu (étape 15, 2026-07-19)

- Besoin exprimé par Samuel : pouvoir inscrire un code court (ex. `CHAP` pour
  la Chapelle) à la création d'un lieu, réutilisable pour afficher le
  départ/arrivée d'un déplacement (`transports`) de façon compacte.
- `Venue.code` (jusqu'à 4 caractères — pas nécessairement exactement 4,
  ex. `MEM` pour le Musée de la santé Armand-Frappier reste valide),
  normalisé en majuscules à l'enregistrement, optionnel. Unicité vérifiée
  par projet (`VenueSerializer`, pas une contrainte en base — sinon
  plusieurs lieux sans code, chaîne vide, entreraient en conflit entre eux).
  Le même code peut être réutilisé dans deux projets différents (productions
  isolées, voir étape 13).
- `TransportSerializer` expose `origin_venue_code`/`destination_venue_code`
  en lecture seule (vide si le lieu concerné n'a pas de code).
- 6 nouveaux tests — suite complète à 104 tests, tous passent. flake8 propre.

### Note sur le module transport — cohérence des emplacements (étape 16, 2026-07-24)

- Besoin exprimé par Samuel : un module qui vérifie (1) que « tout est
  possible sur les emplacements du matériel prévus » et (2) que « tout
  déplacement de matériel est associé à un transport ». Constat de départ :
  `transports` savait *quand*/*où* le matériel bougeait et *quel* technicien
  s'en chargeait, mais pas *quel matériel* montait dans le camion.
- Décision (parmi 2 options proposées) : table de liaison explicite
  `TransportMaterial` (`transport` → `material` + `quantity`), plutôt qu'une
  inférence lieu+horaire — seule façon de détecter un oubli de chargement.
  Écriture imbriquée sur `TransportSerializer.materials`.
- Décision : rapport **non bloquant** (≠ des conflits, bloquants + `force`) —
  `GET /api/shows/{id}/transport-coherence/` et
  `GET /api/projects/{id}/transport-coherence/`.
- Décision : **aller seulement** — on vérifie la présence du matériel là où
  il est requis (livraisons), sans exiger qu'un `pickup` referme la boucle
  vers l'entrepôt.
- `transport_coherence.py` reconstruit une timeline de position par matériel
  (départ = `Material.venue`, transports appliqués à leur `effective_end`) et
  produit trois types d'issue : `materiel_non_livre`, `origine_incoherente`,
  `origine_inconnue`. Exemption d'entreposage respectée.
- 20 nouveaux tests (logique + API imbriquée + endpoints) — suite complète à
  124 tests, tous passent. flake8 (docstrings) propre, `makemigrations
  --check` et `manage.py check` propres. Migration `0011_transportmaterial`.

### Note sur la création des transports — manuelle + génération auto (étape 17, 2026-07-24)

- Deux façons de créer un transport (décidées avec Samuel) : **manuelle**
  (lieux choisis parmi les lieux existants, confirmé d'emblée) et
  **automatique** — l'app détecte le matériel assigné à deux lieux consécutifs
  dans le temps et crée une **proposition** pré-remplie (lieux + matériel), en
  attente de complétion (heure, technicien).
- `Transport.status` (`confirmed`/`to_approve`) + `scheduled_datetime` rendu
  nullable (une proposition n'a pas encore d'heure). Migration
  `0012_transport_status_scheduled_nullable`.
- Décisions Samuel (2026-07-24) : génération **automatique par signaux** (pas
  un bouton) ; **pas de mémoire de rejet** (resync idempotent à chaque
  changement) ; une proposition reste **orange (non résolue)** tant qu'elle
  n'est pas confirmée (exclue de la timeline de position) ; conflit de
  technicien **gardé bloquant + force**, on ajoute juste l'indicateur
  (`has_technician_conflict`).
- `transport_autogen.py` (`regenerate_project_proposals`) : timeline projetée
  par matériel (origines chaînées entrepôt→A puis A→B), groupage par couple
  (origine, spectacle), upsert des propositions (préserve les éditions),
  suppression des obsolètes. `regenerate_signals.py` branche les signaux
  (garde de réentrance). `TransportViewSet` gagne `?status=`/`?show=`.
- 21 nouveaux tests (`TransportAutogenTests` 9, `TransportStatusAPITests` 3,
  + coquilles ajustées) — suite complète à **137 tests** (`tests.py` 113 +
  `test_settings_and_maps.py` 20 + `test_oauth_provisioning.py` 4), tous
  passent. flake8 (docstrings), `makemigrations --check` et `manage.py check`
  propres.

## Fichiers produits

- `schema.md` — structure complète de la base de données
- `architecture.md` — overview technique, logique de conflits, workflows
- `agents_tools.md` — outils/agents par phase (planification, développement, tests, review, documentation)
- `recapitulatif_projet.md` — ce document
