# Schéma de base de données — RégiStock

> Base de données relationnelle : MySQL 8.0 managé (Railway).
> Scope : gestion interne de l'inventaire de matériel, assignation aux spectacles/répétitions, assignation des techniciens, détection de conflits d'horaire. Pas de gestion des communications vendors ni de tâches/notes (gérées dans d'autres outils).

---

## 1. `users`

Comptes ayant accès à l'outil (login via Google OAuth).

| Champ | Type | Description |
|---|---|---|
| id | INT, PK | Identifiant unique |
| email | VARCHAR | Email Google (identifiant de connexion) |
| name | VARCHAR | Nom complet |
| role | ENUM('admin','viewer') | Niveau d'accès — **purement d'affichage côté frontend** (`UtilisateursView.vue`) depuis le 2026-08-02, ne gate plus rien côté API (voir `is_staff_global` ci-dessous et `architecture.md` section 3) |
| is_staff_global | BOOLEAN (default false) | Ajouté le 2026-08-02 : accès de dépannage/support réservé à l'exploitant de la plateforme (Samuel), qui **court-circuite entièrement** le contrôle d'accès par projet (`HasProjectAccess`, voir section 14 et `architecture.md` section 3). Distinct d'un rôle `owner` de `project_memberships`, qui ne donne accès qu'à SES projets |
| created_at | DATETIME | Date de création du compte |
| django_user_id | INT, FK → auth_user.id (nullable) | Lien vers le compte `django.contrib.auth.User` créé automatiquement par django-allauth au premier login Google réussi. Sert à retrouver ce profil applicatif depuis la session Django authentifiée (voir `architecture.md` section 3). Nullable : distinct du superutilisateur Django (`/admin/`), qui n'a pas besoin de ce lien. |

---

## 2. `venues`

Lieux (salles, théâtres, sites de représentation, entrepôts). Isolés par projet — voir section 11 (`projects`).

| Champ | Type | Description |
|---|---|---|
| id | INT, PK | Identifiant unique |
| project_id | INT, FK → projects.id | Production à laquelle ce lieu appartient |
| name | VARCHAR | Nom du lieu |
| code | VARCHAR(4), nullable/vide | Code court (ex. `CHAP` pour Chapelle), saisi à la création ou ajouté après coup — voir note ci-dessous |
| address | VARCHAR | Adresse |
| contact_name | VARCHAR | Contact sur place |
| contact_info | VARCHAR | Téléphone / email du contact |
| notes | TEXT | Notes générales sur le lieu |
| display_order | INT (default 0) | Rang d'affichage dans le projet, réordonnable par glisser-déposer depuis la page Lieux (ajouté le 2026-08-05). 0 = non classé ; à égalité le tri se fait par nom, ce qui reproduit l'ordre alphabétique d'avant |
| is_storage | BOOLEAN (default false) | Lieu d'entreposage (entrepôt) plutôt qu'un vrai lieu de spectacle — voir règle d'exemption dans la section `show_materials` |
| latitude | DECIMAL(9,6), nullable | Coordonnée GPS (ex. copiée depuis Google Maps) — voir section 10, calcul de trajet |
| longitude | DECIMAL(9,6), nullable | Coordonnée GPS — voir latitude |
| color | VARCHAR(64), vide par défaut | Couleur d'affichage optionnelle des bandes représentant ce lieu (Parcours Matériel) — chaîne CSS libre (ex. `oklch(...)` ou hex du sélecteur natif). Vide = couleur générée automatiquement (palette `VENUE_PALETTE` cyclée par ordre d'apparition dans `ParcoursMaterielView.vue`). Ajouté le 2026-08-02 |

**Suppression d'un lieu** (décision du 2026-07-30) : **refusée** tant que le lieu est référencé par un spectacle, un déplacement ou du matériel qui en fait son origine. `Show.venue` et les deux FK de `Transport` sont en `PROTECT` (Django lèverait un `ProtectedError`, rendu en 500 par DRF sans traitement) ; `Material.venue` est en `SET_NULL`, mais le laisser vider silencieusement l'origine contredirait la règle du lieu obligatoire — il bloque donc aussi. `VenueViewSet.destroy` renvoie un 400 avec le décompte de chaque catégorie (`shows`, `transports`, `materials`).

**Code court** (décision du 2026-07-19) : `code` (jusqu'à 4 caractères, normalisé en majuscules à l'enregistrement) sert d'identifiant rapide pour un lieu — ex. `CHAP` pour la Chapelle. Optionnel, unique par projet si renseigné (validé par `VenueSerializer`, pas une contrainte en base — plusieurs lieux sans code coexistent normalement dans un même projet). Réutilisé sur `TransportSerializer` (`origin_venue_code`/`destination_venue_code`) pour un affichage compact du départ/arrivée d'un déplacement. Côté frontend (depuis le 2026-07-30) : saisi dans le formulaire d'ajout de `LieuxView.vue`, et modifiable après coup sur la fiche du lieu (`LieuDetailView.vue`, `PATCH` du seul champ `code`).

---

## 3. `materials`

Inventaire de matériel. Supporte une hiérarchie parent/enfant (kits contenant des composants) et une catégorisation par type d'usage. Isolé par projet — voir section 11 (`projects`).

