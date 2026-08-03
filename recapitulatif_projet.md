# Récapitulatif — RégiStock (application de gestion de matériel)

## Objectif du projet

Application web interne pour gérer l'inventaire de matériel de production (son, éclairage, rigging, mobilier, etc.), l'assigner aux spectacles et répétitions selon leurs horaires, assigner les techniciens, et détecter automatiquement les conflits d'utilisation — matériel comme techniciens.

## Ce que l'application fait (V1)

- **Inventaire de matériel** : chaque item a un nom, une description, une catégorie (type d'usage — son, éclairage, rigging, mobilier, etc.), un statut (propriété ou location générale), un lieu d'entreposage, une quantité totale possédée (`quantity`, défaut 1 — permet du matériel identique en plusieurs exemplaires, ex. 20 rallonges électriques, sans créer un item par unité), et peut être organisé en hiérarchie parent/enfant (ex. "Kit Audio" → "Micro sans fil", "Ampli", "Haut-parleurs") — un matériel en hiérarchie doit rester à `quantity = 1`.
- **Lieux (`venues`)** : table dédiée pour centraliser adresses et contacts des salles/sites, référencée par les spectacles et le matériel. Un lieu peut être marqué `is_storage` (entrepôt) — voir note dédiée plus bas. Coordonnées GPS optionnelles (`latitude`/`longitude`) pour le calcul automatique de temps de trajet — voir note "Google Maps".
- **Fiches spectacles (`shows`)** : titre, lieu, type (répétition/représentation), horaires. Une fenêtre effective d'utilisation est calculée automatiquement en ajoutant 1h avant et 1h après (buffers configurables) pour couvrir le transport et l'installation.
- **Assignation de matériel** (`show_materials`) : associer du matériel de l'inventaire à un spectacle, avec une quantité (`quantity`, défaut 1 — ex. assigner 5 des 20 rallonges en inventaire) et possibilité d'indiquer si ce matériel est loué spécifiquement pour ce spectacle (`is_rental` + `rental_vendor`).
- **Techniciens** (`technicians`) et leur assignation aux spectacles (`show_technicians`).
- **Déplacements (`transports`)** : livraison/ramassage de matériel entre deux lieux pour un spectacle donné, avec heure prévue, durée estimée et technicien assigné — voir note dédiée plus bas.
- **Détection de conflits** : le système vérifie automatiquement, pour le matériel comme pour les techniciens, qu'il n'y a pas de chevauchement entre les fenêtres effectives de deux spectacles différents — et, depuis l'ajout de `transports`, qu'un technicien n'est pas sur un spectacle en même temps qu'il fait un déplacement.
- **Listes par technicien** : possibilité de sortir une liste de matériel et d'horaire propre à chaque technicien, utile sur le terrain.
- **Authentification** : login via Google OAuth (pas de gestion de mot de passe custom), avec rôles admin / viewer.
- **Réglages globaux (`settings`)** : buffers par défaut, durée de transport par défaut, format d'affichage des dates/heures — ajustables via l'API sans redéploiement, en prévision d'une page de réglages côté frontend. Voir note dédiée plus bas.
- **Productions (`projects`)** : Samuel travaille en parallèle sur plusieurs productions sans rien en commun (compagnies de danse, musées, biennales) — `venues`, `materials`, `technicians` et `shows` sont isolés par production, `settings` reste commun à toutes. Bascule d'une production à l'autre entièrement côté frontend (à venir), sans recharger/exporter de fichier. Voir note dédiée plus bas.
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

`users` · `venues` · `materials` (avec hiérarchie parent/enfant + catégorie) · `shows` · `show_materials` · `technicians` · `show_technicians` · `transports` (ajoutée le 2026-07-18) · `settings` (singleton, ajoutée le 2026-07-18) · `projects` (ajoutée le 2026-07-19 — isole `venues`/`materials`/`technicians`/`shows`) · `transport_materials` (liaison transport↔matériel, ajoutée le 2026-07-24 — alimente le module de cohérence des emplacements)

`departments` (table avec couleur d'identification par département) a été ajoutée le 2026-07-18 puis **retirée le 2026-07-29** — voir note dédiée plus bas.

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
16. ~~Conflit de lieu entre spectacles.~~ ✅ (2026-07-19) — voir note ci-dessous

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

### Note sur le conflit de lieu (étape 16, 2026-07-19)

- Clarification demandée par Samuel : le matériel et les techniciens ne
  doivent jamais pouvoir être utilisés à deux endroits en même temps, peu
  importe le lieu (déjà le cas — ces vérifications ne tiennent jamais
  compte du lieu). Mais l'inverse manquait : rien n'empêchait de créer deux
  spectacles qui se chevauchent dans le **même** lieu, sans matériel ni
  technicien en commun.
- Nouvelle fonction `conflicts.get_venue_conflicts` : deux `shows` ne
  peuvent pas se chevaucher dans le même `venue`, occupation physique
  exclusive, indépendante du matériel/technicien. Même exemption
  d'entreposage que le matériel (un entrepôt peut recevoir plusieurs fiches
  de rangement qui se chevauchent). Bloquant + `force: true`, câblé dans
  `ShowSerializer.validate()` (nouveau champ `force` sur ce serializer) et
  exposé sous `venue_conflicts` dans `GET /api/shows/{id}/conflicts/`.
- 12 nouveaux tests — suite complète à 149 tests, tous passent. flake8
  propre.

### Note sur le retrait du modèle Department (2026-07-29)

- En portant l'écran « Départements » du frontend (liste + fiche), Samuel a
  questionné l'utilité du modèle `Department` : en pratique, les noms de
  département (Son, Éclairage, Rigging, Décor...) faisaient doublon avec
  `Material.category`, qui existait déjà comme classification fixe du
  matériel. `Department` apportait un contact/couleur par équipe, mais cette
  distinction ne servait pas assez pour justifier une table séparée.
- Décision de Samuel : retirer complètement `Department` (table, FK
  `Material.department`, `DepartmentSerializer`/`DepartmentViewSet`, route
  `/api/departments/`, écrans Départements liste/fiche) et ne garder que
  `category`. Migration `0013_remove_department`.
- `ShowMaterialSerializer` exposait `department_color` (dérivé, pour colorer
  les assignations show/matériel) — remplacé par `material_category` (dérivé
  de `Material.category`), le frontend colore maintenant par catégorie.
- Duplication de projet (`duplication.py`) : la copie de `Material` ne
  remappe plus de `department` (champ retiré).
- Suite de tests nettoyée (`DepartmentColorTests` retirée, remplacée par
  `MaterialCategorySerializerTests` ; assertions department_color/duplication
  retirées) — suite complète à 141 tests, tous passent. flake8 propre.

### Note sur les écrans Assignations et Conflits (phase 2 frontend, 2026-07-30)

- **Assignations** (`AssignationMateriel.dc.html`/`AssignationTechnicien.dc.html`
  portés en Vue) : ce sont des modales (pas des pages routées), déclenchées
  depuis les deux boutons de `SpectacleDetailView.vue` (« + Assigner du
  matériel »/« + Assigner un technicien »), auparavant désactivés en
  attendant la phase 2. Le mockup matériel montrait un champ « note »
  générique qui n'existe pas sur `ShowMaterial` — remplacé par les vrais
  champs du modèle (`quantity`, `is_rental`, `rental_vendor`). Le mockup
  technicien montrait un « rôle sur ce spectacle » éditable ; `ShowTechnician`
  n'a pas de champ de rôle par assignation, donc affiché en lecture seule
  depuis `Technician.specialty`. Les deux modales excluent du sélecteur le
  matériel/technicien déjà assigné (contrainte `unique_together` côté
  modèle) et réutilisent le flux `force`/conflits déjà en place partout
  ailleurs (bandeau de conflit + bouton « Forcer l'assignation »).
- **Conflits** (`ConflitDetail.dc.html` porté en Vue) : le mockup montrait un
  seul conflit mis en scène (2 spectacles, boutons « Réassigner »/« Forcer
  les deux assignations »). Il n'existait pas d'endpoint listant TOUS les
  conflits d'un projet (seulement `GET /shows/{id}/conflicts/`, un spectacle
  à la fois) — question posée à Samuel, qui a choisi la solution propre :
  un nouvel endpoint `GET /api/projects/{id}/conflicts/`
  (`ProjectViewSet.conflicts` → `get_project_conflicts`, `conflicts.py`)
  plutôt qu'une agrégation N+1 côté frontend. Il agrège et **déduplique**
  lieu/matériel/technicien sur tout le projet (une paire en conflit
  n'apparaît qu'une fois, peu importe de quel côté on la détecte en premier).
  Comme ces conflits existent déjà dans la base (créés avec `force: true`,
  ou apparus après coup), l'écran n'a pas de bouton « Forcer » — la
  résolution se fait en ouvrant la fiche du spectacle concerné pour
  réassigner ou retirer manuellement. `serialize_venue_conflict` gagne au
  passage un champ `venue_name` (utile à l'affichage, absent auparavant).
  5 nouveaux tests (`ProjectConflictsAPITests`) — suite complète à 146,
  flake8 propre.

### Note sur la phase 3 frontend — Réglages/Utilisateurs/Login (2026-07-30)

- Le backend pour cette phase existait déjà en grande partie (voir notes des
  étapes 7-8 ci-dessus) : `/api/settings/` (singleton), `/api/users/` (CRUD),
  `/accounts/google/login/` (django-allauth) et `/api/auth/user/`,
  `/api/auth/logout/` (dj-rest-auth) étaient tous déjà câblés côté Django —
  seul le branchement Vue manquait, annoncé dès l'étape 7 ("ça se fera à
  l'étape 10, en même temps que le branchement du bouton de login côté Vue").
- **Login** (`LoginView.vue`, route `/login`) : le bouton « Continuer avec
  Google » est un `<a href>` classique vers `googleLoginUrl`
  (`useAuth.js`), PAS un appel API — le flux OAuth "classique" est une
  redirection pleine page (navigateur → Google → callback allauth → session
  Django → retour sur `FRONTEND_URL`), pas quelque chose qu'on peut faire en
  `fetch`. `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` restent vides dans
  `backend/.env` — le bouton redirige mais échoue côté Google Cloud tant que
  Samuel n'a pas créé ces identifiants (dernière pièce manquante, hors de
  portée du code).
- **Garde de route** (`router/index.js`) : toutes les routes sauf `/login`
  exigent une session valide (`GET /api/auth/user/`, vérifié une seule fois
  par session SPA via le singleton `useAuth.js` — même pattern que
  `useActiveProject.js`). Redirection vers `/login` si non authentifié.
- **Réglages** (`ReglagesView.vue`, route `/reglages`) : branché sur le vrai
  singleton `Settings` (buffers, durée de transport par défaut, formats
  date/heure) plutôt que l'état local jamais persisté du mockup. La section
  « Projets » réutilise `useActiveProject` (liste + création), avec un nouvel
  export `refreshProjects()` pour que le sélecteur de projet voie
  immédiatement un projet fraîchement créé.
- **Utilisateurs** (`UtilisateursView.vue`, route `/utilisateurs`) : branché
  sur `/api/users/`. Le formulaire « Ajouter un utilisateur » du mockup n'est
  pas cosmétique : il correspond exactement au flux de **pré-provisioning**
  déjà implémenté dans `signals.py` — créer un `User` par courriel avant la
  première connexion Google fait que le compte se lie à cette fiche à son
  premier login et conserve le rôle déjà assigné, au lieu d'être créé
  `viewer` par défaut.
- `AppShell.vue` affiche désormais le courriel de la session active et un
  lien « Se déconnecter » en pied de sidebar.

### Note sur la fenêtre départ/arrivée des transports (2026-07-30)

- Demande de Samuel : afficher les heures des spectacles de départ/arrivée
  pour référence sur un transport, proposer par défaut une heure juste après
  la fin (bufferisée) du départ, et **interdire** d'enregistrer un
  déplacement hors de la fenêtre [fin du départ, début de l'arrivée].
- Point de conception clarifié avec Samuel avant d'implémenter : `Transport`
  ne connaît qu'UN spectacle explicite (`show`) — l'autre bout n'est qu'un
  lieu, pas forcément un spectacle. Décision : déduction **automatique** du
  spectacle manquant (le plus proche chronologiquement à ce lieu, `None` si
  entrepôt), heures **effectives** (buffers inclus, cohérent avec
  `Show.effective_start/end`), validation **bloquante + `force`** (même
  pattern que tous les autres conflits, pas une règle absolue comme la
  quantité de matériel).
- Nouveau : `find_departure_show`/`find_arrival_show`/`get_transport_reference_shows`/
  `validate_transport_window` dans `conflicts.py` ; `TransportSerializer`
  expose `departure_show`/`arrival_show` (lecture) et valide la fenêtre à
  l'écriture. `serialize_venue_conflict`-like helper `serialize_reference_show`
  pour la représentation compacte.
- `TransportDetailView.vue` : bandeau de référence (heures de départ/arrivée),
  heure suggérée = fin effective du départ si aucune heure encore saisie
  (proposition, pas une réécriture forcée), bandeau « Forcer » réutilisé pour
  cette nouvelle validation (même mécanique que le conflit de technicien).
- Étendu ensuite à `TransportsView.vue` (formulaire d'ajout rapide, à la
  demande de Samuel : « ajoute les heures partout où on peut créer un
  transport »). Un Transport n'existe pas encore à ce stade, donc pas de
  `departure_show`/`arrival_show` à lire depuis l'API — le frontend reproduit
  fidèlement `find_departure_show`/`find_arrival_show` côté client à partir
  des `shows`/`venues` déjà chargés pour le formulaire (mêmes règles, mêmes
  exemptions). Heure suggérée seulement si le champ est encore vide (n'écrase
  jamais une saisie manuelle).
- 8 nouveaux tests (`TransportWindowValidationAPITests`) — suite complète à
  154 tests, tous passent, flake8 propre, aucune migration nécessaire (pas de
  nouveau champ de modèle).

### Note sur le code court des lieux, côté frontend (2026-07-30)

- Bug signalé par Samuel : « pour les Salles on n'a pas le champ pour mettre
  le Code à 4 caractères ». Diagnostic : le backend gérait `Venue.code`
  depuis le 2026-07-19 (modèle, normalisation majuscules dans
  `Venue.save()`, unicité par projet dans `VenueSerializer.validate_code`,
  tests) — **seul le frontend ne l'exposait nulle part**. Aucun changement de
  modèle ni migration.
- `LieuxView.vue` : champ « Code (4 car.) » dans le formulaire d'ajout
  (`maxlength=4`, majuscules à la saisie, en écho de la normalisation
  backend), envoyé dans le POST. Le code s'affiche en pastille devant le nom
  sur les cartes de la liste. L'erreur d'unicité est un **message de champ**
  (clé `code`), pas un `detail` global — le formulaire lit
  `e.data?.code?.[0]` en premier.
- `LieuDetailView.vue` : le code n'était affiché qu'en lecture, et seulement
  s'il existait — donc les lieux déjà créés ne pouvaient jamais en recevoir
  un. Édition inline (bouton Ajouter/Modifier → input + Enregistrer/Annuler,
  Entrée/Échap), `PATCH /api/venues/{id}/` avec le seul champ `code`. Choix
  assumé : seul champ éditable de la fiche pour l'instant, le reste attend
  une vraie fiche d'édition.
- 4 nouveaux tests (`VenueCodeTests`) sur le PATCH partiel, qui est le cas
  réellement nouveau : `validate_code` doit retrouver le projet depuis
  l'instance (pas de `project` dans le corps de la requête), ne pas prendre
  un code inchangé pour un doublon de lui-même, refuser un code déjà pris, et
  accepter l'effacement. Suite complète à 158 tests, flake8 propre.

### Note sur l'édition complète de la fiche lieu (2026-07-30)

- Suite immédiate de la note ci-dessus : le petit bouton « Modifier » à côté
  du code prêtait à confusion (il avait l'air de porter sur la fiche alors
  qu'il ne touchait qu'un champ). Décidé avec Samuel : bouton **« Modifier la
  fiche » en haut à droite de l'entête**, qui bascule **toute** la carte
  d'infos en édition, avec un **seul PATCH** à l'enregistrement — plutôt
  qu'un crayon par champ. Un lieu se corrige en bloc (on récupère l'adresse
  et le contact en même temps), pas champ par champ.
- Champs éditables : `name`, `code`, `address`, `contact_name`,
  `contact_info`, `notes`, `is_storage`, `latitude`, `longitude`. `project`
  est volontairement **exclu** — déplacer un lieu vers un autre projet
  casserait les spectacles/matériel/transports qui le référencent (isolation
  par projet, voir `schema.md` section 11).
- Détails d'implémentation côté Vue (`LieuDetailView.vue`) : le brouillon est
  une copie locale (`draft`) créée à l'entrée en édition et jetée à
  l'annulation ; `latitude`/`longitude` vidés sont envoyés en `null` et non
  en chaîne vide (que DRF refuserait sur un `DecimalField` nullable) ; les
  erreurs DRF sont dispatchées **par champ** sous l'input concerné plutôt
  qu'en un message global. Un `watch` sur `route.params.id` annule l'édition
  si on change de lieu sans quitter la vue. Le bloc Notes en lecture est
  masqué pendant l'édition (les notes ont leur propre champ dans le
  formulaire). La lecture affiche maintenant aussi les coordonnées GPS quand
  elles existent.
