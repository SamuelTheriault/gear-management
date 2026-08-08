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

## 3. Authentification et autorisation

- Login via compte Google (OAuth 2.0) — pas de gestion de mots de passe custom.
- `User.role` (`admin`/`viewer`) est un rôle **global historique**, conservé
  mais devenu **purement d'affichage** côté frontend (`UtilisateursView.vue`)
  depuis le 2026-08-02 — il ne gate plus rien côté API. Ne pas le confondre
  avec les rôles PAR PROJET ci-dessous, qui sont le contrôle réel.
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
  Ce même signal active désormais aussi les invitations `pending` de la
  personne qui vient de se connecter pour la première fois — voir le modèle
  d'accès par projet ci-dessous.

### 3bis. Accès par projet (multi-tenant, décision du 2026-08-02)

Jusqu'au 2026-08-02, il n'y avait **aucune isolation multi-tenant réelle** :
`REST_FRAMEWORK.DEFAULT_PERMISSION_CLASSES` ne contenait que
`IsAuthenticated`, et `ProjectFilteredMixin` n'était qu'un filtre optionnel
`?project=<id>` — n'importe quel compte provisionné (même `role='viewer'`)
pouvait lire ET modifier tous les projets de tous les clients via l'API.
Corrigé en vue de vendre des abonnements à d'autres directeurs
techniques/compagnies : chaque `Project` a maintenant des membres, chacun
avec un rôle.

- **`ProjectMembership`** (`project_id` + `user_id`, voir `schema.md` section
  13ter) relie un `User` à un `Project` avec un rôle parmi trois :
  - `owner` : gère les accès du projet (`ProjectMembershipViewSet`) + édite
    tout le reste.
  - `editor` : édite tout SAUF la gestion des accès.
  - `viewer` : lecture seule.

  Un `status` (`pending`/`active`) distingue une invitation pas encore
  « acceptée » (la personne ne s'est jamais connectée via Google) d'un accès
  réellement utilisable — seul `status='active'` compte comme un accès pour
  le contrôle ci-dessous. Pas d'envoi de courriel automatique (aucune infra
  SMTP configurée) : l'invitation reste affichée « en attente » jusqu'au
  premier login Google de l'email invité, qui l'active automatiquement (voir
  le signal ci-dessus).

- **`HasProjectAccess`** (`backend/inventory/permissions.py`) est la
  permission DRF appliquée à tous les ViewSets isolés par projet (Venue,
  Material, MaterialCategory, Technician, Show, Transport, ShowMaterial,
  ShowTechnician, ProjectMembership, et Project lui-même). Elle résout le
  projet concerné — directement (`project_id`) ou via une relation
  (`show__project_id` pour ShowMaterial/ShowTechnician/Transport, qui n'ont
  pas de FK `project` directe) — et vérifie un `ProjectMembership` actif avec
  un rôle suffisant : `viewer` minimum en lecture (`GET`/`HEAD`/`OPTIONS`),
  `editor` minimum en écriture, `owner` pour la gestion des accès
  (`ProjectMembershipViewSet` et `Project.destroy`). Une LISTE ne renvoie
  jamais un 403 : elle est simplement filtrée aux projets accessibles
  (`ProjectMembershipQuerysetMixin`/`restrict_queryset_to_membership`) — un
  `GET` détail sur un objet d'un projet inaccessible répond 404 (l'objet
  n'apparaît jamais dans le queryset filtré), pas 403.

- **`User.is_staff_global`** (BooleanField, distinct de `role`) court-circuite
  entièrement ce contrôle — accès de dépannage/support réservé à
  l'exploitant de la plateforme (Samuel), utile pour intervenir sur un
  projet client sans en être `owner`. Un superutilisateur Django
  (`is_superuser`, ex. via `createsuperuser`/`/admin/`) bénéficie du même
  court-circuit : il a de toute façon un accès complet et non filtré à la
  base via l'admin Django, le gater côté API serait de la sécurité de
  façade — et c'est ce que la suite de tests backend utilise partout pour
  s'authentifier.

- **`ProjectViewSet`** : la liste ne renvoie que les projets où l'appelant a
  un membership actif (tout, pour un compte staff/superutilisateur) — fini
  la vue « tous projets confondus » pour un compte normal. `POST
  /api/projects/` et `POST /api/projects/{id}/duplicate/` créent
  automatiquement un `ProjectMembership(role='owner', status='active')` pour
  l'appelant sur le projet obtenu — sinon personne n'aurait accès au projet
  qu'il vient de créer.

- **`UserViewSet`** (`/api/users/`, liste tous les comptes de la
  plateforme) est réservé aux comptes staff (`IsStaffGlobal`) — la liste
  complète des comptes, tous projets/clients confondus, ne doit pas fuiter
  vers un client normal.

- **Migration des données existantes** (`0020_project_access_data.py`) :
  chaque `User` avec `role='admin'` reçoit `is_staff_global=True` (préserve
  l'accès complet qu'il avait de facto via le bug `IsAuthenticated`-seul) ;
  `samueltheriault@gmail.com` devient `is_staff_global=True` explicitement
  (le seul utilisateur ayant réellement utilisé l'outil jusqu'ici) et
  `owner` actif de chaque `Project` déjà existant.

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
Même logique : un technicien ne peut pas être assigné (`show_technicians`) à deux spectacles dont les fenêtres effectives se chevauchent — peu importe le lieu de chacun des deux spectacles (voir aussi point d, ci-dessous, sur la distinction avec le conflit de lieu).

### d) Conflits de lieu (décision du 2026-07-19)
Indépendamment de tout matériel ou technicien partagé, deux spectacles ne peuvent pas se chevaucher dans le **même lieu** (`venue`) — occupation physique exclusive (`get_venue_conflicts`, câblé sur `ShowSerializer.validate()`). C'est l'inverse des points a) et b) : le matériel et les techniciens ne conflictent JAMAIS entre eux à cause du lieu (deux spectacles simultanés dans deux lieux différents peuvent très bien se disputer le même technicien ou le même matériel, et c'est bien détecté), alors que deux spectacles dans le **même** lieu conflictent même sans rien partager d'autre. Même exemption d'entreposage que pour le matériel (point suivant) : un lieu d'entrepôt peut recevoir plusieurs fiches de rangement qui se chevauchent sans que ce soit un vrai conflit d'occupation. Bloquant + `force: true`, comme les autres conflits ; exposé dans `GET /api/shows/{id}/conflicts/` sous `venue_conflicts`.

**Exception : les blocs rattachés** (2026-07-31). Un événement peut porter une plage de montage/répétition en amont et une de démontage en aval (`Show.parent_show`, voir `schema.md` section 4). Ces blocs sont **collés** à leur événement, dans le même lieu : leurs fenêtres effectives se chevauchent dès qu'un buffer est renseigné. `Show.family_ids` (l'événement + tous ses blocs) est donc passé en `exclude_family_ids` à `get_venue_conflicts`, sans quoi un montage serait signalé en conflit avec le spectacle qu'il prépare. L'exclusion ne joue qu'entre membres d'une même famille — un vrai voisin dans la même salle reste détecté. C'est le « pas de double comptage » décidé avec Samuel : les buffers restent pour les événements sans bloc explicite, mais ne se retournent pas contre les blocs.