| Champ | Type | Description |
|---|---|---|
| id | INT, PK | Identifiant unique |
| project_id | INT, FK → projects.id | Production à laquelle ce matériel appartient |
| name | VARCHAR | Nom du matériel |
| description | TEXT | Description / détails techniques |
| category_id | INT, FK → material_categories.id (nullable) | Catégorie de matériel — était un ENUM figé jusqu'au 2026-07-30, voir section 13 |
| parent_material_id | INT, FK → materials.id (nullable) | Matériel parent (ex. "Kit Audio" est parent de "Micro sans fil") |
| is_kit_parent | BOOLEAN (default false) | Active ce matériel comme parent de kit possible — voir note « Parent de kit explicite » ci-dessous. Ajouté le 2026-08-02 |
| venue_id | INT, FK → venues.id (nullable en base, **obligatoire via l'API**) | Lieu d'**origine** du matériel — son point de départ et l'endroit où il doit revenir en fin de projet |
| ownership_status | ENUM('owned','rental') | Propriété ou location générale |
| quantity | INT (default 1) | Quantité totale possédée de ce matériel identique (ex. 20 rallonges électriques) — voir note quantité ci-dessous |
| is_active | BOOLEAN (default true) | Permet de désactiver un matériel qu'on n'utilise plus (ex. un vieux rideau) sans le supprimer — voir note ci-dessous |
| notes | TEXT | Notes diverses |

**Logique hiérarchique** : un matériel "kit" (parent) peut être assigné en bloc à un spectacle, ou ses composants (enfants) peuvent être assignés individuellement pour un suivi plus granulaire.

**Quantité et hiérarchie kit** (décision du 2026-07-19) : `quantity` permet de posséder plusieurs exemplaires identiques d'un même matériel (ex. 20 rallonges électriques) sans créer un item par unité physique — voir `show_materials` pour l'allocation partielle. Un matériel qui participe à une hiérarchie kit (a un `parent_material_id`, ou est lui-même parent d'au moins un composant) doit obligatoirement rester à `quantity = 1` : un kit reste une unité conceptuelle unique, la notion de capacité partagée ne s'applique qu'au matériel autonome. Contrainte appliquée par `MaterialSerializer.validate()`, pas en base.

**Matériel désactivé** (décision du 2026-07-19) : `is_active = false` retire un matériel qu'on n'utilise plus (ex. un vieux rideau) des listes d'inventaire courantes sans le supprimer — l'historique des assignations existantes (`show_materials`) reste intact. `GET /api/materials/` ne retourne que `is_active = true` par défaut ; ajouter `?include_inactive=true` pour tout revoir. La consultation par id reste toujours accessible peu importe le statut.

**Isolation par projet** (décision du 2026-07-19, étendue à `category` le 2026-07-30) : `parent_material`, `venue` et `category` (si renseignés) doivent obligatoirement appartenir au même `project` que le matériel lui-même — validé par `MaterialSerializer.validate()`, pas en base.

**Lieu d'origine obligatoire** (décision du 2026-07-30) : `venue` était optionnel ; il est désormais **exigé par `MaterialSerializer`** à la création comme à la mise à jour, et ne peut plus être vidé. Sans point de départ, la timeline de position (`transport_coherence.py`) ne peut rien vérifier — ni la disponibilité au départ d'un transport, ni le retour en fin de projet. Le champ reste **nullable en base** pour ne pas invalider l'historique déjà saisi et pour garder l'issue `origine_inconnue` significative ; c'est l'API qui impose la règle, pas une contrainte DB.

**Catégorie devenue une table** (décision du 2026-07-30) : `category` était un `VARCHAR` restreint à 9 slugs codés en dur dans le modèle Django (`CATEGORY_CHOICES`), avec leurs couleurs codées en dur côté Vue — donc impossible d'ajouter « Machinerie » sans redéployer. C'est maintenant une FK vers `material_categories` (section 13). Migration `0014_material_category` : création de la table, seed des 9 catégories historiques pour chaque projet existant, remappage du matériel, puis remplacement du champ texte. Ce n'est **pas** un retour du modèle `Department` retiré la veille — une catégorie ne porte ni responsable ni contact, seulement un nom et une couleur.

**Parent de kit explicite** (décision du 2026-08-02) : `is_kit_parent` doit être coché sur un matériel avant qu'un autre puisse le choisir comme `parent_material` — le sélecteur « Fait partie du kit » du frontend ne propose que les matériels ainsi activés, et `MaterialSerializer.validate_parent_material` refuse aussi côté API un parent qui n'a pas ce drapeau. Un matériel à `quantity > 1` ne peut pas être marqué `is_kit_parent` (même contrainte que la hiérarchie kit ci-dessus). Décision assumée de ne pas basculer automatiquement les kits déjà existants (matériels ayant déjà des composants) à l'ajout de ce champ — à réactiver manuellement au cas par cas.

**Suppression d'un matériel** (2026-08-04) : `ShowMaterial.material` et `TransportMaterial.material` sont en `CASCADE` — supprimer un matériel déjà utilisé n'est **pas bloqué**, contrairement à `MaterialCategory` qui reste en `PROTECT`. Un composant de kit n'est pas perdu mais seulement **détaché** (`parent_material` en `SET_NULL`). `MaterialSerializer.deletion_impact` (lecture seule) expose les décomptes `shows`/`transports`/`components` pour que le frontend annonce ce qui va disparaître ou se détacher avant confirmation.

**Département retiré** (décision du 2026-07-29) : le matériel portait auparavant un `department_id` (FK vers une table `departments` — responsable/contact par type de matériel), retiré à la demande de Samuel : `category` suffisait déjà à classer le matériel, et faisait doublon en pratique avec les noms de département (Son/Éclairage/etc. des deux côtés). Voir migration `0013_remove_department`.

---

## 4. `shows`

Fiches spectacles — regroupe répétitions et représentations avec leurs horaires et le lieu. Isolées par projet — voir section 11 (`projects`).

| Champ | Type | Description |
|---|---|---|
| id | INT, PK | Identifiant unique |
| project_id | INT, FK → projects.id | Production à laquelle ce spectacle appartient — doit correspondre au projet de `venue_id` |
| title | VARCHAR, **nullable** (`blank=True`) | Titre de l'événement — obligatoire pour un événement top-level (validé par `ShowSerializer`, pas en base). Sur un bloc rattaché (voir plus bas), c'est une **précision optionnelle** seulement (ex. « technique »), plus le nom complet — voir *(dérivé)* `display_title` |
| venue_id | INT, FK → venues.id | Lieu de l'événement |
| event_type | ENUM('rehearsal','performance','storage','setup','teardown') | Répétition, représentation, entreposage, montage ou démontage (voir notes ci-dessous) |
| start_datetime | DATETIME | Début (heure réelle) |
| end_datetime | DATETIME | Fin (heure réelle) |
| buffer_before_minutes | INT (default : voir `settings.default_buffer_before_minutes`) | Marge avant (déplacement/installation) |
| buffer_after_minutes | INT (default : voir `settings.default_buffer_after_minutes`) | Marge après (déplacement/désinstallation) |
| notes | TEXT | Notes générales |

**Blocs rattachés** (décision du 2026-07-31) : `parent_show_id` accroche à un événement une plage de **montage** ou de **répétition** en amont et une de **démontage** en aval — trois blocs consécutifs au plus, dans le même lieu. Choix de conception : un bloc est un `shows` **complet**, pas une table parallèle. Il a donc son horaire, son matériel (`show_materials`), ses techniciens (`show_technicians`), ses transports, et participe à la détection de conflits comme n'importe quel événement — un montage occupe la salle et mobilise une équipe, exactement comme un spectacle. Contraintes validées par `ShowSerializer` : un seul niveau de hiérarchie (un bloc ne peut pas en avoir), même projet et même lieu que l'événement principal. `CASCADE` : supprimer l'événement supprime ses blocs, qui n'ont pas de sens seuls.

**Titre dynamique d'un bloc** (décision du 2026-08-02, révise le comportement d'origine du 2026-07-31) : le titre d'un bloc était généré une fois à sa création (« Répétition — Nom du spectacle », recopié dans `title`) et ne se répercutait plus si l'événement était renommé ensuite. La property *(dérivée, non stockée)* `display_title` recalcule ce titre à CHAQUE lecture à partir de `parent_show.title` courant — aucune copie à garder synchronisée. Sur un événement top-level, `display_title` est simplement égal à `title`. Exposée en lecture seule par `ShowSerializer` en plus de `title`, qui reste éditable (nom complet pour un événement, précision optionnelle pour un bloc).

**Ressources — deux régimes** (décision du 2026-07-31, précisée le même jour). Un bloc de **répétition** rattaché est **autonome** : il porte ses propres `show_materials`/`show_technicians`, recopiés de l'événement à sa création (`ShowSerializer.create`) puis modifiables sans que rien ne redescende ensuite. Une répétition est un vrai temps de travail, où l'on n'utilise pas nécessairement tout le matériel du spectacle ni la même équipe. Elle n'étire donc pas la fenêtre d'engagement de son événement — l'y inclure mettrait celui-ci en conflit avec sa propre répétition. Le champ dérivé `inherits_resources` (voir `Show.INHERITING_PHASE_TYPES`) distingue les deux cas, et `ShowSerializer.get_phases` l'expose avec les décomptes du bloc.

Pour le **montage** et le **démontage**, en revanche, le matériel et les techniciens sont **ceux de son événement** — un montage mobilise l'équipe et l'équipement du spectacle qu'il prépare. Implémenté par une **fenêtre d'engagement étendue** (`Show.engagement_start`/`engagement_end` : de l'ouverture du premier bloc à la fermeture du dernier) plutôt qu'en recopiant les assignations dans chaque bloc — une seule vérité, qui ne peut pas diverger quand on modifie l'événement après coup. Conséquences : un technicien pris ailleurs **pendant le montage** est bien détecté en conflit, le matériel est réservé sur toute la période, et `ShowMaterialSerializer`/`ShowTechnicianSerializer` **refusent** une assignation directe sur ces deux types de bloc en renvoyant vers l'événement.

**Exclusion de famille sur le matériel et les techniciens** : `get_material_conflicts` et `get_technician_conflicts` ignorent tous les membres de la famille (`Show.family_ids`), et plus seulement le spectacle courant. Un événement et ses blocs forment une seule unité de travail : la copie portée par une répétition rattachée entrerait sinon en conflit avec l'événement dès qu'un buffer fait toucher les deux fenêtres — le cas par défaut. Pour un spectacle sans bloc, `family_ids` se réduit à `{show.id}` : comportement d'origine inchangé.

À ne pas confondre avec `effective_start`/`effective_end`, qui restent la fenêtre du seul créneau et servent au conflit de **lieu** — un bloc occupe la salle pour son propre compte.

**Blocs et buffers — pas de double comptage** : un bloc est collé à son événement, donc leurs fenêtres *effectives* se chevauchent dès qu'un buffer est renseigné. `Show.family_ids` (l'événement + tous ses blocs) est passé à `get_venue_conflicts` en `exclude_family_ids` pour éviter qu'un montage soit signalé en conflit de lieu avec le spectacle qu'il prépare. Les buffers restent pour les événements sans bloc explicite ; l'exclusion ne vaut qu'entre membres d'une même famille — un vrai voisin dans la même salle est toujours détecté.

**Répétitions indépendantes** : elles n'ont jamais eu besoin de ce mécanisme — un `shows` de type `rehearsal` avec ses propres horaires, sans `parent_show_id`, suffit (ex. une répétition la veille dans une autre salle).

**Suppression d'un spectacle** (décision du 2026-07-30) : **autorisée**, mais elle emporte en cascade ses assignations (`show_materials`, `show_technicians`) ET ses déplacements (`transports.show_id` est en `CASCADE`). Le matériel et les techniciens eux-mêmes survivent — seules les assignations disparaissent. `ShowSerializer.deletion_impact` expose les trois décomptes pour que la confirmation du frontend annonce précisément ce qui va disparaître, proposition auto-générée comprise.

**Fenêtre effective d'utilisation** = `start_datetime - buffer_before` à `end_datetime + buffer_after`. C'est cette fenêtre qui est utilisée pour la détection de conflits.

**Entreposage** : un `show` dont le `venue_id` pointe vers un lieu avec `is_storage = true` représente une période où le matériel est simplement rangé — voir la règle d'exemption dans `show_materials` ci-dessous. `event_type = 'storage'` est la convention pour étiqueter ce genre de fiche (mais c'est bien `venue.is_storage` qui déclenche l'exemption, pas `event_type`).

**Conflit de lieu** (décision du 2026-07-19) : deux `shows` ne peuvent pas se chevaucher dans le **même** `venue_id` — occupation physique exclusive, indépendante de tout matériel ou technicien partagé (ceux-là restent en conflit peu importe le lieu, voir sections 5 et 7). Bloquant + `force: true`, même exemption d'entreposage que le matériel (une même `venue` d'entrepôt peut recevoir plusieurs fiches de rangement qui se chevauchent). Voir `conflicts.get_venue_conflicts` et `architecture.md`, section 4d.