- Aucun changement backend nécessaire (`VenueSerializer` acceptait déjà tous
  ces champs en écriture). 4 tests ajoutés sur ce qui n'était pas couvert :
  PATCH multi-champs, effacement des coordonnées GPS via `null`, bascule
  `is_storage`, refus d'un nom vide. Suite complète à 162 tests, flake8
  propre, pas de migration.

### Note sur l'édition des fiches, généralisée (2026-07-30)

- Demande de Samuel : appliquer le pattern « Modifier la fiche » du lieu à
  toutes les pages qui affichent des infos modifiables — matériel,
  spectacle, technicien, transport.
- **Transport laissé de côté, volontairement** : sa fiche est déjà un
  formulaire toujours ouvert, parce qu'on y arrive pour compléter et
  confirmer une proposition générée automatiquement (voir la note sur
  `transport_autogen`). Lui ajouter un mode lecture aurait ajouté un clic à
  chaque passage sans rien clarifier. Décision prise avec Samuel.
- Nouveau `frontend/src/composables/useFicheEdition.js` : porte l'état
  commun (`editing`/`draft`/`saving`, erreurs DRF dispatchées **par champ**,
  le PATCH). Contrairement à `useActiveProject`/`useAuth`, ce n'est **pas**
  un singleton — chaque fiche a son propre état. Chaque vue garde ses
  champs et son HTML ; le composable ne rend rien.