**Un bloc est un événement à part entière** : il occupe le lieu et participe donc normalement au point d). C'est la raison du choix de modélisation (un `Show` rattaché plutôt qu'une table de créneaux) : rien à réécrire en parallèle.

**Ses ressources dépendent de son type.** Un bloc de **répétition** rattaché est autonome : il porte ses propres assignations, recopiées de l'événement à sa création puis modifiables (précision de Samuel du 2026-07-31). Il n'étire pas la fenêtre d'engagement du parent.

**Montage et démontage, eux, utilisent les ressources de leur événement** (décision du 2026-07-31) : un montage mobilise l'équipe et le matériel du spectacle qu'il prépare. Plutôt que de recopier les assignations dans chaque bloc — des copies qui divergeraient — la **fenêtre d'engagement** de l'événement (`Show.engagement_start`/`engagement_end`) s'étend du premier bloc au dernier, et c'est elle que `get_material_conflicts`/`get_technician_conflicts` comparent. Un technicien pris ailleurs pendant le montage est donc bien en conflit. Deux fenêtres coexistent volontairement : `effective_*` pour le lieu (le créneau seul), `engagement_*` pour matériel et techniciens (créneau + montage/démontage). L'assignation directe sur ces blocs-là est refusée par l'API, qui renvoie vers l'événement.

**Exclusion de famille, côté ressources aussi** : `get_material_conflicts` et `get_technician_conflicts` écartent tous les membres de `Show.family_ids`, pas seulement le spectacle courant. Un événement et ses blocs sont une seule unité de travail, et la copie d'assignations portée par une répétition rattachée entrerait sinon en conflit avec l'événement dès qu'un buffer fait se toucher les deux fenêtres — le cas par défaut. Sans bloc, `family_ids` vaut `{show.id}` : rien ne change.

### c) Conflits de déplacement (décision du 2026-07-18)
Chaque technicien affecté à un `transport` (tournée multi-arrêts depuis le 2026-08-04, fenêtre = `[scheduled_datetime, scheduled_datetime + somme des durées de segment]` — du départ du premier arrêt à l'arrivée au dernier) est vérifié contre **les deux** types d'engagement à la fois : ses autres `transports`, ET ses assignations `show_technicians`. Concrètement : un technicien ne peut pas être en train de livrer du matériel au moment où il est censé être sur un spectacle (et vice-versa) — `get_technician_conflicts` (assignation à un show) et `get_transport_conflicts` (assignation à un transport) croisent désormais l'une contre l'autre (voir `conflicts.py`, `_technician_commitments`).

**Plusieurs techniciens par déplacement** (décision de Samuel du 2026-07-30) : `Transport.technician` (FK unique) a été remplacé par la table de liaison `transport_technicians` (`schema.md`, section 13bis) — un déplacement peut mobiliser une équipe, comme un spectacle le pouvait déjà via `show_technicians`. L'engagement unitaire vérifié est donc le couple **(transport, technicien)**, pas le transport : deux personnes sur le même déplacement sont deux engagements distincts, et apparaissent comme deux conflits distincts dans le rapport project-wide. Côté saisie, un seul bandeau regroupe les conflits de toute l'équipe — donc un seul bouton « Forcer », pas un par personne. Le rôle reste la spécialité du technicien : pas de chauffeur/responsable distingué, pas de rôle par affectation (même choix que `show_technicians`). Cette vérification ne bénéficie PAS de l'exemption d'entreposage (point suivant) : un déplacement est toujours un vrai engagement de temps pour le technicien qui le fait, contrairement au matériel qui dort en entrepôt.

### e) Fenêtre départ/arrivée d'un déplacement (décision du 2026-07-30)
Un déplacement doit avoir lieu **entre** la fin effective du spectacle de départ et le début effectif du spectacle d'arrivée — pas avant que le matériel ne soit libéré, pas après que l'arrivée en ait besoin. Depuis les tournées multi-arrêts (2026-08-04), les bornes sont les PREMIER et DERNIER arrêts — les arrêts intermédiaires ne bornent rien (on s'y arrête en passant). `Transport` ne connaît qu'UN spectacle explicite (`show`, celui « desservi ») : s'il se joue au lieu du dernier arrêt, il est le spectacle d'arrivée (l'ancienne « livraison ») ; au lieu du premier, le spectacle de départ (l'ancien « ramassage ») — ce test de lieu remplace le champ `transport_type`, retiré le 2026-08-04. L'autre bout n'est qu'un lieu, pas forcément lié à un spectacle précis. `find_departure_show`/`find_arrival_show` (`conflicts.py`) déduisent automatiquement ce spectacle manquant — le plus proche chronologiquement à ce lieu — sans champ supplémentaire à saisir. Un lieu d'entrepôt n'a jamais de spectacle associé (même exemption qu'ailleurs) : pas de borne de ce côté. `get_transport_reference_shows` combine les deux ; `TransportSerializer` les expose en lecture (`departure_show`/`arrival_show`, pour affichage ET pour proposer par défaut `departure_show.effective_end` comme heure suggérée côté frontend) et les valide à l'écriture (`validate_transport_window`) — bloquant + `force: true`, même pattern que les autres conflits.

### Comportement bloquant + override (décision du 2026-07-17)
Si chevauchement détecté → l'API refuse l'assignation (`400`) et retourne le détail des conflits. Ajouter `"force": true` dans la requête force l'assignation malgré le conflit. `GET /api/shows/{id}/conflicts/` liste les chevauchements actuellement en place sur un spectacle (utile pour repérer après coup les assignations faites avec `force: true`).

`GET /api/projects/{id}/conflicts/` (ajouté le 2026-07-30, `ProjectViewSet.conflicts` → `get_project_conflicts` dans `conflicts.py`) fait la même chose à l'échelle du projet entier plutôt qu'un seul spectacle, pour l'écran « Conflits » du frontend : agrège lieu/matériel/technicien sur tous les spectacles, et **déduplique** chaque paire en conflit (contrairement à `ShowViewSet.conflicts`, appeler cette dernière pour chaque spectacle du projet renverrait la même paire deux fois, une fois de chaque côté). Réponse : `{'venue_conflicts': [...], 'material_conflicts': [...], 'technician_conflicts': [...], 'conflict_count': n}`, chaque entrée de conflit étant `{'a': ..., 'b': ...}` — les deux côtés, déjà sérialisés. Ce sont des conflits qui **existent déjà** dans la base (créés via `force: true`, ou apparus après coup suite à une modification d'horaire elle-même forcée) : il n'y a rien à « forcer » à nouveau depuis cet écran, la résolution passe par réassignation ou suppression manuelle sur la fiche du spectacle concerné.