---

## 5. `show_materials`

Table d'association — assigne du matériel à un spectacle/répétition. Contient aussi l'information de location ponctuelle (louée à un fournisseur externe pour ce spectacle précis).

| Champ | Type | Description |
|---|---|---|
| id | INT, PK | Identifiant unique |
| show_id | INT, FK → shows.id | Spectacle concerné |
| material_id | INT, FK → materials.id | Matériel assigné |
| quantity | INT (default 1) | Quantité de ce matériel assignée à ce spectacle (ex. 5 des 20 rallonges en inventaire) |
| is_rental | BOOLEAN | Ce matériel est-il loué spécifiquement pour ce spectacle? |
| rental_vendor | VARCHAR (nullable) | Nom du fournisseur externe (si is_rental = true) |

**Règle de conflit — matériel parent/enfant** : pour un matériel parent et ses enfants (hiérarchie kit, toujours à `quantity = 1`), le système refuse (bloquant, avec possibilité de forcer via `force: true`) l'assignation si la fenêtre effective (voir `shows`) chevauche celle d'un autre `show_materials` existant pour un membre de la même famille.

**Règle de conflit — capacité (décision du 2026-07-19)** : pour le matériel exact (même `material_id`), la contrainte n'est plus binaire mais une capacité partagée : la somme des `quantity` déjà assignées sur des fenêtres qui chevauchent celle du nouveau `show_materials` ne peut pas dépasser `materials.quantity`. Ex. 20 rallonges en inventaire, 12 déjà assignées à un spectacle qui chevauche : on peut en assigner jusqu'à 8 de plus avant blocage. Demander plus que `materials.quantity` au total (même sans aucun chevauchement) est rejeté d'emblée et n'est **pas** overridable par `force` (erreur de données, pas un conflit d'horaire) ; un dépassement de capacité dû à un chevauchement, lui, reste bloquant avec possibilité de forcer via `force: true`, comme les autres conflits.

**Exemption d'entreposage** (décision du 2026-07-18) : cette règle de conflit est entièrement ignorée dès qu'un des deux `show_materials` comparés est rattaché à un `show` dont le `venue.is_storage = true`. Le matériel qui est simplement rangé en entrepôt est considéré disponible — il n'entre jamais en conflit avec un autre lieu, et assigner du matériel à un entrepôt ne bloque jamais, même s'il est par ailleurs utilisé sur un vrai spectacle au même moment. Cette exemption ne s'applique qu'au matériel, pas aux techniciens (`show_technicians`) : un technicien assigné à un `show` d'entrepôt (ex. pour de l'inventaire) reste soumis à la détection de conflit normale.

