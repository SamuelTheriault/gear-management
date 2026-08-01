# gear-management — contexte pour Claude Code

Application interne de gestion de matériel de production (inventaire,
assignation aux spectacles/répétitions, techniciens, détection de conflits
d'horaire). Usage solo/interne pour Samuel, directeur technique freelance.

**Documentation de référence (source de vérité) — toujours consulter avant de
modifier la logique métier :**

- [`recapitulatif_projet.md`](./recapitulatif_projet.md) — scope V1, stack, état d'avancement
- [`architecture.md`](./architecture.md) — logique de conflits, workflows
- [`schema.md`](./schema.md) — structure complète de la base de données
- [`security.md`](./security.md) — règles de gestion des secrets (à respecter strictement)
- [`agents_tools.md`](./agents_tools.md) — cycle de dev par phase

## Stack

| Couche | Techno |
|---|---|
| Backend | Django 5.2 + DRF, app `inventory` dans `backend/` |
| Base de données | MySQL 8.0 en prod (Railway managé), SQLite en local par défaut |
| Frontend | Vue 3 + Vite, dans `frontend/` |
| Auth | Google OAuth 2.0 (pas encore implémenté) |
| Hébergement | Railway — déploiement Git automatique depuis `main` |

## Commandes

Backend (depuis `backend/`, venv activé) :
```bash
python manage.py runserver
python manage.py makemigrations && python manage.py migrate
python manage.py test
python manage.py check --deploy   # audit sécurité avant déploiement
```

Frontend (depuis `frontend/`) :
```bash
npm run dev
npm run build
```

## Conventions du projet

- Commentaires et docstrings en français dans le code backend (voir `models.py` existant).
- Les modèles Django (`backend/inventory/models.py`) doivent rester synchronisés
  avec `schema.md` — toute divergence doit être corrigée dans les deux sens.
- Migrations Django uniquement (pas de SQL manuel).
- Aucun secret en dur : tout passe par `.env` (local, non commité) ou les
  variables Railway en prod — voir `security.md`.
- La détection de conflits (matériel + techniciens, fenêtres effectives avec
  buffers) est le cœur fonctionnel de l'app — tout changement à cette logique
  doit être testé (`ShowMaterial`/`ShowTechnician`, propriétés `effective_start`/
  `effective_end` sur `Show`).
- Piège connu : Railway ne supporte pas la phase `release:` façon Heroku —
  `collectstatic` et `migrate` tournent dans la commande `web:` du `Procfile`.

## Sous-agents disponibles (`.claude/agents/`)

- `django-backend` — modèles, serializers, vues DRF, migrations.
- `vue-frontend` — composants Vue, appels API, formulaires.
- `conflict-logic-tester` — tests de la logique de conflits (cas limites d'horaire).
- `code-reviewer` — relecture avant merge (correction + sécurité + cohérence avec la doc).
- `railway-deploy-checker` — checklist pré-déploiement Railway.
- `docs-sync` — met à jour `schema.md`/`architecture.md`/`recapitulatif_projet.md` après un changement structurant.

## Mise à jour (2026-07-30, suite) — Catégories de matériel éditables

`Material.category` n'est plus un `CharField` à choix figés : c'est une FK
vers le nouveau modèle **`MaterialCategory`** (table `material_categories`,
**une liste par projet**, `name` + `color`, unicité en base sur
`project + name`). Migration `0014_material_category` en 3 temps (table +
champ temporaire, `RunPython` de seed/remappage, suppression + renommage) —
un `AlterField` direct CharField → FK ferait tenter la conversion de
« audio » en entier.

Points à ne pas casser :

- **Ce n'est pas `Department`** (retiré le 2026-07-29) : pas de responsable
  ni de contact, seulement nom + couleur.
- Suppression = `DELETE /api/material-categories/{id}/?reassign_to=<id>`
  (FK en `PROTECT`). Sans le paramètre → 400 + `material_count` ;
  `?reassign_to=` vide → matériel laissé sans catégorie.
- Chaque nouveau `Project` reçoit les 9 catégories historiques via le signal
  `creer_categories_par_defaut` (`signals.py`), et `duplicate_project`
  recopie/remappe les catégories du projet source.
- Le frontend n'a plus **aucune** table `categoryMeta` en dur : nom et
  couleur viennent de `category_name`/`category_color`
  (`MaterialSerializer`) et `material_category_name`/`_color`
  (`ShowMaterialSerializer`).
- Nouvel écran `CategoriesMaterielView.vue` (`/materiel/categories`), atteint
  par un sous-menu sous Matériel dans `AppShell.vue`.

Suite de tests : 187, flake8 propre.

## Mise à jour (2026-07-30, suite) — Matériel disponible au départ d'un transport

`get_venue_material_availability()` (`transport_coherence.py`) répond « quel
matériel est présent à ce lieu à cet instant », exposé par
`GET /api/transports/{id}/material-availability/`. La modale « Ajouter du
matériel » de `TransportDetailView.vue` grise et **désactive** ce qui n'est
pas au lieu de départ.

À ne pas confondre : le blocage est **côté interface seulement**. La cohérence
des emplacements reste un rapport non bloquant côté API (décision du
2026-07-24) — ne pas transformer ça en validation `400` sans redemander à
Samuel. Autres points : le transport s'exclut lui-même du calcul
(`exclude_transport`), et sans `scheduled_datetime` l'endpoint renvoie
`at: null` + tout le stock disponible.

Suite de tests : 196, flake8 propre, aucune migration.

## Mise à jour (2026-07-30, suite) — Plusieurs techniciens par déplacement

`Transport.technician` (FK unique) est remplacé par la table de liaison
**`TransportTechnician`** (`transport_technicians`, `unique_together`), sans
rôle ni hiérarchie — le rôle reste `Technician.specialty`, comme pour
`ShowTechnician`. Migration `0015_transport_technicians` : créer la table,
recopier les affectations, **puis** supprimer l'ancien champ (l'ordre
inverse perdrait les données).

Impact sur le cœur fonctionnel — à ne pas casser :

- L'unité d'engagement vérifiée par `conflicts.py` est le couple
  **(transport, technicien)**, plus le transport. `_technician_commitments`,
  `_technician_conflict_object_key` et `serialize_technician_conflict`
  travaillent sur `TransportTechnician`. Le `type` exposé reste
  `'transport'` côté API.
- Un seul bandeau d'erreur regroupe les conflits de toute l'équipe à la
  saisie (un seul « Forcer »). `has_technician_conflict` = vrai dès qu'au
  moins une personne est en conflit.
- `GET /api/transports/?technician=` traverse la liaison avec `distinct()`.
- Écriture imbriquée : `TransportSerializer.technicians` (liste de
  `{technician}`), même pattern que `materials` — PATCH remplace toute la
  liste, l'omettre la laisse intacte. Lecture : `technicians` +
  `technician_names`.
- `AssignerTechnicienModal` est en multi-sélection et **reste ouverte** tant
  qu'il reste des conflits à forcer (argument `done` de l'événement
  `assigned`).

Suite de tests : 208, flake8 propre.

## Mise à jour (2026-07-30, suite) — Décocher pour retirer une assignation

