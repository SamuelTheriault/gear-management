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
| role | ENUM('admin','viewer') | Niveau d'accès |
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
| code | VARCHAR(4), nullable/vide | Code court saisi à la création (ex. `CHAP` pour Chapelle) — voir note ci-dessous |
| address | VARCHAR | Adresse |
| contact_name | VARCHAR | Contact sur place |
| contact_info | VARCHAR | Téléphone / email du contact |
| notes | TEXT | Notes générales sur le lieu |
| is_storage | BOOLEAN (default false) | Lieu d'entreposage (entrepôt) plutôt qu'un vrai lieu de spectacle — voir règle d'exemption dans la section `show_materials` |
| latitude | DECIMAL(9,6), nullable | Coordonnée GPS (ex. copiée depuis Google Maps) — voir section 10, calcul de trajet |
| longitude | DECIMAL(9,6), nullable | Coordonnée GPS — voir latitude |

**Code court** (décision du 2026-07-19) : `code` (jusqu'à 4 caractères, normalisé en majuscules à l'enregistrement) sert d'identifiant rapide pour un lieu — ex. `CHAP` pour la Chapelle. Optionnel, unique par projet si renseigné (validé par `VenueSerializer`, pas une contrainte en base — plusieurs lieux sans code coexistent normalement dans un même projet). Réutilisé sur `TransportSerializer` (`origin_venue_code`/`destination_venue_code`) pour un affichage compact du départ/arrivée d'un déplacement.

---

## 3. `departments`

Départements responsables du matériel (ex. son, éclairage, décor, costumes). Permet de savoir qui doit apporter quoi sur le lieu du spectacle.