---

## 6. `technicians`

Isolés par projet — voir section 11 (`projects`).

| Champ | Type | Description |
|---|---|---|
| id | INT, PK | Identifiant unique |
| project_id | INT, FK → projects.id | Production à laquelle ce technicien appartient |
| name | VARCHAR | Nom du technicien |
| contact_info | VARCHAR | Téléphone / email |
| specialty | VARCHAR | Spécialité (son, éclairage, régie, etc.) |
| notes | TEXT | Notes diverses |

---

## 7. `show_technicians`

Table d'association — assigne des techniciens à un spectacle/répétition.

| Champ | Type | Description |
|---|---|---|
| id | INT, PK | Identifiant unique |
| show_id | INT, FK → shows.id | Spectacle concerné |
| technician_id | INT, FK → technicians.id | Technicien assigné |

**Règle de conflit** : même logique que pour le matériel — un technicien ne peut pas être assigné à deux spectacles dont les fenêtres effectives (horaire + buffers) se chevauchent. Depuis l'ajout de `transports` (section 8), cette règle croise aussi les déplacements du technicien : il ne peut pas non plus être sur un spectacle en même temps qu'il fait une livraison/ramassage.

---

## 8. `transports`

Table ajoutée le 2026-07-18 (hors des 8 tables initiales). **Refonte en tournées multi-arrêts le 2026-08-04 (décision de Samuel)** : un `transports` n'est plus un trajet « lieu A → lieu B » mais une **tournée** — une séquence ordonnée d'arrêts (`transport_stops`, section 8bis) : arrêt 1 on ramasse du matériel, arrêt 2 on en ajoute, arrêt 3 on décharge, etc. Les anciens champs `transport_type` (livraison/ramassage — retiré sans équivalent, il n'avait plus de sens au niveau d'une tournée), `origin_venue_id`, `destination_venue_id` et `estimated_duration_minutes` ont été supprimés (migration `0025_transport_stops` : chaque transport existant devient une tournée à 2 arrêts, fenêtres dérivées identiques).

| Champ | Type | Description |
|---|---|---|
| id | INT, PK | Identifiant unique |
| show_id | INT, FK → shows.id | Spectacle desservi par cette tournée |
| status | ENUM('confirmed','to_approve') (default 'confirmed') | Cycle de vie (ajouté le 2026-07-24) — voir note ci-dessous |
| scheduled_datetime | DATETIME, **nullable** | Heure de départ de la tournée (départ du premier arrêt) — nullable depuis le 2026-07-24 (une proposition `to_approve` n'a pas encore d'heure). Obligatoire pour un `status='confirmed'` (validé par `TransportSerializer`) |
| notes | TEXT | Notes diverses |
| *(dérivés)* origin_venue / destination_venue (+ noms, codes) | — | Lieux des PREMIER et DERNIER arrêts, exposés en lecture pour compat avec l'affichage A → B ; acceptés en **écriture** comme chemin de compat (voir note API ci-dessous) |
| *(dérivé)* estimated_duration_minutes | INT | Durée TOTALE de la tournée = somme des `travel_minutes_from_previous` des arrêts — la clé API garde son nom historique |

**Horaire (décision du 2026-08-04)** : UNE heure d'ancrage (`scheduled_datetime`) + une durée par segment (portée par chaque arrêt) — les heures d'arrivée aux arrêts sont **dérivées** (`Transport.arrival_at`), et décaler toute la tournée reste un seul champ à changer (le glisser-déposer du Dashboard en dépend).

**Fenêtre effective** = `scheduled_datetime` à l'arrivée au dernier arrêt (`scheduled_datetime + somme des segments`) — pas de buffers séparés, les durées de segment couvrent déjà trajet + chargement/déchargement. Les techniciens affectés sont engagés sur toute la tournée.

**Compat API ancien contrat A → B** : `POST` avec `origin_venue`/`destination_venue` (sans `stops`) crée une tournée à 2 arrêts ; `PATCH` de ces champs retouche le lieu du premier/dernier arrêt (réestimation du segment touché) ; `PATCH` de `estimated_duration_minutes` seul ajuste l'unique segment d'une tournée à 2 arrêts (refusé s'il changerait la valeur d'une tournée plus longue — ambigu). Le frontend actuel reste fonctionnel tel quel en attendant sa refonte.

**Techniciens affectés** (décision du 2026-07-30) : *qui* fait le déplacement est décrit par la table de liaison `transport_technicians` (section 13bis), pas directement ici. Le champ `technician_id` (FK unique) a été retiré : un déplacement peut mobiliser plusieurs personnes, comme un spectacle. Voir migration `0015_transport_technicians`.

**Règle de conflit** : **chaque** technicien affecté à un `transport` ne peut pas être engagé par ailleurs (spectacle OU autre déplacement) sur une fenêtre qui chevauche celle-ci — bloquant, avec possibilité de forcer via `force: true`, comme pour `show_materials`/`show_technicians`. Un seul bandeau d'erreur regroupe les conflits de toutes les personnes affectées, donc un seul « Forcer » côté frontend. Cette table ne participe PAS à l'exemption d'entreposage (section 5) : un déplacement est toujours un vrai engagement de temps pour les techniciens qui le font.

**Matériel transporté** (décision du 2026-07-24) : *quel* matériel monte dans un déplacement est décrit par la table de liaison `transport_materials` (section 9), pas directement ici. Ce lien alimente le module de cohérence des emplacements (voir section 9 et `transport_coherence.py`).

**Statut `to_approve` / `confirmed`** (décision du 2026-07-24) : un déplacement `confirmed` est créé/complété par l'utilisateur — il a une heure, participe à la timeline de position (cohérence) et à la détection de conflit du technicien. Un déplacement `to_approve` est une **proposition générée automatiquement** (voir `transport_autogen.py`) quand du matériel est requis à un lieu où rien ne l'amène : lieux + matériel préremplis, mais heure/technicien à saisir. Une proposition est affichée en orange et ne « livre » rien tant qu'elle n'est pas confirmée (elle n'entre pas dans la timeline de position). Deux façons de créer un transport : manuellement (`confirmed` d'emblée) ou automatiquement (`to_approve`, à compléter puis confirmer).

---

## 8bis. `transport_stops`

Table ajoutée le 2026-08-04 (refonte tournées) — les arrêts d'une tournée, dans l'ordre.