Les trois modales d'assignation (techniciens et matériel d'un spectacle,
matériel d'un transport) permettent de **décocher** une ligne déjà assignée
pour la retirer. Rien ne part avant le bouton « Appliquer » — décocher marque
la ligne (barrée), recocher annule.

- Spectacle : `DELETE /api/show-technicians/{id}/` et
  `DELETE /api/show-materials/{id}/`. Transport : purement local, appliqué au
  PATCH (`TransportSerializer.materials`).
- **Les retraits s'exécutent AVANT les ajouts** — libérer une ressource peut
  lever le conflit de capacité qui bloquerait un ajout de la même fournée.
  Ne pas inverser.
- `AssignerTechnicienModal` reçoit `assignedTechnicians` (objets
  `ShowTechnician` complets), plus `assignedTechnicianIds` : le DELETE a
  besoin de l'id de l'assignation, pas du technicien.
- `confirmAddMaterial` (transport) reconstruit la liste depuis les cases
  cochées mais **conserve** le matériel hors catalogue affiché (inactif,
  filtré) — sinon il disparaîtrait silencieusement.

Suite de tests : 211, flake8 propre, aucune migration.

## Mise à jour (2026-07-30, suite) — Retour du matériel à son origine

Trois changements liés :

- **`Material.venue` obligatoire via l'API** (`MaterialSerializer`), non
  effaçable. Le champ reste **nullable en base** : ne pas ajouter de
  contrainte DB, l'historique déjà saisi et l'issue `origine_inconnue` en
  dépendent.
- **Dates de projet** : `Project.start_date`/`end_date` (qui existaient déjà)
  sont maintenant éditables dans `ReglagesView`. Elles sont sur le **projet**,
  pas dans `Settings` — `Settings` est commun à toutes les productions.
- **`retour_manquant`** : 4e type d'incohérence dans `transport_coherence.py`
  (`get_material_return_issue`). À `get_project_horizon(project)` —
  `end_date` fin de journée, sinon fin du dernier événement — tout le
  matériel doit être revenu à son `venue`. **Non bloquant**, comme le reste
  du rapport.

Ça **révise la portée « aller seulement »** du 2026-07-24 : on ne vérifie
toujours pas qu'un `pickup` précis existe pour chaque livraison, on contrôle
le **résultat net** à l'horizon. Ne pas transformer ça en exigence de boucle
fermée sans redemander à Samuel.

La fenêtre de dates ne borne **que** ce contrôle de retour — la détection de
conflits continue de couvrir tout le projet.

Suite de tests : 222, flake8 propre, aucune migration.

## Mise à jour (2026-07-30, suite) — Sélection en cascade des kits

Cocher un matériel parent dans une modale d'assignation coche aussi ses
composants ; décocher le parent les décoche. Les composants restent
décochables individuellement. Appliqué à `AssignerMaterielModal` (spectacle)
et à la modale « Ajouter du matériel » de `TransportDetailView`.

- **Spectacle** : la cascade ne touche jamais un composant déjà assigné.
- **Transport** : la cascade saute les composants absents du lieu de départ.
- **Hypothèse critique** (couverte par `KitCascadeAssignmentTests`) :
  assigner un kit ET ses composants au **même** spectacle n'est pas un
  conflit, parce que `get_material_conflicts` fait
  `.exclude(show_id=show.id)` sur ses candidats de famille. Retirer cet
  `exclude` casserait la cascade à chaque kit coché.

Frontend seulement, aucun changement backend. Suite de tests : 225.

## Mise à jour (2026-07-30, suite) — Suppression lieu / spectacle / transport

Bouton Supprimer + confirmation en bas du formulaire d'édition des trois
fiches (`useSuppressionFiche.js`, styles globaux `fiche-danger` /
`fiche-confirm`). Comportements **volontairement différents** :

- **Lieu** : `VenueViewSet.destroy` refuse (400 + décomptes `shows` /
  `transports` / `materials`) tant qu'il est référencé. Ne pas retirer ce
  garde-fou : `Show.venue` et les FK de `Transport` sont en `PROTECT`, un
  `ProtectedError` sortirait en **500**. Le matériel bloque aussi, bien que
  `Material.venue` soit en `SET_NULL` — vider l'origine contredirait la
  règle du lieu obligatoire.
- **Spectacle** : autorisé, cascade sur assignations + transports.
  `ShowSerializer.deletion_impact` donne les décomptes affichés dans la
  confirmation — propositions auto-générées comprises.
- **Transport** : autorisé, cascade sur ses lignes matériel/techniciens.

Suite de tests : 232, flake8 propre, aucune migration.

## Mise à jour (2026-07-30, suite) — Écrans « Parcours »