| Champ | Type | Description |
|---|---|---|
| id | INT, PK | Identifiant unique |
| name | VARCHAR | Nom du département |
| contact_name | VARCHAR | Nom du responsable |
| contact_info | VARCHAR | Téléphone / email du responsable |
| notes | TEXT | Notes diverses |
| color | VARCHAR(7) | Code couleur hexadécimal (#RRGGBB, ex. #64748B par défaut) — identifie visuellement le département ; reflétée dans les sous-sections où il apparaît (voir note ci-dessous) |

**Couleur reflétée dans les sous-sections** : `color` n'est stockée que sur `departments`, mais l'API expose un champ dérivé en lecture seule `department_color` sur `MaterialSerializer` et `ShowMaterialSerializer` (source : `department.color`), pour que le frontend puisse colorer le matériel et les assignations show/matériel de façon cohérente sans requête supplémentaire.

---

## 4. `materials`

Inventaire de matériel. Supporte une hiérarchie parent/enfant (kits contenant des composants) et une catégorisation par type d'usage. Isolé par projet — voir section 11 (`projects`).

| Champ | Type | Description |
|---|---|---|
| id | INT, PK | Identifiant unique |
| project_id | INT, FK → projects.id | Production à laquelle ce matériel appartient |
| name | VARCHAR | Nom du matériel |
| description | TEXT | Description / détails techniques |
| category | VARCHAR/ENUM | Type d'usage (ex. audio, éclairage, rigging, mobilier) |
| parent_material_id | INT, FK → materials.id (nullable) | Matériel parent (ex. "Kit Audio" est parent de "Micro sans fil") |
| venue_id | INT, FK → venues.id (nullable) | Lieu physique où le matériel est entreposé |
| department_id | INT, FK → departments.id (nullable) | Département responsable d'apporter ce matériel sur le lieu du spectacle |
| ownership_status | ENUM('owned','rental') | Propriété ou location générale |
| quantity | INT (default 1) | Quantité totale possédée de ce matériel identique (ex. 20 rallonges électriques) — voir note quantité ci-dessous |
| is_active | BOOLEAN (default true) | Permet de désactiver un matériel qu'on n'utilise plus (ex. un vieux rideau) sans le supprimer — voir note ci-dessous |
| notes | TEXT | Notes diverses |

**Logique hiérarchique** : un matériel "kit" (parent) peut être assigné en bloc à un spectacle, ou ses composants (enfants) peuvent être assignés individuellement pour un suivi plus granulaire.

**Quantité et hiérarchie kit** (décision du 2026-07-19) : `quantity` permet de posséder plusieurs exemplaires identiques d'un même matériel (ex. 20 rallonges électriques) sans créer un item par unité physique — voir `show_materials` pour l'allocation partielle. Un matériel qui participe à une hiérarchie kit (a un `parent_material_id`, ou est lui-même parent d'au moins un composant) doit obligatoirement rester à `quantity = 1` : un kit reste une unité conceptuelle unique, la notion de capacité partagée ne s'applique qu'au matériel autonome. Contrainte appliquée par `MaterialSerializer.validate()`, pas en base.

**Matériel désactivé** (décision du 2026-07-19) : `is_active = false` retire un matériel qu'on n'utilise plus (ex. un vieux rideau) des listes d'inventaire courantes sans le supprimer — l'historique des assignations existantes (`show_materials`) reste intact. `GET /api/materials/` ne retourne que `is_active = true` par défaut ; ajouter `?include_inactive=true` pour tout revoir. La consultation par id reste toujours accessible peu importe le statut.

**Isolation par projet** (décision du 2026-07-19) : `parent_material` et `venue` (si renseignés) doivent obligatoirement appartenir au même `project` que le matériel lui-même — validé par `MaterialSerializer.validate()`, pas en base. `department`, lui, n'est PAS soumis à cette contrainte : les départements restent communs à tous les projets (voir section 3).

---

## 5. `shows`

Fiches spectacles — regroupe répétitions et représentations avec leurs horaires et le lieu. Isolées par projet — voir section 11 (`projects`).

| Champ | Type | Description |
|---|---|---|
| id | INT, PK | Identifiant unique |
| project_id | INT, FK → projects.id | Production à laquelle ce spectacle appartient — doit correspondre au projet de `venue_id` |
| title | VARCHAR | Titre du spectacle |
| venue_id | INT, FK → venues.id | Lieu de l'événement |
| event_type | ENUM('rehearsal','performance','storage') | Répétition, représentation, ou entreposage (voir note ci-dessous) |
| start_datetime | DATETIME | Début (heure réelle) |
| end_datetime | DATETIME | Fin (heure réelle) |
| buffer_before_minutes | INT (default : voir `settings.default_buffer_before_minutes`) | Marge avant (déplacement/installation) |
| buffer_after_minutes | INT (default : voir `settings.default_buffer_after_minutes`) | Marge après (déplacement/désinstallation) |
| notes | TEXT | Notes générales |

**Fenêtre effective d'utilisation** = `start_datetime - buffer_before` à `end_datetime + buffer_after`. C'est cette fenêtre qui est utilisée pour la détection de conflits.

**Entreposage** : un `show` dont le `venue_id` pointe vers un lieu avec `is_storage = true` représente une période où le matériel est simplement rangé — voir la règle d'exemption dans `show_materials` ci-dessous. `event_type = 'storage'` est la convention pour étiqueter ce genre de fiche (mais c'est bien `venue.is_storage` qui déclenche l'exemption, pas `event_type`).

---

## 6. `show_materials`

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

## 7. `technicians`

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

## 8. `show_technicians`

Table d'association — assigne des techniciens à un spectacle/répétition.

| Champ | Type | Description |
|---|---|---|
| id | INT, PK | Identifiant unique |
| show_id | INT, FK → shows.id | Spectacle concerné |
| technician_id | INT, FK → technicians.id | Technicien assigné |

**Règle de conflit** : même logique que pour le matériel — un technicien ne peut pas être assigné à deux spectacles dont les fenêtres effectives (horaire + buffers) se chevauchent. Depuis l'ajout de `transports` (section 9), cette règle croise aussi les déplacements du technicien : il ne peut pas non plus être sur un spectacle en même temps qu'il fait une livraison/ramassage.

---

## 9. `transports`

Table ajoutée le 2026-07-18 (hors des 8 tables initiales) — trace la livraison/ramassage de matériel entre deux lieux pour un spectacle donné, et quel technicien s'en charge.

| Champ | Type | Description |
|---|---|---|
| id | INT, PK | Identifiant unique |
| show_id | INT, FK → shows.id | Spectacle desservi par ce déplacement |
| transport_type | ENUM('delivery','pickup') | Livraison (aller) ou ramassage (retour) |
| status | ENUM('confirmed','to_approve') (default 'confirmed') | Cycle de vie (ajouté le 2026-07-24) — voir note ci-dessous |
| origin_venue_id | INT, FK → venues.id | Lieu de départ (souvent un entrepôt pour une livraison) |
| destination_venue_id | INT, FK → venues.id | Lieu d'arrivée (souvent le lieu du spectacle pour une livraison) — doit être différent de `origin_venue_id` |
| scheduled_datetime | DATETIME, **nullable** | Heure prévue du déplacement — nullable depuis le 2026-07-24 (une proposition `to_approve` n'a pas encore d'heure). Obligatoire pour un `status='confirmed'` (validé par `TransportSerializer`) |
| *(dérivé)* origin_venue_code / destination_venue_code | VARCHAR(4) | Code court des lieux (voir `venues.code`), exposé en lecture seule pour un affichage compact départ/arrivée — vide si le lieu n'a pas de code |
| estimated_duration_minutes | INT (default : voir `settings.default_transport_duration_minutes`) | Durée estimée (trajet + chargement/déchargement) — pré-remplie automatiquement via l'API Google Routes si les deux venues ont des coordonnées GPS (voir section 10) |
| technician_id | INT, FK → technicians.id (nullable) | Technicien assigné (peut être vide tant que non confirmé) |
| notes | TEXT | Notes diverses |

**Fenêtre effective** = `scheduled_datetime` à `scheduled_datetime + estimated_duration_minutes` (pas de buffers séparés — la durée estimée couvre déjà trajet + chargement).

**Règle de conflit** : le technicien assigné à un `transport` ne peut pas non plus être engagé (spectacle OU autre déplacement) sur une fenêtre qui chevauche celle-ci — bloquant, avec possibilité de forcer via `force: true`, comme pour `show_materials`/`show_technicians`. Cette table ne participe PAS à l'exemption d'entreposage (section 6) : un déplacement est toujours un vrai engagement de temps pour le technicien qui le fait.

**Matériel transporté** (décision du 2026-07-24) : *quel* matériel monte dans un déplacement est décrit par la table de liaison `transport_materials` (section 12), pas directement ici. Ce lien alimente le module de cohérence des emplacements (voir section 12 et `transport_coherence.py`).

**Statut `to_approve` / `confirmed`** (décision du 2026-07-24) : un déplacement `confirmed` est créé/complété par l'utilisateur — il a une heure, participe à la timeline de position (cohérence) et à la détection de conflit du technicien. Un déplacement `to_approve` est une **proposition générée automatiquement** (voir `transport_autogen.py`) quand du matériel est requis à un lieu où rien ne l'amène : lieux + matériel préremplis, mais heure/technicien à saisir. Une proposition est affichée en orange et ne « livre » rien tant qu'elle n'est pas confirmée (elle n'entre pas dans la timeline de position). Deux façons de créer un transport : manuellement (`confirmed` d'emblée) ou automatiquement (`to_approve`, à compléter puis confirmer).

---

## 12. `transport_materials`

Table de liaison ajoutée le 2026-07-24 (module transport) — relie un `transport` au matériel (et à la quantité) qu'il transporte. Sans elle, un `transport` savait *quand* et *où* le matériel bougeait, mais pas *lequel* montait dans le camion.

| Champ | Type | Description |
|---|---|---|
| id | INT, PK | Identifiant unique |
| transport_id | INT, FK → transports.id (CASCADE) | Déplacement qui transporte ce matériel |
| material_id | INT, FK → materials.id (CASCADE) | Matériel transporté |
| quantity | INT (default 1) | Quantité transportée (ex. 8 des 20 rallonges) — un même matériel n'apparaît qu'une fois par transport (`unique_together (transport, material)`) |

**Écriture** : géré en écriture imbriquée sur `TransportSerializer` via le champ `materials` (liste de `{material, quantity}`). Fournir `materials` lors d'un PATCH remplace intégralement les lignes du transport ; l'omettre les laisse inchangées. Validations (non overridables par `force`, ce sont des erreurs de données) : chaque matériel doit appartenir au même projet que le déplacement, ne pas être listé deux fois, et sa quantité transportée ne peut dépasser `materials.quantity` (la quantité totale possédée).

**Module de cohérence des emplacements** (`transport_coherence.py`, non bloquant) : à partir de ce lien, le module reconstruit une *timeline* de position par matériel — départ au lieu d'entreposage `materials.venue`, puis application chronologique des transports (un transport est réputé « arrivé » à sa `effective_end`). Il produit un **rapport** (jamais un blocage) exposé par `GET /api/shows/{id}/transport-coherence/` (centré sur un spectacle) et `GET /api/projects/{id}/transport-coherence/` (toute la production). Trois types d'incohérence :

- `materiel_non_livre` : un `show_material` requiert du matériel à un lieu où il n'est pas présent (en quantité suffisante) au début de la fenêtre effective — aucun transport **confirmé** ne l'y amène. Répond à « tout déplacement de matériel est associé à un transport ». Porte un champ `etat` : `propose` (orange — une proposition auto `to_approve` couvre le déplacement, `proposal_transport_id` la pointe) ou `manquant` (rouge — rien, même proposé, ne le couvre).
- `origine_incoherente` : un `transport` prétend transporter du matériel depuis un lieu où ce matériel n'est pas disponible à l'heure du départ. Répond à « tout est possible sur les emplacements prévus ».
- `origine_inconnue` : le matériel n'a pas de lieu d'entreposage (`materials.venue` vide), sa position de départ est inconnue — signalé une seule fois, impossible à suivre.

**Portée assumée — aller seulement** (décision du 2026-07-24) : le module vérifie la *présence* du matériel là où il est requis (livraisons). Il n'exige PAS qu'un ramassage (`pickup`) ramène le matériel à son entrepôt d'origine (pas de boucle de retour fermée) — un `pickup` est tout de même pris en compte dans la timeline comme tout déplacement.

**Exemption d'entreposage** : un `show_material` rattaché à un `show` d'entrepôt (`venue.is_storage=True`) n'exige aucune livraison — cohérent avec l'exemption de la section 6.

**Génération automatique des propositions** (`transport_autogen.py`, décision du 2026-07-24) : plutôt que d'attendre que l'utilisateur crée chaque transport, l'app **génère automatiquement** un `transports` en `status='to_approve'` pour chaque déplacement manquant détecté. Déclenchement par signaux (`regenerate_signals.py`), à chaque changement pertinent : assignation de matériel (`show_materials`), transport confirmé, ligne `transport_materials` d'un transport confirmé, ou horaire/lieu d'un `shows`. La proposition est préremplie avec le lieu de départ (dernière position connue du matériel — origines chaînées entrepôt→A puis A→B), le lieu d'arrivée (le lieu du spectacle) et le matériel (groupé : une proposition par couple origine/spectacle peut porter plusieurs matériels). Régénération = *resync* idempotent des seules propositions `to_approve` (pas de mémoire de rejet — décision Samuel : on recalcule à chaque fois ; les transports confirmés ne sont jamais touchés). L'utilisateur complète (heure, technicien) puis confirme, ce qui fait passer la proposition de l'orange au vert.

**Conflit de technicien sur un transport** (rappel) : reste **bloquant + `force`** comme avant (section 9 / `architecture.md` section 4). Le champ dérivé `has_technician_conflict` sur `TransportSerializer` expose l'info en lecture seule pour l'indicateur orange du frontend, y compris pour une assignation créée avec `force: true`.

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

**Note technique** : les valeurs par défaut de `shows`/`transports` ci-dessus ne sont pas de simples constantes — elles sont lues dynamiquement depuis cette table à chaque création (voir `inventory/models.py`, callables `_default_buffer_before_minutes` etc.), pour que changer un réglage ici s'applique immédiatement aux nouvelles fiches, sans redéploiement.

---

## 11. `projects`

Table ajoutée le 2026-07-19 (hors des 8 tables initiales) à la demande de Samuel : il travaille en parallèle sur plusieurs productions qui n'ont rien en commun (compagnies de danse, musées, biennales comme CINARS/Parcours Danse/Furies). Une `project` regroupe tout le travail propre à une production précise.

| Champ | Type | Description |
|---|---|---|
| id | INT, PK | Identifiant unique |
| name | VARCHAR | Nom de la production |
| client_name | VARCHAR (nullable) | Compagnie ou organisation cliente, si pertinent |
| status | ENUM('active','archived') (default 'active') | Une production terminée s'archive plutôt que de se supprimer — voir note ci-dessous |
| start_date | DATE, nullable | Date de début |
| end_date | DATE, nullable | Date de fin |
| notes | TEXT | Notes diverses |
| created_at | DATETIME | Date de création |

**Isolation par projet** : `venues`, `materials`, `technicians` et `shows` portent chacun un `project_id` obligatoire (FK `on_delete=PROTECT` — impossible de supprimer une `project` tant qu'il lui reste des données rattachées ; archiver via `status` est la voie normale pour retirer une production terminée sans rien perdre). `departments` et `settings` restent **communs à tous les projets** (décision explicite de Samuel) — voir sections 3 et 10.

**Pas de vue « tous projets confondus »** (décision validée) : chaque liste de l'API se filtre par `?project=<id>` (optionnel — voir `inventory/views.py`, `ProjectFilteredMixin`), et bascule d'un projet à l'autre se fait entièrement côté frontend, sans recharger/exporter de fichier. Conséquence assumée : aucune détection de conflit entre deux projets différents (un même technicien réel entré dans deux projets isolés n'est jamais reconnu comme la même personne — voir `architecture.md`).

---

## Calcul du temps de trajet (Google Routes API)

Décision du 2026-07-18 : `venues.latitude`/`longitude` (section 2) permettent de calculer automatiquement `transports.estimated_duration_minutes` via l'API Google Routes ("Compute Routes", un trajet simple = un lieu de départ, un lieu d'arrivée), plutôt que de saisir cette durée à la main à chaque fois. Voir `inventory/maps.py` et `security.md` pour la gestion de la clé API (`GOOGLE_MAPS_API_KEY`). Si la clé n'est pas configurée, ou si l'appel échoue, le calcul se rabat silencieusement sur `settings.default_transport_duration_minutes` — aucune dépendance dure à ce service externe.

## Relations — vue d'ensemble

```
projects 1───N venues
projects 1───N materials
projects 1───N technicians
projects 1───N shows
venues 1───N shows
materials N───1 materials (self, parent/enfant)
materials N───1 venues (entreposage)
materials N───1 departments (responsable, COMMUN à tous les projets)
shows 1───N show_materials N───1 materials
shows 1───N show_technicians N───1 technicians
shows 1───N transports
transports N───1 venues (origin_venue_id)
transports N───1 venues (destination_venue_id)
transports N───1 technicians (nullable)
transports 1───N transport_materials N───1 materials
materials N───1 venues (entreposage = point de départ des timelines de cohérence)
settings (singleton, COMMUN à tous les projets — lu par shows/transports comme source de leurs valeurs par défaut)
```

## Ce qui est explicitement HORS scope (par décision)

- Pas de table de communications/vendors (géré par courriel, hors app).
- Pas de table de tâches ou de notes de suivi (gérées dans un autre outil).
- Pas d'historique des changements d'assignation (seules les données actuelles comptent).
- Pas de dates de location générales sur `materials` (la location est toujours liée à un spectacle précis via `show_materials`).