| Champ | Type | Description |
|---|---|---|
| id | INT, PK | Identifiant unique |
| transport_id | INT, FK → transports.id (CASCADE) | Tournée à laquelle cet arrêt appartient |
| venue_id | INT, FK → venues.id (PROTECT) | Lieu de l'arrêt — PROTECT : un lieu référencé par un arrêt bloque la suppression du lieu (même règle que `shows.venue_id`) |
| order | INT | Position dans la séquence (0 = départ) — `unique_together (transport, order)` |
| travel_minutes_from_previous | INT (default 0) | Durée du segment depuis l'arrêt précédent (trajet + chargement/déchargement) — toujours 0 sur le premier arrêt ; pré-remplie via Google Routes (section 4ter), sinon `settings.default_transport_duration_minutes` |

**Heure d'arrivée** : dérivée, jamais stockée — `scheduled_datetime` de la tournée + cumul des segments jusqu'à l'arrêt inclus (`Transport.arrival_at`). Exposée en lecture (`arrival_datetime`) par `TransportStopSerializer`.

**Règles** : au moins 2 arrêts par tournée ; deux arrêts CONSÉCUTIFS ne peuvent pas partager le même lieu ; un même lieu peut revenir plus loin dans la séquence — c'est ce qui permet une tournée aller-retour (entrepôt → salle → entrepôt) en une seule fiche. À l'écriture (`TransportSerializer.stops`), l'ordre est la position dans la liste envoyée ; la resynchronisation se fait EN PLACE par position (mêmes ids — les lignes de matériel qui pointent un arrêt survivent à une retouche de lieu/durée). Retirer un arrêt encore utilisé par une ligne de matériel est refusé (sauf si `materials` est refourni dans la même requête).

---

## 9. `transport_materials`

Table de liaison ajoutée le 2026-07-24 (module transport) — relie un `transport` au matériel (et à la quantité) qu'il transporte. Sans elle, un `transport` savait *quand* et *où* le matériel bougeait, mais pas *lequel* montait dans le camion.

| Champ | Type | Description |
|---|---|---|
| id | INT, PK | Identifiant unique |
| transport_id | INT, FK → transports.id (CASCADE) | Tournée qui transporte ce matériel |
| material_id | INT, FK → materials.id (CASCADE) | Matériel transporté |
| quantity | INT (default 1) | Quantité transportée sur cette portion (ex. 8 des 20 rallonges) |
| load_stop_id | INT, FK → transport_stops.id (CASCADE) | **Arrêt de chargement** (2026-08-04) — le matériel monte dans le camion à l'arrivée de la tournée à cet arrêt ; doit précéder `unload_stop` |
| unload_stop_id | INT, FK → transport_stops.id (CASCADE) | **Arrêt de déchargement** — le matériel descend à l'arrivée à cet arrêt |

**Portion de tournée (2026-08-04)** : chaque ligne associe le matériel à SA portion de la séquence — c'est une donnée stockée, pas une reconstruction d'affichage. `unique_together` couvre le quadruplet `(transport, material, load_stop, unload_stop)` : un même matériel peut apparaître deux fois dans une tournée pour une répartition (8 rallonges chargées au départ, 3 déposées à l'arrêt 1 et 5 à l'arrêt 2 = deux lignes) ou un relais (A → B puis B → C dans le même véhicule).