Deux pages en **sous-menu du Tableau de bord** (`AppShell.vue` : Vue
d'ensemble / Parcours Matériel / Parcours Technicien) : `/parcours/materiel`
et `/parcours/techniciens`, avec redirections depuis les anciens chemins
`/materiel/parcours` et `/techniciens/parcours`. L'entrée parente utilise
`activeMatch` — `/` préfixe tout, un `startsWith` ne peut pas servir ici.
Sélection multiple à cocher, timeline sur **toute la durée du projet**
(`get_project_window`), graduation en jours.

- `GET /api/projects/{id}/material-journey/?materials=` — séjours par lieu
  (`get_material_journey`), plus les assignations à marquer par-dessus.
  **Réutilise le grand livre de positions** de `transport_coherence.py` :
  même source que la cohérence et que la disponibilité au départ d'un
  transport. Ne pas dupliquer cette logique ailleurs.
- `GET /api/projects/{id}/technician-journey/?technicians=` — spectacles ET
  déplacements sur la même piste, en fenêtres **effectives** (buffers
  compris, comme la détection de conflit), avec le drapeau `conflict` issu du
  rapport project-wide.
- Simplification à connaître : pour du matériel en plusieurs exemplaires
  éparpillés, un séjour porte le **lieu majoritaire** + la quantité — le
  modèle n'identifie pas les unités une à une.
- Nouveau composable `useParcours.js` (chargement, sélection, temps →
  pourcentage, graduations) et styles globaux `parcours-*`.
- Filtre par catégorie sur le parcours matériel ; « Tout » ne coche que les
  options **visibles** (`selectAll(visible)`). Attention : appeler
  `selectAll` sans parenthèses dans un template passerait l'événement de
  clic — un garde-fou l'ignore.
- Les puces de catégorie (inventaire, parcours, modales) ne listent que les
  catégories **réellement présentes** dans le matériel affiché — essayé dans
  l'autre sens le 2026-07-30, puis revenu en arrière : une barre de puces qui
  ne mènent nulle part n'aide pas. Le référentiel complet est dans
  `/materiel/categories`. Idem pour « Sans catégorie », affichée seulement
  s'il y a du matériel non classé.

Suite de tests : 240, flake8 propre, aucune migration.

## Mise à jour (2026-07-31) — Blocs rattachés à un événement

`Show.parent_show` (self-FK, CASCADE) accroche à un événement une plage de
**montage**/répétition en amont et une de **démontage** en aval. Nouveaux
`event_type` : `setup`, `teardown`. Migration `0016_show_phases`.

Choix de fond : **un bloc est un `Show` complet**, pas une table de créneaux
— il occupe le lieu, a son matériel, ses techniciens, ses transports, et
participe aux conflits comme tout événement. Ne pas le remplacer par un
modèle parallèle : c'est précisément ce qu'on a évité.

- **Piège central** : un bloc est collé à son événement, leurs fenêtres
  effectives se chevauchent dès qu'un buffer existe. `Show.family_ids` est
  passé en `exclude_family_ids` à `get_venue_conflicts` — sans quoi chaque
  montage serait en « conflit de lieu » avec son propre spectacle. Ne pas
  retirer : `ShowPhasesAPITests` couvre les deux sens (pas de faux conflit
  avec le parent, vrai conflit avec un tiers toujours détecté).
- Contraintes serializer : un seul niveau de hiérarchie, même projet, **même
  lieu** que le parent.
- **Ressources : deux régimes selon le type de bloc**
  (`Show.INHERITING_PHASE_TYPES` / `inherits_resources`).
  - **Montage et démontage héritent** : ils n'ont aucune assignation propre,
    l'assignation directe est refusée par `ShowMaterialSerializer`/
    `ShowTechnicianSerializer`. Deux fenêtres coexistent volontairement sur
    `Show` — `effective_*` (le créneau seul, pour le conflit de **lieu**) et
    `engagement_*` (événement + montage/démontage, pour les conflits
    **matériel et technicien**). Ne pas fusionner les deux.
  - **Une répétition rattachée est autonome** : `ShowSerializer.create`
    recopie les assignations de l'événement une fois, à la création, puis
    elles s'éditent librement (rien ne redescend ensuite). Elle n'étire donc
    **pas** la fenêtre d'engagement du parent — l'y inclure mettrait
    l'événement en conflit avec sa propre répétition.
  - Corollaire : `get_material_conflicts` et `get_technician_conflicts`
    excluent toute la **famille** (`Show.family_ids`), plus seulement
    `show.id`. Sans ça, la copie entre en conflit avec l'événement dès qu'un
    buffer fait toucher les deux fenêtres — ce qui est le cas par défaut. Sur
    un spectacle sans bloc, `family_ids` vaut `{show.id}` : comportement
    inchangé, y compris l'hypothèse du kit assigné avec ses composants.
- Les blocs créés depuis la fiche ont des buffers à 0 (leur créneau est déjà
  explicite) — décision « pas de double comptage », les buffers restent pour
  les événements sans bloc.
- La carte de résumé de la fiche (Horaire prévu / Fenêtre effective /
  Buffers / Lieu) rappelle les blocs, une ligne par bloc en ordre
  chronologique (`summaryRange`, `fmtBlockRange`) : la fenêtre effective
  affichée à côté ne couvre que le créneau de l'événement, la période
  réellement mobilisée va du premier bloc au dernier. La date n'est rappelée
  que si elle diffère de celle de l'événement (ou, pour la fin, du début du
  bloc). La section « Blocs rattachés » plus bas reste celle où on ajoute et
  supprime.
- Les répétitions **indépendantes** n'utilisent pas ce mécanisme : un `Show`
  `rehearsal` sans `parent_show` suffit, c'était déjà le cas.

Suite de tests : 266, flake8 propre.

## Revue de code et commentaires (CI)

Workflow par PR (pas de push direct sur `main`) : le gabarit
`.github/pull_request_template.md` rappelle d'invoquer `code-reviewer` avant
de merger. GitHub empêchant l'auto-approbation d'une PR par son propre
auteur, il n'y a pas de blocage strict "1 approbation requise" — la
discipline repose sur la checklist du gabarit.

La CI (`.github/workflows/ci.yml`) fait tourner un job `flake8` (config
`backend/.flake8`) qui **échoue si un module, une classe ou une fonction
publique du backend n'a pas de docstring** (codes D100/D101/D103 —
volontairement restreint à la présence de docstring, pas de style
pycodestyle complet). Dépendances de lint dans `backend/requirements-dev.txt`.