- Les styles du formulaire d'édition sont **globaux** (classes `fiche-*`
  dans `src/style.css`) et non `scoped` : les quatre fiches partagent
  exactement le même formulaire, et dupliquer ~90 lignes de CSS dans chaque
  `<style scoped>` garantissait qu'elles divergeraient à la première
  retouche.
- Fiches traitées :
  - **Lieu** — refondu sur le composable, comportement inchangé.
  - **Matériel** — nouveau : nom, description, catégorie, propriété,
    quantité, lieu d'entreposage, kit parent, statut actif/inactif, notes.
    Le formulaire reproduit les garde-fous du serializer plutôt que
    d'attendre le 400 : la liste des parents possibles exclut le matériel
    lui-même et tout ce qui n'a pas `quantity=1`, et le champ quantité est
    figé quand le matériel appartient à un kit ou en est un.
  - **Technicien** — nouveau : nom, spécialité, coordonnées, notes.
  - **Spectacle** — avait déjà une édition inline, réécrite au même format.
    Le champ **`notes` manquait** : il existait sur `ShowSerializer` mais
    n'était éditable nulle part dans l'app. Le conflit de lieu garde son
    bandeau « Forcer malgré le conflit » distinct (il n'est pas une erreur
    de champ ordinaire) — d'où `lastError` sur le composable, qui expose le
    corps brut de la réponse d'erreur.
- Dans la foulée, les **formulaires d'ajout rapide des cinq listes**
  (matériel, lieux, spectacles, techniciens, transports) reçoivent des
  **libellés au-dessus de chaque champ** : les menus déroulants n'étaient
  identifiables que par leur valeur courante, donc illisibles une fois
  renseignés. Le dimensionnement flex passe de l'input au `<label>` qui
  l'enveloppe (`add-form__field`), et la rangée s'aligne sur `flex-end`
  pour rester droite quand un libellé passe sur deux lignes.
- Les champs `datetime-local` (début/fin d'un spectacle, heure prévue d'un
  transport) reçoivent une largeur plancher de 230px
  (`add-form__field--date`) : en dessous d'environ 215px les navigateurs
  tronquent l'affichage date + heure. Les champs de date sont en plus
  **forcés sur une deuxième ligne** (`add-form__break`, un élément vide de
  largeur pleine et de hauteur nulle qui casse la rangée flex) plutôt que de
  dépendre de la largeur de la fenêtre : sur Spectacles, titre/lieu/type sur
  la première ligne et la fenêtre horaire sur la seconde ; sur Transports,
  spectacle/type/lieux puis l'heure prévue. Tous les `datetime-local` de
  l'app (listes **et** fiches) portent `step="300"` — l'attribut est en
  secondes, donc le sélecteur natif propose les minutes par pas de 5.