**Écriture** : géré en écriture imbriquée sur `TransportSerializer` via le champ `materials` (liste de `{material, quantity, load_stop_order?, unload_stop_order?}` — positions 0-indexées dans la séquence ; absentes, la ligne couvre la tournée entière, ce qui garde l'ancien contrat `{material, quantity}` fonctionnel). Fournir `materials` lors d'un PATCH remplace intégralement les lignes du transport ; l'omettre les laisse inchangées. Validations (non overridables par `force`, ce sont des erreurs de données) : chaque matériel doit appartenir au même projet que le déplacement, `load < unload`, pas deux lignes identiques sur la même portion, et la quantité PAR LIGNE ne peut dépasser `materials.quantity` (pas de somme par matériel — un relais réutilise les mêmes unités physiques ; le réalisme spatial est jugé par le rapport de cohérence).

**Module de cohérence des emplacements** (`transport_coherence.py`, non bloquant) : à partir de ce lien, le module reconstruit une *timeline* de position par matériel — départ au lieu d'entreposage `materials.venue`, puis application chronologique des LIGNES de tournée (2026-08-04) : chaque ligne déplace sa quantité du lieu de son arrêt de chargement (le matériel doit y être disponible à l'heure d'ARRIVÉE du camion à cet arrêt) vers celui de son arrêt de déchargement (réputé « arrivé » à l'heure d'arrivée à ce dernier). Il produit un **rapport** (jamais un blocage) exposé par `GET /api/shows/{id}/transport-coherence/` (centré sur un spectacle) et `GET /api/projects/{id}/transport-coherence/` (toute la production). Trois types d'incohérence :

- `materiel_non_livre` : un `show_material` requiert du matériel à un lieu où il n'est pas présent (en quantité suffisante) au début de la fenêtre effective — aucun transport **confirmé** ne l'y amène. Répond à « tout déplacement de matériel est associé à un transport ». Porte un champ `etat` : `propose` (orange — une proposition auto `to_approve` couvre le déplacement, `proposal_transport_id` la pointe) ou `manquant` (rouge — rien, même proposé, ne le couvre).
- `origine_incoherente` : une tournée prétend charger du matériel à un arrêt où ce matériel n'est pas disponible à l'heure d'arrivée du camion. Répond à « tout est possible sur les emplacements prévus ».
- `origine_inconnue` : le matériel n'a pas de lieu d'entreposage (`materials.venue` vide), sa position de départ est inconnue — signalé une seule fois, impossible à suivre.

**Portée assumée — aller seulement** (décision du 2026-07-24) : le module vérifie la *présence* du matériel là où il est requis (livraisons). Il n'exige PAS qu'un déplacement de retour précis ramène le matériel à son entrepôt d'origine (pas de boucle fermée) — tout déplacement, retour compris, est pris en compte dans la timeline.

**Retour à l'origine en fin de projet** (ajout du 2026-07-30) : quatrième type d'incohérence, `retour_manquant`. À l'**horizon du projet** — `projects.end_date` si renseignée (fin de journée), sinon la fin effective du dernier événement du projet — chaque matériel doit se retrouver en totalité à son `venue` d'origine. Sinon l'issue liste la quantité manquante et les lieux où le reliquat se trouve encore. Non bloquant comme le reste du rapport. Cela **révise la portée « aller seulement »** décidée le 2026-07-24 : on ne vérifie toujours pas qu'un `pickup` précis existe pour chaque livraison, mais on contrôle le résultat net à la fin.

**Disponibilité par arrêt** (ajout du 2026-07-30, par-arrêt depuis le 2026-08-04) : la même timeline sert aussi *avant* la saisie, via `get_venue_material_availability()` et `GET /api/transports/{id}/material-availability/?stop=<position>` — « quel matériel est présent à cet arrêt à l'heure d'arrivée du camion, en quelle quantité ». Sans paramètre `stop`, le premier arrêt (l'ancien comportement « lieu de départ », intact pour la modale actuelle). Le frontend grise et rend non sélectionnable ce qui n'est pas sur place. Le blocage est **côté interface seulement** : l'API accepte toujours un chargement incohérent (créé par l'API brute, ou devenu faux après un changement d'horaire), que le rapport ci-dessus continue de signaler en `origine_incoherente`. Le transport est exclu de son propre calcul ; sans `scheduled_datetime`, l'endpoint renvoie `at: null` et tout le stock comme disponible.

**Exemption d'entreposage** : un `show_material` rattaché à un `show` d'entrepôt (`venue.is_storage=True`) n'exige aucune livraison — cohérent avec l'exemption de la section 5.

**Génération automatique des propositions** (`transport_autogen.py`, décision du 2026-07-24) : plutôt que d'attendre que l'utilisateur crée chaque transport, l'app **génère automatiquement** un `transports` en `status='to_approve'` pour chaque déplacement manquant détecté. Déclenchement par signaux (`regenerate_signals.py`), à chaque changement pertinent : assignation de matériel (`show_materials`), transport confirmé, ligne `transport_materials` d'un transport confirmé, ou horaire/lieu d'un `shows`. La proposition est une tournée simple à 2 arrêts (2026-08-04), préremplie avec le lieu de départ (dernière position connue du matériel — origines chaînées entrepôt→A puis A→B), le lieu d'arrivée (le lieu du spectacle) et le matériel (groupé : une proposition par couple origine/spectacle peut porter plusieurs matériels ; chaque ligne couvre la tournée entière). Fusionner des propositions en une vraie tournée multi-arrêts reste un geste manuel (phase ultérieure, décision du 2026-08-04). Régénération = *resync* idempotent des seules propositions `to_approve` (pas de mémoire de rejet — décision Samuel : on recalcule à chaque fois ; les transports confirmés ne sont jamais touchés). L'utilisateur complète (heure, technicien) puis confirme, ce qui fait passer la proposition de l'orange au vert.

**Conflit de technicien sur un transport** (rappel) : reste **bloquant + `force`** comme avant (section 8 / `architecture.md` section 4). Le champ dérivé `has_technician_conflict` sur `TransportSerializer` expose l'info en lecture seule pour l'indicateur orange du frontend, y compris pour une affectation créée avec `force: true` — il vaut `true` dès qu'**au moins une** des personnes affectées est en conflit (2026-07-30).

**Déplacement vide** : le champ dérivé `is_empty` sur `TransportSerializer` (lecture seule) vaut `true` si le déplacement ne transporte aucun matériel — pour un indicateur « camion vide » côté frontend (le contenu détaillé reste visible via `materials`).

---

## 10. `settings`

Table ajoutée le 2026-07-18 (hors des 8 tables initiales) — **singleton** : une seule ligne (id=1), toujours forcée par le modèle (`Settings.load()`/`save()`). Centralise des valeurs par défaut et des préférences d'affichage pour la future page de réglages du frontend, plutôt que de les coder en dur.

| Champ | Type | Description |
|---|---|---|
| id | INT, PK | Toujours 1 |
| default_buffer_before_minutes | INT (default 60) | Valeur proposée par défaut pour `shows.buffer_before_minutes` à la création |
| default_buffer_after_minutes | INT (default 60) | Valeur proposée par défaut pour `shows.buffer_after_minutes` à la création |
| default_transport_duration_minutes | INT (default 60) | Valeur proposée par défaut pour `transports.estimated_duration_minutes` à la création |
| date_format | ENUM('DMY','MDY') | Format d'affichage des dates côté frontend (JJ/MM/AAAA vs MM/DD/YYYY) |
| time_format | ENUM('24h','12h') | Format d'affichage des heures côté frontend |
| transport_color | VARCHAR(64) (default `oklch(0.64 0.21 340)`) | Couleur des déplacements confirmés (Dashboard, Parcours Matériel) — ajouté le 2026-08-02 |
| event_color_rehearsal | VARCHAR(64) (default `oklch(0.8 0.13 85)`) | Couleur du type de spectacle Répétition |
| event_color_performance | VARCHAR(64) (default `oklch(0.75 0.13 320)`) | Couleur du type de spectacle Représentation |
| event_color_storage | VARCHAR(64) (default `rgba(var(--fg-rgb),.6)`) | Couleur du type de spectacle Entreposage |
| event_color_setup | VARCHAR(64) (default `oklch(0.75 0.13 165)`) | Couleur du type de bloc Montage |
| event_color_teardown | VARCHAR(64) (default `oklch(0.7 0.11 255)`) | Couleur du type de bloc Démontage |
| event_type_order | VARCHAR(200), vide par défaut | Ordre d'affichage des types, en CSV (ex. `rehearsal,setup,performance,teardown,transport,storage`) — vide = ordre par défaut. Ajouté le 2026-08-02 |

**Ordre des types (2026-08-02)** : `event_type_order` porte l'ordre dans lequel les types apparaissent — dans la section « Couleurs » des Réglages (où il se réordonne par glisser-déposer) ET dans les puces de filtre du Tableau de bord et de Spectacles. Stocké en CSV plutôt qu'en table dédiée : c'est une préférence d'affichage à six valeurs, du même ordre de grandeur que `date_format`. Exposé par l'API comme une **liste**, pas comme la chaîne brute.

Toute lecture passe par `Settings.event_type_order_list`, qui garantit une liste complète et sans doublon : une clé inconnue est ignorée, une clé manquante rajoutée à sa place canonique. C'est ce qui empêche une valeur écrite par une version antérieure — ou l'arrivée d'un 7e type plus tard — de faire disparaître une ligne de réglages ou une puce de filtre. Côté écriture, `SettingsSerializer` refuse les doublons et les types inconnus, mais **accepte une liste incomplète**, pour qu'un client qui ignore un futur type ne l'efface pas en enregistrant l'ordre de ceux qu'il connaît.

**Note technique** : les valeurs par défaut de `shows`/`transports` ci-dessus ne sont pas de simples constantes — elles sont lues dynamiquement depuis cette table à chaque création (voir `inventory/models.py`, callables `_default_buffer_before_minutes` etc.), pour que changer un réglage ici s'applique immédiatement aux nouvelles fiches, sans redéploiement.

**Couleurs (2026-08-02)** : les 6 champs `*_color` couvrent les bandes qui ne
sont rattachées à aucune fiche éditable (contrairement à `venues.color` et
`material_categories.color`) — transport confirmé + les 5 types de
`shows.event_type`, jusqu'ici dupliqués en dur dans 4 fichiers Vue distincts.
Chaîne CSS libre, même convention que `venues.color`
(`frontend/src/composables/useEventColors.js` les pose comme CSS custom
properties `--transport`/`--event-*` sur `<html>`, consommées via
`frontend/src/constants/eventTypeMeta.js` — un seul chargement pour toute
l'app). Volontairement exclues : les couleurs sémantiques (conflit rouge,
à-approuver orange, statut OK vert du Dashboard) — non stockées ici, pas de
risque de les rendre illisibles par erreur.

---

## 11. `projects`

Table ajoutée le 2026-07-19 (hors des 8 tables initiales) à la demande de Samuel : il travaille en parallèle sur plusieurs productions qui n'ont rien en commun (compagnies de danse, musées, biennales comme CINARS/Parcours Danse/Furies). Une `project` regroupe tout le travail propre à une production précise.

| Champ | Type | Description |
|---|---|---|
| id | INT, PK | Identifiant unique |
| name | VARCHAR | Nom de la production |
| client_name | VARCHAR (nullable) | Compagnie ou organisation cliente, si pertinent |
| status | ENUM('active','archived') (default 'active') | Une production terminée s'archive plutôt que de se supprimer — voir note ci-dessous |
| start_date | DATE, nullable | Date de début de la production — saisie dans Réglages |
| end_date | DATE, nullable | Date de fin — sert d'**horizon** au contrôle de retour du matériel (section 9). Sans elle, l'app retombe sur la fin du dernier événement du projet |
| notes | TEXT | Notes diverses |
| created_at | DATETIME | Date de création |

**Isolation par projet** : `venues`, `material_categories`, `materials`, `technicians` et `shows` portent chacun un `project_id` obligatoire. `settings` reste **commun à tous les projets** (décision explicite de Samuel) — voir section 10.

**Suppression d'un projet** (décision du 2026-08-04, révise l'affirmation « impossible de supprimer » qui vivait ici avant cette date) : ces 5 FK sont passées de `on_delete=PROTECT` à `on_delete=CASCADE` (migration `0026_project_cascade_delete`, `AlterField` pur, aucune donnée touchée) — supprimer un `Project` efface désormais **toute** la production (lieux, catégories, matériel, techniciens, spectacles, et par ricochet leurs transports/assignations, déjà en CASCADE plus bas dans la chaîne). Irréversible, sans corbeille. `ProjectViewSet.destroy` (réservé au rôle `owner`/staff, voir section 13ter) supprime d'abord les `shows` du projet puis met `Material.category` à `null`, avant `project.delete()` — sans cet ordre, `Django` lève un `ProtectedError` (→ 500) à cause des 3 FK qui restent en `PROTECT` ailleurs dans le modèle (`Show.venue`, `TransportStop.venue`, `Material.category`), qui protègent l'objet visé même s'il est lui-même promis à la suppression par un autre chemin CASCADE dans le même appel. Le frontend (`ProjetDetailView.vue`) exige de retaper le nom du projet avant d'activer le bouton — friction purement côté UI. Archiver via `status` reste la voie normale pour retirer une production terminée **sans rien perdre** — la suppression est réservée à un vrai nettoyage définitif.

**Pas de vue « tous projets confondus »** (décision validée) : chaque liste de l'API se filtre par `?project=<id>` (optionnel — voir `inventory/views.py`, `ProjectFilteredMixin`), et bascule d'un projet à l'autre se fait entièrement côté frontend, sans recharger/exporter de fichier. Conséquence assumée : aucune détection de conflit entre deux projets différents (un même technicien réel entré dans deux projets isolés n'est jamais reconnu comme la même personne — voir `architecture.md`).