Pour activer un vrai blocage de merge sur GitHub (PR obligatoire + CI verte
avant de pouvoir merger) : Settings → Branches → Add branch protection rule
sur `main` → cocher "Require a pull request before merging" et "Require
status checks to pass before merging" (sélectionner les jobs `Backend
(Django)` et `Frontend (Vue)`). Nécessite un accès admin au repo GitHub —
pas faisable depuis Claude Code.

## État actuel (2026-07-24)

Backend/frontend scaffoldés, déploiement Railway fonctionnel
(`gear-management-production.up.railway.app`). Modèles Django (8 tables
initiales + `Transport`, `Settings`, `Project`, et `TransportMaterial`
ajouté le 2026-07-24), logique de détection de conflits
(`backend/inventory/conflicts.py`, chevauchement strict — deux fenêtres
dos-à-dos ne sont pas en conflit), serializers DRF
(`backend/inventory/serializers.py`, validation bloquante par défaut avec
override via un champ `force`), vues/urls DRF câblées
(`backend/inventory/views.py`/`urls.py`, montées sous `/api/`), et une suite
de tests (`backend/inventory/tests.py`, 124 tests, tous au vert).

**Module transport — cohérence des emplacements (2026-07-24)** :
`backend/inventory/transport_coherence.py` reconstruit une timeline de
position par matériel (départ = `Material.venue`, puis transports **confirmés**
via la table de liaison `TransportMaterial`) et produit un **rapport non
bloquant** (≠ des conflits, qui sont bloquants) : matériel requis mais non
livré (`materiel_non_livre`, avec `etat` orange/rouge), transport à l'origine
incohérente (`origine_incoherente`), matériel sans entrepôt
(`origine_inconnue`). Exposé par `GET /api/shows/{id}/transport-coherence/` et
`GET /api/projects/{id}/transport-coherence/`. Portée : aller seulement.

**Module transport — création manuelle + génération auto (2026-07-24)** :
`Transport` gagne un `status` (`confirmed`/`to_approve`) et un
`scheduled_datetime` nullable. `backend/inventory/transport_autogen.py`
(`regenerate_project_proposals`) génère automatiquement des propositions
`to_approve` (orange) pour chaque déplacement manquant — origines chaînées,
matériel groupé par couple origine/spectacle — déclenché par signaux
(`regenerate_signals.py`) sur `ShowMaterial`/`Transport` confirmé/
`TransportMaterial`/`Show`, avec garde de réentrance. Resync idempotent, pas
de mémoire de rejet, transports confirmés jamais touchés. Le conflit de
technicien reste **bloquant + force** ; `has_technician_conflict` (dérivé sur
`TransportSerializer`) l'expose pour l'indicateur orange. Voir
`architecture.md`, section 4quinquies, et `schema.md`, sections 9 et 12.

Suite de tests : `inventory/tests.py` (113) + `test_settings_and_maps.py` (20)
+ `test_oauth_provisioning.py` (4) = 137 tests, tous au vert ; flake8
(docstrings) propre. Migrations `0011_transportmaterial` et
`0012_transport_status_scheduled_nullable`.

Reste à faire : superutilisateur Django, OAuth Google, frontend connecté à
l'API (dont l'UI du module transport : menus déroulants de lieux, indicateur
orange « à approuver », complétion/confirmation des propositions).

## Mise à jour (2026-07-29)

Le modèle `Department` (table `departments`, FK `Material.department`) a été
**retiré** à la demande de Samuel : faisait doublon avec `Material.category`
en pratique. Voir migration `0013_remove_department` et la note dédiée dans
`recapitulatif_projet.md`. Le frontend colore désormais le matériel et les
assignations show/matériel par `category` (`material_category` sur
`ShowMaterialSerializer`) plutôt que par département. Suite de tests : 141
(était 149), flake8 propre.

Phase 1 du portage frontend (Vue) terminée depuis : Spectacles, Matériel,
Lieux, Techniciens — liste + fiche pour chacun, branchés sur l'API réelle
(voir `frontend/src/views/`, `frontend/src/router/index.js`). L'écran
Départements existait mais a été retiré avec le modèle. Phase 2 (Transports/
Assignations/Conflits/Cohérence) et phase 3 (Réglages/Utilisateurs/Login) pas
encore commencées.

## Mise à jour (2026-07-30)

Phase 2 bien avancée : Transports (liste+fiche), Assignations matériel et
technicien (modales déclenchées depuis `SpectacleDetailView.vue`,
`AssignerMaterielModal.vue`/`AssignerTechnicienModal.vue`) et Conflits
(`ConflitsView.vue`, route `/conflits`) sont faits et branchés sur l'API
réelle. Nouvel endpoint `GET /api/projects/{id}/conflicts/`
(`ProjectViewSet.conflicts` → `get_project_conflicts` dans `conflicts.py`) :
vue d'ensemble project-wide et **dédupliquée** des conflits (lieu/matériel/
technicien), à ne pas confondre avec `GET /shows/{id}/conflicts/` qui reste
par spectacle. `serialize_venue_conflict` expose maintenant `venue_name`.
Voir la note dédiée dans `recapitulatif_projet.md` et `architecture.md`
(section 4, comportement bloquant + override). Suite de tests : 146 (était
141), flake8 propre.

Phase 2 terminée : Cohérence des emplacements (`CoherenceEmplacementsView.vue`,
route `/coherence`) branchée sur l'endpoint déjà existant `GET /api/projects/
{id}/transport-coherence/` (aucun changement backend requis ici, contrairement
à Conflits). Les 4 catégories du mockup (manquant/proposé/origine incohérente/
origine inconnue) sont reconstituées côté frontend à partir des champs réels
`type`/`etat` du rapport (`materiel_non_livre` + `etat` distingue manquant vs
proposé côté backend, pas deux types séparés). Le texte de contexte de chaque
ligne réutilise directement `issue.detail` (généré backend) plutôt que d'être
reconstruit côté Vue.

Phase 2 (Transports/Assignations/Conflits/Cohérence) est maintenant
**complète**.

## Mise à jour (2026-07-30, suite) — Phase 3

Phase 3 (Réglages/Utilisateurs/Login) terminée côté frontend. Le backend
existait déjà en grande partie (voir `recapitulatif_projet.md`, notes des
étapes 7-8) : `/api/settings/`, `/api/users/`, `/accounts/google/login/`
(django-allauth), `/api/auth/user/`/`/api/auth/logout/` (dj-rest-auth)
étaient tous câblés, seul le Vue manquait.

- `LoginView.vue` (`/login`) : bouton Google = `<a href>` vers
  `googleLoginUrl` (`useAuth.js`), pas un appel API (redirection pleine page,
  flux OAuth "classique").
- `useAuth.js` (nouveau, même pattern singleton que `useActiveProject.js`) +
  garde `router.beforeEach` : toute route sauf `/login` exige une session
  valide, sinon redirection.
- `ReglagesView.vue` (`/reglages`) : branché sur le singleton `Settings` réel
  + section Projets (liste/création) via `useActiveProject` (nouvel export
  `refreshProjects()`).
- `UtilisateursView.vue` (`/utilisateurs`) : branché sur `/api/users/`. Le
  formulaire d'ajout correspond au vrai flux de pré-provisioning par courriel
  déjà implémenté dans `signals.py`.
- `AppShell.vue` : courriel de session + lien déconnexion en pied de sidebar.

**Bloquant restant, hors du code** : `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET`
sont vides dans `backend/.env` — le bouton de login redirige vers Google mais
échouera tant que Samuel n'a pas créé ces identifiants dans Google Cloud.

## Mise à jour (2026-07-30, suite) — Dashboard branché

`DashboardView.vue` ne reprend plus les données de démonstration de la
maquette — dernière pièce statique de l'app, maintenant branchée :
`GET /shows/`, `GET /materials/` (total d'items = somme des `quantity`) et
`GET /projects/{id}/conflicts/` (même endpoint que `ConflitsView.vue`).
Différences volontaires par rapport au mockup : la fenêtre horaire de
« Cette semaine » est calculée dynamiquement à partir des vrais horaires
(plutôt que figée 16h–minuit), et un bloc n'est coloré en conflit que s'il
apparaît dans le vrai rapport de conflits (`conflictedShowIds`) — un simple
chevauchement horaire entre deux spectacles sans ressource/lieu partagé
n'est pas un conflit dans cette app.

Reste : le statut d'`Exploration.dc.html` à confirmer avec Samuel
(probablement des brouillons de design jetables).

## Mise à jour (2026-07-30, suite) — Fenêtre départ/arrivée des transports

Nouvelle règle sur `Transport` (backend `conflicts.py`/`serializers.py`) : un
déplacement doit avoir lieu entre la fin effective du spectacle de départ et
le début effectif du spectacle d'arrivée. `Transport` n'a qu'UN spectacle
explicite (`show`) — l'autre bout (juste un lieu) est déduit automatiquement
(`find_departure_show`/`find_arrival_show`/`get_transport_reference_shows`,
`None` si lieu d'entrepôt). Bloquant + `force: true`, même pattern que les
autres conflits (pas une règle absolue). `TransportSerializer` expose
`departure_show`/`arrival_show` en lecture. `TransportDetailView.vue` les
affiche pour référence et propose par défaut `departure_show.effective_end`
comme heure suggérée si aucune heure n'est encore saisie. Voir la note dédiée
dans `recapitulatif_projet.md` et `architecture.md` (section 4e). 8 nouveaux
tests, suite complète à 154, flake8 propre, pas de migration.

## Mise à jour (2026-07-30, suite) — Code court des lieux exposé au frontend

`Venue.code` (VARCHAR(4), majuscules, unique par projet) existait côté
backend depuis le 2026-07-19 mais n'était saisissable nulle part dans le
Vue. Ajouté : champ « Code » au formulaire d'ajout de `LieuxView.vue` (+
pastille sur les cartes) et édition inline du code sur `LieuDetailView.vue`
(`PATCH /api/venues/{id}/` avec ce seul champ). Aucun changement de modèle
ni migration ; 4 tests sur le PATCH partiel de `code`, suite à 158, flake8
propre.

Étendu ensuite (même jour) : l'édition inline du seul code est remplacée par
un bouton **« Modifier la fiche »** dans l'entête de `LieuDetailView.vue`,
qui bascule toute la carte d'infos en édition et enregistre en **un seul
PATCH** (`name`, `code`, `address`, `contact_name`, `contact_info`, `notes`,
`is_storage`, `latitude`, `longitude` — `project` volontairement exclu :
déplacer un lieu de projet casserait ses spectacles/matériel/transports).
`latitude`/`longitude` vidés partent en `null`, pas en chaîne vide. Erreurs
DRF affichées par champ. 4 tests de plus, suite à 162, flake8 propre.

## Mise à jour (2026-07-30, suite) — Édition des fiches généralisée

Le pattern « Modifier la fiche » est étendu à Matériel, Technicien et
Spectacle. Deux points structurants :

- `frontend/src/composables/useFicheEdition.js` (nouveau) porte l'état
  commun — `editing`/`draft`/`saving`, erreurs DRF **dispatchées par champ**
  (`fieldErrors`), corps brut de la dernière erreur (`lastError`, pour les
  validations qui ne sont pas des erreurs de champ, comme le conflit de lieu
  overridable par `force`), et le PATCH. **Pas** un singleton, contrairement
  à `useActiveProject`/`useAuth`.
- Les styles du formulaire sont **globaux** (classes `fiche-*` dans
  `src/style.css`), pas `scoped` : quatre fiches partagent le même
  formulaire, quatre copies auraient divergé.

`TransportDetailView.vue` est volontairement **exclu** : sa fiche est déjà
un formulaire toujours ouvert (on y arrive pour compléter/confirmer une
proposition auto-générée), un mode lecture n'y ajouterait qu'un clic.

Le champ `notes` du spectacle, exposé par `ShowSerializer` mais éditable
nulle part dans le Vue, est enfin dans le formulaire. Aucun changement
backend ; 9 tests ajoutés (`FicheEditionPatchAPITests`), suite à 171,
flake8 propre, pas de migration.

## Mise à jour (2026-07-30, suite) — Dashboard : axe horaire + transports

Deux ajouts frontend-only sur `DashboardView.vue` (aucun changement backend,
aucune migration) :

- La timeline « Cette semaine » affiche maintenant un axe d'heures en haut
  du tableau (graduation adaptative : 30/60/120 min selon l'étendue de la
  fenêtre) et des lignes verticales pointillées de référence dans chaque
  piste, alignées sur les mêmes repères.
- Les déplacements (`GET /api/transports/?project=`) apparaissent désormais
  dans cette même timeline, aux côtés des spectacles — fusionnés dans une
  seule liste d'entrées avant l'attribution de « voie », pour éviter tout
  chevauchement visuel entre un bloc spectacle et un bloc transport. Un
  transport sans `scheduled_datetime` (proposition `to_approve` non
  complétée) est ignoré, faute de fenêtre exploitable. Code couleur :
  lavande = confirmé, orange = à approuver, rouge = conflit technicien
  (`has_technician_conflict`) — bordure pointillée en plus pour distinguer
  visuellement un bloc transport d'un bloc spectacle.

## Mise à jour (2026-07-30, suite) — Filtres de type sur le Dashboard

Puces de filtre (« Tous »/Spectacles/Répétitions/Entreposage/Transports) en
haut de `DashboardView.vue`, une par `event_type` de `Show` plus Transport.
Bascule indépendante par type (pas un select unique façon `MaterielView.vue`)
pour pouvoir combiner librement, ex. cacher les répétitions en gardant
spectacles + transports. S'applique à la timeline « Cette semaine » et à
« Spectacles à venir » ; les cartes de stats ne sont pas filtrées (pas de
découpage naturel par ce type). Frontend-only, aucun changement backend.

## Mise à jour (2026-07-30, suite) — Info-bulle + navigation sur la timeline

Chaque bloc de la timeline « Cette semaine » (`DashboardView.vue`) affiche
maintenant une info-bulle au survol (lieu + type pour un spectacle,
technicien assigné + contenu du camion pour un transport, mention du conflit
le cas échéant) — CSS-only via `:hover`, pas d'état Vue à gérer. Un clic sur
le bloc navigue vers la fiche associée (`/spectacles/:id` ou
`/transports/:id`). `.dash-timeline__track`/`.dash-timeline__block` ont perdu
leur `overflow:hidden` pour laisser l'info-bulle déborder au-dessus de la
piste. Frontend-only, aucun changement backend.

## Mise à jour (2026-07-30, suite) — Glisser-déposer pour ajuster l'horaire

Chaque bloc de la timeline « Cette semaine » a maintenant deux poignées de
redimensionnement (bords gauche/droit = début/fin) et se déplace en entier
depuis son centre (garde la durée) — horizontal seulement, on ne change pas
le jour d'un événement par ce biais. Au relâchement : `PATCH /shows/{id}/`
(`start_datetime`/`end_datetime`) ou `PATCH /transports/{id}/`
(`scheduled_datetime`/`estimated_duration_minutes`), **sans** `force` — en
cas de conflit bloquant (400), le bloc revient à sa position d'origine et un
bandeau d'erreur s'affiche (pas de bouton « Forcer » inline ici,
l'ajustement fin se fait sur la fiche). `dragState` porte le glisser en
cours ; un clic sans mouvement continue de naviguer vers la fiche
(`suppressClick` évite la navigation accidentelle juste après un glisser
réel). Frontend-only, aucun changement backend — les endpoints PATCH
existaient déjà.

À noter (comportement préexistant, pas introduit ici) : `ShowSerializer.
validate()` ne bloque que les conflits de **lieu** sur un changement
d'horaire — les conflits de matériel/technicien (`ShowMaterial`/
`ShowTechnician`) ne sont pas revalidés à ce moment-là, même chose que
l'édition de fiche existante sur `SpectacleDetailView.vue`.

Étendu ensuite (même jour, à la demande de Samuel) : le glisser-déposer ne
démarre que si la touche **Cmd (⌘)** est enfoncée au moment du
`pointerdown` (`event.metaKey`), pour éviter un ajustement accidentel
d'horaire lors d'un simple clic. Sans Cmd, `beginDrag` retourne
immédiatement sans `preventDefault`/`stopPropagation` — le clic continue
normalement vers la navigation, y compris sur une poignée de
redimensionnement. Indice discret dans la légende de la timeline
(« ⌘ + glisser un bloc pour ajuster son horaire »).

## Mise à jour (2026-07-30, suite) — Modales d'ajout de matériel unifiées

`AssignerMaterielModal.vue` (assignation matériel → spectacle) est réécrite
pour reprendre l'affichage de la modale « Ajouter du matériel » de
`TransportDetailView.vue` : liste à cocher de tout le catalogue disponible
avec une quantité modifiable à droite de chaque ligne, plutôt qu'un unique
`<select>` + un item à la fois. Les deux modales sont aussi agrandies
(`min(640px, 94vw)`, `max-height: 85vh`) pour voir plus d'éléments sans
défiler.

Différence structurelle qui a orienté l'implémentation : `Transport` a un
champ imbriqué `materials` (un seul PATCH), donc sa modale ne fait que du
staging local. `ShowMaterial` n'a pas d'équivalent bulk côté API — chaque
ligne cochée devient un `POST /api/show-materials/` séparé au clic sur
« Assigner » (boucle séquentielle, pas un seul appel). Les lignes qui
réussissent disparaissent de la liste (`submittedIds`, exclu de
`availableMaterials` en plus de `assignedMaterialIds`) ; celles en conflit
bloquant (voir `ShowMaterialSerializer.validate()`) restent affichées avec
le détail, regroupées derrière un bouton « Forcer N conflits » au pied de la
modale ; celles en erreur non-overridable (quantité > stock, projet
différent) affichent l'erreur sous la ligne, à corriger avant de
ressoumettre. La « location ponctuelle » (`is_rental`/`rental_vendor`,
propre à `ShowMaterial`, sans équivalent sur `Transport`) reste disponible
via un toggle + champ fournisseur révélé sous chaque ligne cochée. Aucun
changement backend, aucune migration.

Complété ensuite (même jour) : `SpectacleDetailView.vue` n'avait aucun moyen
de retirer un matériel déjà assigné. Ajout d'un bouton « ✕ » par ligne
(`removeMaterial`, `DELETE /api/show-materials/{id}/` puis rechargement) —
même geste que le retrait de ligne sur `TransportDetailView.vue`, mais ici
l'appel API est immédiat (pas de confirmation, pas de staging local) : à la
différence du transport, `ShowMaterial` est déjà persisté dès l'assignation,
il n'y a pas de PATCH global à attendre. Aucun changement backend (`DELETE`
déjà supporté par `ShowMaterialViewSet`, `ModelViewSet` standard).

Complété une troisième fois (même jour, à la demande de Samuel : « voir tout
d'un coup d'œil sans changer d'écran ») : le matériel déjà assigné au
spectacle n'est plus masqué dans la modale — il reste visible, verrouillé
(case cochée grisée, quantité affichée en lecture seule « Déjà assigné ·
×N », pas de toggle location). Le prop `assignedMaterialIds` (juste des ids)
est remplacé par `assignedMaterials` (objets `{material, quantity}` du vrai
`ShowMaterial`, passés depuis `SpectacleDetailView.vue` via `showMaterials`)
pour pouvoir afficher la quantité. Une ligne qu'on vient d'assigner pendant
la session de la modale (`submittedQty`) passe au même état verrouillé
immédiatement plutôt que de disparaître, pour rester cohérent avec l'idée de
tout voir d'un coup. Aucun changement backend.

Complété une quatrième fois (même jour) : puces de filtre par catégorie
(« Tous » + seulement les catégories présentes dans le catalogue, même
esprit que `MaterielView.vue`) ajoutées à la fois dans
`AssignerMaterielModal.vue` et dans la modale « Ajouter du matériel » de
`TransportDetailView.vue` (qui n'affichait encore aucune catégorie — un
point de couleur par ligne y a été ajouté au passage, avec un helper
`categoryOf` dupliqué faute de composant partagé). Le filtre agit sur la
liste affichée (`catalogRows`), pas sur la sélection déjà cochée. Aucun
changement backend.

## Mise à jour (2026-07-30, suite) — Tri des catégories insensible à la casse/aux accents

Bug signalé par Samuel : « la dernière catégorie créée n'est pas classée
adéquatement ». Cause : `MaterialCategory.Meta.ordering = ['name']` délègue
le tri à la collation par défaut du moteur — sur SQLite (dev), c'est un tri
par octets où les minuscules passent après toutes les majuscules et les
caractères accentués après tout l'ASCII. Une catégorie créée avec un nom qui
ne commence pas par une majuscule non accentuée atterrissait donc en fin de
liste au lieu de sa place alphabétique (MySQL en prod utilise en général une
collation `_ci` qui n'a pas ce problème, d'où l'écart dev/prod).
`MaterialCategoryViewSet.list()` (`backend/inventory/views.py`) retrie donc
explicitement en Python (`unicodedata.normalize('NFKD', name).casefold()`)
plutôt que de compter sur l'ORDER BY. Un test dédié
(`test_categories_listed_case_and_accent_insensitively`) crée des catégories
en minuscule et accentuée et vérifie qu'aucune n'atterrit en fin de liste.
Suite à 190 (`inventory.tests`), flake8 propre, pas de migration.

## Mise à jour (2026-07-30, suite) — Flèche de dépliage du matériel conforme à la maquette

Signalé par Samuel : la flèche de dépliage des kits (`MaterielView.vue`) ne
respectait pas `Materiel.dc.html` — c'était un simple caractère « ▸ » gris,
alors que la maquette prévoit une icône décorative en losange de points (5
rangées de 1/3/4/3/1 points, `scale(.5)`), colorée par catégorie quand
replié et grise (`rgba(255,255,255,.4)`) quand déplié, avec rotation 90° à
l'ouverture. `.kit-children` avait déjà le trait vertical (`border-left`)
mais pas les traits horizontaux de raccordement par enfant — ajoutés via
`.kit-child::before`. Frontend-only, aucun changement backend.

Ajusté ensuite (même jour, à la demande de Samuel) : le losange de points est
remplacé par un simple triangle pointant à droite (triangle CSS via
`border`, coloré par `--chevron-color`, pivote 90° à l'ouverture) — la
maquette n'était pas le bon repère ici. Le trait vertical de raccordement
(`.kit-children`) ne repose plus sur un `border-left` unique couvrant tout
le conteneur (ce qui le faisait dépasser sous le dernier enfant) : chaque
`.kit-child` porte son propre segment vertical (`::after`) jusqu'à sa propre
branche horizontale, et seul le dernier s'arrête pile à cette hauteur
(`:last-child::after { bottom: 50% }`) plutôt que de continuer dans le vide.

## Mise à jour (2026-07-31) — Parcours Matériel/Technicien : barres agrandies + info-bulle

À la demande de Samuel, les segments d'événement (`.parcours-seg`, séjours en
matériel / engagements en technicien) passent de ~22px à 30px de haut
(`.parcours-track` 34→46px, marge interne 6→8px), et le tooltip natif
(`:title`) est remplacé par une info-bulle CSS-only calquée sur celle du
Dashboard (`.parcours-tooltip`, titre + plage horaire + lignes de détail),
révélée au survol de `.parcours-seg`.

Différence assumée avec le Dashboard : l'info-bulle s'ouvre **vers le bas**,
pas au-dessus. `.parcours-board` a `overflow-x: auto` (défilement horizontal
nécessaire pour une timeline qui couvre tout le projet) — ce qui force
`overflow-y` à `auto` même sans le déclarer (règle CSS standard), donc tout
ce qui déborde verticalement risque d'être coupé. Au-dessus, la seule marge
disponible pour la première ligne est le padding-top du panneau + la
hauteur de l'axe (~34px), insuffisant. En dessous, chaque ligne suivante
(et la légende, pour la dernière) donne de la place — le padding-bottom du
panneau a été agrandi (16→28px) pour couvrir ce dernier cas. Le libellé du
segment est passé dans un span dédié (`.parcours-seg__label`, son propre
ellipsis) pour retirer `overflow:hidden` du segment lui-même, qui aurait
coupé l'info-bulle (même pattern que `.dash-timeline__block-name` sur le
Dashboard). Frontend-only, aucun changement backend, aucune migration.

Étendu ensuite (même jour, à la demande de Samuel : « la petite barre
blanche [Requis par un spectacle] plus visible ») : le marqueur
`.parcours-mark` (liseré lavande posé sous le séjour, sur
`ParcoursMaterielView.vue`) double de hauteur (3→6px) et gagne sa propre
info-bulle au survol, même pattern `.parcours-tooltip` que les segments —
ancrée sur le marqueur lui-même, pas sur le séjour, pour rester alignée
horizontalement avec l'assignation qu'il représente plutôt qu'avec le lieu
de séjour. Le marqueur reste toujours sous le segment de séjour (qui
s'arrête à `bottom:8px`), jamais chevauché. Frontend-only, aucun changement
backend.

Étendu une nouvelle fois (même jour) : la hauteur du marqueur passe à 15px
(demande explicite de Samuel), ce qui le fait maintenant chevaucher le bas
du segment de séjour — chevauchement volontaire, cohérent avec le
commentaire déjà en place (« posé PAR-DESSUS le séjour »). Découvert au
passage : l'info-bulle avait été codée (markup + données) mais jamais
révélée, faute de règle `.parcours-mark:hover .parcours-tooltip` — seul
`.parcours-seg:hover` existait. Corrigé.

## Mise à jour (2026-07-31, suite) — Transports confirmés sur le Parcours Matériel

Nouveau champ `transports` sur `GET /api/projects/{id}/material-journey/`
(`get_material_transports()`, `transport_coherence.py`) : les déplacements
**confirmés et horodatés** de chaque matériel dont la fenêtre
(`scheduled_datetime` → `effective_end`) croise la fenêtre demandée — même
filtre que `_material_events` (une proposition à approuver n'a pas encore
déplacé quoi que ce soit), mais couvre la fenêtre du transport lui-même,
pas seulement son arrivée. 2 tests ajoutés (présence + exclusion des
propositions non confirmées), suite à 244, flake8 propre, pas de migration.

Côté `ParcoursMaterielView.vue` : nouveau marqueur `.parcours-transport`,
posé au-DESSUS du segment de séjour (symétrique au marqueur d'assignation
qui est en dessous) — bleu (`oklch(0.5 0.1 250)`, même teinte que
« Déplacement » sur le Parcours Technicien), avec sa propre info-bulle
(origine → destination, quantité). Légende mise à jour.

## Mise à jour (2026-07-31, suite) — Parcours Matériel/Technicien : affichage jour par jour

Demande de Samuel : « comme le dashboard principal, avec des boutons de
filtre pour sélectionner la journée ». Le Dashboard donne à CHAQUE JOUR sa
propre ligne (avec un axe horaire) ; ici les lignes sont déjà prises par les
ressources (matériel/technicien) pour les comparer entre elles — donc au
lieu de dupliquer les lignes par jour, une seule journée à la fois est
affichée (axe 0h→24h identique à une ligne du Dashboard, avec gridlines),
choisie via `ParcoursDayPicker.vue` (nouveau composant partagé : puces +
flèches ←/→, désactivées en bout de liste).

`useParcours.js` a été retravaillé en profondeur : l'ancien axe multi-jours
continu (`ticks`, position `pct()` relative à TOUT le projet) est remplacé
par `days` (un jour calendaire par entrée, pour les puces), `selectedDayKey`/
`selectDay`/`stepDay` (la sélection), `dayBounds` (les 24h du jour choisi) et
`hourMarks` (graduation fixe toutes les 2h — plus besoin d'adaptatif 30/60/
120min comme le Dashboard, la fenêtre est toujours la même taille). Nouveau
`overlapsDay(start, end)` : chaque vue filtre ses séjours/marques/transports/
engagements avec cette fonction AVANT de les passer à `segmentStyle`, qui
positionne maintenant par rapport à la journée choisie, pas au projet entier
— un séjour à cheval sur deux jours n'apparaît donc que pour sa portion dans
le jour affiché (tronqué, pas dupliqué).

Défaut de sélection : aujourd'hui si le projet le couvre, sinon le premier
jour — ne se réinitialise que si le jour choisi sort de la liste (nouveau
projet), pas à chaque rechargement de données. Sur `ParcoursTechniciensView`,
les compteurs « X engagement(s) / Y conflit(s) » de la ligne portent
maintenant sur la journée affichée, pas tout le projet — cohérent avec
l'affichage jour par jour. Frontend-only, aucun changement backend, aucune
migration.

## Mise à jour (2026-07-31, suite) — Listes de matériel plus compactes

Demande de Samuel : « il y aura beaucoup de matériel et la liste risque de
devenir longue ». Espacement réduit sur trois listes (padding/gap, rien de
structurel) : `MaterielView.vue` (`.kit-list`/`.kit-row`/`.kit-children`/
`.kit-child`, avec les offsets du trait de raccordement des kits ajustés en
conséquence — voir la note du 2026-07-30 sur la flèche de dépliage),
`AssignerMaterielModal.vue` et la modale « Ajouter du matériel » de
`TransportDetailView.vue` (`.modal__body`/`.catalog-row`), et
`.parcours-picker`/`.parcours-option` (global, `style.css`) — ce dernier
compacte donc aussi le panneau de sélection du Parcours Technicien, pas
seulement celui du Parcours Matériel, les deux partageant le même CSS.
Frontend-only, aucun changement backend.

## Mise à jour (2026-07-31, suite) — L'événement dans la chronologie des blocs

Demande de Samuel : la liste « Montage, répétition, démontage » de
`SpectacleDetailView.vue` n'affichait que les blocs rattachés — l'heure du
spectacle lui-même n'était visible que dans la carte de résumé plus haut, pas
remise en contexte dans la chronologie. Nouveau computed `timelineEntries` :
fusionne `decoratedPhases` avec une entrée synthétique pour l'événement
(`isEvent: true`, id `'event'`), triées ensemble par `start_datetime`.

L'entrée événement n'est pas un `RouterLink` (on est déjà sur sa fiche) et
n'a pas de bouton de suppression (`v-if="!p.isEvent"` des deux côtés) — ce
n'est pas un bloc qu'on peut retirer. Légère mise en valeur visuelle
(`.row--event`, fond/bordure teintés) pour la distinguer des vrais blocs
sans la confondre avec eux. Frontend-only, aucun changement backend.

Étendu ensuite (même jour, demande de Samuel : « exactement la même chose
ici ») à la carte de résumé plus haut (« Blocs rattachés », sous Horaire
prévu/Fenêtre effective/Buffers/Lieu) : elle utilise maintenant
`timelineEntries` au lieu de `decoratedPhases`, avec le même accent visuel
(`.summary-phase--event`). L'entrée événement gagne un `summaryRange` (même
fonction `fmtBlockRange`, comparée à elle-même — la date ne s'y affiche donc
jamais). La carte n'est plus masquée quand il n'y a aucun bloc rattaché
(elle contient toujours au moins la ligne de l'événement).

## Mise à jour (2026-07-31, suite) — Chronologie accessible depuis les blocs, surbrillance, lignes cliquables

Trois changements liés, toujours sur la chronologie « Blocs rattachés » /
« Montage, répétition, démontage » de `SpectacleDetailView.vue` :

- **Visible aussi sur la fiche d'un bloc** (montage/répétition/démontage),
  pas seulement sur celle de l'événement — demande de Samuel. Piège :
  `ShowSerializer.get_phases()` renvoie toujours `[]` pour un bloc (pas de
  récursion, un seul niveau de hiérarchie), donc `show.phases` ne suffit
  plus. Nouveau ref `parentShow` : quand `show.parent_show` est défini,
  `loadShow()` va chercher `GET /shows/{parent_show}/` en plus (même
  `Promise.all`) pour obtenir les blocs FRÈRES et l'horaire de l'événement.
  Nouveau computed `timelineSource` = l'événement lui-même OU le parent
  selon le cas ; `decoratedPhases`/`timelineEntries` s'appuient dessus au
  lieu de `show.value` directement.
- **Surbrillance de la fiche affichée** : chaque entrée (bloc ou événement)
  porte un `isCurrent` (comparaison à `show.value.id`) — bordure gauche +
  fond teinté (`.row--current`/`.summary-phase--current`), cumulable avec
  `--event` quand on est sur la fiche de l'événement lui-même.
- **Lignes cliquables** : `goToItem(entry)` navigue vers `/spectacles/{id}`
  au clic sur la ligne entière (plus seulement le titre), sauf sur la ligne
  courante (no-op). Les boutons « + Montage/+ Répétition/+ Démontage »
  restent réservés à la fiche de l'événement (`v-if="!show.parent_show"`) :
  `startAddPhase`/`savePhase` utilisent `show.value.id` comme parent, et
  l'invoquer depuis la fiche d'un bloc créerait un 2e niveau de hiérarchie,
  refusé par l'API. Le bouton de suppression d'un bloc (`✕`) est masqué sur
  sa propre ligne courante (`!p.isCurrent`) pour éviter de se supprimer
  soi-même en le regardant — cette action reste possible via « Supprimer ce
  spectacle » en haut de la fiche, avec sa confirmation dédiée.

Frontend-only, aucun changement backend (réutilise `GET /shows/{id}/` déjà
existant).

## Mise à jour (2026-07-31, suite) — Audit ergonomie/navigation, première action

Passe d'ergonomie sur `frontend/src/` à la demande de Samuel (voir
`audit_ergonomie_navigation.md`, racine du repo — constats détaillés et
recommandations priorisées, non exhaustif ici). Première action retenue :
Conflits et Cohérence rejoignent le sous-menu du Tableau de bord dans
`AppShell.vue` (`navItems`), aux côtés de Vue d'ensemble et des deux
Parcours — les quatre sont des rapports transversaux au projet, plutôt que
des entités qu'on liste/édite comme un spectacle ou un lieu ; ils étaient
scindés en deux traitements sans raison apparente. `activeMatch` du parent
étend son préfixe à `/conflits` et `/coherence`, mêmes chemins qu'avant
(aucune redirection nécessaire, contrairement au renommage `/materiel/
parcours` → `/parcours/materiel` du 2026-07-30). Frontend-only, aucun
changement backend, aucune migration.

Reste du plan d'audit (non fait) : fondations CSS (tokens), classes
globales pour titres de page/puces de filtre/fond de modale, recherche
texte sur Matériel, accès mobile aux sections hors tabbar, fermeture des
modales à Échap. Voir `audit_ergonomie_navigation.md` pour le détail et
l'ordre de priorité.

## Mise à jour (2026-07-31, suite) — Audit ergonomie, point 1 : tokens CSS

`style.css` gagne six variables dans `:root` (`--accent`, `--bg-card`,
`--border-card`, `--radius-notch-lg`/`--radius-notch-sm`, `--font-mono`).
279 occurrences codées en dur dans 24 fichiers (23 vues/composants +
`style.css`) remplacées par `var(...)` — remplacement littéral exact,
aucune valeur modifiée, zéro changement visuel. Seule exception à « aucune
valeur modifiée » : `--border-card` réutilise aussi la valeur du fond
pointillé de `LoginView.vue` (identique au pixel près, mais ce n'est pas un
bord de carte — nommage à garder en tête si ce point est retouché). Le
« point 5 » de l'audit (drift des `header__title`/`.chip`) n'a volontairement
**pas** été corrigé à cette étape — seulement renommé.

## Mise à jour (2026-07-31, suite) — Audit ergonomie, point 2 : titres/puces/fond de modale globalisés

Trois blocs remontés en classes globales dans `style.css`, sur le modèle
déjà validé de `fiche-*`/`add-form-*`/`parcours-*` :

- **`.page-title`** (libellé de section statique, majuscules — écrans de
  liste + Dashboard + Réglages/Utilisateurs, qui utilisaient `dash-title`/
  `title` en local) et **`.header__title`** (titre de fiche/rapport, jamais
  en majuscules — Cohérence, Conflits, Lieu, Matériel, Spectacle,
  Transport). Ce sont deux rôles distincts, pas fusionnés en un seul.
  `header__title` avait dérivé à trois tailles (27/26/25/24px selon
  l'écran) ; unifié à 27px/0.04em (valeur déjà majoritaire, confirmé avec
  Samuel) — Lieu, Matériel et Transport ont donc un titre visiblement plus
  grand qu'avant. La fiche Technicien n'est pas concernée : son en-tête à
  avatar (`header__name`/`header__role`) reste local, c'est le point 7 de
  l'audit, pas celui-ci.
- **`.chip`/`.chip--active`** : dupliquées (avec dérive de padding/taille)
  dans 9 fichiers au total, dont 3 découverts après coup, hors du grep
  initial de l'audit (`DashboardView.vue`, `TransportsView.vue`, et le
  composant `AssignerMaterielModal.vue` — l'audit n'avait balayé que
  `views/`, pas `components/`). Unifié à `7px 14px` / `12px` (valeur
  majoritaire, confirmé avec Samuel). `.chip--small` (Spectacles),
  `.picker-chip` (Parcours Matériel) et `.tech-chip` (Transport) sont des
  variantes volontairement différentes, non touchées.
- **`.modal-overlay`** (fond assombri des modales d'assignation/
  suppression de catalogue) : remplace `overlay`/`modal-backdrop`/
  `modal-overlay`, trois noms locaux différents pour le même rôle.
  Contrairement aux deux points ci-dessus, pas de dérive visible à
  arbitrer (juste du nommage) — z-index fixé à 100, sous
  `.fiche-confirm-backdrop` (120, déjà global, inchangée) : une
  confirmation de suppression reste toujours au-dessus d'une modale
  d'assignation, jamais l'inverse.

Frontend-only, aucun changement backend, aucune migration. Les 25 fichiers
`.vue` parsent sans erreur (`@vue/compiler-sfc`) ; `npm run build` n'a pas
pu être vérifié dans ce bac à sable (binaire natif du bundler manquant pour
cette architecture) — à confirmer avec `npm run dev` en conditions réelles.