### Exemption d'entreposage (décision du 2026-07-18)
Un `venue` peut être marqué `is_storage = true` (un entrepôt, pas un vrai lieu de spectacle). Un `show` rattaché à un tel `venue` (convention : `event_type = 'storage'`) est **entièrement ignoré** par la détection de conflit **matériel** : assigner du matériel à un entrepôt ne bloque jamais, et une assignation existante à un entrepôt ne compte jamais comme conflit pour un vrai spectacle ailleurs — le matériel rangé est considéré disponible. Cette exemption ne s'applique qu'au matériel ; un technicien assigné à un `show` d'entrepôt (ex. pour de l'inventaire) reste soumis à la détection normale, puisque ça représente un vrai engagement de temps pour lui.

### Buffers
Par défaut, 1h avant et 1h après chaque événement (répétition ou représentation), pour couvrir le transport et l'installation/désinstallation du matériel. Configurable par spectacle si besoin — et depuis le 2026-07-18, ce "par défaut" lui-même est configurable globalement via `settings.default_buffer_before_minutes`/`default_buffer_after_minutes` (voir section 4bis), plutôt que codé en dur.

## 4bis. Réglages globaux (`settings`, décision du 2026-07-18)

Table singleton (une seule ligne, voir `schema.md` section 10) exposée en lecture/écriture sur `GET`/`PATCH /api/settings/` (`SettingsView`, pas de liste ni de création — toujours la même ligne, créée automatiquement avec des valeurs par défaut si absente). Objectif : donner à une future page de réglages du frontend Vue le contrôle sur des valeurs jusqu'ici codées en dur, sans redéploiement backend.

- `default_buffer_before_minutes`/`default_buffer_after_minutes` : valeur proposée à la création d'un `Show` — lue dynamiquement par un callable Django (`models._default_buffer_before_minutes` etc.), pas une constante Python.
- `default_transport_duration_minutes` : idem pour la durée d'un segment de tournée (`TransportStop.travel_minutes_from_previous`, 2026-08-04), utilisé seulement si l'estimation automatique Google Routes (section 4ter) échoue ou n'est pas configurée.
- `date_format`/`time_format` : préférences d'affichage pour le frontend (pas encore consommées, le frontend n'étant pas branché — mais déjà en place côté API).

## 4ter. Calcul du temps de trajet (Google Routes API, décision du 2026-07-18)

Samuel a demandé si géolocaliser les lieux pour calculer automatiquement les temps de trajet valait la peine. Réponse : oui à ce volume d'usage, le coût n'est pas un frein (l'API Google Routes offre 10 000 requêtes gratuites/mois pour le tier "Essentials" — largement suffisant), mais ça demande un compte Google Cloud avec facturation activée et une clé API à gérer comme un secret.

- `venues.latitude`/`longitude` (nullables, saisie manuelle — pas de géocodage automatique d'adresse pour l'instant) permettent de localiser un lieu.
- `inventory/maps.py` (`estimate_travel_minutes`) appelle l'API Google Routes ("Compute Routes" — un trajet simple, cohérent avec le fait qu'un `Transport` a toujours une origine et une destination uniques) pour estimer la durée du trajet entre deux venues.
- `TransportSerializer` appelle cette fonction automatiquement à la création d'un `Transport`, seulement si le client n'a pas fourni `estimated_duration_minutes` explicitement et que les deux venues ont des coordonnées. Le résultat est utilisé directement, y compris pour la détection de conflit du technicien assigné.
- Dégradation silencieuse à chaque étape : pas de clé API configurée, coordonnées manquantes, erreur réseau/quota → retombe sur `settings.default_transport_duration_minutes`, jamais d'erreur ni de blocage.
- **Étapes manuelles restantes côté Samuel** (voir aussi `inventory/maps.py` et `security.md`) : créer/choisir un projet Google Cloud, activer la facturation, activer "Routes API", créer une clé API restreinte à cette API, puis l'ajouter comme `GOOGLE_MAPS_API_KEY` dans les Variables Railway (et `backend/.env` en local, voir `.env.example`). Tant que ce n'est pas fait, l'app fonctionne normalement, juste sans l'auto-estimation.

## 4quater. Isolation par projet (`projects`, décision du 2026-07-19)

Samuel travaille en parallèle sur plusieurs productions qui n'ont rien en commun (compagnies de danse, musées, biennales comme CINARS/Parcours Danse/Furies). `Project` (voir `schema.md`, section 11) isole les données propres à chaque production :