**Accès** (2026-08-02, révise l'affirmation « pas de propriétaire » qui vivait ici avant cette date) : un `project` n'a plus de FK owner direct, mais chaque `User` ayant accès à un projet donné a une ligne dans `project_memberships` (section 13ter) avec un rôle. `HasProjectAccess` (`inventory/permissions.py`) applique ce contrôle sur toutes les ressources isolées par projet — voir `architecture.md`, section 3, pour le détail. `?project=<id>` reste le mécanisme de FILTRAGE (quel projet regarder) ; le membership est le mécanisme d'AUTORISATION (a-t-on le droit de le regarder/modifier), les deux sont désormais nécessaires ensemble.

---

## 13. `material_categories`

Catégories de matériel (Audio, Éclairage, Décor…) — remplacent depuis le 2026-07-30 la liste de choix figée qui vivait dans `Material.CATEGORY_CHOICES`. Isolées par projet.

| Champ | Type | Description |
|---|---|---|
| id | INT, PK | Identifiant unique |
| project_id | INT, FK → projects.id | Production à laquelle cette catégorie appartient |
| name | VARCHAR(100) | Nom affiché (ex. `Audio`, `Machinerie`) |
| color | VARCHAR(64) | Couleur d'affichage (pastille dans les listes, point de couleur sur les assignations). Chaîne CSS libre, `oklch()` par convention |

**Unicité** : contrainte en base sur `(project_id, name)` — contrairement à `venues.code` (validé côté serializer seulement), une catégorie a toujours un nom, il n'y a donc pas de cas « plusieurs lignes vides » à ménager. `MaterialCategorySerializer.validate_name` double la contrainte pour renvoyer une erreur de champ exploitable plutôt qu'un 500.

**Catégories par défaut** : les 9 catégories historiques (Audio, Éclairage, Vidéo, Réseau, Rigging, Mobilier, Décor, Costumes, Autre) sont créées automatiquement à la création de chaque `Project` (signal `creer_categories_par_defaut`, voir `signals.py`) — une nouvelle production ne démarre pas sur une liste vide. Elles restent librement modifiables et supprimables.

**Suppression** (décision de Samuel du 2026-07-30) : `materials.category_id` est en `PROTECT`. Supprimer une catégorie encore utilisée passe donc par une **réassignation explicite** du matériel concerné : `DELETE /api/material-categories/{id}/?reassign_to=<id>`. Sans le paramètre, l'API renvoie un 400 contenant `material_count` — le frontend s'en sert pour demander vers quelle catégorie basculer. `?reassign_to=` (vide) laisse le matériel **sans catégorie** (la FK est nullable) plutôt que de le forcer dans un fourre-tout. Une catégorie inutilisée se supprime directement.

**Duplication de projet** : `duplicate_project` (voir `duplication.py`) recopie les catégories du projet source et remappe le matériel copié vers les copies — sinon une nouvelle édition pointerait vers les catégories de l'édition précédente, en travers de l'isolation par projet.

**Exposition API** : `MaterialSerializer` expose `category` (id, en écriture) plus `category_name`/`category_color` en lecture seule ; `ShowMaterialSerializer` fait de même avec `material_category`/`material_category_name`/`material_category_color`. Le frontend n'a donc plus aucune table de correspondance codée en dur.

---

## 13bis. `transport_technicians`

Table de liaison ajoutée le 2026-07-30 — relie un `transport` aux techniciens qui l'effectuent. Remplace l'ancien champ `transports.technician_id` (FK unique) : Samuel a demandé de pouvoir affecter plusieurs personnes à un même déplacement, exactement comme `show_technicians` le permet déjà pour un spectacle.

| Champ | Type | Description |
|---|---|---|
| id | INT, PK | Identifiant unique |
| transport_id | INT, FK → transports.id (CASCADE) | Déplacement concerné |
| technician_id | INT, FK → technicians.id (CASCADE) | Technicien affecté — une seule ligne par couple (`unique_together`) |

**Volontairement sans rôle ni hiérarchie** (décision de Samuel du 2026-07-30) : pas de chauffeur/responsable distingué des renforts, et pas de champ de rôle par affectation — le rôle reste `technicians.specialty`, exactement comme pour `show_technicians`.

**Écriture** : gérée en écriture imbriquée sur `TransportSerializer` via le champ `technicians` (liste de `{technician}`), même pattern que `materials`. Fournir `technicians` lors d'un PATCH remplace intégralement la liste ; l'omettre la laisse inchangée. Validations non overridables (erreurs de données) : même projet que le déplacement, pas de doublon dans la même requête.

**Détection de conflit** : l'engagement unitaire est le couple (transport, technicien), plus le transport lui-même — deux personnes sur le même déplacement sont deux engagements distincts, et donc deux conflits distincts dans le rapport project-wide. Voir `conflicts.py` (`_technician_commitments`, `serialize_technician_conflict`).

**Lecture** : `TransportSerializer` expose `technicians` (liste détaillée) et `technician_names` (noms à plat, pour les listes et les info-bulles). Le filtre `GET /api/transports/?technician=<id>` traverse désormais cette table (avec `distinct()`).

---

## 13ter. `project_memberships`

Table ajoutée le 2026-08-02, quand Samuel a décidé de vendre des abonnements à l'outil à d'autres directeurs techniques/compagnies. Jusque-là, aucune isolation multi-tenant réelle n'existait côté API : `IsAuthenticated` seul suffisait à lire/modifier TOUS les projets de TOUS les comptes. Relie un `user` à un `project` avec un rôle.

| Champ | Type | Description |
|---|---|---|
| id | INT, PK | Identifiant unique |
| project_id | INT, FK → projects.id (CASCADE) | Projet concerné |
| user_id | INT, FK → users.id (CASCADE) | Compte qui reçoit l'accès — jamais nul, voir le flux d'invitation ci-dessous |
| role | ENUM('owner','editor','viewer') (default 'viewer') | `owner` : gère les accès du projet (cette table) + édite tout le reste. `editor` : édite tout SAUF la gestion des accès. `viewer` : lecture seule |
| invited_by_id | INT, FK → users.id (nullable, SET_NULL) | Qui a envoyé l'invitation — nul pour un accès créé automatiquement (ex. le créateur d'un projet devient son propre owner) |
| status | ENUM('pending','active') (default 'pending') | Voir le flux d'invitation ci-dessous — `pending` NE COMPTE PAS comme un accès actif |
| created_at | DATETIME | Date de création |

