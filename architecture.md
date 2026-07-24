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

## 4quater. Isolation par projet (`projects`, décision du 2026-07-19)

Samuel travaille en parallèle sur plusieurs productions qui n'ont rien en commun (compagnies de danse, musées, biennales comme CINARS/Parcours Danse/Furies). `Project` (voir `schema.md`, section 11) isole les données propres à chaque production :

- `venues`, `materials`, `technicians` et `shows` portent chacun un `project_id` **obligatoire**. `departments` et `settings` restent volontairement **communs à tous les projets** — un choix explicite de Samuel, pas un oubli.
- Validation bloquante côté serializers (`_same_project()` dans `serializers.py`) : impossible d'assigner du matériel/technicien d'un projet à un spectacle d'un autre (`ShowMaterialSerializer`/`ShowTechnicianSerializer`), impossible de donner à un `Show` un `venue` d'un autre projet (`ShowSerializer`), impossible qu'un `Material` référence un `parent_material` ou un `venue` d'entreposage d'un autre projet que le sien (`MaterialSerializer` — `department` reste volontairement exempté), et impossible qu'un `Transport` mélange un `show`, ses `origin_venue`/`destination_venue` et son `technician` de projets différents (`TransportSerializer`).
- Filtrage optionnel `?project=<id>` sur les listes (`ProjectFilteredMixin` dans `views.py`) — optionnel plutôt qu'obligatoire pour ne pas casser un accès API brut, mais le frontend (une fois branché) passera toujours ce paramètre pour refléter le projet actif choisi par Samuel.
- **Bascule entre projets** : entièrement côté frontend (sélecteur qui change le `?project=` utilisé par les appels API), sans recharger ni exporter/importer de fichier — c'est la demande initiale de Samuel (« comme une sauvegarde, mais je veux basculer sans charger un fichier »).
- **Pas de vue « tous projets confondus »** (décision validée avec Samuel) : chaque vue reste filtrée par le projet actif. Conséquence assumée — la détection de conflits (section 4) ne peut jamais croiser deux projets différents, puisque `Technician`/`Material` d'un projet sont des lignes distinctes de celles d'un autre projet, même si elles représentent la même personne/le même équipement réel.
- **Suppression** : `project` FK en `on_delete=PROTECT` sur les 4 modèles isolés — impossible de supprimer une `Project` tant qu'il lui reste des données. La voie normale pour retirer une production terminée est de l'archiver (`status='archived'`), pas de la supprimer.
- **Duplication pour une nouvelle édition** (décision du 2026-07-19, voir `inventory/duplication.py`) : `POST /api/projects/{id}/duplicate/` copie `venues`, `materials` (hiérarchie parent/enfant remappée vers les nouvelles lignes) et `technicians` vers un nouveau projet — **jamais** `shows`/`show_materials`/`show_technicians`/`transports` (une nouvelle édition a son propre calendrier, pas celui de la précédente). `department` n'est jamais dupliqué ni remappé : référentiel commun, la copie pointe vers la même ligne que l'original. Le nouveau projet reprend `client_name` du projet source par défaut (surchargeable dans la requête) ; `notes`, `start_date`, `end_date` et `status` repartent à leurs valeurs par défaut (`status='active'`), quel que soit l'état du projet source. Réponse : `{'project': {...}, 'copied': {'venues': n, 'materials': n, 'technicians': n}}`. Opération atomique (tout ou rien) ; le projet source n'est jamais modifié.

## 4quinquies. Module transport — cohérence des emplacements (décision du 2026-07-24)

Complément à la détection de conflits (section 4) : là où celle-ci vérifie les chevauchements d'horaire (capacité matériel, techniciens), ce module vérifie la cohérence **spatiale** du matériel dans le temps. Deux questions posées par Samuel :

1. **« Tout est-il possible sur les emplacements prévus ? »** — un `Transport` prétend transporter du matériel depuis un lieu de départ ; ce matériel s'y trouve-t-il vraiment à ce moment ?
2. **« Tout déplacement de matériel est-il associé à un transport ? »** — le matériel requis à un lieu de spectacle y est-il bien amené par un transport ?

**Lien matériel↔transport** : nouvelle table de liaison `transport_materials` (voir `schema.md`, section 12), gérée en écriture imbriquée sur `TransportSerializer.materials`. C'est ce lien explicite (plutôt qu'une inférence lieu+horaire) qui permet de vérifier réellement *quel* matériel voyage — choix retenu avec Samuel le 2026-07-24 pour pouvoir détecter un oubli de chargement.