- Ces styles, jusque-là **dupliqués à l'identique dans les cinq
  `<style scoped>`**, sont remontés en global dans `src/style.css` (classes
  `add-form*`), même raisonnement que pour les classes `fiche-*`. Aucun
  changement de logique dans les vues.
- Aucun changement backend : les serializers acceptaient déjà tous ces
  champs en écriture. 9 tests ajoutés (`FicheEditionPatchAPITests`) sur les
  PATCH que ces formulaires produisent réellement — multi-champs, FK
  nullables remises à `null`, isolation par projet, `notes` de spectacle,
  et le couple refus/`force` du conflit de lieu. Suite complète à 171 tests,
  flake8 propre, pas de migration.

### Note sur les catégories de matériel devenues éditables (2026-07-30)

- Demande de Samuel : un sous-menu et une page sous Matériel pour ajouter,
  modifier et supprimer les catégories. Point de départ : `Material.category`
  était un `CharField` restreint à 9 slugs codés en dur
  (`Material.CATEGORY_CHOICES`), et leurs **couleurs** étaient codées en dur
  dans 4 fichiers Vue — ajouter « Machinerie » demandait un redéploiement.
- **Ce n'est pas un retour du modèle `Department`** retiré la veille : une
  catégorie ne porte ni responsable ni contact, seulement un nom et une
  couleur. C'est le champ `category` existant, rendu éditable.
- Décisions prises avec Samuel avant d'implémenter :
  - **Une liste par projet** (et non commune à toutes les productions) —
    chaque mandat a ses propres besoins de classement. Conséquence :
    `duplicate_project` doit recopier les catégories et remapper le matériel
    copié, sinon une nouvelle édition pointerait vers les catégories de
    l'édition précédente.
  - **Suppression avec réassignation** plutôt que blocage sec : la FK est en
    `PROTECT`, et `DELETE ?reassign_to=<id>` bascule le matériel concerné
    avant de supprimer. Sans le paramètre, l'API renvoie un 400 avec
    `material_count`, ce que le frontend transforme en confirmation. La
    valeur vide (`?reassign_to=`) laisse le matériel **sans catégorie** —
    la FK est nullable, autant l'utiliser plutôt que d'imposer un fourre-tout.
  - **Couleur éditable** par catégorie (palette de 12 teintes) : sinon une
    catégorie créée n'aurait aucune couleur d'affichage.
- Backend : nouveau modèle `MaterialCategory` (contrainte d'unicité en base
  sur `project + name`, contrairement à `Venue.code` qui n'est validé que
  côté serializer — une catégorie a toujours un nom), `Material.category`
  devenu FK, `MaterialCategoryViewSet` (CRUD + `destroy` avec réassignation),
  signal `creer_categories_par_defaut` qui dote chaque nouveau projet des 9
  catégories historiques.
- Migration `0014_material_category` en 3 temps, parce qu'un `AlterField`
  CharField → ForeignKey ferait tenter à la base de convertir « audio » en
  identifiant entier : création de la table + champ temporaire `category_ref`,
  `RunPython` qui seed les catégories de chaque projet et remappe le matériel,
  puis suppression de l'ancien champ et renommage. Réversible (`RunPython`
  inverse qui réécrit les slugs).
- Frontend : sous-menu dans la sidebar (Matériel → Inventaire / Catégories,
  affiché seulement quand la section est active), nouvelle
  `CategoriesMaterielView.vue` (`/materiel/categories`) avec ajout, édition
  inline nom + couleur, et suppression via une modale qui demande la
  catégorie de remplacement. Cet écran n'utilise **pas** `useFicheEdition` :
  ce composable gère une fiche de détail unique, pas des lignes de liste.
- Les tables `categoryMeta` codées en dur ont disparu des 4 fichiers Vue qui
  les portaient (`MaterielView`, `MaterielDetailView`, `SpectacleDetailView`,
  `AssignerMaterielModal`) : nom et couleur viennent maintenant de l'API
  (`category_name`/`category_color` sur `MaterialSerializer`,
  `material_category_name`/`_color` sur `ShowMaterialSerializer`).
- 16 tests ajoutés (`MaterialCategoryAPITests`) : création automatique des
  défauts, CRUD, unicité par projet, isolation, les 5 chemins de suppression
  (inutilisée / sans cible / réassignée / sans catégorie / cible invalide) et
  le remappage à la duplication de projet. Suite complète à **187 tests**,
  flake8 propre.

### Note sur la disponibilité du matériel au départ d'un transport (2026-07-30)

- Demande de Samuel : la liste de matériel d'un transport ne doit permettre de
  prendre que ce qui se trouve au lieu de départ ; le matériel non disponible
  s'affiche en gris moyen contre le blanc du disponible.
- Décisions prises avant d'implémenter :
  - **Position réelle à l'heure du départ**, pas simplement
    `Material.venue == origin_venue`. Le second serait faux dès qu'un
    transport antérieur a déplacé le matériel : il resterait « disponible » à
    son entrepôt alors qu'il est en salle. On réutilise donc le grand livre
    de positions déjà écrit pour la Cohérence des emplacements.
  - **Non sélectionnable**, pas seulement grisé (« ne devrait permettre de
    prendre que… »).
  - **Sans heure prévue** (proposition auto non complétée) : tout est proposé
    comme disponible, avec une mention explicative. On n'invente pas de
    restriction sur une donnée manquante.
- Backend : `get_venue_material_availability()` dans
  `transport_coherence.py`, exposé par
  `GET /api/transports/{id}/material-availability/`. Renvoie **tout** le
  matériel actif du projet avec un champ `available` — y compris à 0, puisque
  le frontend affiche l'inventaire complet et grise ce qui manque. Le
  transport en cours est exclu du calcul (`exclude_transport`), sinon rouvrir
  la modale d'un transport déjà rempli montrerait son propre chargement comme
  déjà parti.
- Nuance à ne pas perdre : le blocage est **côté interface uniquement**. La
  cohérence des emplacements reste un rapport non bloquant côté API (décision
  du 2026-07-24, inchangée) — un chargement incohérent créé par l'API brute,
  ou devenu faux après un changement d'horaire, sera toujours signalé par le
  rapport plutôt que refusé.