**Unicité** : contrainte en base sur `(project_id, user_id)` — un compte n'a qu'une seule ligne par projet.

**Flux d'invitation** (décision de Samuel : pas d'envoi de courriel automatique pour l'instant, aucune infra SMTP configurée) : `POST /api/project-memberships/` (réservé owner/staff) prend `{project, email, role}`. Réutilise le pattern `get_or_create` par email déjà en place dans `signals.py` (`provisionner_utilisateur_inventory`) pour résoudre ou créer le `User` cible. `status` part à `'active'` d'emblée si cette personne a déjà un compte Google lié (`users.django_user_id` renseigné), sinon `'pending'` jusqu'à son premier login — `signals.py` active alors automatiquement tous ses memberships `pending`, exactement comme le pré-provisioning global de `User` lui-même.

**Garde du dernier owner** : `PATCH`/`DELETE` sur le dernier `ProjectMembership` `role='owner'` `status='active'` d'un projet renvoie un 400 explicite plutôt que de laisser le projet sans owner.

**`users.is_staff_global`** (voir section 1) contourne entièrement ce contrôle — un accès de dépannage plateforme, distinct d'un `owner` qui reste limité à SES projets.

**Exposition API** : `GET /api/project-memberships/?project=<id>` — lecture accessible à tout membre actif (pas seulement l'owner) ; `POST`/`PATCH`/`DELETE` réservés owner/staff. `ProjectMembershipSerializer` expose `user_email`/`user_name`/`invited_by_email` en lecture en plus des champs bruts.

---

## Calcul du temps de trajet (Google Routes API)

Décision du 2026-07-18 : `venues.latitude`/`longitude` (section 2) permettent de calculer automatiquement `transports.estimated_duration_minutes` via l'API Google Routes ("Compute Routes", un trajet simple = un lieu de départ, un lieu d'arrivée), plutôt que de saisir cette durée à la main à chaque fois. Voir `inventory/maps.py` et `security.md` pour la gestion de la clé API (`GOOGLE_MAPS_API_KEY`). Si la clé n'est pas configurée, ou si l'appel échoue, le calcul se rabat silencieusement sur `settings.default_transport_duration_minutes` — aucune dépendance dure à ce service externe.

## Relations — vue d'ensemble

```
projects 1───N venues (CASCADE depuis le 2026-08-04, était PROTECT)
projects 1───N material_categories (CASCADE depuis le 2026-08-04, était PROTECT)
projects 1───N materials (CASCADE depuis le 2026-08-04, était PROTECT)
materials N───1 material_categories (nullable, PROTECT — inchangé, protège la catégorie, pas le projet)
projects 1───N technicians (CASCADE depuis le 2026-08-04, était PROTECT)
projects 1───N shows (CASCADE depuis le 2026-08-04, était PROTECT)
venues 1───N shows (PROTECT — inchangé, un lieu encore référencé bloque sa propre suppression)
materials N───1 materials (self, parent/enfant)
materials N───1 venues (entreposage)
shows 1───N show_materials N───1 materials
shows 1───N show_technicians N───1 technicians
shows 1───N transports
transports 1───N transport_stops N───1 venues (PROTECT — séquence ordonnée d'arrêts, remplace origin_venue/destination_venue depuis le 2026-08-04)
transports 1───N transport_technicians N───1 technicians
transports 1───N transport_materials N───1 materials (chaque ligne référence aussi load_stop/unload_stop → transport_stops)
materials N───1 venues (entreposage = point de départ des timelines de cohérence)
settings (singleton, COMMUN à tous les projets — lu par shows/transports comme source de leurs valeurs par défaut)
projects 1───N project_memberships N───1 users (accès par projet, rôle owner/editor/viewer)
users 1───N project_memberships (invited_by, nullable — qui a envoyé l'invitation)
```

## Ce qui est explicitement HORS scope (par décision)

- Pas de table de communications/vendors (géré par courriel, hors app).
- Pas de table de tâches ou de notes de suivi (gérées dans un autre outil).
- Pas d'historique des changements d'assignation (seules les données actuelles comptent).
- Pas de dates de location générales sur `materials` (la location est toujours liée à un spectacle précis via `show_materials`).