**Timeline de position** (`inventory/transport_coherence.py`) : pour chaque matériel, on reconstruit un « grand livre » de positions dans le temps — départ = `Material.venue` (lieu d'entreposage, le « bercail »), avec `Material.quantity` unités, puis application chronologique des transports qui le transportent. Un transport est réputé « arrivé » (matériel présent à destination) à la fin de sa fenêtre (`effective_end` = `scheduled_datetime` + `estimated_duration_minutes`). On compare ensuite :
- chaque `Transport` : son matériel est-il disponible à l'origine à l'heure du départ ? Sinon → `origine_incoherente`.
- chaque `ShowMaterial` : le matériel est-il présent (en quantité suffisante) au lieu du spectacle au début de sa fenêtre effective ? Sinon → `materiel_non_livre`.
- matériel sans `venue` d'entreposage → `origine_inconnue` (position de départ inconnue, non suivi).

**Non bloquant** (décision Samuel du 2026-07-24) : contrairement à la détection de conflits (bloquante + `force`), la cohérence des emplacements est un **rapport** consultable à la demande, jamais un refus `400`. Endpoints : `GET /api/shows/{id}/transport-coherence/` (centré sur un spectacle, à la manière de `/conflicts/`) et `GET /api/projects/{id}/transport-coherence/` (toute la production). Réponse : `{'issues': [...], 'issue_count': n}`.

**Portée — aller seulement** (décision Samuel du 2026-07-24) : on vérifie la présence du matériel là où il est requis (livraisons). On n'exige PAS qu'un ramassage (`pickup`) ferme la boucle en ramenant le matériel à son entrepôt — un `pickup` reste pris en compte dans la timeline comme tout déplacement, sans contrôle de retour.

**Exemption d'entreposage** : un `ShowMaterial` sur un `show` d'entrepôt (`venue.is_storage=True`) n'exige aucune livraison, cohérent avec l'exemption matériel de la section 4.

### Création des transports — manuelle et automatique (décision du 2026-07-24)

Deux façons de créer un `Transport`, décidées avec Samuel :

1. **Manuelle** : l'utilisateur crée un déplacement (lieux de départ/arrivée choisis parmi les lieux existants, heure, matériel). Créé directement en `status='confirmed'` (une heure est alors obligatoire).
2. **Automatique** (`inventory/transport_autogen.py`) : dès que du matériel est requis à un lieu où rien ne l'amène, l'app crée une **proposition** en `status='to_approve'`, pré-remplie avec ce qu'on peut déduire — lieu de départ (dernière position connue du matériel, origines **chaînées** via la timeline : entrepôt→A puis A→B, pas entrepôt→B), lieu d'arrivée (le lieu du spectacle) et matériel (groupé par couple origine/spectacle). Ce qu'on ne peut pas déduire — heure, technicien — reste vide ; l'utilisateur complète puis confirme, ce qui fait passer la proposition de l'**orange** (à approuver) au **vert** (confirmé).

**Déclenchement** (décision Samuel : automatique, pas un bouton à la demande) : signaux (`regenerate_signals.py`) sur `ShowMaterial` (assignation), `Transport` confirmé, `TransportMaterial` d'un transport confirmé, et `Show` (horaire/lieu). Chaque déclenchement lance `regenerate_project_proposals`, un *resync* idempotent des seules propositions `to_approve` du projet (garde de réentrance pour ne pas boucler sur ses propres écritures).

**Pas de mémoire de rejet** (décision Samuel) : chaque régénération recalcule l'ensemble des propositions nécessaires ; une proposition écartée réapparaîtra si le besoin est toujours là. Les transports **confirmés** ne sont jamais touchés, et un déplacement déjà couvert par un transport confirmé (même mal chronométré — c'est au rapport de cohérence de le signaler) n'est pas reproposé.

**Une proposition ne livre rien** tant qu'elle n'est pas confirmée : elle est exclue de la timeline de position (donc l'alerte `materiel_non_livre` reste, mais en `etat='propose'` / orange, avec `proposal_transport_id`), et son technicien/heure vides l'excluent de la détection de conflit.

### Conflit de technicien — reste bloquant, indicateur ajouté (décision du 2026-07-24)

Samuel a confirmé qu'un technicien ne peut pas être à deux endroits en même temps — ce qui **était déjà** détecté (section 4c), de façon **bloquante avec override `force`**. Décision retenue : **garder ce comportement** (ne pas passer en non-bloquant) et simplement **exposer l'information** pour un indicateur orange côté frontend, via le champ dérivé `has_technician_conflict` sur `TransportSerializer` (lecture seule ; vrai même pour une assignation créée avec `force: true`). Autrement dit : le blocage à la saisie reste, l'indicateur sert à repérer après coup les conflits acceptés avec `force`.

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
1. Deux entrées possibles (voir section 4quinquies) : soit **créer manuellement** un `transport` (type, lieu de départ, lieu d'arrivée, heure) — confirmé d'emblée ; soit **compléter une proposition auto** déjà générée (`status='to_approve'`, orange) quand du matériel manque à un lieu — lieux et matériel sont déjà préremplis, il ne reste qu'à saisir l'heure (et le technicien) puis à confirmer. La durée estimée peut être laissée vide : si les deux lieux ont des coordonnées GPS, elle est calculée automatiquement (Google Routes) ; sinon elle prend la valeur par défaut des réglages.
2. Renseigner le matériel transporté via le champ `materials` (liste de `{material, quantity}`) — c'est ce qui permet au module de cohérence de vérifier que le matériel requis à destination y est bien amené, et que l'origine du déplacement est cohérente (voir section 4quinquies).
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

## 6. Explicitement hors scope (validé avec Samuel)

- Portail ou module de communication bidirectionnelle avec les vendors (reste par courriel).
- Table de tâches ou de notes de suivi dans l'app.
- Historique des changements d'assignation (seules les données actuelles sont conservées).
- Budget de location (prévu comme étape future, une fois le système de base en place).

## 7. Étapes futures (non incluses dans la V1)

- Génération automatisée de courriels de demande de location (via Claude ou script), pré-remplis avec les infos du spectacle.
- Module de budget de location attaché aux spectacles.
- Rôles utilisateurs plus granulaires si l'équipe grandit.
