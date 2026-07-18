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

---

## 2. `venues`

Lieux (salles, théâtres, sites de représentation).

| Champ | Type | Description |
|---|---|---|
| id | INT, PK | Identifiant unique |
| name | VARCHAR | Nom du lieu |
| address | VARCHAR | Adresse |
| contact_name | VARCHAR | Contact sur place |
| contact_info | VARCHAR | Téléphone / email du contact |
| notes | TEXT | Notes générales sur le lieu |

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
| event_type | ENUM('rehearsal','performance') | Répétition ou représentation |
| start_datetime | DATETIME | Début (heure réelle) |
| end_datetime | DATETIME | Fin (heure réelle) |
| buffer_before_minutes | INT (default 60) | Marge avant (déplacement/installation) |
| buffer_after_minutes | INT (default 60) | Marge après (déplacement/désinstallation) |
| notes | TEXT | Notes générales |

**Fenêtre effective d'utilisation** = `start_datetime - buffer_before` à `end_datetime + buffer_after`. C'est cette fenêtre qui est utilisée pour la détection de conflits.

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

**Règle de conflit** : pour un même `material_id` (ou pour un matériel parent et ses enfants), le système refuse ou signale l'assignation si la fenêtre effective (voir `shows`) chevauche celle d'un autre `show_materials` existant pour ce matériel.

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

**Règle de conflit** : même logique que pour le matériel — un technicien ne peut pas être assigné à deux spectacles dont les fenêtres effectives (horaire + buffers) se chevauchent.

---

## Relations — vue d'ensemble

```
venues 1───N shows
materials N───1 materials (self, parent/enfant)
materials N───1 venues (entreposage)
materials N───1 departments (responsable)
shows 1───N show_materials N───1 materials
shows 1───N show_technicians N───1 technicians
```

## Ce qui est explicitement HORS scope (par décision)

- Pas de table de communications/vendors (géré par courriel, hors app).
- Pas de table de tâches ou de notes de suivi (gérées dans un autre outil).
- Pas d'historique des changements d'assignation (seules les données actuelles comptent).
- Pas de dates de location générales sur `materials` (la location est toujours liée à un spectacle précis via `show_materials`).