- `venues`, `materials`, `technicians` et `shows` portent chacun un `project_id` **obligatoire**. `settings` reste volontairement **commun à tous les projets** — un choix explicite de Samuel, pas un oubli.
- Validation bloquante côté serializers (`_same_project()` dans `serializers.py`) : impossible d'assigner du matériel/technicien d'un projet à un spectacle d'un autre (`ShowMaterialSerializer`/`ShowTechnicianSerializer`), impossible de donner à un `Show` un `venue` d'un autre projet (`ShowSerializer`), impossible qu'un `Material` référence un `parent_material` ou un `venue` d'entreposage d'un autre projet que le sien (`MaterialSerializer`), et impossible qu'un `Transport` mélange un `show`, ses `origin_venue`/`destination_venue` et son `technician` de projets différents (`TransportSerializer`).
- Filtrage optionnel `?project=<id>` sur les listes (`ProjectFilteredMixin` dans `views.py`) — optionnel plutôt qu'obligatoire pour ne pas casser un accès API brut, mais le frontend (une fois branché) passera toujours ce paramètre pour refléter le projet actif choisi par Samuel.
- **Bascule entre projets** : entièrement côté frontend (sélecteur qui change le `?project=` utilisé par les appels API), sans recharger ni exporter/importer de fichier — c'est la demande initiale de Samuel (« comme une sauvegarde, mais je veux basculer sans charger un fichier »).
- **Pas de vue « tous projets confondus »** (décision validée avec Samuel) : chaque vue reste filtrée par le projet actif. Conséquence assumée — la détection de conflits (section 4) ne peut jamais croiser deux projets différents, puisque `Technician`/`Material` d'un projet sont des lignes distinctes de celles d'un autre projet, même si elles représentent la même personne/le même équipement réel.
- **Suppression** (révisée le 2026-08-04 — jusque-là volontairement non implémentée) : les FK `project` de `Venue`, `MaterialCategory`, `Material`, `Show` et `Technician` sont passées de `on_delete=PROTECT` à `on_delete=CASCADE` (migration `0026_project_cascade_delete`, `AlterField` pur). Supprimer une `Project` efface donc désormais toute la production. `ProjectViewSet.destroy` (`owner_only_actions`, voir section 3bis) ne peut pas se contenter d'un `project.delete()` nu : trois autres FK du modèle restent volontairement en `PROTECT` (`Show.venue`, `TransportStop.venue`, `Material.category`), et Django les évalue indépendamment du fait que l'objet protégé soit lui-même promis à la suppression par un chemin `CASCADE` dans le même appel — un `project.delete()` direct lève donc un `ProtectedError` (500 non catché) dès qu'un lieu a des spectacles ou qu'une catégorie a du matériel, ce qui couvre presque tout projet réel. Contourné en supprimant d'abord ce qui protège, dans une transaction : les `Show` du projet (cascade déjà `Transport`/`TransportStop`/`TransportMaterial`/`ShowMaterial`/`ShowTechnician`, ce qui lève la protection sur `Venue`), puis `Material.category` mis à `null` pour le projet (lève la protection sur `MaterialCategory`) — `project.delete()` peut alors cascader `Venue`/`Material`/`MaterialCategory`/`Technician` sans plus rien qui bloque. La voie normale pour retirer une production terminée reste de l'archiver (`status='archived'`), pas de la supprimer — la suppression est irréversible, sans corbeille ; le frontend (`ProjetDetailView.vue`) exige de retaper le nom du projet avant d'activer le bouton, comme friction supplémentaire côté UI.
- **Duplication pour une nouvelle édition** (décision du 2026-07-19, voir `inventory/duplication.py`) : `POST /api/projects/{id}/duplicate/` copie `venues`, `materials` (hiérarchie parent/enfant remappée vers les nouvelles lignes) et `technicians` vers un nouveau projet — **jamais** `shows`/`show_materials`/`show_technicians`/`transports` (une nouvelle édition a son propre calendrier, pas celui de la précédente). Le nouveau projet reprend `client_name` du projet source par défaut (surchargeable dans la requête) ; `notes`, `start_date`, `end_date` et `status` repartent à leurs valeurs par défaut (`status='active'`), quel que soit l'état du projet source. Réponse : `{'project': {...}, 'copied': {'venues': n, 'materials': n, 'technicians': n}}`. Opération atomique (tout ou rien) ; le projet source n'est jamais modifié.

**Spectacle desservi optionnel (2026-08-06, migration `0028`)** : `Transport`
porte une FK `project` directe et son `show` est nullable — décision de
Samuel (« — Aucun spectacle — » au formulaire de création, l'étiquette
précisant que le spectacle sélectionné est celui de l'ARRIVÉE, et la liste
filtrée sur les spectacles du lieu d'arrivée choisi — un entrepôt à
l'arrivée propose tout). Sans spectacle : aucune borne départ/arrivée, pas
de couverture autogen, `show_title: null` côté API. `transport_detach`
révisé : sans candidat de réancrage, la tournée survit « sans spectacle »
au lieu d'être supprimée (catégorie `transports_detached` de
`deletion_impact`) ; la suppression ne reste que pour une séquence < 2
arrêts, désormais explicite (SET_NULL ne cascade pas). La suppression de
projet purge les tournées AVANT les spectacles (protection
`TransportStop.venue`).

## 4quinquies. Module transport — cohérence des emplacements (décision du 2026-07-24)

Complément à la détection de conflits (section 4) : là où celle-ci vérifie les chevauchements d'horaire (capacité matériel, techniciens), ce module vérifie la cohérence **spatiale** du matériel dans le temps. Deux questions posées par Samuel :

1. **« Tout est-il possible sur les emplacements prévus ? »** — une tournée prétend charger du matériel à un arrêt ; ce matériel s'y trouve-t-il vraiment à l'arrivée du camion ?
2. **« Tout déplacement de matériel est-il associé à un transport ? »** — le matériel requis à un lieu de spectacle y est-il bien amené par un transport ?

**Lien matériel↔transport** : nouvelle table de liaison `transport_materials` (voir `schema.md`, section 9), gérée en écriture imbriquée sur `TransportSerializer.materials`. C'est ce lien explicite (plutôt qu'une inférence lieu+horaire) qui permet de vérifier réellement *quel* matériel voyage — choix retenu avec Samuel le 2026-07-24 pour pouvoir détecter un oubli de chargement.

