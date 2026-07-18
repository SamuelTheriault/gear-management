# Schéma de base de données — Gestion de matériel

> Base de données relationnelle : MySQL 8.0 (ou MariaDB 10, compatible) — confirmé disponible chez Ionos.
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

Lieux (salles, théâtres, sites de représentation, entrepôts).

| Champ | Type | Description |
|---|---|---|
| id | INT, PK | Identifiant unique |
| name | VARCHAR | Nom du lieu |
| address | VARCHAR | Adresse |
| contact_name | VARCHAR | Contact sur place |
| contact_info | VARCHAR | Téléphone / email du contact |
| notes | TEXT | Notes générales sur le lieu |
| is_storage | BOOLEAN (default false) | Lieu d'entreposage (entrepôt) plutôt qu'un vrai lieu de spectacle — voir règle d'exemption dans la section `show_materials` |
| latitude | DECIMAL(9,6), nullable | Coordonnée GPS (ex. copiée depuis Google Maps) — voir section 10, calcul de trajet |
| longitude | DECIMAL(9,6), nullable | Coordonnée GPS — voir latitude |

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

---

## 4. `materials`

Inventaire de matériel. Supporte une hiérarchie parent/enfant (kits contenant des composants) et une catégorisation par type d'usage.

| Champ | Type | Description |
|---|---|---|
| id | INT, PK | Identifiant unique |
| name | VARCHAR | Nom du matériel |
| description | TEXT | Description / détails techniques |
| category | VARCHAR/ENUM | Type d'usage (ex. audio, éclairage, rigging, mobilier) |
| parent_material_id | INT, FK → materials.id (nullable) | Matériel parent (ex. "Kit Audio" est parent de "Micro sans fil") |
| venue_id | INT, FK → venues.id (nullable) | Lieu physique où le matériel est entreposé |
| department_id | INT, FK → departments.id (nullable) | Département responsable d'apporter ce matériel sur le lieu du spectacle |
| ownership_status | ENUM('owned','rental') | Propriété ou location générale |
| notes | TEXT | Notes diverses |

**Logique hiérarchique** : un matériel "kit" (parent) peut être assigné en bloc à un spectacle, ou ses composants (enfants) peuvent être assignés individuellement pour un suivi plus granulaire.

---

## 5. `shows`

Fiches spectacles — regroupe répétitions et représentations avec leurs horaires et le lieu.

| Champ | Type | Description |
|---|---|---|
| id | INT, PK | Identifiant unique |
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
| is_rental | BOOLEAN | Ce matériel est-il loué spécifiquement pour ce spectacle? |
| rental_vendor | VARCHAR (nullable) | Nom du fournisseur externe (si is_rental = true) |

**Règle de conflit** : pour un même `material_id` (ou pour un matériel parent et ses enfants), le système refuse (bloquant, avec possibilité de forcer via `force: true`) l'assignation si la fenêtre effective (voir `shows`) chevauche celle d'un autre `show_materials` existant pour ce matériel.

**Exemption d'entreposage** (décision du 2026-07-18) : cette règle de conflit est entièrement ignorée dès qu'un des deux `show_materials` comparés est rattaché à un `show` dont le `venue.is_storage = true`. Le matériel qui est simplement rangé en entrepôt est considéré disponible — il n'entre jamais en conflit avec un autre lieu, et assigner du matériel à un entrepôt ne bloque jamais, même s'il est par ailleurs utilisé sur un vrai spectacle au même moment. Cette exemption ne s'applique qu'au matériel, pas aux techniciens (`show_technicians`) : un technicien assigné à un `show` d'entrepôt (ex. pour de l'inventaire) reste soumis à la détection de conflit normale.

---

## 7. `technicians`

| Champ | Type | Description |
|---|---|---|
| id | INT, PK | Identifiant unique |
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
| origin_venue_id | INT, FK → venues.id | Lieu de départ (souvent un entrepôt pour une livraison) |
| destination_venue_id | INT, FK → venues.id | Lieu d'arrivée (souvent le lieu du spectacle pour une livraison) — doit être différent de `origin_venue_id` |
| scheduled_datetime | DATETIME | Heure prévue du déplacement |
| estimated_duration_minutes | INT (default : voir `settings.default_transport_duration_minutes`) | Durée estimée (trajet + chargement/déchargement) — pré-remplie automatiquement via l'API Google Routes si les deux venues ont des coordonnées GPS (voir section 10) |
| technician_id | INT, FK → technicians.id (nullable) | Technicien assigné (peut être vide tant que non confirmé) |
| notes | TEXT | Notes diverses |

**Fenêtre effective** = `scheduled_datetime` à `scheduled_datetime + estimated_duration_minutes` (pas de buffers séparés — la durée estimée couvre déjà trajet + chargement).

**Règle de conflit** : le technicien assigné à un `transport` ne peut pas non plus être engagé (spectacle OU autre déplacement) sur une fenêtre qui chevauche celle-ci — bloquant, avec possibilité de forcer via `force: true`, comme pour `show_materials`/`show_technicians`. Cette table ne participe PAS à l'exemption d'entreposage (section 6) : un déplacement est toujours un vrai engagement de temps pour le technicien qui le fait.

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

## Calcul du temps de trajet (Google Routes API)

Décision du 2026-07-18 : `venues.latitude`/`longitude` (section 2) permettent de calculer automatiquement `transports.estimated_duration_minutes` via l'API Google Routes ("Compute Routes", un trajet simple = un lieu de départ, un lieu d'arrivée), plutôt que de saisir cette durée à la main à chaque fois. Voir `inventory/maps.py` et `security.md` pour la gestion de la clé API (`GOOGLE_MAPS_API_KEY`). Si la clé n'est pas configurée, ou si l'appel échoue, le calcul se rabat silencieusement sur `settings.default_transport_duration_minutes` — aucune dépendance dure à ce service externe.

## Relations — vue d'ensemble

```
venues 1───N shows
materials N───1 materials (self, parent/enfant)
materials N───1 venues (entreposage)
materials N───1 departments (responsable)
shows 1───N show_materials N───1 materials
shows 1───N show_technicians N───1 technicians
shows 1───N transports
transports N───1 venues (origin_venue_id)
transports N───1 venues (destination_venue_id)
transports N───1 technicians (nullable)
settings (singleton, pas de relation — lu par shows/transports comme source de leurs valeurs par défaut)
```

## Ce qui est explicitement HORS scope (par décision)

- Pas de table de communications/vendors (géré par courriel, hors app).
- Pas de table de tâches ou de notes de suivi (gérées dans un autre outil).
- Pas d'historique des changements d'assignation (seules les données actuelles comptent).
- Pas de dates de location générales sur `materials` (la location est toujours liée à un spectacle précis via `show_materials`).