- Frontend : la modale « Ajouter du matériel » de `TransportDetailView.vue`
  charge la disponibilité à l'ouverture, grise et désactive les lignes
  absentes (« Pas sur place — entreposé à X »), plafonne la quantité à ce qui
  est réellement présent, et signale le cas où l'heure saisie n'est pas encore
  enregistrée (le calcul porte alors sur l'heure en base).
- 9 tests ajoutés (`TransportMaterialAvailabilityAPITests`) : matériel à
  l'origine, ailleurs, déplacé par un transport confirmé antérieur, quantité
  partielle, proposition non confirmée qui ne déplace rien, non-décompte de
  soi-même, absence d'heure, matériel inactif et matériel d'un autre projet.
  Suite complète à **196 tests**, flake8 propre, aucune migration.

### Note sur les techniciens multiples par déplacement (2026-07-30)

- Demande de Samuel : « permettre d'ajouter plus d'un technicien sur les
  événements et les transports ». Diagnostic préalable : côté **spectacles**
  c'était déjà possible en base (`show_technicians` existe depuis le début) —
  seule la modale n'en assignait qu'un à la fois. Côté **transports**,
  `Transport.technician` était une FK unique.
- Décisions prises avant d'implémenter :
  - **Table de liaison sans hiérarchie** : `TransportTechnician` remplace la
    FK unique, tous les techniciens d'un déplacement à égalité — pas de
    chauffeur/responsable distingué des renforts.
  - **Pas de rôle par affectation** : le rôle reste `Technician.specialty`,
    même choix que `ShowTechnician` depuis le début.
  - **Modales en multi-sélection** pour les deux (spectacle et transport).
- Migration `0015_transport_technicians` en 3 temps : créer la table,
  recopier les affectations existantes, **puis seulement** supprimer
  l'ancien champ — l'ordre inverse perdrait les données. Le retour arrière
  ne garde que la première personne (perte assumée, c'est la nature d'un
  champ unique).
- Impact sur le cœur fonctionnel : l'unité d'engagement vérifiée par
  `conflicts.py` devient le couple **(transport, technicien)** et non plus le
  transport. Deux personnes sur le même déplacement sont deux engagements
  distincts, donc deux conflits distincts dans le rapport project-wide.
  `_technician_commitments`, `_technician_conflict_object_key` et
  `serialize_technician_conflict` travaillent désormais sur
  `TransportTechnician`. Le type exposé côté API reste `'transport'` : c'est
  bien une fiche déplacement que le frontend ouvre.
- Un seul bandeau d'erreur regroupe les conflits de **toute** l'équipe à la
  saisie — donc un seul bouton « Forcer », pas un par personne.
  `has_technician_conflict` vaut `true` dès qu'au moins une personne est en
  conflit.
- Le filtre `GET /api/transports/?technician=` traverse maintenant la table
  de liaison, avec `distinct()` (un JOIN sur une relation inverse duplique
  les lignes).
- Frontend : liste à cocher sur la fiche transport (à la place du `<select>`),
  `AssignerTechnicienModal` réécrite en multi-sélection sur le modèle de la
  modale matériel — les personnes déjà assignées restent visibles mais
  verrouillées, et la modale **reste ouverte** tant qu'il reste des conflits à
  forcer (nouvel argument `done` sur l'événement `assigned`, sinon on
  perdrait le détail juste après l'avoir affiché). `TransportsView` et le
  tableau de bord lisent `technician_names` (liste) au lieu de
  `technician_name`.
- 12 tests ajoutés (`TransportMultipleTechniciansAPITests`) + tous les tests
  existants sur `Transport.technician` adaptés via un helper
  `_transport_avec_technicien`. Suite complète à **208 tests**, flake8 propre.

### Note sur le retrait par décochage dans les modales (2026-07-30)

- Demande de Samuel : « dans la liste d'assignation, permettre de décocher un
  élément qu'on veut retirer ». Jusque-là les lignes déjà assignées étaient
  affichées **verrouillées** — visibles mais intouchables, ce qui obligeait à
  fermer la modale et à utiliser le ✕ de la fiche pour retirer quoi que ce soit.
- Décision : le retrait s'applique **à la validation**, avec le reste — pas
  immédiatement au clic. Décocher marque la ligne (barrée, estompée) et le
  bouton, renommé « Appliquer », exécute ajouts et retraits d'un coup. Une
  erreur de clic se rattrape en recochant.
- Appliqué aux trois modales :
  - **Assigner des techniciens** (spectacle) : `DELETE /api/show-technicians/{id}/`.
  - **Assigner du matériel** (spectacle) : `DELETE /api/show-materials/{id}/`.
  - **Ajouter du matériel** (transport) : purement local, la liste part au
    PATCH du transport (`TransportSerializer.materials`).
- **Les retraits partent avant les ajouts**, volontairement : libérer une
  ressource peut lever le conflit de capacité qui bloquerait un ajout dans la
  même fournée. Un test le vérifie explicitement.
- Deux conséquences sur les props : `AssignerTechnicienModal` reçoit
  maintenant les objets `ShowTechnician` complets (`assignedTechnicians`) et
  non plus des ids — le DELETE a besoin de l'id de l'assignation, pas de
  celui du technicien. Même raison pour `assignedMaterials`, déjà en place.
- Piège évité côté transport : `confirmAddMaterial` reconstruit la liste à
  partir des lignes cochées, mais **conserve** le matériel absent du
  catalogue affiché (inactif, ou filtré) plutôt que de le perdre
  silencieusement.
- 3 tests ajoutés (`AssignmentRemovalAPITests`) — le `DELETE` des deux tables
  de liaison n'était jamais couvert, alors que le frontend en dépend
  maintenant, plus le cas « retirer libère la capacité ». Suite complète à
  **211 tests**, flake8 propre, aucune migration.
- Retouche visuelle dans la foulée : les trois modales passent d'un
  `max-height: 85vh` à une **hauteur fixe** de 85vh. Avec un simple plafond,
  une liste courte faisait remonter le pied de page et la modale « sautait »
  d'une ouverture à l'autre selon le nombre de lignes. Le corps prend
  `flex: 1; min-height: 0` pour absorber la hauteur restante et défiler,
  entête et pied restant à leur place. La confirmation de suppression de
  `CategoriesMaterielView` est laissée telle quelle : c'est un petit dialogue
  de confirmation, pas une liste.

### Note sur le retour du matériel à son origine (2026-07-30)

- Demande de Samuel, en trois volets : rendre le lieu obligatoire à la
  création du matériel, vérifier qu'à la fin du dernier événement tout est
  revenu à son origine, et disposer de dates de début/fin pour borner
  l'analyse.
- **Les dates vivent sur le projet, pas dans les Réglages** (contrairement à
  la formulation initiale) : `Project.start_date`/`end_date` existaient déjà
  depuis le 2026-07-19 mais n'étaient saisissables nulle part, alors que les
  Réglages sont **communs à toutes les productions** — une seule paire de
  dates aurait couvert CINARS, Furies et Parcours Danse à la fois. Les champs
  sont maintenant éditables dans la section Projets de `ReglagesView`.
- **Lieu d'origine obligatoire** : exigé par `MaterialSerializer` à la
  création comme à la mise à jour, et non effaçable. Le champ reste
  **nullable en base** — invalider l'historique déjà saisi n'apporterait
  rien, et l'issue `origine_inconnue` doit rester significative pour les
  lignes anciennes. C'est donc l'API qui impose la règle, pas une contrainte
  DB. Les huit matériels existants avaient déjà tous un lieu.
- **Contrôle de retour** : nouveau type d'incohérence `retour_manquant` dans
  le rapport de cohérence, non bloquant comme le reste. L'horizon est
  `Project.end_date` (fin de journée) si renseignée, sinon la fin effective
  du dernier événement du projet — `get_project_horizon`. L'issue précise la
  quantité manquante et les lieux où le reliquat se trouve encore, pour
  savoir où aller le chercher.
- Ça **révise la portée « aller seulement »** décidée le 2026-07-24. Nuance
  retenue : on ne contrôle toujours pas qu'un `pickup` précis existe pour
  chaque livraison — le chemin reste libre — mais on vérifie le **résultat
  net** à la fin. Un aller-retour fait par deux transports quelconques passe ;
  du matériel resté en salle est signalé.
- Sur « limiter dans le temps les analyses de conflits » : après discussion,
  la fenêtre sert uniquement d'horizon au contrôle de retour. La détection de
  conflits continue de tourner sur tout le projet — l'écarter hors fenêtre
  masquerait une vraie erreur de saisie de date plutôt que du bruit.
- Frontend : lieu d'origine obligatoire dans le formulaire d'ajout et sur la
  fiche matériel (option « Aucun » retirée, message dédié), dates éditables
  par projet dans les Réglages, et nouvelle catégorie « Non retourné » dans
  l'écran Cohérence des emplacements.
- 9 tests ajoutés (`MaterialReturnToOriginTests`) : jamais déplacé, laissé en
  salle, ramené, retour partiel, retour prévu **après** la date de fin (le
  cas que Samuel veut attraper), retour avant, repli sur le dernier événement,
  projet sans horizon, et exposition via l'API. Plus les tests existants
  adaptés au lieu obligatoire. Suite complète à **222 tests**, flake8 propre,
  aucune migration (les champs de date existaient déjà).

### Note sur la sélection en cascade des kits (2026-07-30)

- Demande de Samuel : cocher un matériel qui contient des sous-éléments doit
  cocher aussi tous ses composants, avec possibilité de les décocher ensuite.
- Appliqué aux **deux** modales (assignation à un spectacle et ajout au
  camion d'un transport). Décocher le kit décoche ses composants — ils
  avaient été ajoutés à cause de lui.
- Deux garde-fous propres à chaque contexte :
  - **Spectacle** : la cascade ne touche jamais un composant **déjà assigné**
    au spectacle — cette ligne n'est pas pilotée par la case du kit.
  - **Transport** : la cascade **saute** les composants absents du lieu de
    départ (grisés, voir la note sur la disponibilité) plutôt que de les
    forcer dans le camion.
- Hypothèse à ne pas casser, désormais couverte par un test
  (`KitCascadeAssignmentTests`) : assigner un kit **et** ses composants au
  **même** spectacle n'est pas un conflit de hiérarchie, parce que
  `get_material_conflicts` exclut explicitement le spectacle courant de ses
  candidats. Sans ça, la cascade produirait un conflit à chaque kit coché. Le
  test vérifie aussi que la règle reste entière ailleurs : kit ici + composant
  sur un autre spectacle qui chevauche = toujours un conflit.
- Indice visuel dans les listes : « Kit · N composant(s) » sur un parent,
  « Composant » sur un enfant, pour comprendre d'où vient la cascade.
- Affichage aligné sur l'inventaire général (`MaterielView`) dans la foulée :
  chaque composant suit immédiatement son kit et s'affiche **en retrait**,
  avec le trait de raccordement, au lieu de l'ordre alphabétique brut où kit
  et composants se retrouvaient dispersés. Cas limite traité : un composant
  dont le kit est masqué par le filtre de catégorie reste affiché, mais au
  premier niveau — mieux vaut orphelin que perdu.
- Aucun changement backend. Suite complète à **225 tests**, flake8 propre.

### Note sur la suppression d'un lieu, d'un spectacle, d'un transport (2026-07-30)

- Demande de Samuel : bouton Supprimer avec confirmation, dans la page de
  l'item en modification.
- **Placement** : en bas du formulaire d'édition, séparé par un filet, à
  l'écart d'Enregistrer/Annuler — une suppression ne doit pas se cliquer par
  accident. Sur la fiche transport, qui n'a pas de mode lecture (formulaire
  toujours ouvert), le bloc vit simplement sous les actions.
- Les trois entités ne se comportent **pas** pareil, et c'est assumé :
  - **Lieu** — suppression **refusée** tant qu'il est référencé.
    `Show.venue` et les FK de `Transport` sont en `PROTECT` : sans traitement,
    Django lèverait un `ProtectedError` que DRF rendrait en **500**. D'où la
    vérification en amont, qui renvoie un 400 avec le décompte de chaque
    catégorie. `Material.venue` est en `SET_NULL` côté modèle, mais le
    laisser vider silencieusement l'origine contredirait la règle du lieu
    obligatoire posée le même jour — le matériel bloque donc aussi.
  - **Spectacle** — autorisée, mais emporte ses assignations ET ses
    déplacements (`transports.show_id` en CASCADE). Plutôt que de le
    découvrir après coup, `ShowSerializer.deletion_impact` expose les trois
    décomptes et la confirmation les annonce.
  - **Transport** — autorisée, emporte ses lignes de matériel et de
    techniciens.
- Détail relevé en écrivant les tests : le décompte de déplacements d'un
  spectacle inclut les **propositions auto-générées** (`transport_autogen`
  crée une proposition dès qu'on assigne du matériel). C'est voulu — elles
  disparaîtront aussi, la confirmation doit donc les compter.
- Nouveau `frontend/src/composables/useSuppressionFiche.js` (état de
  confirmation + DELETE + redirection vers la liste) et bloc de styles
  globaux `fiche-danger` / `fiche-confirm`, dans la lignée des classes
  `fiche-*`.
- 7 tests ajoutés (`SuppressionFicheAPITests`) : lieu libre supprimé, refusé
  par un spectacle / un transport / du matériel, `deletion_impact` exposé,
  cascade du spectacle (en vérifiant que le matériel lui-même survit),
  cascade du transport. Suite complète à **232 tests**, flake8 propre, aucune
  migration.

### Note sur les écrans « Parcours » (2026-07-30)

- Demande de Samuel : voir le parcours du matériel et des techniciens, en
  sous-menu comme le tableau de bord, avec sélection individuelle.
- Deux nouvelles pages : `/parcours/materiel` et `/parcours/techniciens`,
  en **sous-menu du Tableau de bord** (Vue d'ensemble / Parcours Matériel /
  Parcours Technicien). Elles avaient d'abord été placées sous Matériel et
  Techniciens, puis déplacées le même jour à la demande de Samuel — d'où le
  préfixe d'URL `/parcours/` plutôt que `/materiel/...`, et deux redirections
  depuis les anciens chemins pour ne pas casser un signet.
- Le Tableau de bord pointe sur `/`, qui préfixe tout : son activation dans
  la sidebar passe donc par un prédicat explicite (`activeMatch`) plutôt que
  par le `startsWith` habituel.
- Décisions prises avant d'implémenter :
  - **Le parcours matériel montre où il se trouve**, pas seulement ses
    engagements : une barre par item, segmentée par lieu de séjour. Un liseré
    lavande marque par-dessus les moments où il est requis par un spectacle —
    on voit d'un coup d'œil « il est bien là où il sert ».
  - **Toute la durée du projet** plutôt qu'une semaine glissante : c'est
    l'échelle où un parcours a du sens, et ça rejoint le contrôle de retour à
    l'origine.
  - **Sélection multiple à cocher**, pour comparer deux techniciens ou suivre
    un kit et ses composants côte à côte. Les 5 premiers sont cochés par
    défaut — un écran vide à l'ouverture n'apprend rien, 200 lignes non plus.
- Backend : `get_project_window` et `get_material_journey` dans
  `transport_coherence.py`, exposés par
  `GET /api/projects/{id}/material-journey/` et
  `.../technician-journey/` (filtres `?materials=` / `?technicians=`).
  Le parcours matériel **réutilise le grand livre de positions** déjà en
  place — même source de vérité que la cohérence des emplacements et que la
  disponibilité au départ d'un transport, donc les trois écrans ne peuvent
  pas se contredire.
- Simplification assumée sur le matériel en plusieurs exemplaires : un séjour
  porte le **lieu majoritaire** à cet instant, avec la quantité. Suivre chaque
  unité séparément supposerait de les identifier une à une, ce que le modèle
  ne fait pas (décision `Material.quantity` du 2026-07-19).
- Côté techniciens, spectacles et déplacements sont mélangés sur la même
  piste, avec les fenêtres **effectives** (buffers compris) : c'est exactement
  ce que croise la détection de conflit, donc un chevauchement se voit
  directement. Les blocs en conflit passent en rouge, le rapport
  project-wide servant de source.
- Nouveau composable `useParcours.js` : chargement, sélection, conversion
  temps → pourcentage et graduations de l'axe (en jours, avec un pas
  adaptatif — au-delà d'une trentaine de repères les libellés se chevauchent).
  Styles `parcours-*` en global, comme `fiche-*` et `add-form*`.
- 8 tests ajoutés (`ParcoursAPITests`). Suite complète à **240 tests**,
  flake8 propre, aucune migration.
- Complété le même jour (« on va avoir beaucoup de matériel ») : puces de
  filtre par catégorie dans le panneau de sélection du parcours matériel,
  plus une puce « Sans catégorie ». Conséquence sur « Tout » : il ne coche
  que ce qui est **visible** après filtrage — cocher 200 items alors qu'on en
  regarde 12 n'aurait pas de sens (`selectAll(visible)` dans `useParcours`).
- Sur l'affichage des catégories vides dans les puces de filtre : essayé dans
  les deux sens le même jour, à la demande de Samuel, puis **revenu au
  comportement initial** — seules les catégories réellement présentes
  deviennent des puces. Tout afficher remplissait la barre de filtres qui ne
  mènent nulle part. Vaut pour l'inventaire, le parcours et les modales
  d'assignation ; le référentiel complet se consulte dans
  `/materiel/categories`. La puce « Sans catégorie » du parcours suit la même
  règle : affichée seulement s'il existe du matériel non classé.
- Les puces du parcours acceptent la **sélection multiple** : ⌘ + clic (ou
  Ctrl sur PC) cumule les catégories, un clic simple remplace la sélection.
  Aucune catégorie sélectionnée équivaut à « Tous » — décocher la dernière y
  retombe, plutôt que de laisser un panneau vide. Même touche que le
  glisser-déposer de la timeline du tableau de bord, pour rester cohérent.
- Le panneau de sélection affiche enfin les **composants en retrait sous leur
  kit**, comme l'inventaire et les modales d'assignation (trait de
  raccordement compris), avec le nombre de composants en pastille sur le kit.
  Même cas limite traité partout : un composant dont le kit est masqué par le
  filtre reste affiché, au premier niveau.
- Et la **sélection en cascade** qui va avec, à la demande de Samuel : cocher
  un kit coche ses composants, décocher le kit les décoche — comportement
  identique aux modales d'assignation. La cascade porte sur tous les
  composants du kit, y compris ceux que le filtre de catégorie masque. Détail
  d'implémentation : `selectedIds` est réécrit en une seule fois plutôt que
  par appels successifs au `toggle` du composable, qui est observé et
  déclencherait un appel API par composant.

### Note sur les blocs rattachés à un événement (2026-07-31)

- Demande de Samuel : pouvoir ajouter une plage de montage/répétition en
  amont d'un événement et une de démontage en aval — trois blocs consécutifs
  au plus — plus des répétitions indépendantes.
- **Les répétitions indépendantes ne demandaient rien** : un `Show` de type
  Répétition, avec ses propres horaires et sans rattachement, existait déjà
  (ex. la répétition de la veille dans une autre salle). Signalé avant
  d'implémenter.
- Décision de modélisation, validée avec Samuel : un bloc est un **`Show`
  complet** rattaché par `parent_show`, pas une table de créneaux à part.
  Un montage occupe la salle, mobilise une équipe et du matériel — c'est un
  événement. Conséquence : il hérite sans une ligne de code supplémentaire
  des assignations, de la détection de conflits, des transports, du parcours
  technicien et de la cohérence des emplacements. Deux nouveaux `event_type`
  (`setup`, `teardown`) ; la répétition en amont réutilise `rehearsal`.
- Contraintes validées côté serializer : **un seul niveau** (un bloc ne peut
  pas en avoir), même projet et **même lieu** que l'événement principal.
  `CASCADE` à la suppression — un bloc n'a pas de sens sans son événement.
- **Le piège, traité explicitement** : un bloc est collé à son événement,
  donc leurs fenêtres *effectives* se chevauchent dès qu'un buffer est
  renseigné. Sans traitement, chaque montage aurait été signalé en conflit de
  lieu avec le spectacle qu'il prépare. D'où `Show.family_ids` et le nouvel
  argument `exclude_family_ids` de `get_venue_conflicts`. L'exclusion ne vaut
  qu'entre membres d'une même famille : un vrai voisin dans la même salle est
  toujours détecté (un test le vérifie). C'est le « pas de double comptage »
  choisi plutôt que de forcer les buffers à zéro.
- Frontend : section « Montage, répétition, démontage » sur la fiche
  spectacle (ajout avec horaires proposés — 3 h avant, 2 h après — collés à
  l'événement, bouton Forcer en cas de conflit réel, retrait par ligne, lien
  vers la fiche de chaque bloc) ; fil d'Ariane remontant au parent depuis la
  fiche d'un bloc ; blocs groupés en retrait sous leur événement dans la
  liste des Spectacles ; couleurs, filtres et info-bulle dédiés dans le
  tableau de bord. Les blocs créés depuis la fiche portent des buffers à 0 :
  leur créneau est déjà explicite.
- **Ressources héritées** (précision de Samuel, même jour) : le matériel et
  les techniciens d'un bloc de **montage/démontage** sont ceux de l'événement.
  (Le bloc de **répétition** a été sorti de ce régime le même jour — voir la
  note suivante.) Deux façons de le faire ; la copie des
  assignations dans chaque bloc a été écartée parce que les copies divergent
  dès qu'on modifie l'événement après coup. Retenu : une **fenêtre
  d'engagement** (`engagement_start`/`engagement_end`) qui couvre l'événement
  et tous ses blocs, utilisée par la détection de conflit matériel et
  technicien. Une seule assignation, portée par l'événement, valable du
  montage au démontage.
  - Conséquence utile : un technicien pris ailleurs **pendant le montage**
    est maintenant détecté en conflit, et le matériel est réservé sur toute
    la période — ce qui n'était pas le cas avant ce changement.
  - `effective_start`/`effective_end` restent la fenêtre du seul créneau et
    continuent de servir au conflit de **lieu** : un bloc occupe la salle pour
    son propre compte. Les deux notions coexistent volontairement.
  - L'assignation directe sur un bloc est **refusée** par l'API, avec un
    message qui renvoie vers l'événement — plutôt que de laisser coexister
    deux vérités. Côté fiche, un bloc affiche le matériel et l'équipe hérités
    en lecture seule, avec un lien « Gérer sur l'événement ».
- Migration `0016_show_phases` (ajout de `parent_show`, extension des types).
  11 tests ajoutés (`ShowPhasesAPITests`), dont l'absence de faux conflit avec
  le parent, la détection maintenue avec un tiers, la hiérarchie à un seul
  niveau, le lieu imposé et la cascade — plus 5 tests d'héritage
  (`ShowPhaseInheritanceTests`) : fenêtre étendue, conflit pendant le montage,
  matériel réservé, absence de conflit hors fenêtre, et non-régression pour un
  événement sans bloc. Suite complète à **256 tests**, flake8 propre.

- **Le bloc de répétition redevient autonome** (2026-07-31, deuxième
  précision de Samuel : « le bloc répétition n'obtient pas de matériel et de
  technicien du spectacle parent, on va copier les infos lors de la création
  mais on permet d'éditer par la suite »). Un montage manipule forcément le
  matériel du spectacle avec son équipe ; une répétition est un vrai temps de
  travail, où l'on n'utilise pas nécessairement tout, ni avec les mêmes
  personnes.
  - `Show.INHERITING_PHASE_TYPES` (montage, démontage) et le champ dérivé
    `inherits_resources` tranchent les deux cas. La fenêtre d'engagement de
    l'événement ne s'étend plus que sur les blocs qui héritent — l'étendre
    jusqu'à une répétition rattachée mettrait l'événement en conflit avec sa
    propre répétition.
  - `ShowSerializer.create` recopie les assignations de l'événement dans un
    bloc de répétition nouvellement créé — une seule fois. Ce qu'on ajoute
    ensuite à l'événement ne redescend pas : c'est le prix de l'autonomie,
    sans quoi éditer le bloc n'aurait pas de sens. Les lignes sont créées une
    à une (pas de `bulk_create`) pour que les signaux de régénération des
    transports les voient passer.
  - Conséquence à ne pas manquer : `get_material_conflicts` et
    `get_technician_conflicts` excluent désormais toute la **famille**
    (`Show.family_ids`) et plus seulement le spectacle courant. La copie
    entrerait sinon en conflit avec l'événement dès qu'un buffer fait toucher
    les deux fenêtres — le cas par défaut, la fiche proposant une répétition
    collée au spectacle. Même raisonnement que l'exclusion déjà en place pour
    le conflit de lieu.
  - Côté fiche : la répétition rattachée affiche ses propres listes avec ses
    boutons d'assignation, plus un rappel que la liste vient d'une copie. Le
    montage et le démontage gardent l'affichage en lecture seule et le lien
    « Gérer sur l'événement ».
  - 9 tests (`RehearsalPhaseAutonomyTests`) : copie à la création, absence de
    copie pour un montage, non-propagation des ajouts ultérieurs, assignation
    et retrait sur le bloc, fenêtre d'engagement inchangée, absence de faux
    conflit avec l'événement, conflit réel avec un tiers toujours détecté,
    exposition de `inherits_resources`. Suite complète à **266 tests**,
    flake8 propre, aucune migration.

### Chronologie de la fiche matériel (2026-08-01)

Demande de Samuel : « dans la fiche de chaque item matériel on va afficher en
plus des assignations spectacle tous les éléments comme les montages,
démontages, répétitions et les transports dans l'ordre chronologique », avec
le même affichage à lignes cliquables que la fiche spectacle.

- `get_material_schedule()` (`transport_coherence.py`) réunit trois sources :
  les assignations (`ShowMaterial`), les blocs qui **héritent** du matériel de
  leur événement (montage, démontage — ils n'ont pas d'assignation propre,
  leurs entrées sont dérivées et marquées `inherited`), et les déplacements
  (`TransportMaterial`). Exposé par `GET /api/materials/{id}/schedule/`.
- Calculé côté backend délibérément : l'héritage des blocs est une règle
  métier. La reproduire dans le Vue en ferait une deuxième implémentation à
  maintenir.
- Effet de bord bienvenu : le drapeau `conflict` vient maintenant de
  `get_material_conflicts` restreint à ce matériel, au lieu d'un appel à
  `GET /shows/{id}/conflicts/` par assignation depuis le navigateur.
- Une proposition de transport sans heure part en fin de liste avec
  `start: null` — la masquer cacherait exactement ce qu'il reste à compléter.
- Bornée à la **fenêtre du projet** (`get_project_window`, la même que les
  écrans « Parcours ») depuis le 2026-08-01 : la fiche affiche les dates de la
  fenêtre en tête de carte, et annonce le nombre d'éléments écartés plutôt que
  de les faire disparaître en silence.
- 7 tests (`MaterialScheduleAPITests`). Suite complète à **277 tests**,
  flake8 propre, aucune migration.

### Répartition du matériel entre les lieux (2026-08-01)

Demande de Samuel : « on a besoin d'implémenter un affichage pour le matériel
avec plusieurs items qui se séparent en plusieurs lieux », puis « afficher par
défaut tout le parcours de la date de départ du projet à la date de fin ».

- `GET /api/materials/{id}/distribution/` rend `get_material_journey` +
  `get_material_transports` sur la fenêtre du projet. **Pas de nouvel
  algorithme** : c'est la même source que l'écran Parcours Matériel, les deux
  ne peuvent donc pas se contredire. Le regroupement diffère — le Parcours
  empile une ligne par *lane* pour tracer les bifurcations, la carte de la
  fiche regroupe par **lieu**, ce qui répond à « où est mon stock, et depuis
  quand ».
- Côté fiche : une ligne par lieu, un segment par période de détention avec la
  quantité écrite dedans, une ligne « En transit » pour les déplacements
  confirmés, un axe en jours et un repère « maintenant » (affiché seulement
  s'il tombe dans la fenêtre). Visible à partir de 2 exemplaires.
- Contrairement au parcours project-wide, l'endpoint répond aussi pour un
  matériel désactivé : on y arrive depuis sa fiche, qui reste consultable.
- **Piste abandonnée** : une première version répondait à un instant donné
  (`?at=`), avec une notion de « en transit » qui sortait le matériel de son
  origine pendant le trajet — un écart volontaire avec le grand livre partagé
  (`_ledger_before`, déplacement atomique à l'arrivée). Retirée le même jour au
  profit de la vue par période ; c'est le point à réexaminer si l'idée revient.
- 7 tests (`MaterialDistributionAPITests`) : fenêtre du projet, stock intact
  avant tout transport, séparation entre deux lieux, transports renvoyés,
  proposition non confirmée sans effet, projet sans dates ni événement,
  matériel désactivé. Suite complète à **288 tests**, flake8 propre, aucune
  migration.

## Fichiers produits

- `schema.md` — structure complète de la base de données
- `architecture.md` — overview technique, logique de conflits, workflows
- `agents_tools.md` — outils/agents par phase (planification, développement, tests, review, documentation)
- `recapitulatif_projet.md` — ce document