**Timeline de position** (`inventory/transport_coherence.py`) : pour chaque matériel, on reconstruit un « grand livre » de positions dans le temps — départ = `Material.venue` (lieu d'entreposage, le « bercail »), avec `Material.quantity` unités, puis application chronologique des LIGNES de tournée qui le transportent (tournées multi-arrêts, 2026-08-04) : chaque ligne déplace sa quantité du lieu de son arrêt de chargement (quitté à l'heure d'arrivée du camion à cet arrêt) vers celui de son arrêt de déchargement (réputé « arrivé » à l'heure d'arrivée à ce dernier). Pour une tournée à 2 arrêts — le cas migré — ces instants sont l'ancien couple départ/`effective_end`, à l'identique. On compare ensuite :
- chaque `Transport` : son matériel est-il disponible à l'origine à l'heure du départ ? Sinon → `origine_incoherente`.
- chaque `ShowMaterial` : le matériel est-il présent (en quantité suffisante) au lieu du spectacle au début de sa fenêtre effective ? Sinon → `materiel_non_livre`.
- matériel sans `venue` d'entreposage → `origine_inconnue` (position de départ inconnue, non suivi).

**Non bloquant** (décision Samuel du 2026-07-24) : contrairement à la détection de conflits (bloquante + `force`), la cohérence des emplacements est un **rapport** consultable à la demande, jamais un refus `400`. Endpoints : `GET /api/shows/{id}/transport-coherence/` (centré sur un spectacle, à la manière de `/conflicts/`) et `GET /api/projects/{id}/transport-coherence/` (toute la production). Réponse : `{'issues': [...], 'issue_count': n}`.

**Portée — aller seulement** (décision Samuel du 2026-07-24) : on vérifie la présence du matériel là où il est requis (livraisons). On n'exige PAS qu'un ramassage (`pickup`) ferme la boucle en ramenant le matériel à son entrepôt — un `pickup` reste pris en compte dans la timeline comme tout déplacement, sans contrôle de retour.

**Exemption d'entreposage** : un `ShowMaterial` sur un `show` d'entrepôt (`venue.is_storage=True`) n'exige aucune livraison, cohérent avec l'exemption matériel de la section 4.

**Disponibilité au lieu de départ** (ajout du 2026-07-30, demande de Samuel) : la même timeline sert maintenant *en amont*, à la saisie, et plus seulement en rapport a posteriori. `get_venue_material_availability(venue, at, exclude_transport=)` répond « quel matériel est présent à ce lieu à cet instant, en quelle quantité », exposé par `GET /api/transports/{id}/material-availability/?stop=<position>` (lieu et heure d'arrivée de l'arrêt choisi — sans paramètre, le premier arrêt, l'ancien comportement). Le frontend (`TransportDetailView.vue`) s'en sert pour **griser et rendre non sélectionnable** le matériel qui n'est pas sur place — on ne charge pas dans un camion ce qui est ailleurs. Trois précisions de conception :

- **Bloquant à la saisie, contrairement au rapport.** La cohérence reste non bloquante côté API (aucun `400`) ; c'est l'interface qui empêche la sélection en amont. Le serveur accepterait toujours un chargement incohérent — créé par l'API brute ou devenu faux après coup — et le rapport continuerait de le signaler. Les deux mécanismes sont complémentaires, pas redondants.
- **Le transport ne se décompte pas lui-même** (`exclude_transport`) : sans ça, rouvrir la modale d'un transport déjà rempli montrerait son propre chargement comme « déjà parti ».
- **Sans `scheduled_datetime`** (proposition auto non complétée), la position n'est pas calculable : l'endpoint renvoie `at: null` et tout le stock comme disponible, plutôt que d'inventer une restriction sur une donnée manquante. Le frontend l'explique dans la modale.

### Création des transports — manuelle et automatique (décision du 2026-07-24)

Deux façons de créer un `Transport`, décidées avec Samuel :

1. **Manuelle** : l'utilisateur crée un déplacement (lieux de départ/arrivée choisis parmi les lieux existants, heure, matériel). Créé directement en `status='confirmed'` (une heure est alors obligatoire).
2. **Automatique** (`inventory/transport_autogen.py`) : dès que du matériel est requis à un lieu où rien ne l'amène, l'app crée une **proposition** en `status='to_approve'` — une tournée simple à 2 arrêts (fusionner des propositions en une vraie tournée multi-arrêts reste un geste manuel, décision du 2026-08-04) — pré-remplie avec ce qu'on peut déduire — lieu de départ (dernière position connue du matériel, origines **chaînées** via la timeline : entrepôt→A puis A→B, pas entrepôt→B), lieu d'arrivée (le lieu du spectacle) et matériel (groupé par couple origine/spectacle). Ce qu'on ne peut pas déduire — heure, technicien — reste vide ; l'utilisateur complète puis confirme, ce qui fait passer la proposition de l'**orange** (à approuver) au **vert** (confirmé).

**Déclenchement** (décision Samuel : automatique, pas un bouton à la demande) : signaux (`regenerate_signals.py`) sur `ShowMaterial` (assignation), `Transport` confirmé, `TransportMaterial` et `TransportStop` d'un transport confirmé (2026-08-04 — déplacer un arrêt change la couverture), et `Show` (horaire/lieu). Chaque déclenchement lance `regenerate_project_proposals`, un *resync* idempotent des seules propositions `to_approve` du projet (garde de réentrance pour ne pas boucler sur ses propres écritures).

**Pas de mémoire de rejet** (décision Samuel) : chaque régénération recalcule l'ensemble des propositions nécessaires ; une proposition écartée réapparaîtra si le besoin est toujours là. Les transports **confirmés** ne sont jamais touchés, et un déplacement déjà couvert par un transport confirmé (même mal chronométré — c'est au rapport de cohérence de le signaler) n'est pas reproposé.

**Une proposition ne livre rien** tant qu'elle n'est pas confirmée : elle est exclue de la timeline de position (donc l'alerte `materiel_non_livre` reste, mais en `etat='propose'` / orange, avec `proposal_transport_id`), et son technicien/heure vides l'excluent de la détection de conflit.

### Conflit de technicien — reste bloquant, indicateur ajouté (décision du 2026-07-24)

Samuel a confirmé qu'un technicien ne peut pas être à deux endroits en même temps — ce qui **était déjà** détecté (section 4c), de façon **bloquante avec override `force`**. Décision retenue : **garder ce comportement** (ne pas passer en non-bloquant) et simplement **exposer l'information** pour un indicateur orange côté frontend, via le champ dérivé `has_technician_conflict` sur `TransportSerializer` (lecture seule ; vrai même pour une affectation créée avec `force: true`, et vrai dès qu'**au moins une** des personnes affectées est en conflit depuis le 2026-07-30). Autrement dit : le blocage à la saisie reste, l'indicateur sert à repérer après coup les conflits acceptés avec `force`.

## 4sexies. Export/import CSV par section (décision du 2026-08-04)

Ajouté à la demande de Samuel pour un passage par Excel — distinct de l'export/import complet ci-dessous (4septies), qui vise la fidélité totale et la réimportation directe dans l'app. Ici, chaque section (`materials`, `venues`, `technicians`, `shows`) s'exporte et se réimporte **indépendamment**, une ligne humainement lisible par entité.

- **Fichiers** : `backend/inventory/csv_export.py` (en-têtes `MATERIAL_CSV_HEADER`/`VENUE_CSV_HEADER`/`TECHNICIAN_CSV_HEADER`/`SHOW_CSV_HEADER`, `csv_response`, une fonction `*_export_rows` par section) et `backend/inventory/csv_import.py` (`parse_csv_rows`, une fonction `import_*_csv` par section). Les deux fichiers partagent les mêmes en-têtes constants — une colonne renommée d'un côté casserait la réimportation d'un export existant, donc à ne jamais faire diverger.
- **Format** : séparateur `;` (pas `,` — Excel en français interprète la virgule comme séparateur décimal), BOM UTF-8 en tête (force Excel à lire en UTF-8 plutôt qu'en Latin-1 à l'ouverture directe).
- **Endpoints** : `POST /api/materials/import-csv/`, `GET /api/materials/export-csv/`, et les mêmes actions sur `VenueViewSet`, `TechnicianViewSet`, `ShowViewSet` (`@action(detail=False)`). Ces actions ne passent pas par `get_object()` (pas d'objet unique visé), donc pas par `has_object_permission` de `HasProjectAccess` — l'accès est vérifié explicitement dans le corps de chaque vue via `permissions.can_access_project`/`can_edit_project` (voir `_resolve_csv_project`, section 3bis), avec le même résultat 404 (pas 403) pour un projet inaccessible que le reste de l'API.
- **Deux modes d'import**, choisis par l'utilisateur à chaque import : `append` (les lignes s'ajoutent à la suite du contenu existant) et `replace` (tout le contenu existant de CETTE liste, pour CE projet, est supprimé avant l'import — jamais les autres listes, jamais un autre projet). L'en-tête du fichier est validé AVANT toute écriture ; chaque import est atomique (tout ou rien).
- **Objets créés directement** (`Model.objects.create()`), pas via les serializers DRF — même raisonnement que `duplication.py`/`portability.py` (section 4septies) : un CSV peut légitimement contenir des lignes qui, prises isolément, déclencheraient une détection de conflit (ex. deux spectacles qui se chevauchent), sans que ce soit une erreur de saisie à bloquer à l'import.
- **Résolution des références par nom** (lieu, catégorie, kit parent) plutôt que par id — un CSV est modifié à la main dans Excel, où les id n'ont pas de sens. Une catégorie mentionnée mais absente du projet est **créée à la volée** (couleur par défaut) ; un lieu mentionné mais introuvable **fait échouer l'import** (contrairement à une catégorie, un lieu inconnu est plus probablement une faute de frappe qu'une nouvelle entrée voulue).
- **`shows` couvre uniquement les événements top-level** (pas de colonne pour rattacher un bloc montage/répétition/démontage à un événement parent) — utiliser l'export/import JSON complet (4septies) pour couvrir les blocs. Les buffers reprennent les valeurs par défaut de `Settings` à l'import, comme pour toute création normale d'un `Show`.
- **`mode=replace` sur les lieux** refuse (sans rien supprimer) si un lieu existant est encore référencé par un spectacle, un arrêt de tournée (`TransportStop.venue`, `PROTECT`) ou du matériel qui en fait son origine — même logique de garde que `VenueViewSet.destroy` (section 2 de `schema.md`).

## 4septies. Export/import complet d'un projet — JSON et XML (décision du 2026-08-04)

Complément aux CSV ci-dessus : `backend/inventory/portability.py` couvre TOUTES les tables d'un projet (y compris `Show`/`ShowMaterial`/`ShowTechnician`/`Transport`/`TransportStop`/`TransportMaterial`/`TransportTechnician`) dans un seul fichier, pour archiver un projet complet ou le faire passer vers une autre instance de l'app.

- **`GET /api/projects/{id}/export/`** (`ProjectViewSet.export`) : JSON par défaut (réimportable), ou XML avec `?format=xml` (lecture seule, jamais réimporté — un `renderer_classes` factice, `_ProjectXmlRenderer`, existe uniquement pour que DRF reconnaisse `format=xml` comme valide pendant la négociation de contenu). Contrôle d'accès : rôle `viewer` minimum, via `has_object_permission` standard (c'est un `GET` détail classique, contrairement aux actions CSV `detail=False` du 4sexies).
- **`POST /api/projects/import/`** (`ProjectViewSet.import_project`, `url_path='import'` — `import` est un mot réservé Python côté nom de méthode) : crée un **NOUVEAU** `Project` à partir d'un fichier JSON produit par `export` — n'écrase jamais un projet existant, même logique de sécurité que `duplicate` (section 4quater). Corps de requête : soit le contenu exporté directement, soit `{'data': ..., 'name': ..., 'client_name': ...}` pour renommer à l'import sans modifier le fichier source.
- **Format** (`EXPORT_FORMAT`/`EXPORT_FORMAT_VERSION`) : un dict avec `project` (champs de la fiche) et une liste par table. Chaque ligne garde son id d'origine UNIQUEMENT pour permettre aux autres lignes du même fichier de s'y référer (ex. `materials[].venue` pointe un `id` de `venues`) — cet id n'a plus aucun sens une fois réimporté (nouvelles clés primaires) et n'est jamais réutilisé tel quel. Les lignes de matériel d'un transport référencent leur arrêt de chargement/déchargement par **position** (`order`) dans la séquence, pas par id de `TransportStop` — pour la même raison.
- **Objets créés directement**, pas via les serializers DRF — les serializers `ShowMaterialSerializer`/`ShowTechnicianSerializer`/`TransportSerializer` déclenchent la détection de conflits à la création, ce qui bloquerait la réimportation de données historiques parfaitement valides (ex. deux assignations en conflit acceptées avec `force: true` dans le projet d'origine).
- **Import en deux passes** pour les hiérarchies auto-référentielles (`materials[].parent_material`, `shows[].parent_show`) — même principe que `duplication.duplicate_project` : toutes les copies sont créées d'abord, puis les références sont remappées, parce qu'un parent peut apparaître après son enfant dans le fichier.
- **Opération atomique** : en cas d'erreur (référence brisée, format inconnu, version non prise en charge), rien n'est créé. `PortabilityError` couvre les deux cas (fichier structurellement invalide, référence introuvable) et remonte en 400 avec un message explicite, jamais en 500.
- **`_grant_owner_membership`** (même mécanisme que `POST /api/projects/` et `duplicate`, section 3bis) donne à l'appelant un accès `owner` actif sur le projet nouvellement importé — sans quoi personne n'y aurait accès juste après l'import.

## 4octies. Sorties de rapports imprimables et liens publics (décision du 2026-08-08)

Chantier demandé par Samuel : imprimer des feuilles pour les techniciens et les salles partenaires, avec un **code QR** en pied de page qui renvoie vers la version numérique à jour. Le QR n'est pas le vrai chantier — la page publique derrière lui l'est.

**Le blocage résolu** : toute l'API est derrière `IsAuthenticated` + `HasProjectAccess`, et la garde du routeur Vue renvoie vers `/bienvenue` tout compte sans `ProjectMembership` actif. Un QR pointant vers l'app aurait mené un technicien pigiste à un écran de login puis à un cul-de-sac. D'où `ReportShare` (voir `schema.md` section 14) et un jeu de vues publiques étroit (voir `security.md` section 6, qui détaille le modèle de menace — **à lire avant de toucher à `public_views.py`**).

**Quatre feuilles**, portées depuis les maquettes Claude Design de `frontend/design/Maquette pour impression` : fiche de transport, fiche spectacle, parcours technicien, et horaire de la journée (seule en paysage).

- **`backend/inventory/reports.py`** — assemblage des données, un `build_*` par type. **Source unique de l'écran ET du papier** : la page publique Vue et le PDF WeasyPrint consomment le même dictionnaire. Sans ça, les deux versions divergeraient — exactement le défaut que le QR est censé corriger. Les feuilles n'affichent délibérément PAS les conflits de `conflicts.py` : un conflit est un problème de planification qui appartient à Samuel, l'afficher à une salle publierait un doute qu'elle ne peut pas résoudre.
- **`backend/inventory/report_shares.py`** — émission et résolution des jetons, et génération du QR (`segno`, Python pur). Le QR est rendu **côté serveur** et pour l'écran et pour le PDF : une bibliothèque QR en JavaScript serait une deuxième vérité à maintenir, et le premier écart entre l'aperçu et le papier passerait inaperçu jusqu'au quai. Les maquettes appelaient `api.qrserver.com` — écarté, cela transmettrait l'URL privée de partage à un tiers à chaque rendu.
- **`backend/inventory/report_pdf.py` + `templates/reports/*.html`** — rendu WeasyPrint A4. L'import de `weasyprint` est **différé à l'intérieur de `render_pdf`** : il charge Pango et HarfBuzz, et un paquet système manquant ferait échouer tout démarrage de Django (y compris `manage.py check` en CI) au lieu de la seule requête qui demande un PDF. Le Dockerfile installe `libpango-1.0-0`, `libpangoft2-1.0-0`, `libharfbuzz-subset0`. JetBrains Mono est embarquée dans `inventory/fonts/` (4 graisses) plutôt que chargée depuis Google Fonts — sinon chaque rendu part sur le réseau.
- **`backend/inventory/public_views.py`** — `GET /api/public/reports/<token>/` (JSON) et `.../pdf/`. Les seules vues DRF en `AllowAny` de tout le projet.
- **Frontend** : `views/PublicReportView.vue` (route `/p/:token`, **exemptée de la garde d'authentification** du routeur), `components/PartagerFicheModal.vue` (panneau « Partager / Imprimer » branché sur les fiches tournée / spectacle / technicien et sur le Tableau de bord pour la journée), et une section « Liens de partage » dans `ReglagesView.vue` pour la vue d'ensemble.

**Écarts imposés par WeasyPrint** — mesurés dans un bac à sable le 2026-08-08, ne pas les « corriger » vers la maquette sans revérifier : `writing-mode: vertical-rl` n'est pas supporté (la légende du QR est passée à l'horizontale) ; la sortie SVG de segno n'a pas de `viewBox`, donc aucune largeur CSS ne s'applique tant qu'on ne l'injecte pas ; les boîtes de marge `@top-center`/`@bottom-center` exigent `width: 100%` sous peine de se centrer sur leur contenu ; et les maquettes calculent un `transform: scale()` en JavaScript pour tenir sur une page, ce que WeasyPrint ne peut pas exécuter — on laisse donc couler sur plusieurs pages, avec en-tête et pied **répétés** (le QR se trouve ainsi sur chaque page, une feuille désagrafée reste scannable).

## 5. Workflows principaux

### Workflow 1 — Créer une fiche spectacle
1. Créer le spectacle (`shows`) : titre, lieu (`venue_id`), type (répétition/représentation), horaires.
2. Le système calcule automatiquement la fenêtre effective (horaire + buffers).
3. Depuis la fiche, sélectionner le matériel requis dans l'inventaire.
4. Le système valide en temps réel s'il y a conflit avec une autre fiche.
5. Si matériel loué spécifiquement pour ce spectacle, cocher `is_rental` et indiquer le `rental_vendor`.
6. Assigner les techniciens requis — même validation de conflit.

### Workflow 2 — Sortir les listes de matériel par technicien ou par catégorie
1. Depuis une fiche spectacle (ou globalement), générer une liste filtrée par technicien assigné.
2. Chaque technicien reçoit/consulte uniquement son propre matériel et son horaire pour le spectacle concerné.
3. Le matériel étant aussi classé par catégorie (`materials.category` — voir `schema.md`, section 3), on peut aussi générer une liste par catégorie, indépendamment de l'assignation technicien.
4. Le frontend colore le matériel et les assignations show/matériel par catégorie (voir `MaterialSerializer`/`ShowMaterialSerializer`, champs `category_name`/`category_color` et `material_category_name`/`material_category_color`). Un modèle `Department` séparé (responsable/contact/couleur par département) avait été introduit le 2026-07-18 puis retiré le 2026-07-29 à la demande de Samuel : il faisait doublon avec `category` sans apporter de valeur distincte en pratique.
5. **Catégories éditables** (2026-07-30) : `category` est devenu une FK vers `material_categories` (`schema.md`, section 13), une liste **par projet** gérée depuis l'écran `/materiel/categories`. Les couleurs, jusque-là codées en dur dans les vues Vue, sont désormais une donnée. La suppression d'une catégorie encore utilisée exige une réassignation explicite du matériel (`?reassign_to=`) — la FK est en `PROTECT`, rien ne se perd par accident.

### Workflow 3 — Suivi des besoins de location
1. Lors de l'assignation de matériel à un spectacle, si le matériel n'existe pas encore dans l'inventaire ou doit être loué, l'ajouter comme entrée dans `materials` avec `ownership_status = rental` (ou simplement cocher `is_rental` dans `show_materials` si le matériel de base existe déjà mais que cette instance-là est louée).
2. Les démarches de location (contact vendor, confirmation, etc.) se font **hors application**, par courriel. Un futur module d'automatisation (Claude / scripts) pourra pré-remplir ces courriels à partir des données du spectacle — **hors scope actuel**, prévu comme étape future.

### Workflow 4 — Tracer le passage en entreposage
1. Créer (une fois) un `venue` avec `is_storage = true` pour chaque entrepôt physique.
2. Créer un `show` sur ce venue (convention : `event_type = 'storage'`) pour la période où le matériel y est rangé, puis y assigner le matériel via `show_materials` — comme pour un vrai spectacle, mais sans jamais déclencher de conflit (voir section 4).

### Workflow 5 — Planifier une livraison ou un ramassage
1. Deux entrées possibles (voir section 4quinquies) : soit **créer manuellement** une tournée (séquence d'arrêts `stops` — ou le simple couple départ/arrivée du contrat de compat — plus l'heure de départ) — confirmée d'emblée ; soit **compléter une proposition auto** déjà générée (`status='to_approve'`, orange, tournée à 2 arrêts) quand du matériel manque à un lieu — lieux et matériel sont déjà préremplis, il ne reste qu'à saisir l'heure (et le technicien) puis à confirmer. La durée d'un segment peut être laissée vide : si les deux lieux ont des coordonnées GPS, elle est calculée automatiquement (Google Routes) ; sinon elle prend la valeur par défaut des réglages.
2. Renseigner le matériel transporté via le champ `materials` (liste de `{material, quantity, load_stop_order?, unload_stop_order?}` — chaque ligne pointe sa portion de la séquence ; sans les positions, la tournée entière) — c'est ce qui permet au module de cohérence de vérifier que le matériel requis à destination y est bien amené, et que l'origine du déplacement est cohérente (voir section 4quinquies).
3. Assigner (ou laisser vide pour l'instant) le technicien qui s'en charge — le système valide en temps réel qu'il n'est pas déjà engagé (spectacle ou autre déplacement) sur cette fenêtre.
4. `GET /api/shows/{id}/conflicts/` inclut les déplacements dans les conflits techniciens listés, aux côtés des assignations `show_technicians`.
5. `GET /api/shows/{id}/transport-coherence/` (ou `/api/projects/{id}/transport-coherence/`) liste, sans rien bloquer, le matériel requis mais non livré et les transports dont l'origine est incohérente — le rapport de cohérence des emplacements (section 4quinquies).

### Workflow 6 — Ajuster les réglages globaux
1. `GET /api/settings/` pour consulter les valeurs actuelles (buffers par défaut, durée de transport par défaut, format de date/heure).
2. `PATCH /api/settings/` avec les champs à changer — s'applique immédiatement aux prochaines fiches créées (pas de redéploiement, pas d'effet rétroactif sur les fiches existantes).

### Workflow 7 — Basculer entre productions
1. Créer une `project` par production (`POST /api/projects/` : nom, client, dates optionnelles).
2. Tout le contenu propre à cette production (`venues`, `materials`, `technicians`, `shows`) se crée avec ce `project_id`.
3. Le frontend (une fois branché) garde en mémoire le projet actif et l'ajoute systématiquement en `?project=<id>` sur les appels API — basculer d'une production à l'autre est instantané, sans recharger ni exporter/importer de fichier.
4. Une production terminée s'archive (`PATCH /api/projects/{id}/` avec `status: "archived"`) plutôt que de se supprimer — elle reste consultable et re-sélectionnable.

### Workflow 8 — Démarrer une nouvelle édition d'un mandat existant
1. `POST /api/projects/{id}/duplicate/` sur le projet de l'édition précédente, avec au minimum `{"name": "Furies 2027"}`.
2. Le nouveau projet reprend `client_name` de l'édition précédente (surchargeable avec `client_name` dans le corps de la requête), ainsi que tous les lieux, tout le matériel (hiérarchie kit/composants incluse) et tous les techniciens — copiés, pas partagés : modifier la copie n'affecte jamais l'édition précédente.
3. Aucun spectacle, aucune assignation de matériel/technicien, aucun déplacement n'est copié — la nouvelle édition démarre avec un calendrier vierge, prête à recevoir ses propres `shows`.
4. La réponse inclut le décompte de ce qui a été copié (`copied: {venues, materials, technicians}`) pour confirmation immédiate.

### Workflow 9 — Sortir ou faire entrer une section en CSV (Excel), décision du 2026-08-04
1. Depuis les Réglages (ou la fiche du projet), `GET /api/materials/export-csv/?project=<id>` (ou `venues`/`technicians`/`shows`) télécharge la section choisie en `.csv`, modifiable dans Excel.
2. `POST /api/materials/import-csv/` (même pattern sur les 3 autres) avec `{project, mode, csv}` — `mode: "append"` pour ajouter à la suite, `mode: "replace"` pour remplacer tout le contenu de cette section pour ce projet (le frontend avertit avant confirmation, l'API elle-même n'écrase rien tant que l'en-tête n'est pas validé).
3. Un fichier `shows` réimporté ne recrée que des événements top-level — les blocs (montage/répétition/démontage) et le calendrier complet passent par le workflow 10 ci-dessous.

### Workflow 10 — Exporter/importer un projet complet, décision du 2026-08-04
1. `GET /api/projects/{id}/export/` télécharge un JSON complet et réimportable (ou `?format=xml` pour une version lecture seule) — toutes les tables du projet, assignations et déplacements compris.
2. `POST /api/projects/import/` avec ce fichier crée un **nouveau** projet (jamais n'écrase un projet existant) — utile pour archiver hors de l'app, migrer vers une autre instance, ou restaurer un état antérieur sous un nouveau nom.
3. Contrairement à `duplicate` (Workflow 8), qui démarre une nouvelle édition avec un calendrier vierge, l'export/import vise la fidélité complète — c'est la bonne opération pour une sauvegarde, pas pour préparer la prochaine édition d'un mandat.

### Workflow 11 — Imprimer une feuille et la partager, décision du 2026-08-08

1. Depuis la fiche tournée (ou spectacle, ou technicien), bouton « Partager / Imprimer ». Pour l'horaire d'une journée, le bouton est sur le Tableau de bord et la date se choisit dans le panneau.
2. Le panneau cherche d'abord un lien actif existant — **il ne publie rien juste parce qu'on l'a ouvert**. S'il n'y en a pas, il explique ce qu'un lien implique avant de proposer de le créer.
3. « Ouvrir le PDF » produit la feuille A4, code QR compris. « Copier l'adresse » sert à l'envoyer par courriel sans imprimer.
4. La personne qui reçoit la feuille scanne le code et tombe sur `/p/<token>` : la même feuille, à jour, sans compte, avec la date de lecture bien en vue pour la comparer à la date imprimée en pied de page.
5. Réimprimer plus tard donne le **même** code QR — les copies déjà distribuées restent valides. Pour couper l'accès, « Révoquer » dans le panneau ou dans Réglages → Liens de partage : cela invalide aussi les copies papier, d'où la confirmation explicite.

## 6. Explicitement hors scope (validé avec Samuel)

- Portail ou module de communication bidirectionnelle avec les vendors (reste par courriel).
- Table de tâches ou de notes de suivi dans l'app.
- Historique des changements d'assignation (seules les données actuelles sont conservées).
- Budget de location (prévu comme étape future, une fois le système de base en place).

## 7. Étapes futures (non incluses dans la V1)

- Génération automatisée de courriels de demande de location (via Claude ou script), pré-remplis avec les infos du spectacle.
- Module de budget de location attaché aux spectacles.
- Rôles utilisateurs plus granulaires si l'équipe grandit.
