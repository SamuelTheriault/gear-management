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

## Mise à jour (2026-08-02, suite) — Défilement horizontal natif sous zoom

Demande de Samuel : « se déplacer dans la vue » quand le zoom (ci-dessus) est
actif, pas seulement re-zoomer par paliers. Les 3 écrans passent d'un
recalcul de fenêtre (blocs positionnés relativement à la portion zoomée,
avec filtrage/rognage aux bords) à un vrai défilement natif du navigateur :
les positions restent TOUJOURS relatives à la journée complète fixe (0-24h),
seule la largeur du conteneur change avec le zoom, et `scrollLeft` amène la
portion voulue à l'écran — même principe que zoomer une image dans un
conteneur `overflow: auto`.

- **Nouveau composable partagé `useZoomScroll.js`** (`scrollRef, zoomLevel,
  scrollFraction`) : un seul `watch(zoomLevel, ...)` qui repositionne
  `el.scrollLeft = (el.scrollWidth - el.clientWidth) * scrollFraction`
  après chaque `zoomIn`/`zoomOut`/`resetZoom` (`nextTick` pour attendre le
  nouveau `scrollWidth`). Ne lit jamais le scroll manuel de l'utilisateur en
  retour — molette/trackpad/barre restent entièrement natifs entre deux
  actions de zoom.
- **`useParcours.js`** : `pct`/`segmentStyle`/`hourMarks` sont déjà
  relatifs à `dayBounds` (journée complète) depuis l'ajout du zoom — aucun
  changement de calcul de position n'était nécessaire ici, seulement
  l'exposition de deux nouveaux computed, `zoomLevel` (`dayBounds.span /
  activeWindow.span`, ≥ 1) et `scrollFraction` (position 0-1 du début de la
  fenêtre active dans la largeur totale). `ParcoursMaterielView.vue` et
  `ParcoursTechniciensView.vue` gagnent tous les deux la même structure à
  deux colonnes : `.parcours-labels` (étiquettes fixes, `style.css`) à
  gauche, `.parcours-scroll` (`overflow-x: auto`) à droite contenant
  `.parcours-scroll__content` (axe + pistes, largeur `zoomLevel * 100 %`).
  `ParcoursMaterielView` y place son axe/ses pistes/connecteurs de
  bifurcation existants tels quels ; `ParcoursTechniciensView` son
  `row.blocks` — dans les deux cas, `row.trackStyle` (matériel) ou le
  `min-height` par défaut (technicien, pas de notion de lane) fixent la
  hauteur de chaque paire étiquette/piste.
- **`DashboardView.vue`** : changement plus structurant, car `weekWindow`
  positionnait auparavant les blocs relativement à `activeWindow` (la
  portion zoomée), avec filtrage des blocs hors fenêtre et rognage aux
  bords. Réécrit pour positionner TOUS les blocs relativement à
  `DAY_SPAN_MIN` (0-1440 min) fixe, sans plus jamais filtrer/rogner — le
  zoom ne change désormais que `zoomLevel = DAY_SPAN_MIN /
  activeWindow.span` (largeur du conteneur) et `scrollFraction =
  activeWindow.start / DAY_SPAN_MIN` (position de défilement). Comme
  `autoWindow` (fenêtre par défaut) est plus étroite que la journée
  complète, `zoomLevel` est déjà > 1 avant tout clic sur zoom — c'est
  attendu, cohérent avec « Réinitialiser » qui cible `autoWindow`, pas
  0h-24h (différence déjà actée avec les Parcours). Timeline restructurée
  en deux colonnes (`.dash-timeline__labels` fixe + `.dash-timeline__scroll`
  défilable), symétrique aux Parcours.
  - **Glisser-déposer impacté** : `blockStyle` (aperçu pendant un glisser)
    et `onDragMove` (conversion pixel → minutes) utilisaient
    `weekWindow.winStart`/`span` (la fenêtre zoomée) — remplacés par
    `DAY_SPAN_MIN` directement, puisque `trackWidthPx`
    (`getBoundingClientRect` sur `.dash-timeline__track`) représente
    désormais toujours la journée complète à l'échelle du zoom courant. Un
    même déplacement en pixels correspond donc à moins de minutes quand on
    est zoomé — plus de précision, pas un bug.
- Aucun changement backend, aucune migration. Vérifié : les 5 fichiers
  touchés (3 vues, `ZoomControls.vue`, `ParcoursDayPicker.vue`) plus les 2
  composables compilent (`compileScript`/`--check`) ; simulation Node du
  calcul `scrollLeft` (fraction × `maxScroll`) sur 3 scénarios de zoom
  (milieu de journée, réinitialisé, fin de journée) et de la position de
  bloc/conversion de glisser sur le Dashboard (position fixe indépendante
  du zoom, delta de glisser proportionnellement plus fin à zoom élevé) —
  tous cohérents avec les valeurs attendues.

## Mise à jour (2026-08-02, suite) — Défilement vertical désynchronisé des étiquettes

Bug signalé par Samuel après l'ajout du défilement horizontal ci-dessus : le
défilement vertical ne faisait pas bouger les noms de matériel/technicien/
jour à gauche des pistes. Cause : `.dash-timeline__scroll`/`.parcours-scroll`
n'avaient que `overflow-x: auto` — la règle CSS standard fait alors passer
`overflow-y` à `auto` aussi, transformant ce conteneur en une DEUXIÈME zone
de défilement vertical, indépendante de la page et de
`.dash-timeline__labels`/`.parcours-labels` (simples `<div>`, pas des
conteneurs de scroll) : la molette/le trackpad au-dessus des pistes se
faisait capter là plutôt que de faire défiler la page. Corrigé en fixant
`overflow-y: hidden` explicitement sur les deux — seul le défilement
horizontal reste local à la colonne des pistes, le défilement vertical
retombe sur la page, qui fait bouger étiquettes et pistes ensemble (siblings
du même flux normal). Frontend-only, aucun changement backend.

## Mise à jour (2026-08-02, suite) — Sous-lignes par lieu dans « Cette semaine »

Demande de Samuel : dans le Tableau de bord, séparer chaque lieu d'une
journée sur sa propre ligne plutôt que de tout empiler dans une seule piste
par jour ; un lieu sans événement le(s) jour(s) affiché(s) n'apparaît pas.

- **`weekDays`** groupe maintenant les entrées PAR JOUR PUIS PAR LIEU
  (`venueName` pour un spectacle). Un lieu sans événement n'a simplement pas
  d'entrée dans la `Map` — rien à cacher explicitement, il n'existe pas.
  L'empilement de « voies » (`packLanes`, factorisé) s'applique maintenant
  PAR LIEU (utile pour un montage/spectacle/démontage dont les fenêtres
  effectives se touchent au même lieu), pas par jour entier.
- **Transports** (décision Samuel, `AskUserQuestion` : pas de lieu unique à
  choisir) : dupliqués dans les DEUX lignes de lieu, origine ET destination
  — sauf cas limite origine = destination (une seule ligne). Chaque
  occurrence est une COPIE indépendante de l'entrée (`{ ...item }`) : la
  voie assignée dans une ligne de lieu ne doit pas écraser celle assignée
  dans l'autre (deux `packLanes` séparés sur deux tableaux distincts,
  mêmes objets sources sans la copie → bug détecté et corrigé avant
  livraison).
- **Gabarit** (décision Samuel : en-tête de jour + lignes de lieux en
  dessous) : `.dash-timeline__day-header` (texte seul, bordure basse) suivi
  d'une `.dash-timeline__venue-label` par lieu, indentée. Côté piste,
  `.dash-timeline__day-spacer` (même hauteur que l'en-tête) garde les deux
  colonnes alignées — même principe que `.dash-timeline__labels-spacer`
  pour l'axe. Implémenté avec `<template v-for>` (nombre de lignes variable
  par jour).
- Glisser-déposer inchangé : un transport affiché deux fois partage le même
  `dragState` (comparaison par `kind`+`id`), donc les deux occurrences
  bougent ensemble pendant un glisser — cohérent, c'est la même entité.

Frontend-only, aucun changement backend. Vérifié : le fichier compile
(`compileScript`) ; logique de regroupement/empilement simulée en Node
(chevauchement au même lieu → 2 voies, transport dupliqué avec voies
indépendantes par lieu, cas origine=destination → une seule ligne, aucun
lieu vide créé).

## Mise à jour (2026-08-02, suite) — Filtres jour/lieu sur « Cette semaine »

Deux nouvelles rangées de puces (`dayChips`/`venueChips`, `dayFilter`/
`venueFilter`, même `useChipFilter` que le filtre de type existant)
au-dessus de la timeline. Décidé avec Samuel (`AskUserQuestion`) : puces
multi-sélection (pas un sélecteur mono-jour façon Parcours), listant
seulement les jours/lieux réellement présents cette semaine, portée limitée
à cette carte — « Spectacles à venir » n'est pas affecté, contrairement au
filtre de type qui touche les deux.

- **`availableDays`/`availableVenues`** énumèrent les options à partir de
  `weekEntries` (déjà filtré par type) — AVANT le filtre jour/lieu
  lui-même : une puce ne doit pas disparaître parce qu'on vient d'en cocher
  une autre.
- Un transport touche deux lieux. `availableVenues` le compte pour les
  deux ; le filtrage réel se fait à deux niveaux différents pour deux
  raisons différentes : `visibleWeekEntries` (filtre large — jour, et lieu
  au sens « au moins UN des deux ») alimente `weekDays` ET `autoWindow` ;
  `pushTo` dans `weekDays` réapplique `venueFilter.passes(...)` PAR LIEU (pas
  par entrée) pour qu'un transport dont un seul des deux lieux est
  sélectionné ne perde que la ligne correspondante, cohérent avec le fait
  qu'il apparaît déjà en double (voir la note du 2026-08-02 précédente).
- `autoWindow` (donc le zoom « Réinitialiser ») se base maintenant sur
  `visibleWeekEntries` plutôt que sur `weekEntries` — se recentre
  automatiquement sur ce qui reste visible après filtrage. Le zoom courant
  ne se réinitialise PAS quand on change les filtres (même principe déjà en
  place pour le filtre de type et pour le glisser-déposer — seul un
  changement de projet le fait).
- Message d'état vide devient contextuel : « Aucun événement ne correspond
  aux filtres jour/lieu sélectionnés » (filtres actifs) distinct de « Aucun
  spectacle ni transport cette semaine » (vraiment rien cette semaine) —
  `hasAnyEntriesThisWeek` (basé sur `weekEntries`, pas `visibleWeekEntries`)
  fait la distinction.

Frontend-only, aucun changement backend, aucune migration. Vérifié : le
fichier compile (`compileScript`) ; logique de filtrage simulée en Node
(stabilité des puces disponibles sous filtre actif, filtre jour, filtre lieu
à deux niveaux — visibilité large vs suppression fine par ligne pour un
transport partiellement filtré, retour à « Tous »).

## Mise à jour (2026-08-02, suite) — Fiche Transport : mode lecture/édition

Demande de Samuel : appliquer à `TransportDetailView.vue` le même pattern
que les trois autres fiches (bouton « Modifier la fiche » en haut, infos
statiques par défaut, « Enregistrer »/« Annuler » en édition) — jusqu'ici
volontairement exclue (note du 2026-07-30 : « déjà un formulaire toujours
ouvert »).

- **Pas `useFicheEdition.js`** : `editing` reste un `ref` local. `save()`
  a déjà sa propre logique (payload imbriqué `technicians`/`materials`,
  `status: 'confirmed'` conditionnel, conflit `force`) qui ne correspond
  pas au simple `toDraft`/`toPayload` générique du composable — pas de
  raison de la forcer dans ce moule pour un seul écran.
- `buildForm(t)` (extrait de `loadTransport`) reconstruit le brouillon à
  partir du transport enregistré — réutilisé à l'entrée ET à la sortie
  (Annuler) du mode édition, pour ne jamais laisser une modification
  abandonnée traîner après un « Annuler ».
- Le formulaire existant (déjà bien testé : sélection en cascade des kits,
  disponibilité au départ, techniciens multiples) est **inchangé**, juste
  déplacé sous `v-if="editing"`. Le bloc lecture réutilise `.field__static`
  (même classe que le champ « Spectacle », déjà en lecture seule depuis le
  début) ; nouvelles variantes `.field__static--area` (notes, multi-ligne)
  et `.tech-chip--static` (techniciens affectés, même puce que l'édition
  sans l'interaction).
- Bouton principal en édition : **« Confirmer le transport » ou
  « Enregistrer » selon le statut** — exactement le choix qu'affichait déjà
  l'ancien bas de page, relocalisé dans `.fiche-actions` (entête). Pas de
  bouton « juste enregistrer sans confirmer » ajouté pour un `to_approve` —
  limitation déjà présente avant cette migration, pas dans la portée de la
  demande de Samuel.
- **Suppression déplacée** dans le bas du formulaire d'édition (n'était pas
  gated auparavant, puisqu'il n'y avait pas de mode lecture) — même
  emplacement que les trois autres fiches qui en ont un (Lieu/Spectacle/
  Transport).

Frontend-only, aucun changement backend, aucune migration. Vérifié : le
fichier compile (`compileScript`), les bindings `editing`/`startEdit`/
`cancelEdit`/`buildForm`/`assignedTechnicianRows`/`canConfirm` résolvent
tous correctement.

## Mise à jour (2026-08-02, suite) — Fiche Transport : style lecture aligné sur la fiche spectacle

Révision du mode lecture ajouté ci-dessus, à la demande de Samuel : « mêmes
règles visuelles que la fiche spectacle », « retirer les boîtes des
champs ». Les `.field__static` (fond + bordure) du mode lecture sont
remplacées par le gabarit sans boîte de `SpectacleDetailView.vue` :

- **`.summary-grid`/`.summary-label`/`.summary-value`** pour les champs à
  valeur unique (type, spectacle, lieux, horaires, durée) — juste un
  libellé au-dessus d'une valeur, aucun fond ni bordure. `.summary-value--accent`
  signale une heure prévue manquante (même teinte que le badge de conflit).
- **`.card-title`/`.card-text`** pour les notes — carte absente si
  `transport.notes` est vide (même convention que `v-if="!editing &&
  show.notes"` sur la fiche spectacle), pas de « — » de remplissage.
- **`.row-list`/`.row`** pour les techniciens (avatar à initiales,
  `initials()` dupliqué de SpectacleDetailView.vue) et le matériel (pastille
  de couleur par catégorie, `materialCategoryById` — nouveau, la fiche avait
  déjà `categoryOf()` mais pas de table id→catégorie). Fond `#1b1f25` SANS
  bordure — à ne pas confondre avec les `.field__static` boîtées, qui
  restent utilisées telles quelles en mode ÉDITION (inchangé, hors de la
  portée de cette demande).
- `.field__static--area` et `.tech-chip--static` (introduites au tour
  précédent pour l'ancien gabarit boîté du mode lecture) sont retirées,
  devenues mortes.

Frontend-only, aucun changement backend. Vérifié : le fichier compile
(`compileScript`), les nouvelles liaisons (`initials`,
`materialCategoryById`) résolvent correctement.

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

## Mise à jour (2026-07-31, suite) — Audit ergonomie, point 3 : recherche texte sur Matériel

`MaterielView.vue` gagne un champ de recherche (`search`), au-dessus des
puces de catégorie — se combine avec le filtre de catégorie (ET logique),
pas à la place. Insensible à la casse et aux accents (NFD +
`\p{Mn}`/`.toLowerCase()`, même logique que le tri des catégories côté
backend du 2026-07-30, mais en JS ici — aucun changement backend, filtrage
entièrement côté client sur les données déjà chargées).

Un kit reste dans les résultats si son propre nom correspond **ou** si un
de ses composants correspond (`m.children.some(...)`) — sinon chercher
« XLR » ferait disparaître le flightcase qui en contient un. Dans ce
second cas, le kit se déplie automatiquement (`isExpanded` forcé à `true`
dans le computed `filtered`) pour que le composant trouvé reste visible
sans clic de plus — sauf si l'utilisateur a déjà replié ce kit lui-même
pendant la session (`isManuallyToggled`, basé sur la présence de la clé
dans `expanded.value`, pas sur sa valeur). L'état vide devient
contextuel : « Aucun matériel ne correspond à « {terme} » » quand une
recherche est active, au lieu du message générique par catégorie.

Le champ réutilise `.fiche-input` (classe globale déjà existante, voir
point 2) plutôt que d'inventer un style de champ de recherche à part.
Portée volontairement limitée à Matériel pour l'instant (recommandation de
l'audit : étendre à Spectacles/Techniciens si le volume le justifie plus
tard). Aucun changement backend, aucune migration.

## Mise à jour (2026-07-31, suite) — Audit ergonomie, point 4 : sidebar en tiroir sous 860px

L'ancienne tabbar mobile (4 raccourcis fixes : Accueil/Spectacles/Matériel/
Techniciens) est **retirée** de `AppShell.vue` et remplacée par un tiroir qui
reprend la sidebar desktop telle quelle — mêmes `navItems`/`bottomNavItems`,
mêmes sous-menus. Elle ne couvrait qu'une fraction des sections (Lieux,
Transports, Catégories, Conflits, Cohérence, Réglages, Utilisateurs étaient
inatteignables sous 860px sans repasser en desktop).

- Bouton **☰ flottant** (`position: fixed`, coin haut-gauche, `z-index: 210`)
  plutôt qu'une nouvelle barre d'en-tête mobile — décision demandée à Samuel
  (option retenue : pas de barre d'en-tête, moins de changement structurel).
  Se transforme en croix quand le tiroir est ouvert (rotation CSS des trois
  barres).
- `.shell-nav` gagne `position: fixed` + `transform: translateX(-100%)`
  **uniquement dans la media query `max-width: 860px`** — au-dessus de ce
  seuil, ces règles n'existent pas, la sidebar reste en flux normal comme
  avant. `drawerOpen` (ref) pilote la classe `.shell-nav--open`
  (`translateX(0)`) et l'overlay (`.shell-nav-overlay`, `v-if`, ferme au
  clic).
- Le tiroir se referme automatiquement à la navigation (`watch(() =>
  route.path, ...)`) — sinon il resterait ouvert par-dessus la page suivante
  après un clic sur un lien.
- `.shell-main` gagne un `padding-top` de 76px sous 860px (au lieu de 20px
  partout) pour laisser la place au bouton ☰ flottant, qui sinon chevaucherait
  le haut du contenu.

Frontend-only, aucun changement backend, aucune migration. Le fichier parse
sans erreur (`@vue/compiler-sfc`) ; `npm run build` non vérifiable dans ce
bac à sable (même limitation que le point 2) — à confirmer avec `npm run
dev` en conditions réelles, notamment le comportement tactile du tiroir sur
un vrai appareil.

## Mise à jour (2026-07-31, suite) — Audit ergonomie, point 6 : fermeture des modales à Échap

Nouveau composable `useEscapeKey.js` (`onEscape` appelé tant que le
composant est monté, à charge de l'appelant de vérifier l'état pertinent
avant d'agir — pas de notion d'« ouvert » dans le composable lui-même).
Câblé sur les 8 fiches/écrans qui ont une modale ou une confirmation :

- **`AssignerMaterielModal.vue`/`AssignerTechnicienModal.vue`** : le
  composant entier est la modale tant qu'il est monté — `useEscapeKey(() =>
  emit('close'))` directement.
- **`useSuppressionFiche.js`** : Échap y ferme la confirmation
  (`cancelDelete`) — les trois fiches qui l'utilisent (Lieu, Spectacle,
  Transport) l'obtiennent donc sans y toucher elles-mêmes.
- **`TransportDetailView.vue`** : cas particulier, deux états de modale
  distincts en jeu (la confirmation de suppression, déjà couverte par
  `useSuppressionFiche`, et la modale « Ajouter du matériel »,
  `showAddModal`) — un second appel local à `useEscapeKey` gère celle-ci.
- **`CategoriesMaterielView.vue`/`UtilisateursView.vue`** : confirmation de
  suppression/retrait locale (`deleting`/`confirmTarget`), même geste
  qu'un clic sur le fond.

Pas touché : le tiroir mobile du point 4 ci-dessus (`drawerOpen` sur
`AppShell.vue`) — c'est un panneau de navigation, pas une modale, hors du
périmètre demandé par Samuel pour ce point-là. Aucun changement backend,
aucune migration. Les fichiers modifiés compilent réellement (pas
seulement « parsent ») via `compileScript` de `@vue/compiler-sfc` — testé
au-delà du simple `parse` pour ce point-ci, `npm run build` restant
indisponible dans ce bac à sable.

## Mise à jour (2026-07-31, suite) — Recherche texte étendue aux modales d'assignation

À la demande de Samuel, la même recherche texte que `MaterielView.vue`
(point 3 ci-dessus) est ajoutée à `AssignerMaterielModal.vue` et à la
modale « Ajouter du matériel » de `TransportDetailView.vue` — les deux
autres écrans qui affichent le catalogue de matériel sous forme de liste à
cocher. `normalizeText()` (accents/casse) est sortie dans
`frontend/src/utils/text.js` à cette occasion, pour ne pas en avoir une
troisième copie ; `MaterielView.vue` a été retouché pour importer la même
fonction au lieu de sa version locale.

Nuance propre à ces deux modales (elles ne replient jamais leurs kits,
contrairement à `MaterielView.vue`) : plutôt qu'un flag `isExpanded`, la
recherche calcule un ensemble d'ids à garder (`searchFilteredIds`) — si un
composant correspond, son kit parent ET tous les autres composants du kit
restent visibles (pas seulement celui qui a matché), pour ne jamais montrer
un kit à moitié. Ce filtre se combine (ET logique) avec le filtre de
catégorie existant via un nouveau computed partagé (`filteredMaterials`
dans `AssignerMaterielModal.vue`, filtre étendu sur `visibleCatalog` dans
`TransportDetailView.vue`) — au passage, ça a éliminé une petite
duplication de filtre entre `catalogRows` et `visibleIds` qui existait déjà
avant cette modification dans `AssignerMaterielModal.vue`. Un message
« Aucun matériel ne correspond à ces filtres » apparaît maintenant quand
category+recherche ne laissent rien — absent auparavant (la liste
retombait silencieusement à vide). Le champ se réinitialise à l'ouverture
de la modale transport (`openAddModal`), comme le filtre de catégorie déjà
en place.

Aucun changement backend, aucune migration. Les 3 fichiers touchés
compilent (`compileScript`) ; logique de correspondance testée avec un jeu
de données simulé (kit + composants, recherche sur le composant seul, sur
le kit, et sans résultat) — les trois cas se comportent comme attendu.

## Mise à jour (2026-07-31, suite) — Échap referme aussi le tiroir mobile

Extension du point 6 ci-dessus au tiroir mobile du point 4
(`drawerOpen`/`closeDrawer` sur `AppShell.vue`, exclu du point 6 à
l'origine car ce n'est pas une modale) : à la demande de Samuel, même
`useEscapeKey` que les modales, `if (drawerOpen.value) closeDrawer()`.
Frontend-only, aucun changement backend, aucune migration. `AppShell.vue`
compile (`compileScript`).

## Mise à jour (2026-07-31, suite) — Audit ergonomie, points 7 et 8 : dernières décisions

Les deux derniers points de l'audit (`audit_ergonomie_navigation.md`) tranchés
avec Samuel — clôt la liste des 8 recommandations.

- **Point 7** : l'en-tête à avatar de la fiche Technicien (`header__avatar`/
  `header__name`/`header__role`) est conservé tel quel plutôt qu'unifié avec
  le `.header__title` des quatre autres fiches — décision documentée dans
  le docstring de `TechnicienDetailView.vue` pour qu'un futur changement à
  cet endroit sache que c'est un choix assumé (l'avatar aide à repérer un
  nom de personne), pas une dérive à corriger.
- **Point 8** : `v0.1 · JD` retiré du pied de `AppShell.vue`
  (`.shell-nav__version`, template et CSS, y compris le sélecteur
  `.shell-nav__account + .shell-nav__version` qui n'avait plus de raison
  d'être) — confirmé résidu du mockup original.

Frontend-only, aucun changement backend, aucune migration. `AppShell.vue`
et `TechnicienDetailView.vue` compilent (`compileScript`).

## Mise à jour (2026-08-01) — Puces de filtre : ⌘+clic pour la sélection multiple

Demande de Samuel : « tous les boutons de filtre en haut des pages
devraient avoir le même comportement avec ⌘ pour la sélection multiple ».
Nouveau composable `useChipFilter.js` (comportement à la Finder) : clic
simple = une seule valeur (remplace la sélection), ⌘+clic (ou Ctrl+clic) =
ajoute/retire sans effacer le reste. Un ensemble vide = aucun filtre = tout
s'affiche — c'est l'état par défaut et ce à quoi la puce « Tous » ramène
toujours, avec ou sans ⌘.

Remplace deux modèles bespoke qui coexistaient : un `ref('Tous')` à valeur
unique (Matériel, Spectacles ×2, Cohérence, Transports ×3, les deux modales
de catalogue) et un objet de booléens indépendants par clé qui permettait
déjà de combiner via un simple clic, sans ⌘ (Dashboard — seul écran qui
dérogeait déjà à l'ancien modèle, mais pas de la même façon que les
autres). Les 7 écrans/composants suivants sont passés à `useChipFilter` :
`MaterielView.vue`, `SpectaclesView.vue` (type + lieu), `TransportsView.vue`
(spectacle + statut + technicien), `CoherenceEmplacementsView.vue`,
`DashboardView.vue`, `AssignerMaterielModal.vue`,
`TransportDetailView.vue` (modale « Ajouter du matériel »).

Cas particulier : le filtre technicien de `TransportsView.vue` a sa propre
fonction de correspondance (`techMatches`) plutôt que `passes()` — un
déplacement peut avoir plusieurs personnes assignées, il doit matcher dès
qu'UNE d'entre elles est dans la sélection, pas comparer une valeur unique.

Volontairement **non touchés** : les puces de format date/heure de
`ReglagesView.vue` (ce sont des réglages à valeur unique, pas des filtres —
un format de date ne se combine pas) ; `.picker-chip` du Parcours Matériel
et `.tech-chip` de la fiche Transport (sélection d'éléments à afficher ou à
assigner, pas un filtre de liste — variantes déjà identifiées comme
volontairement différentes lors du point 2 de l'audit ergonomie).

Aucun changement backend, aucune migration. Les 7 fichiers touchés
compilent (`compileScript`) ; logique de `useChipFilter` (clic exclusif,
⌘+clic ajoute, ⌘+clic retire, retour à « Tous ») vérifiée par simulation
Node — les 7 cas se comportent comme attendu.

## Mise à jour (2026-08-01, suite) — Parcours Matériel : bifurcations et fusions

Demande de Samuel : quand un matériel à quantité multiple est réparti sur
plusieurs lieux à la fois, le Parcours Matériel doit le montrer comme une
vraie bifurcation (une bande qui se divise, quantité par branche), pas
s'aplatir sur le lieu majoritaire — révision explicite de la « simplification
assumée » documentée le 2026-07-30 pour `get_material_journey`. Les
subdivisions en cascade et les fusions devaient être prévues dès le départ,
pas ajoutées plus tard.

- **Backend, `get_material_journey()` (`transport_coherence.py`)** :
  réécrite pour construire directement depuis `_material_events` (déjà
  filtré sur le matériel), plutôt que de rejouer `_ledger_before` à chaque
  tranche et prendre le lieu majoritaire. Chaque événement dit explicitement
  quelle position il vide (origine) et laquelle il alimente (destination) —
  c'est le tracé même d'une bifurcation ou d'une fusion, une ambiguïté que
  les seuls totaux par lieu (ce que fait `_ledger_before`) ne permettent pas
  de lever dès que deux mouvements touchent le même lieu la même journée.
  `_ledger_before` n'est pas touchée (sert telle quelle à l'état initial ici,
  et sans changement aux trois autres fonctions du module qui en dépendent :
  disponibilité, cohérence, retour).
  - Chaque séjour porte maintenant `lane` (ligne), `parent_lane` (bifurcation
    — posé UNIQUEMENT sur le tout premier séjour d'une ligne née d'un
    départ vers un lieu encore inoccupé) et `merge_from_lane` (fusion — posé
    sur le séjour qui commence quand une autre ligne rejoint une position
    déjà active). Les numéros de ligne sont réutilisés dès qu'ils se
    libèrent (`free_lanes`), pour ne pas grimper sans fin sur du matériel qui
    bifurque/fusionne souvent.
  - **Cas courant préservé à l'identique** : un déplacement qui vide
    entièrement une ligne vers un lieu encore inoccupé (relocalisation
    simple, l'écrasante majorité des cas réels) ne crée ni bifurcation ni
    fusion — la même `lane` continue, rebaptisée. C'est ce qui permet aux 7
    tests `ParcoursAPITests` déjà existants de passer sans modification.
  - 4 nouveaux tests (`test_material_journey_forks_into_two_venues`,
    `_cascading_fork`, `_merges_back_into_existing_lane`,
    `_simple_relocation_has_no_fork_fields`) couvrent la bifurcation simple,
    la bifurcation en cascade (une ligne née d'une bifurcation qui se scinde
    à nouveau plus tard), la fusion dans une ligne déjà active, et l'absence
    de `parent_lane`/`merge_from_lane` sur le cas courant. Suite complète à
    251 tests (`inventory.tests`), flake8 propre, pas de migration (champs
    additifs sur une réponse déjà JSON, rien en base).
- **Frontend, `ParcoursMaterielView.vue`** : une ligne (matériel) dont toutes
  les positions du **jour affiché** tiennent sur une seule `lane` garde le
  rendu d'avant à l'identique (une barre, piste à hauteur fixe) — le calcul
  de lanes actives est refait **par jour affiché**, pas sur tout le
  parcours, pour ne pas agrandir une piste un jour où rien ne se scinde. Dès
  que deux lanes ou plus sont actives le même jour, la piste s'agrandit
  (`row.trackStyle`) et empile une sous-ligne par lane (22px + 6px d'écart,
  `LANE_HEIGHT`/`LANE_GAP`), et une bande courbe SVG (`row.connectors`,
  `<path>` en overlay, `vector-effect="non-scaling-stroke"` pour ne pas
  déformer l'épaisseur du trait sous le `preserveAspectRatio="none"` du
  viewBox 0-100/0-100 étiré sur une piste large et peu haute) relie le point
  de bifurcation/fusion entre les deux lanes concernées. La quantité de
  chaque branche est écrite dans son propre libellé (`{lieu} · {quantité}`)
  plutôt que sur la bande — plus robuste qu'un texte flottant à positionner
  sur une courbe, et lisible même si la bande est petite. `useParcours.js`
  n'a pas eu besoin de changer : `pct()`/`segmentStyle()` (déjà exposés)
  suffisaient, le placement vertical par lane et le tracé des bandes sont
  entièrement portés par `ParcoursMaterielView.vue`.
  - **Limite connue, assumée** : `.parcours-mark` (assignation) et
    `.parcours-transport` (transport confirmé) continuent de couvrir toute
    la hauteur de la piste plutôt qu'une lane précise — l'API ne relie pas
    (encore) une assignation ou un transport à la lane qu'il concerne. Pas
    dans la portée de cette demande.
  - Vérifié : `ParcoursMaterielView.vue` compile (`compileScript`) ; la
    logique de lanes/connecteurs (positionnement, `forkPath`, hauteur de
    piste) simulée en Node sur un cas de bifurcation en cascade à 3 lanes —
    positions et courbes cohérentes avec les données attendues.

## Mise à jour (2026-08-01, suite) — Parcours Matériel : transports intégrés à la ligne

Révision du rendu ci-dessus, toujours à la demande de Samuel : le liseré fin
`.parcours-transport` (2026-07-31) est retiré au profit d'un vrai bloc de
transit intégré à la timeline, et la bande courbe SVG des bifurcations/
fusions est remplacée par un connecteur en équerre. Frontend seulement,
aucun changement backend (les champs `start`/`end`/`lane`/`parent_lane`/
`merge_from_lane` existaient déjà).

- **Transports en transit** : chaque transport confirmé occupe maintenant sa
  vraie fenêtre (`scheduled_datetime` → `effective_end`) DANS la ligne
  (lane) où se trouvait le matériel juste avant — un bloc hachuré
  (`.parcours-transit`) au même niveau que `.parcours-seg`, pas un liseré
  superposé. Le séjour qui le précède sur cette même lane est raccourci
  visuellement pour s'arrêter à l'instant du DÉPART plutôt que de l'arrivée
  (`departureTrim`, une correspondance lieu+instant d'arrivée — même clé que
  le backend utilise pour fermer une lane) : les deux ne se chevauchent donc
  plus. Le séjour suivant (continuation ou nouvelle lane) recommence pile à
  la fin du bloc de transit, comme avant.
- **Connecteur en équerre** : une bifurcation ou une fusion (lane de
  destination différente de la lane d'origine) part maintenant du bloc de
  transit lui-même, pas du bord du séjour — tronc vertical + branche
  horizontale, même langage visuel que le raccordement des kits dans
  l'inventaire (`.kit-child::after`) plutôt qu'une courbe SVG. La largeur de
  la branche est délibérément FIXE, égale à la hauteur d'une lane
  (`LANE_HEIGHT`, 22px) — demande explicite de Samuel, pour éviter une
  longue diagonale disproportionnée. Un transport qui ne change pas de lane
  (relocalisation simple, l'écrasant majorité des cas) n'a aucun
  connecteur : le bloc de transit s'insère juste avant la suite du séjour,
  sur la même ligne, comme sur une piste à une seule lane.
- La correspondance transport ↔ lanes réutilise exactement la même clé
  lieu+instant que le backend (`_material_events`/lane algorithm) pour
  identifier quelle lane un transport ferme (son arrivée) et laquelle il
  ouvre — pas de nouveau champ API, juste un rapprochement côté frontend
  entre `row.stays` et `row.transports`, déjà tous les deux renvoyés par
  `GET /api/projects/{id}/material-journey/`.
- Vérifié : `ParcoursMaterielView.vue` compile (`compileScript`) ; la
  logique de rognage (`departureTrim`) et de connecteur en équerre simulée
  en Node sur un cas de bifurcation avec transport — séjour d'origine
  correctement raccourci à l'heure de départ, bloc de transit sur la bonne
  lane, tronc/branche du connecteur aux bonnes coordonnées.

## Mise à jour (2026-08-01, suite) — Parcours Matériel : chevauchement séjour/transport et couleur constante

Deux corrections signalées par Samuel sur le rendu ci-dessus, frontend
seulement, aucun changement backend.

- **Chevauchement corrigé** : le segment qui suit un transport pouvait
  déborder visuellement sur sa durée. Cause : `segmentStyle` (useParcours)
  impose une largeur plancher de 0,6 % (pensée pour qu'un marqueur ponctuel
  du Dashboard reste visible même très court), qui étire le bord DROIT d'un
  séjour court au-delà de sa fin réelle — précisément l'instant où le bloc
  de transit suivant commence. Nouvelle fonction locale `rangeStyle`
  (identique à `segmentStyle` mais sans plancher) utilisée pour les séjours
  et les blocs de transit, qui doivent se toucher pile bout à bout ; `row.
  marks` (marqueurs d'assignation, purement décoratifs) gardent
  `segmentStyle`. Vérifié en Node sur un séjour de 5 minutes suivi d'un
  transit : avec plancher, chevauchement mesurable (33,93 % > 33,68 %) ;
  sans plancher, jointure exacte (33,68 % = 33,68 %).
- **Couleur du transit rendue constante** : `.parcours-transit` passe du
  motif hachuré coloré par lieu à `var(--accent)` fixe + bordure pointillée
  (`1px dashed rgba(0,0,0,.25)`, texte `#211c33` pour le contraste) — même
  code couleur que les transports confirmés sur le Dashboard
  (`.dash-timeline__block--transport`, qui utilise aussi `var(--accent)`) :
  un transport reste un transport, peu importe sa destination, cohérent
  entre les deux écrans.

## Mise à jour (2026-08-02) — Zoom sur les 3 écrans à axe horaire

Demande de Samuel : zoomer pour voir le détail dans une journée chargée, sur
le Tableau de bord et les deux écrans Parcours, avec un bouton pour tout
réafficher. Décidé avec Samuel (`AskUserQuestion`) : interaction par boutons
+/- (pas de glisser-sélectionner ni de molette — plus simple, ne touche à
aucun geste existant, notamment le ⌘+glisser du Dashboard), et le zoom
repart à zéro à chaque changement de jour ou rechargement des données. Le
composant `ZoomControls.vue` (nouveau, présentationnel — trois boutons
`zoom-out`/`reset`/`zoom-in`, `style.css` global `.zoom-controls`/
`.zoom-btn`) est partagé par les 3 écrans ; la logique de zoom elle-même vit
séparément à deux endroits, car les fenêtres par défaut diffèrent :

- **`useParcours.js`** (Parcours Matériel + Techniciens, qui le partagent
  déjà) : `zoomWindow` (ref, `null` = pas de zoom) restreint `dayBounds` (la
  journée choisie, 0h-24h) via `viewBounds` — computed dont dépendent
  maintenant `pct`/`overlapsDay`/`segmentStyle`/`hourMarks`, donc le zoom
  est transparent pour les deux vues (aucun changement de calcul dans
  `ParcoursMaterielView.vue`/`ParcoursTechniciensView.vue` au-delà du
  branchement des boutons). `hourMarks` gagne une graduation adaptative
  (10/15/30/60/120 min selon la largeur affichée, mêmes paliers que le
  Dashboard) — avant le zoom, l'axe était toujours 0h-24h donc un pas fixe
  de 2h suffisait. `zoomIn`/`zoomOut` par palier ×0,6 centré sur le milieu
  de la fenêtre affichée, plancher 15 min. `resetZoom` remet `zoomWindow` à
  `null` → **retombe sur la journée complète**, cible naturelle puisque
  c'était déjà la fenêtre par défaut. Reset automatique dans `selectDay`/
  `stepDay` (changement de jour) et au début de `loadParcours` (tout
  rechargement) — décision Samuel : une plage zoomée qui n'a plus de sens
  pour le nouveau contexte serait plus déroutante qu'utile.
- **`DashboardView.vue`** : refactor de l'ancien `weekWindow` monolithique en
  trois computed séparés — `weekEntries` (spectacles + transports de la
  semaine, indépendant du zoom), `weekDays` (groupement par jour +
  attribution de lane, également indépendant du zoom — la hauteur d'une
  piste et la ligne verticale d'un bloc ne doivent pas sauter en zoomant),
  et `autoWindow` (la fenêtre event-bounded ±30 min qui existait déjà,
  désormais isolée). `activeWindow = zoomWindow ?? autoWindow` fait foi pour
  le rendu ; `weekWindow` garde son nom et sa forme (`{days, hourMarks,
  winStart, span}`) pour ne rien casser côté `blockStyle`/`onDragMove`
  (glisser-déposer, voir note du 2026-07-30). Un bloc entièrement hors de la
  fenêtre active est exclu, un bloc partiellement dedans est rogné (même
  logique que le Parcours Matériel) — `.dash-timeline__track` n'a toujours
  pas d'`overflow:hidden`.
  - **Différence assumée avec les Parcours, demandée explicitement par
    Samuel** : `resetZoom` ramène à `autoWindow` (premier événement au
    dernier ± 30 min), **pas** à 0h-24h — contrairement aux Parcours, la
    fenêtre par défaut du Dashboard n'a jamais été la journée complète.
    `zoomOut` peut en revanche dépasser `autoWindow` et aller jusqu'à
    0h-24h si on le répète ; `zoomWindow=null` n'y représente donc PAS
    « journée complète » comme dans `useParcours.js` (piège à ne pas
    reproduire si ce module est retouché : les deux composables ont une
    sémantique différente pour `null`).
  - **Pas de reset automatique après glisser-déposer** : `onDragEnd()`
    appelle `loadDashboard()` mais ne touche pas au zoom — perdre son zoom
    juste après l'avoir utilisé pour ajuster un bloc précisément serait
    contre-productif. Seul un changement de projet
    (`watch(activeProjectId, ...)`) réinitialise.
  - Nouveau `.dash-card__head` (titre + `ZoomControls`, uniquement sur
    « Cette semaine » — « Spectacles à venir » garde son `.dash-card__title`
    seul).

Aucun changement backend, aucune migration. Vérifié : les 5 fichiers
touchés compilent (`compileScript`) ; logique de zoom simulée en Node pour
les deux sémantiques (Parcours : `zoomOut` répété retombe sur `null` en
approchant la journée complète ; Dashboard : `resetZoom` redonne exactement
`autoWindow`, `zoomOut` répété atteint 0h-24h sans jamais passer par
`null`).

## Mise à jour (2026-08-01, suite) — Chronologie sur la fiche matériel

`GET /api/materials/{id}/schedule/` (`get_material_schedule()`,
`transport_coherence.py`) renvoie tout ce qui mobilise un matériel — les
spectacles auxquels il est assigné, les blocs, et les déplacements — trié
chronologiquement. `MaterielDetailView.vue` remplace sa liste « Assignations
actuelles » (sans horaire) par cette chronologie, avec les mêmes lignes
cliquables que celle de la fiche spectacle.

- **La raison d'être de l'endpoint** : un montage/démontage n'a aucune ligne
  `ShowMaterial` — il utilise le matériel de son événement
  (`Show.inherits_resources`). Ces entrées sont **dérivées** de l'assignation
  du parent et marquées `inherited: true`. Ne pas déplacer ce calcul côté Vue :
  c'est une règle métier, pas un détail d'affichage. Un bloc de répétition,
  lui, porte sa propre assignation et apparaît normalement — d'où l'absence de
  doublon (`show.phases` est toujours vide sur un bloc).
- `conflict` est calculé par `get_material_conflicts` **restreint à ce
  matériel**, ce qui remplace la rafale d'appels à `GET /shows/{id}/conflicts/`
  (un par assignation) que faisait la vue.
- Les propositions de transport sans `scheduled_datetime` sont renvoyées avec
  `start: null`, **en fin de liste** plutôt que masquées : c'est justement ce
  qu'il reste à compléter.
- **Fenêtre du projet** (demande de Samuel, même jour) : la liste est bornée
  par `get_project_window(material.project)` — la même fenêtre que les écrans
  « Parcours », pour que les deux racontent la même période. Ce qui tombe
  dehors est **compté** (`outside_window`) et annoncé sous la carte : une
  assignation qui disparaîtrait sans un mot ferait douter de l'écran plutôt
  que des dates du projet. Une proposition sans heure n'a rien à comparer à la
  fenêtre — elle est conservée.
- Les lignes de **déplacement** sont en retrait et en plus petits caractères
  (`.row--transit`, demande de Samuel) : un transport est un changement de
  lieu ENTRE deux utilisations, pas une utilisation. Sans ce décrochage, la
  liste se lit comme une suite d'engagements de même nature.

Suite de tests : 289, flake8 propre, aucune migration.

## Mise à jour (2026-08-01, suite) — Répartition du matériel sur sa fiche

`GET /api/materials/{id}/distribution/` (`MaterialViewSet.distribution`) répond
« où sont les N exemplaires de ce matériel, sur toute la durée du projet ».
Nouvelle carte **Répartition** sur `MaterielDetailView.vue` : une ligne par
lieu, un segment par période de détention avec la quantité écrite dedans, plus
une ligne « En transit » et un repère « maintenant ».

- **Aucune logique nouvelle** : l'endpoint rend `get_material_journey` +
  `get_material_transports` sur `get_project_window(material.project)` — la
  même source que l'écran Parcours Matériel, qui ne peut donc pas raconter
  autre chose. La seule différence est le **regroupement**, fait côté Vue :
  le Parcours empile une ligne par *lane* (pour tracer les bifurcations),
  cette carte regroupe par **lieu** (« où est mon stock, et depuis quand »).
- Répond aussi pour un matériel **désactivé**, contrairement à
  `ProjectViewSet.material_journey` qui filtre sur `is_active` : on arrive ici
  depuis la fiche, qui reste consultable (voir `MaterialViewSet.get_queryset`).
- Sans dates ni événement, `window` vaut `null` et la carte affiche un renvoi
  vers les Réglages plutôt qu'une piste vide.
- La carte n'apparaît qu'à `quantity > 1` (`showsDistribution`) — pour un
  exemplaire unique, la chronologie et le lieu d'origine disent déjà tout.
- **Écarté en cours de route** : une première version répondait à un instant
  donné (`?at=`, avec `get_material_distribution` dans
  `transport_coherence.py`), retirée le même jour au profit de la vue par
  période. Elle sortait le matériel en cours de trajet de son lieu d'origine
  pour le compter « en transit », un écart volontaire avec `_ledger_before` —
  si cette idée revient, c'est le point à réexaminer d'abord.

Suite de tests : 288, flake8 propre, aucune migration.

## Mise à jour (2026-08-02) — Parcours Matériel : couleurs de légende recalées

Signalé par Samuel : les puces « Requis par un spectacle » et « Déplacement
confirmé » n'étaient plus à jour, et gardaient la hauteur de 3px des anciens
liserés.

- `.parcours-mark` (assignation) passe de `var(--accent)` au **bleu**
  `oklch(0.72 0.15 250)` : il partageait la couleur d'accent avec
  `.parcours-transit` depuis la révision du 2026-08-01, les deux étaient
  devenus indistinguables. Le bleu est volontairement plus **clair** (0.72)
  que les couleurs de lieu des séjours (toutes en 0.52-0.55, dont un
  bleu-vert) — sinon le marqueur se fondrait dans le séjour qu'il recouvre.
- Les deux puces de légende reprennent le gabarit commun de
  `.legend__swatch` (plus de `height: 3px`) et les couleurs réelles des blocs
  : bleu pour le marqueur, `var(--accent)` + bordure pointillée pour le
  transit.

Frontend seulement, aucun changement backend.

- Le **titre du spectacle** est maintenant écrit dans la bande du marqueur
  (`.parcours-mark__label`, demande de Samuel) — l'info-bulle n'était pas
  suffisante pour lire une journée d'un coup d'œil. Le label porte son propre
  `overflow: hidden` plutôt que le marqueur, qui rognerait l'info-bulle (même
  pattern que `.parcours-seg__label` et `.dash-timeline__block-name`).

## Mise à jour (2026-08-02, suite) — Fiche Transport : libellés et heure d'arrivée montage compris

Signalé par Samuel : les heures de référence de la fiche Transport
n'étaient pas claires. Deux changements, lecture ET édition (les deux
blocs — `.summary-grid` en lecture, `.reference-times` en édition —
affichaient le même texte, donc les deux devaient changer) :

- **Libellés renommés** : « Fin du départ » → « Fin de l'événement au
  départ », « Début de l'arrivée » → « Début de l'événement à l'arrivée ».
  Purement cosmétique, aucune donnée touchée.
- **Heure d'arrivée = début du bloc complet, montage compris** :
  `transport.arrival_show.effective_start` (le seul début de l'événement)
  devient `transport.arrival_show.engagement_start` (`Show.engagement_start`,
  propriété déjà en place depuis le 2026-07-31 — voir « Blocs rattachés à un
  événement » : sur l'événement lui-même, c'est le min entre son propre
  `effective_start` et celui de ses blocs `setup`/`teardown` ; sur un bloc,
  ça retombe sur son propre `effective_start`). Demande volontairement
  **asymétrique** : le côté départ reste sur `effective_end`, Samuel n'a
  demandé le changement que côté arrivée.
- **Backend** : `serialize_reference_show()` (`conflicts.py`) n'exposait que
  `effective_start`/`effective_end` sur `departure_show`/`arrival_show` —
  ajout de `engagement_start`/`engagement_end` aux deux. `get_transport_
  reference_shows`/`find_departure_show`/`find_arrival_show` cherchent déjà
  parmi TOUS les `Show` d'un lieu (blocs compris), donc quand l'arrivée
  résout directement sur un bloc de montage, `engagement_start` retombe sur
  son propre `effective_start` (pas de double comptage) ; quand elle résout
  sur l'événement top-level (le cas de Samuel : « Spectacle 1 », pas un
  bloc), `engagement_start` étend correctement jusqu'au montage rattaché.
  Aucune migration (propriété déjà existante sur `Show`, juste exposée dans
  ce sérialiseur).

Vérifié : `TransportWindowValidationAPITests` (8, la classe qui couvre
directement cette sérialisation) + `ShowPhasesAPITests`/
`ShowPhaseInheritanceTests`/`RehearsalPhaseAutonomyTests`/
`TransportConflictTests`/`TransportStatusAPITests` (33 de plus, la logique
`engagement_start`/blocs) au vert, flake8 propre sur `conflicts.py`. Suite
complète non relancée intégralement dans ce bac à sable (limite de temps
d'exécution, sans lien avec ce changement) — la portée touchée est
entièrement couverte par les 41 tests ci-dessus. `TransportDetailView.vue`
compile (`compileScript`). Frontend + backend, aucune migration.

## Mise à jour (2026-08-02, suite) — Fiche Transport : réorganisation des champs

Toujours à la demande de Samuel, sur la même fiche : l'ordre des champs
change, **identique en lecture et en édition**.

- **« Heure prévue » remonte en première position** (avec « Durée estimée »,
  restée groupée avec elle comme avant) — « l'élément le plus important »
  selon Samuel. En édition, ce `field-grid` passe donc en tête du
  formulaire, devant Type/Spectacle ; le message d'aide (« Ajoute une heure
  prévue… ») le suit toujours immédiatement.
- **Lieu de départ et lieu d'arrivée fusionnés sur une seule ligne avec une
  flèche de direction** (`→`) plutôt que deux items séparés. Nouvelles
  classes partagées lecture/édition : `.route-value` (flex, lecture) et
  `.field-grid--route` (grille `1fr auto 1fr`, édition — les deux `<select>`
  encadrent la flèche). `.route-arrow` gagne un `padding-bottom` **en
  édition seulement** (`.field-grid--route .route-arrow`) pour retomber au
  niveau des `<select>` plutôt que des libellés au-dessus.
- **Les horaires de référence** (« Fin de l'événement au départ » / « Début
  de l'événement à l'arrivée », voir note précédente) **déménagent dans une
  boîte séparée**, juste après le bloc principal — en lecture, un second
  `.card.summary-grid` sans titre ; en édition, `.reference-times`
  (inchangée visuellement) est simplement repositionnée après le trajet, au
  lieu d'être coincée entre les lieux et l'heure prévue.

Frontend-only, aucun changement backend, aucune migration. Vérifié :
`TransportDetailView.vue` compile (`compileScript`).

## Mise à jour (2026-08-02, suite) — Fiche Transport : mise en page fine

Deux derniers ajustements demandés par Samuel sur la même fiche :

- **Titre + date/heure du spectacle de référence sur 2 lignes** plutôt qu'un
  seul texte « Titre · date, heure » — en lecture, `.summary-value--lines`
  (flex colonne, seconde ligne atténuée, même hiérarchie que `.row__title`/
  `.row__subtitle`) ; en édition, `.reference-times__item` était déjà en
  colonne, il suffisait d'y empiler deux `.reference-times__value` au lieu
  d'un seul.
- **Le trajet (lieu de départ → lieu d'arrivée) s'étend sur 2 colonnes** de
  `.summary-grid` (`.summary-span-2`, `grid-column: span 2`) pour ne plus
  risquer de retour de ligne — en lecture seulement, l'édition avait déjà
  deux `<select>` explicites côte à côte qui ne wrappent pas.

Frontend-only, aucun changement backend, aucune migration. Vérifié :
`TransportDetailView.vue` compile (`compileScript`).

## Mise à jour (2026-08-02, suite) — Fiche Transport : jour de la semaine

Toujours à la demande de Samuel : les dates de la fiche Transport gagnent le
jour de la semaine.

- **`dateTimeFmt`** (donc `fmtReference`, utilisée par le spectacle de
  référence en lecture ET en édition) gagne `weekday: 'short'` —
  « ven. 31 juill., 20 h 00 » au lieu de « 31 juill., 20 h 00 ». Un seul
  endroit à changer, les deux modes en profitent.
- **« Heure prévue »** (lecture seulement — l'édition reste un
  `<input type="datetime-local">` natif, non concerné) est éclatée sur 2
  lignes : jour+date (nouveau `fmtDate`, `weekday`+`day`+`month`) puis heure
  seule (nouveau `fmtTime`, reprend le `timeFmt` déjà déclaré mais inutilisé
  jusqu'ici).
- **`.summary-value--lines`/`.summary-value__sub`** (introduites au tour
  précédent pour le spectacle de référence) sont généralisées : la classe
  `__sub` (ligne atténuée) est maintenant posée **explicitement** sur la
  bonne ligne plutôt que déduite par `:last-child` — nécessaire parce que la
  ligne secondaire n'est pas la même selon le champ (la date pour le
  spectacle de référence, mais le jour+date pour l'heure prévue, où c'est
  l'heure qui doit rester la ligne principale).

Frontend-only, aucun changement backend, aucune migration. Vérifié :
`TransportDetailView.vue` compile (`compileScript`) ; sortie de
`Intl.DateTimeFormat('fr-CA', …)` vérifiée en Node pour confirmer le format
exact (« ven. 31 juill. », « 22 h 00 », « ven. 31 juill., 22 h 00 »).

## Mise à jour (2026-08-02, suite) — Filtres de jour sur Transports et Spectacles

Demande de Samuel : ajouter un filtre par jour sur `TransportsView.vue` et
`SpectaclesView.vue`, en plus des filtres déjà en place (spectacle/statut/
technicien ; type/lieu). Décidé avec Samuel (`AskUserQuestion`) : puces
multi-sélection `useChipFilter` (⌘+clic pour combiner), même pattern que
tous les autres filtres de l'app plutôt qu'un sélecteur compact façon
Parcours — l'homogénéité l'emporte, malgré le risque de rangée de puces
longue sur un projet étalé sur plusieurs mois (pas de bornage type
« Cette semaine » du Dashboard sur ces deux écrans).

- **`TransportsView.vue`** : réutilise `t.day` (déjà calculé par `decorated`,
  `dateFmt.format(start)` ou `'À planifier'` sans `scheduled_datetime`) comme
  clé de filtre — aucun nouveau champ. `dayOptions` trie chronologiquement
  par la vraie date (pas l'ordre de l'API), avec **« À planifier » toujours
  en dernier** plutôt que mélangé aux vraies dates (comparateur dédié : `!a`
  ou `!b` renvoie en fin de liste). Combiné en ET avec les trois filtres
  existants dans `filtered`.
- **`SpectaclesView.vue`** : réutilise `s.date` (déjà calculé). Pas de
  bucket « À planifier » à gérer ici — `start_datetime` est obligatoire sur
  `Show`, contrairement à `Transport.scheduled_datetime` — donc simple tri
  chronologique par première occurrence. Filtre appliqué dans `matching`
  (avant le regroupement parent/enfant des blocs `filtered`) : un bloc dont
  le jour ne correspond pas disparaît comme avec type/lieu, même
  comportement déjà établi pour ces filtres.
- Sur les deux écrans, la puce « Tous » du groupe jour porte un libellé
  spécifique (« Tous les jours ») plutôt que le générique « Tous », même
  convention que « Tous les lieux » déjà en place sur Spectacles.

Frontend-only, aucun changement backend, aucune migration. Vérifié : les
deux fichiers compilent (`compileScript`) ; tri jour/« À planifier » simulé
en Node sur un jeu de dates mélangé — ordre chronologique correct, « À
planifier » toujours en dernier.

## Mise à jour (2026-08-02, suite) — Couleur fuchsia pour les blocs de transport

Signalé par Samuel sous le thème clair : les blocs de transport confirmé du
Parcours Matériel (`var(--accent)`, mauve) se confondaient avec certaines
couleurs de lieu de la même famille de teinte (ex. Salon 58). Décidé avec
Samuel (`AskUserQuestion`) : le changement s'applique aussi au Dashboard
plutôt qu'au seul Parcours, pour préserver la cohérence volontaire établie
le 2026-08-01 (« un transport reste un transport, peu importe l'écran »).

- Nouveau token `--transport: oklch(0.64 0.21 340)` (fuchsia) dans `style.css`
  `:root` — **fixe entre les deux thèmes**, même logique que les couleurs de
  statut/catégorie déjà codées en `oklch(...)` (conflits, types de spectacle,
  etc.) : un transport reste identifiable partout, peu importe le thème.
  Pas dans le bloc `:root[data-theme='light']`, qui ne réassigne que les
  tokens structurels (fonds/texte/bordures/accent/liens).
- Remplace `var(--accent)` par `var(--transport)` à 4 endroits : `.parcours-
  transit` + son survol (`style.css`, désormais `oklch(0.72 0.18 340)` plutôt
  que `#e4defa`) et `.legend__swatch--transport` (`ParcoursMaterielView.vue`)
  côté Parcours ; la couleur inline du bloc transport confirmé dans
  `weekWindow` + `.dash-legend__swatch--transport` (`DashboardView.vue`) côté
  Dashboard. Les autres couleurs de statut (orange « à approuver », rouge
  conflit) sont inchangées.

Frontend-only, aucun changement backend, aucune migration. Vérifié :
`ParcoursMaterielView.vue` et `DashboardView.vue` compilent (`compileScript`).

## Mise à jour (2026-08-02, suite) — Couleur de lieu personnalisable

Demande de Samuel : pouvoir fixer, depuis la fiche d'un lieu, la couleur de
ses bandes dans le Parcours Matériel — **en gardant la génération
automatique actuelle comme comportement par défaut**, inchangée.

- **Backend** : nouveau champ `Venue.color` (`CharField`, `blank=True,
  default=''` — PAS `null=True`, même convention que `address`/`notes`).
  Chaîne vide = pas de couleur fixée = comportement actuel intact. Migration
  `0021_venue_color`, additive pure (pas de `RunPython`). Exposé dans
  `VenueSerializer.Meta.fields`, aucune validation particulière (chaîne CSS
  libre, même traitement que `MaterialCategory.color`). `duplicate_project`
  copie aussi ce champ — sans quoi une édition dupliquée perdrait
  silencieusement une couleur fixée à la main.
- **Palette partagée** : `VENUE_PALETTE` (les 6 `oklch(...)` déjà utilisées
  par la génération automatique de `ParcoursMaterielView.vue`) déplacée dans
  `frontend/src/constants/venuePalette.js`, importée des deux côtés — le
  sélecteur manuel de `LieuDetailView.vue` propose exactement ces teintes,
  pas une palette différente, à la demande explicite de Samuel. Nouveau
  bouton **« ✕ » (Automatique)** en plus des puces de couleur : contrairement
  à `MaterialCategory.color` (toujours requis), une couleur de lieu est
  optionnelle — il fallait un moyen explicite de revenir à `''`.
- **`ParcoursMaterielView.vue`** : nouveau chargement `GET /api/venues/`
  (le material-journey ne renvoie que `venue_id`/`venue_name`/`is_storage`
  par séjour, pas la couleur — pas jugé utile d'étoffer ce contrat partagé
  avec `transport_coherence.py` pour un détail d'affichage).
  `venueColorOverrides` (Map id→couleur, seulement les lieux avec `color`
  non vide) est vérifié **en premier** dans `venueColors`, avant le
  traitement neutre de l'entrepôt et avant le cycle `VENUE_PALETTE` — un
  entrepôt auquel Samuel fixe une couleur obtient donc sciemment cette
  couleur plutôt que le gris neutre habituel. Sans aucune couleur fixée
  nulle part, la fonction est un no-op : cycle `VENUE_PALETTE` identique à
  avant.
- **`LieuDetailView.vue`** : lecture — pastille + « Personnalisée » ou
  « Automatique » ; édition — mêmes puces `.swatches`/`.swatch` que
  `CategoriesMaterielView.vue` (dupliquées faute de composant partagé).

Suite de tests : 288 (inchangée, champ additif), + `ProjectDuplicationTests`
revérifiés après l'ajout de la copie de `color`, flake8 propre. Frontend :
`LieuDetailView.vue` et `ParcoursMaterielView.vue` compilent
(`compileScript`). Migration **non appliquée dans ce bac à sable** —
`db.sqlite3` y est monté en lecture seule (écriture SQLite impossible même
en lecture directe, `disk I/O error`/`attempt to write a readonly
database` ; testé, pas une régression de ce changement). Samuel doit lancer
`python manage.py migrate` localement avant de tester.

## Mise à jour (2026-08-02, suite) — Fiche Lieu : aperçu de couleur + sélecteur natif

Deux ajustements demandés par Samuel sur le sélecteur de couleur ci-dessus :

- **`.color-preview`** (carré 28px, remplace l'ancien `.color-dot` de 12px)
  affiche la teinte réellement retenue — en lecture (à côté de
  « Personnalisée »/« Automatique ») ET en édition (à côté des puces).
  Nécessaire dès qu'une couleur ne vient PAS de `VENUE_PALETTE` : les puces
  de palette ne peuvent alors plus s'« allumer » (`.swatch--active`) pour
  indiquer ce qui est choisi, l'aperçu devient la seule confirmation
  visuelle.
- **`<input type="color">`** (`.swatch--picker`) ajouté à la suite des
  puces de palette — ouvre le sélecteur système pour une teinte libre, hors
  charte. `draft.color` devient alors une chaîne hex plutôt que
  `oklch(...)` ; les deux formats sont des chaînes CSS valides pour
  `Venue.color`, aucune conversion n'est nécessaire côté backend. `hexColor()`
  (nouveau helper) ne fait que donner une valeur de départ affichable au
  picker natif — qui ne comprend pas `oklch(...)` — sans jamais modifier
  `draft.color` tant que l'utilisateur n'a pas interagi avec le picker.

Frontend-only, aucun changement backend, aucune migration. Vérifié :
`LieuDetailView.vue` compile (`compileScript`) ; `hexColor()` vérifiée en
Node sur 4 cas (vide, `oklch(...)`, hex 6 caractères, hex 3 caractères).

## Mise à jour (2026-08-02, suite) — Fiche Lieu : aperçu en mode auto, 10 couleurs, icône du sélecteur

Trois ajustements demandés par Samuel sur la couleur de lieu ci-dessus :

- **`VENUE_PALETTE` passe de 6 à 10 teintes** (`constants/venuePalette.js`) —
  les 6 d'origine conservées telles quelles en tête de tableau (continuité),
  4 nouvelles ajoutées à la suite. Angles oklch choisis pour un écart
  minimal de 25° entre les 10 (vérifié en Node), largement suffisant pour
  rester « bien différentes les unes des autres » à chroma/luminosité
  constantes (`0.13`/`0.52–0.55`, même style que les 6 d'origine).
- **Aperçu même en mode Automatique** : `autoPreviewColor({id, is_storage})`
  (nouveau, `LieuDetailView.vue`) retourne `VENUE_PALETTE[id %
  VENUE_PALETTE.length]` (ou la teinte neutre d'entrepôt) quand `color` est
  vide — la pastille `.color-preview` n'est donc plus jamais vide/« Auto »
  en texte. **Limite assumée, documentée dans le module** : cet aperçu est
  déterministe par `id`, alors que la vraie couleur du Parcours Matériel est
  cyclée par ORDRE D'APPARITION dans les données affichées (dépend du jour
  et des lieux réellement visités) — les deux peuvent donc différer. Seule
  une couleur **fixée** (non vide) est garantie identique partout ; retiré
  au passage : `.color-preview--empty` (plus de variante « vide » à styler).
- **Icône dégradé/roue de teintes sur le sélecteur natif** : `<input
  type="color">` n'affichait que sa valeur courante (un carré uni) — sans
  rapport visuel avec « choisir une couleur ». `.swatch--picker` pose
  maintenant un `conic-gradient` (roue de teintes) en fond, avec le vrai
  `<input>` natif superposé en `opacity: 0` (`.swatch--picker__input`,
  `inset: 0`) — invisible mais toujours cliquable, c'est lui qui ouvre le
  sélecteur système. Remplace l'ancienne approche (`::-webkit-color-swatch`
  stylée directement), qui ne pouvait pas afficher autre chose que la
  valeur courante du champ.

Frontend-only, aucun changement backend, aucune migration. Vérifié :
`LieuDetailView.vue` et `ParcoursMaterielView.vue` compilent
(`compileScript`) ; écart de teinte minimal (25°) et `autoPreviewColor()`
(cas normal, cyclage au-delà de 10, entrepôt) vérifiés en Node.

## Mise à jour (2026-08-02, suite) — Page Lieux : tag du code coloré

Demande de Samuel : sur les fiches sommaire de `LieuxView.vue`, le badge du
code court (4 caractères) reprend la couleur du lieu plutôt que le gris
neutre d'origine.

- `venueColor` (nouveau, dans `decorated`) = `v.color` s'il est fixé, sinon
  `autoPreviewColor(v)` (même fonction qu'sur `LieuDetailView.vue`, dupliquée
  faute de composant partagé — même limite : aperçu déterministe par id, pas
  la couleur exacte du Parcours Matériel). **Exception** : un entrepôt SANS
  couleur fixée reste `null` → le badge retombe sur son style neutre
  d'origine (`.card-code`, inchangé) plutôt que la teinte grise translucide
  de l'aperçu d'entrepôt, trop pâle pour servir de couleur de TEXTE.
- `background`/`color` du badge posés en `:style` inline (priorité sur la
  règle `.card-code` de base) via `color-mix(in oklch, ${venueColor} X%,
  transparent)` pour le fond — fonctionne quel que soit le format de
  `venueColor` (`oklch(...)` de la palette ou hex du sélecteur natif),
  contrairement à la syntaxe `oklch(... / .16)` déjà utilisée pour les
  badges de type sur cet écran, qui n'accepte que de l'oklch.
- Texte du tag en blanc fixe (`#fff`), demande de Samuel juste après —
  mélange remonté de 22 % à 65 % en même temps pour garder un contraste
  correct (un fond trop translucide rendait le blanc peu lisible).

Frontend-only, aucun changement backend, aucune migration. Vérifié :
`LieuxView.vue` compile (`compileScript`).

## Mise à jour (2026-08-01, suite) — Fenêtre effective de la fiche spectacle : montage/démontage inclus

Signalé par Samuel : la carte résumé de `SpectacleDetailView.vue` affichait
« Fenêtre effective » = `show.effective_start`/`effective_end`, c'est-à-dire
le créneau de l'événement seul, buffers compris — pas la période réellement
mobilisée quand un montage/démontage est rattaché. C'était un choix assumé du
2026-07-31 (« la fenêtre effective affichée à côté ne couvre que le créneau
de l'événement »), explicitement révisé ici à la demande de Samuel.

- **Aucun nouveau calcul** : `Show.engagement_start`/`engagement_end`
  (2026-07-31, montage/démontage + buffer, voir `architecture.md` section 4
  et `schema.md`) existaient déjà côté modèle pour la détection de conflits
  matériel/technicien, mais n'étaient jamais exposés par `ShowSerializer`.
  Ajoutés en lecture seule (`ShowSerializer.Meta.fields`), sans toucher
  `effective_start`/`effective_end` qui restent la référence du conflit de
  **lieu** — les deux fenêtres continuent de coexister, comme documenté,
  seule leur exposition à l'API change.
- `SpectacleDetailView.vue` : la carte « Fenêtre effective » source
  maintenant `show.engagement_start`/`engagement_end`. Sur un bloc
  (montage/démontage/répétition), ces propriétés renvoient sa propre fenêtre
  effective (`parent_show_id` non nul) — comportement déjà correct côté
  modèle, aucun cas particulier à gérer côté Vue.
- **Nuance qui reste** : la fenêtre affichée couvre montage/démontage mais
  PAS une répétition rattachée (autonome, voir `RehearsalPhaseAutonomyTests`)
  — la liste « Blocs rattachés » juste en dessous peut donc encore déborder
  de cette fenêtre si une répétition est planifiée hors de ce créneau.
- 1 test ajouté (`test_api_exposes_engagement_window`, dans
  `ShowPhaseInheritanceTests`) : vérifie que l'API expose bien
  `engagement_start`/`engagement_end` et qu'ils diffèrent de
  `effective_start`/`effective_end` quand un montage est rattaché.

Suite de tests : 286, flake8 propre, aucune migration.

## Mise à jour (2026-08-01, suite) — Liste « Matériel assigné » compactée

Demande de Samuel, portée volontairement limitée à cette liste (`.row` reste
partagé avec techniciens/blocs rattachés/transports, qui gardent leur
hauteur habituelle) :

- Catégorie remontée à la suite du titre (`· {{ catLabel }}`), sur la même
  ligne — remplace l'ancienne sous-ligne `.row__subtitle` dédiée. La couleur
  de catégorie reste sur le point (`row__dot`), le texte lui-même est neutre.
- Quantité entre parenthèses (`(N)`) plutôt que `×N`, toujours affichée
  seulement si `quantity > 1`, comme avant.
- Ligne passée sur une seule ligne de texte → hauteur réduite en
  conséquence (`.row--compact`, nouveau modificateur appliqué uniquement à
  cette liste, padding 6px au lieu de 10px).

Frontend-only, aucun changement backend, aucune migration. `SpectacleDetailView.vue` compile (`compileScript`).

## Mise à jour (2026-08-01, suite) — Transports liés : date + tri chronologique

Demande de Samuel sur la liste « Transports liés » de `SpectacleDetailView.vue` :
l'API ne les renvoie pas triés, et l'heure affichée (`row__time`) n'indiquait
pas la date — trompeur dès qu'un déplacement de veille/lendemain de montage
apparaît dans la liste. `decoratedTransports` trie maintenant par
`scheduled_datetime` croissant (réutilise `dayShortFmt` déjà présent dans le
fichier pour la chronologie des blocs) ; une proposition sans heure encore
saisie (`scheduled_datetime` nul) va en fin de liste plutôt que de casser le
tri, même convention que la chronologie de la fiche matériel du 2026-08-01.

Frontend-only, aucun changement backend, aucune migration. `SpectacleDetailView.vue` compile (`compileScript`).

## Mise à jour (2026-08-01, suite) — Carte « Blocs rattachés » : journée toujours affichée

Demande de Samuel : « comme il y a déjà pour la répétition » — une
répétition rattachée tombe souvent un autre jour que l'événement, sa journée
s'affichait donc déjà (`fmtBlockRange` ne la montrait qu'en cas de date
différente de la référence) ; montage, démontage et l'événement lui-même, eux,
restaient muets sur ce point dès qu'ils tombaient le même jour que
l'événement (le cas courant), incohérent au premier coup d'œil dans une liste
qui mélange les deux cas.

`fmtBlockRange` (carte de résumé « Blocs rattachés » en haut de
`SpectacleDetailView.vue`, PAS la liste « Montage, répétition, démontage »
plus bas, qui affichait déjà la journée pour tout via `phaseFmt`) affiche
maintenant systématiquement la journée du début ; la fin ne la répète que si
elle diffère de celle du début (bloc à cheval sur minuit). Le paramètre
`refIso` (comparaison à l'événement) devient inutile, retiré des deux points
d'appel.

Frontend-only, aucun changement backend, aucune migration. `SpectacleDetailView.vue`
compile (`compileScript`) ; logique vérifiée en Node sur 3 cas (montage même
jour, répétition la veille, bloc à cheval sur minuit).

## Mise à jour (2026-08-02, suite) — Thème clair + toggle Dark/Bright

Demande de Samuel : « une version claire du visuel » + un toggle en pied de
sidebar. Nouveaux tokens dans `style.css` (`:root`) : `--accent-rgb`,
`--link`, `--bg-page`, `--bg-row`, `--bg-deep` (`--bg-card`/`--border-card`
existaient déjà depuis le 2026-07-31), plus `--fg-rgb: 255, 255, 255`. Bloc
`:root[data-theme='light']` réassigne ces mêmes tokens vers des valeurs
claires, activé en posant `data-theme="light"` sur `<html>`.

- **Technique « fg-rgb »** : toute la hiérarchie de texte/bordures de l'app
  est un seul blanc à opacité variable (`rgba(255, 255, 255, X)`, X de .05 à
  .85 selon le rôle) — jamais une couleur distincte par rôle. Plutôt que des
  dizaines de tokens par opacité, UNE variable porte le triplet RGB
  (`--fg-rgb`) ; chaque `rgba(255, 255, 255, X)` du code est devenu
  `rgba(var(--fg-rgb), X)`, opacité d'origine inchangée. Le thème clair n'a
  donc qu'à réassigner ce triplet (`15, 18, 22`) pour que toute la
  hiérarchie continue de fonctionner telle quelle sur fond clair. Même
  principe pour `--accent-rgb` (37 occurrences de `rgba(155, 138, 239, X)`
  → `rgba(var(--accent-rgb), X)`).
- **Remplacement mécanique** sur les 25 fichiers `.vue` (composants + vues)
  et `style.css` : `rgba(255, 255, 255, X)` → `rgba(var(--fg-rgb), X)`,
  `#fff`/`color: #fff` → `rgb(var(--fg-rgb))`, `#1b1f25`/`#0e1013`/`#161a1f`
  → `var(--bg-row)`/`var(--bg-deep)`/`var(--bg-card)`, `#a5b4fc` →
  `var(--link)`, `#d0c8f0` → `var(--accent)`, `rgba(155, 138, 239, X)` →
  `rgba(var(--accent-rgb), X)`. Deux occurrences de `#9b8aef` (point actif
  sidebar, puce de marque `LoginView.vue`) — même triplet que
  `--accent-rgb` en dur — passées à `rgb(var(--accent-rgb))` par cohérence.
- **Exclusions volontaires, non touchées** :
  - `LoginView.vue`, bouton Google (`background: #fff`) — exigence de
    branding Google, pas un token de l'app.
  - Texte sur puce/bouton à fond accent ou statut (`#0b0d10` sur
    `.fiche-btn--primary`/`.add-form__submit`/`.parcours-option__check`,
    `#211c33` sur `.parcours-transit`, `#101828` sur `.parcours-mark__label`,
    `#2a1400` sur `.add-form__submit--force`) — texte sombre choisi pour
    contraster sur un fond clair/pastel qui reste sensiblement le même ton
    dans les deux thèmes ; pas la même règle que le texte « sur fond de
    page » couvert par `--fg-rgb`.
  - **Couleurs de statut/catégorie codées en `oklch(...)`** (conflits, types
    de spectacle, catégories de matériel, badges de transport) et les
    `rgba(255, 217, 207, X)`/`#ffe3c9` des alertes (toujours posées sur un
    fond `oklch(0.27...)` fixe, pas la page) — **intentionnellement
    inchangées** pour cette première version. Certaines pourraient perdre en
    lisibilité sur fond clair (pensées pour du fond sombre) — à ajuster au
    cas par cas une fois vues en conditions réelles, pas devinées à
    l'aveugle ici.
- **`useTheme.js`** (nouveau composable, singleton comme `useAuth.js`) :
  `ref` seedé depuis `localStorage['registock-theme']`, pose l'attribut
  `data-theme` sur `document.documentElement`, persiste au changement.
  `index.html` gagne un script anti-flash dans `<head>` (lit la même clé
  AVANT le premier rendu Vue) — sinon un flash sombre→clair serait visible
  au chargement en thème clair.
- **Toggle** dans le pied de `AppShell.vue` (`.shell-nav__footer`, nouveau
  wrapper qui porte le `margin-top: auto`/`border-top` auparavant sur
  `.shell-nav__account` directement), juste au-dessus du courriel de
  session — un seul bouton qui bascule vers l'AUTRE mode (« Passer en
  clair »/« Passer en sombre »), pas deux boutons séparés. Même geste
  visuel que les `zoom-btn` déjà en place ailleurs dans l'app.

Frontend-only, aucun changement backend, aucune migration. Les 26 fichiers
`.vue` de `src/` compilent (`compileScript`, `@vue/compiler-sfc`).

## Mise à jour (2026-08-02, suite) — Titre des blocs généré dynamiquement, plus dupliqué

Signalé par Samuel : le titre d'un bloc (montage/répétition/démontage)
rattaché à un événement était généré UNE FOIS à sa création
(« Répétition — Nom du spectacle », recopié dans `Show.title`) et ne bougeait
plus si l'événement était renommé ensuite — un doublon qui divergeait.
Décidé avec Samuel (`AskUserQuestion`) : pas de titre entièrement figé
(« générique + suffixe optionnel ») — le nom du spectacle n'est plus jamais
stocké en double, mais un bloc peut porter une précision libre (ex.
« technique », « costumes »).

- **`Show.title` devient `blank=True` en base** (migration
  `0018_alter_show_title`, `AlterField` seule, aucune donnée touchée). Sur un
  bloc, ce champ n'est plus le nom complet mais cette précision optionnelle.
  Sur un événement top-level, il reste le nom complet et obligatoire —
  **validé au niveau du serializer**, pas du modèle (`ShowSerializer.
  validate()` : `title` requis seulement si `parent_show` est absent).
- **Nouvelle property `Show.display_title`** : sur un bloc, recalcule à
  chaque lecture `"{Type}{ précision} — {parent_show.title COURANT}"` (ex.
  « Répétition technique — Vertiges », ou « Répétition — Vertiges » sans
  précision) — rien n'est jamais recopié, `parent_show.title` reste la seule
  vérité. Sur un événement top-level, identique à `title`. Exposée en lecture
  seule par `ShowSerializer` (`display_title`), en plus de `title` qui reste
  éditable.
- **Tous les endroits qui affichaient `show.title` alors que `show` peut être
  un bloc** sont passés à `display_title` : `conflicts.py`
  (`serialize_reference_show`/`serialize_material_conflict`/
  `serialize_venue_conflict`/`serialize_technician_conflict`, messages de
  fenêtre de transport), `ShowMaterialSerializer`/`ShowTechnicianSerializer`/
  `TransportSerializer` (`show_title`), `transport_coherence.py`
  (`get_material_transports`, issues de cohérence, `get_material_schedule`),
  `views.py` (assignations du Parcours Matériel, engagements du Parcours
  Technicien). **Laissé tel quel** partout où la source est garantie
  top-level : `parent_show.title` (un parent n'est jamais lui-même un bloc,
  hiérarchie à un seul niveau) et le `parent_title` d'une entrée non héritée
  dans `get_material_schedule`.
- `Show.__str__` renvoie `display_title` pour un bloc (évite de doubler le
  type — `display_title` l'inclut déjà).
- Frontend (`SpectacleDetailView.vue`) : le champ « Titre » du formulaire
  d'ajout de bloc et de la fiche en édition devient « Précision (optionnel) »
  quand on édite un bloc (nouveau computed `isBlock`), avec un aperçu en
  direct (`phasePreviewTitle`/`editPreviewTitle`, qui mime `display_title`
  côté client). `startAddPhase` ne pré-remplit plus rien (vide par défaut).
  `isValid` de `useFicheEdition` n'exige plus un titre non vide sur un bloc.
  Header, fil d'ariane, confirmation de suppression et `showLabel` (passé
  aux modales d'assignation) utilisent `show.display_title`. La chronologie
  des blocs (`p.title` dans `decoratedPhases`/`timelineEntries`) n'a rien eu
  à changer : elle vient de `ShowSerializer.get_phases()`, déjà corrigé côté
  backend.
- Trois autres écrans affichaient aussi des shows (blocs compris) sans passer
  par un endpoint déjà corrigé : `SpectaclesView.vue` (liste imbriquée,
  `show.display_title`), `TransportsView.vue` (spectacles de référence et
  liste déroulante « Spectacle »), `DashboardView.vue` (timeline « Cette
  semaine » et « Spectacles à venir » — ce dernier n'accole plus le suffixe
  de type quand `display_title` l'a déjà, pour ne pas doubler « — montage —
  montage »). `TransportDetailView.vue`/`MaterielDetailView.vue`
  n'avaient rien à changer : ils lisent déjà `title`/`show_title` depuis des
  réponses backend corrigées à la source.
- Un test préexistant (`test_entries_are_sorted_chronologically`) créait un
  bloc avec `title="Montage"` comme nom complet — devenu redondant avec le
  nouveau sens de `title` (précision, pas nom). Fixture nettoyée (titre
  laissé vide) et assertion mise à jour pour `"Montage — Vertiges"`.
- 3 tests ajoutés (`ShowPhaseInheritanceTests`) : `display_title` suit un
  renommage de l'événement sans re-sauvegarder le bloc, format avec/sans
  précision, `title` optionnel pour un bloc mais toujours requis pour un
  événement top-level (400 sinon).

Suite de tests : 291, flake8 propre. Vérifié : les 26 fichiers `.vue` de
`src/` compilent (`compileScript`).

## Mise à jour (2026-08-02, suite) — Gestion des accès par projet

Isolation multi-tenant réelle, en vue de vendre des abonnements à l'outil à
d'autres directeurs techniques/compagnies. Avant ce changement, il n'y en
avait AUCUNE : `REST_FRAMEWORK.DEFAULT_PERMISSION_CLASSES` ne contenait que
`IsAuthenticated`, et `ProjectFilteredMixin` n'était qu'un filtre optionnel
`?project=<id>` — n'importe quel compte provisionné (même `role='viewer'`)
pouvait lire ET modifier tous les projets de tout le monde via l'API.

Décisions déjà actées avec Samuel (voir aussi `architecture.md`, section
3bis, et `schema.md`, section 13ter) :

- Rôles **par projet**, table `ProjectMembership` (`project_memberships`) :
  `owner` (gère les accès + édite tout) / `editor` (édite tout sauf les
  accès) / `viewer` (lecture seule). `status` `pending`/`active` — pas
  d'envoi de courriel automatique (aucune infra SMTP), l'invitation reste
  « en attente » jusqu'au premier login Google de l'email invité, qui
  l'active (`signals.py`, `provisionner_utilisateur_inventory`, même
  fonction que le pré-provisioning existant).
- `User.is_staff_global` (nouveau, distinct de `User.role` — **`role`
  ne gate plus rien côté API depuis ce changement**, purement affichage
  frontend) court-circuite entièrement le contrôle : accès de dépannage
  plateforme réservé à Samuel.
- Migration de données Samuel devient `owner` actif de tous les projets
  préexistants ; chaque `User` `role='admin'` reçoit `is_staff_global=True`.

Ce qui a changé, à ne pas casser :

- **`inventory/permissions.py`** (nouveau) : `HasProjectAccess` — appliquée
  à `VenueViewSet`, `MaterialViewSet`, `MaterialCategoryViewSet`,
  `TechnicianViewSet`, `ShowViewSet`, `TransportViewSet`,
  `ShowMaterialViewSet`, `ShowTechnicianViewSet`, `ProjectMembershipViewSet`
  et `ProjectViewSet`. Résout le projet directement (`project_id`) ou via
  relation (`show__project_id` pour ShowMaterial/ShowTechnician/Transport,
  qui n'ont pas de FK `project`) — chaque ViewSet déclare `project_lookup`
  et, si besoin, `get_create_project_id`/`get_object_project_id`. Rôle
  minimal : `viewer` en lecture, `editor` en écriture, `owner` pour les
  actions listées dans `owner_only_actions` (gestion des memberships,
  suppression d'un projet).
- **`ProjectMembershipQuerysetMixin`** (`views.py`) : sur CHAQUE ViewSet
  project-scoped, filtre le queryset aux projets où l'utilisateur a un
  membership actif — c'est ce qui empêche une LISTE (même sans `?project=`)
  de fuiter les données d'un projet inaccessible. Un `GET` détail sur un
  objet d'un projet inaccessible répond **404** (l'objet n'est jamais dans
  le queryset filtré), pas 403 — cohérent avec l'usage REST habituel.
- **Bypass superutilisateur Django** (`is_superuser`), en plus de
  `is_staff_global` — décision technique non explicitement demandée par
  Samuel mais nécessaire : toute la suite de tests backend existante
  s'authentifie via `DjangoUser.objects.create_superuser(...)` sans jamais
  créer de profil `inventory.User`/`ProjectMembership`. Un compte
  `/admin/` a de toute façon un accès complet et non filtré à la base via
  l'admin Django — le gater côté API serait de la sécurité de façade. **Ne
  pas retirer ce bypass** sans réécrire les ~30 classes de tests qui en
  dépendent.
- **`ProjectViewSet`** : la liste ne renvoie que les projets avec
  membership actif (tout pour staff/superutilisateur). `POST
  /api/projects/` et `POST /api/projects/{id}/duplicate/` créent
  automatiquement un `ProjectMembership(role='owner', status='active')`
  pour l'appelant sur le projet obtenu (`_grant_owner_membership`) — sans
  profil applicatif (superutilisateur Django hors flux Google), ne fait
  simplement rien, pas d'erreur.
- **`ProjectMembershipViewSet`** (`/api/project-memberships/`, filtrable
  par `?project=<id>`) : lecture accessible à tout membre actif (pas
  seulement l'owner) ; `create`/`update`/`destroy` réservés owner/staff.
  `create` réutilise le pattern `get_or_create` par email de
  `signals.py`. `update`/`destroy` refusent (400) de retirer ou rétrograder
  le **dernier owner actif** d'un projet.
- **`UserViewSet`** (`/api/users/`) restreint à `is_staff_global`
  (`IsStaffGlobal`) — la liste de tous les comptes de la plateforme ne doit
  pas fuiter vers un client normal. `UtilisateursView.vue` n'a pas été
  touché (Samuel est staff, l'écran continue de fonctionner tel quel pour
  lui) — passe frontend séparée si l'écran doit un jour distinguer un
  compte non-staff.
- **Migrations** : `0019_project_access` (schéma : `users.is_staff_global`
  + table `project_memberships`) puis `0020_project_access_data`
  (`RunPython`). **Piège** : la fonction de données est gardée par `if not
  Project.objects.exists(): return` — sans cette garde, elle insère
  inconditionnellement une ligne `User` (Samuel) dans CHAQUE base de test
  fraîchement créée par `manage.py test` (les migrations de données
  s'exécutent aussi contre elle), ce qui faisait échouer des tests qui
  comptent les `User` créés dans leur `setUp()` (ex.
  `OAuthProvisioningTests`). Une base neuve n'a par définition aucun
  `Project` préexistant à préserver.

Nouveau fichier de tests `backend/inventory/test_project_access.py` (26
tests) : bypass staff/superutilisateur, owner/editor/viewer sur une
ressource ordinaire (`VenueViewSet`) et sur `ShowMaterialViewSet` (résolution
via relation), non-membre (403/404 en détail, liste vide sans fuite),
`ProjectMembershipViewSet` (invitation pending/active, activation au login,
garde du dernier owner, changement de rôle), `UserViewSet` restreint,
création de projet/duplication accordant l'ownership. La logique de la
migration de données `0020` est testée en import dynamique de sa fonction
`RunPython` (`importlib.import_module('inventory.migrations.0020_project_access_data')`)
plutôt que via un test de migration historique — l'infra
`django-test-migrations` n'est pas installée dans ce projet.

Suite de tests : 317 (était 291), flake8 propre. Migrations
`0019_project_access` et `0020_project_access_data`.

## Mise à jour (2026-08-02, suite) — Sous-items en retrait : Parcours Matériel + Matériel assigné

Demande de Samuel : dans le Parcours Matériel et dans la liste « Matériel
assigné » de la fiche spectacle, indenter les composants de kit avec la même
« petite ligne de sous-catégories » qu'ailleurs dans l'app (`.kit-child`,
inventaire ; `.parcours-option--nested`, panneau de sélection du Parcours,
qui avait déjà ce traitement — mais pas les LIGNES de la timeline elle-même,
ni la liste de matériel assigné). Frontend-only sur les deux écrans, aucun
changement backend.

- **`ParcoursMaterielView.vue`** : nouveau computed `orderedRows`, calqué
  sur `visibleOptions` du panneau de sélection — regroupe chaque composant
  juste après son kit dans l'ordre d'affichage de la timeline, et ne marque
  `nested` que si le kit parent est LUI AUSSI dans la sélection courante
  (composant sélectionné seul → orphelin affiché à plat, même principe que
  le panneau). `decorated` construit maintenant `stays`/`transports`/
  `connectors` à partir de `orderedRows` plutôt que de `rows` directement —
  `nested` traverse le spread jusqu'au bout. Seule la colonne d'étiquettes
  (`.parcours-row__label--nested`, nouveau) est indentée ; les pistes/
  segments de la timeline n'ont pas changé, alignement label↔piste par index
  toujours garanti puisque les deux `v-for` itèrent maintenant sur le même
  `decorated` réordonné.
- **`SpectacleDetailView.vue`** : `ShowMaterialSerializer` n'expose pas
  `parent_material` (seul `MaterialSerializer` le fait) — `loadShow()`
  charge donc en plus le catalogue complet du projet (`GET /api/materials/
  ?project=`, nouveau ref `materials`) dans le même `Promise.all`, pour
  pouvoir croiser `sm.material` (juste un id sur `ShowMaterial`) avec son
  `parent_material`. `decoratedMaterials` réécrite : même logique de
  regroupement/orphelin que `orderedRows` ci-dessus, appliquée à
  `showMaterials`. Nouvelle classe `.row--nested` (indentation + tick,
  n'affecte que cette liste — `.row`/`.row--compact` restent partagés avec
  techniciens/blocs/transports, inchangés).
- Les deux implémentations dupliquent la même logique de regroupement
  (options catalogue → parent → enfants → réordonnancement) plutôt que de
  factoriser un composable partagé — même choix assumé qu'ailleurs dans
  l'app (`categoryOf`, `initials`, `autoPreviewColor`) : deux écrans, pas
  encore de troisième cas d'usage qui justifierait l'extraction.

Vérifié : les deux fichiers compilent (`compileScript`) ; logique de
regroupement/orphelin simulée en Node sur 4 cas (kit + 2 composants dans un
ordre arbitraire → regroupés et réordonnés, composant seul sans son kit →
orphelin à plat, mêmes deux cas côté fiche spectacle) — tous cohérents avec
le comportement attendu.

## Mise à jour (2026-08-02, suite) — Suffixe « x » sur les quantités (Parcours Matériel + Répartition)

Demande de Samuel : un chiffre nu à côté d'un nom de lieu peut se confondre
avec autre chose — suffixe `x` (ex. `3x`) là où la quantité est affichée
seule, sans le mot « unité(s) » qui la désambiguïse déjà ailleurs.

- **`ParcoursMaterielView.vue`** : `stay.label` (segment de séjour en
  bifurcation multi-lane, `{{ stay.quantity }}` → `{{ stay.quantity }}x`) et
  `t.label` (bloc de transit, même changement). Les `tooltipLines`
  (« N unité(s) ») ne sont **pas** touchées — déjà explicites, pas de raison
  d'ajouter un second suffixe.
- **`MaterielDetailView.vue`**, carte Répartition : `seg.quantity` (texte
  écrit dans chaque segment de la piste) gagne le même suffixe.

Frontend-only, aucun changement backend. Vérifié : les deux fichiers
compilent (`compileScript`).

## Mise à jour (2026-08-02, suite) — Couleurs personnalisables : transport + types de spectacle

Demande de Samuel : « les options pour changer les couleur des bandes qui ne
sont pas gérée dans une fiche (matériel, lieux). Je pense surtout aux
transports. » Après audit (`grep -rn "oklch(" src/`), constat que les 5
couleurs de `Show.EVENT_TYPE_CHOICES` étaient **aussi** dans ce cas —
dupliquées en dur, identiques mais non synchronisées, dans 4 fichiers Vue
(`SpectaclesView.vue`, `SpectacleDetailView.vue`, `MaterielDetailView.vue`,
`DashboardView.vue`). Samuel a confirmé (`AskUserQuestion`) : « Transport +
types de spectacle », scope étendu par rapport à la demande initiale.

- **6 nouveaux champs sur `Settings`** (`transport_color` +
  `event_color_rehearsal`/`_performance`/`_storage`/`_setup`/`_teardown`),
  migration `0023_settings_colors` (additive, aucun `RunPython`). Même
  convention que `Venue.color`/`MaterialCategory.color` : `CharField(64)`,
  chaîne CSS libre, pas de validation de format. Défauts = valeurs qui
  étaient codées en dur (voir `schema.md` section 10 pour le détail).
  Volontairement **exclues** : les couleurs sémantiques (conflit rouge,
  à-approuver orange, statut OK vert du Dashboard) — décision actée avec
  Samuel avant implémentation, les rendre personnalisables risquerait de
  casser la lisibilité plutôt que d'aider.
- **`useEventColors.js`** (nouveau composable, singleton comme
  `useTheme.js`) : charge `Settings` une fois, pose les 6 couleurs comme CSS
  custom properties sur `<html>` (`--transport`, `--event-rehearsal`, etc.)
  — mêmes noms que le `--transport` déjà existant (2026-08-02, note
  précédente), qui devient donc le premier d'une famille plutôt qu'un cas
  isolé. `style.css` garde des valeurs de repli statiques identiques aux
  défauts de `Settings`, pour qu'il n'y ait jamais de flash de variable
  manquante avant que ce composable ait fini de charger. Appelé une fois
  dans `AppShell.vue` (donc dès l'entrée dans l'app, après connexion) ;
  `refreshEventColors()` est rappelée par `ReglagesView.vue` après un PATCH
  réussi pour que les couleurs se reflètent immédiatement partout sans
  recharger la page.
- **`constants/eventTypeMeta.js`** (nouveau) : objet `EVENT_TYPE_META`
  (label + `color`/`bg`/`dot` en `var(--event-*)`/`color-mix()`) qui
  remplace les 4 copies locales de `typeMeta`/`TYPE_META` — élimine à la
  fois la duplication de VALEURS (déjà réglée par les CSS vars) et de
  STRUCTURE. `bg` reprend la même transparence qu'avant via `color-mix()`
  plutôt que la notation `oklch(... / .16)` (qui n'acceptait que de
  l'oklch) — nécessaire puisque la couleur de base peut maintenant être
  n'importe quelle syntaxe CSS choisie par Samuel (hex du sélecteur natif
  compris). Entreposage garde son ratio de transparence plus discret (8%
  contre 16% pour les 4 autres types, et un `dot` à 50% du badge) — c'était
  déjà le cas avant ce changement, reproduit à l'identique via `color-mix()`
  plutôt qu'aplati. `MaterielDetailView.vue` avait en plus une entrée
  `transport` qui reprenait par erreur la teinte de Démontage plutôt que la
  vraie couleur de transport — corrigé au passage (`TRANSPORT_META`, même
  fichier), pareil pour la couleur « En transit » de sa carte Répartition.
- **`DashboardView.vue`** : cas particulier documenté dans le fichier — sa
  timeline ne reprend PAS les 5 couleurs de badge. Répétition/Représentation/
  Entreposage y restent sur un vert « statut OK » fixe (sémantique, comme le
  rouge conflit/l'orange à-approuver, hors de la portée de ce changement) ;
  seuls Montage et Démontage ont une teinte dédiée sur cette timeline, pour
  se distinguer du spectacle qu'ils encadrent — remplacée par une déclinaison
  **calculée** (`color-mix(in oklch, var(--event-setup) 70%, black)`,
  `70%` choisi pour reproduire visuellement le ratio des anciennes valeurs
  codées en dur) plutôt qu'une deuxième couleur stockée : une seule source
  par type, la nuance de la timeline n'est qu'un rendu différent de la même
  couleur.
- **`ColorField.vue`** (nouveau composant, `frontend/src/components/`) :
  aperçu + puces de palette (réutilise `VENUE_PALETTE`) + sélecteur natif,
  même gabarit que le sélecteur déjà dupliqué sur `LieuDetailView.vue`/
  `CategoriesMaterielView.vue` — mais cette fois EXTRAIT en composant plutôt
  qu'une 3e copie (préférence de Samuel pour « la solution adéquate »). Les
  deux fiches existantes ne sont pas touchées (pas demandé). Contrairement à
  `Venue.color`, ces couleurs ne sont jamais vides : pas de puce «
  ✕ Automatique », un bouton ↺ optionnel (`defaultValue`) revient à la valeur
  d'origine du champ plutôt qu'à « rien ».
- **`ReglagesView.vue`** : nouvelle section « Couleurs », 6 `ColorField` avec
  leurs libellés, PATCH englobant les 6 champs en plus des réglages
  existants, `refreshEventColors()` après succès.

Suite de tests : 329 (était 323), flake8 propre. Vérifié : les fichiers Vue
touchés (`SpectaclesView.vue`, `SpectacleDetailView.vue`,
`MaterielDetailView.vue`, `DashboardView.vue`, `ReglagesView.vue`,
`AppShell.vue`, `ColorField.vue`) compilent (`compileScript`/
`compileTemplate`, `@vue/compiler-sfc`).

## Mise à jour (2026-08-02, suite) — Tableau de bord borné au projet

Demande de Samuel : « le dashboard principal ne devrait pas suivre la semaine
en cours réel, ça devrait être un affichage comme les autres dashboards, on
borne tout sur les dates spécifiées du projet ». Forme retenue
(`AskUserQuestion`) : **une piste continue avec filtre de dates**, pas un
sélecteur jour par jour façon Parcours.

**Cette note remplace les trois notes du 2026-08-02 sur « Cette semaine »**
(sous-lignes par lieu, filtres jour/lieu, défilement horizontal) partout où
elles décrivent un découpage par jour — les filtres et le défilement restent,
la structure par jour disparaît.

- Nouveau `GET /api/projects/{id}/window/` (`ProjectViewSet.window`) : expose
  `get_project_window` telle quelle. La règle « dates du projet, sinon du
  premier au dernier événement » reste côté backend, comme pour les Parcours
  et les chronologies de fiche — pas de réécriture en JS.
- **Les positions ne sont plus des minutes DANS LA JOURNÉE mais des minutes
  DEPUIS LE DÉBUT DE LA FENÊTRE.** `DAY_SPAN_MIN` (1440) disparaît au profit
  de `windowBounds.span`. Tout ce qui en dépendait suit : `zoomLevel`,
  `scrollFraction`, `blockStyle`, et la conversion pixel → minutes du
  glisser-déposer.
- `weekEntries`/`weekDays`/`weekWindow` deviennent `projectEntries`/
  `venueRows`/`timeline`. Plus d'en-tête de jour ni d'espaceur côté piste
  (`.dash-timeline__day-header`/`__day-spacer` supprimés) : **une ligne par
  lieu** sur toute la période, les journées se lisant sur l'axe et sur les
  lignes verticales renforcées à minuit (`--day`).
- Le « filtre de dates » n'a demandé aucun mécanisme nouveau : les puces de
  jour existantes restreignent les entrées, et `autoWindow` se resserre sur ce
  qui reste — sélectionner un seul jour revient donc à s'y recentrer.
- **Deux conséquences du passage à l'axe continu**, à connaître avant de
  toucher au glisser-déposer : un glisser horizontal peut désormais changer la
  DATE d'un événement (l'ancien axe 0h-24h l'interdisait par construction), et
  un même geste en pixels vaut beaucoup plus de temps sur un projet long —
  c'est le zoom qui redonne de la précision.
- La carte s'appelle « Calendrier du projet » et affiche les bornes de la
  fenêtre en tête. Sans dates ni événement, elle renvoie vers les Réglages
  plutôt que d'afficher une piste vide.
- **Puces de lieu remontées hors de la carte** (demande de Samuel, même
  jour) : type et lieu forment deux rangées étiquetées en haut de page
  (`.filters__row`/`.filters__label`), le filtre de JOUR reste dans la carte.
  Ce n'est pas qu'esthétique — le jour ne concerne que la timeline, alors que
  le type touche aussi « Spectacles à venir ».
- `upcoming` (« Spectacles à venir ») reste relatif à MAINTENANT, volontairement
  — c'est la seule partie de l'écran dont le sens est « ce qui arrive
  bientôt », pas « ce que contient le projet ».

Suite de tests : 332 (3 ajoutés, `ProjectWindowAPITests`), flake8 propre,
aucune migration. Vérifié : `DashboardView.vue` compile (`compileScript` +
`compileTemplate`) ; regroupement par lieu, voies indépendantes d'un transport
présent sur deux lignes, positions relatives à la fenêtre, conversion du
glisser à deux niveaux de zoom et graduation adaptative simulés en Node.

## Mise à jour (2026-08-02, suite) — Ordre des types unifié

Demande de Samuel : « les filtres dans le même ordre que les réglages de
couleurs ». Nouvelle constante **`EVENT_TYPE_ORDER`**
(`constants/eventTypeMeta.js`) : `rehearsal`, `setup`, `performance`,
`teardown`, `transport`, `storage` — le déroulement réel d'une production,
puis les deux types qui ne sont pas des moments de plateau.

Les trois listes en dérivent maintenant au lieu de la recopier :
`ReglagesView.vue` (section Couleurs, qui garde son séparateur avant
`transport`), les puces de type du `DashboardView.vue` et celles de
`SpectaclesView.vue` (qui retire `transport`, absent de cet écran).

- Les **libellés** restent propres à chaque écran — pluriel sur le Tableau de
  bord (« Répétitions », et « Spectacles » plutôt que « Représentation »),
  singulier ailleurs. Seul l'ordre est partagé.
- `SpectaclesView.vue` filtre sur des LIBELLÉS, pas des clés : il mappe
  l'ordre via `EVENT_TYPE_META[k].label`.

Frontend seulement, aucun changement backend.

## Mise à jour (2026-08-02, suite) — Ordre des types réordonnable

Demande de Samuel : pouvoir changer l'ordre des libellés depuis les Réglages,
ce qui change aussi l'ordre des puces de filtre, avec une poignée « 4 petits
points en carré » à droite de chaque ligne.

- **`Settings.event_type_order`** (migration `0024_settings_event_type_order`,
  additive) : CSV, vide = ordre par défaut. Toute lecture passe par
  `Settings.event_type_order_list` — clé inconnue ignorée, clé manquante
  rajoutée à sa place canonique (`EVENT_TYPE_ORDER_DEFAULT`). Ne pas lire le
  champ brut ailleurs : c'est ce garde-fou qui empêche une valeur écrite par
  une version antérieure, ou un futur 7e type, de faire disparaître une ligne.
- **Exposé comme une LISTE**, pas comme la chaîne CSV : `SettingsSerializer`
  convertit dans les deux sens (`to_representation`/`update`) et refuse les
  doublons et les types inconnus. Une liste **incomplète est acceptée**
  volontairement — un client qui ignore un futur type ne doit pas l'effacer en
  enregistrant l'ordre des six qu'il connaît.
- **`useEventColors.js` → `useEventDisplay.js`** : le composable porte
  maintenant les couleurs ET l'ordre (`eventTypeOrder`), qui voyagent dans le
  même singleton `Settings` — les séparer aurait voulu dire deux appels pour
  la même ligne. `refreshEventColors()` devient `refreshEventDisplay()`.
  Retombe sur `EVENT_TYPE_ORDER` tant que Settings n'a pas répondu, sinon les
  puces de filtre apparaîtraient vides au premier rendu.
- **`ReglagesView.vue`** : `colorFields` devient un computed piloté par
  l'ordre ; glisser-déposer HTML5 natif (pas de librairie) sur toute la ligne,
  avec la poignée 2×2 (`.drag-handle`, une grille CSS de 4 pastilles — pas une
  image ni un caractère). Le brouillon `typeOrder` ne part qu'au clic sur
  Enregistrer, comme les couleurs voisines, puis est re-seedé depuis la
  réponse (c'est l'ordre assaini par le backend qui fait foi).
- **Séparateur retiré** de la section Couleurs : il annonçait un regroupement
  « moments de plateau / le reste » que Samuel peut maintenant défaire d'un
  glisser — il aurait menti dès le premier réordonnancement.
- `DashboardView.vue` et `SpectaclesView.vue` lisent `eventTypeOrder` au lieu
  de la constante. `EVENT_TYPE_ORDER` reste le défaut et le repli.

Suite de tests : 340 (8 ajoutés, `EventTypeOrderTests`), flake8 propre,
migration `0024` **à appliquer** (`python manage.py migrate`).

## Mise à jour (2026-08-03) — Frontend en ligne : Django sert le build Vue

Le frontend n'était déployé nulle part (Railway ne servait que `backend/`,
`rootDirectory: backend`). Décidé avec Samuel (`AskUserQuestion`, tableau
comparatif de 3 options) : **« option B » — Django sert le build Vue via
WhiteNoise, même service** — plutôt qu'un 2e service Railway (cross-origin
sans bénéfice net ici, nécessiterait en plus un proxy pour partager le
domaine) ou un hébergeur statique séparé type Vercel (retenu comme
migration future possible, voir plus bas — pas pour ce premier déploiement).

- **`Dockerfile` à la racine du repo** (nouveau — remplace Railpack pour ce
  service) : build multi-étapes, `node:22-slim` pour `npm run build` du
  frontend puis `python:3.12-slim` pour le backend, qui copie le build Vue
  déjà prêt. **Root Directory du service Railway doit passer de `backend`
  à `/`** (racine du repo) pour que ce Dockerfile ait accès aux deux
  dossiers — Railway détecte un `Dockerfile` à la racine du répertoire
  source automatiquement, pas de builder à choisir manuellement. `migrate`/
  `collectstatic` restent dans la commande de démarrage du conteneur (`CMD`
  du Dockerfile), pas dans le build — même piège que documenté plus haut
  (Railway sans phase `release:`), juste déplacé du `Procfile` (devenu
  inutilisé par Railway une fois le Dockerfile détecté, mais laissé tel
  quel pour référence locale) vers le `Dockerfile`.
- **`frontend/vite.config.js`** : `base` devient conditionnel au mode —
  `/` en dev (`npm run dev`, inchangé), `/static/` en build
  (`npm run build`), pour que les assets construits correspondent au
  préfixe `STATIC_URL` de Django.
- **`backend/config/settings.py`** : `FRONTEND_DIST_DIR` (nouveau) pointe
  vers `frontend/dist`. `STATICFILES_DIRS` inclut `frontend/dist/assets`
  sous le préfixe `'assets'` (donc servi à `/static/assets/...`, exactement
  ce que le HTML construit référence) — **avec garde d'existence du
  dossier** : `STATICFILES_DIRS` sur un chemin absent lève
  `ImproperlyConfigured`, et ce dossier n'existe qu'après un
  `npm run build` (absent en dev local sans build, ou avant la première
  étape du Dockerfile). Ne pas retirer cette garde.
- **`backend/inventory/frontend_views.py`** (nouveau) : `spa_index` sert
  `frontend/dist/index.html` tel quel (lecture disque directe, PAS via
  `STATICFILES_DIRS`/`ManifestStaticFilesStorage` — qui renommerait le
  fichier avec un hash et casserait l'URL stable dont ce catch-all a
  besoin). Répond 501 avec un message explicite si le frontend n'est pas
  construit, plutôt qu'un 404/500 opaque.
- **`config/urls.py`** : catch-all `re_path(r'^(?!api/|admin/|accounts/|static/).*$', ...)`
  **en dernier** dans `urlpatterns` — sert `spa_index` pour toute route non
  capturée par l'API/l'admin/allauth, à charge de `vue-router` (mode
  `history`, voir `frontend/src/router/index.js`) de prendre le relais
  côté client sur une route profonde (ex. `/spectacles/5`, qui n'a pas de
  fichier correspondant sur disque). `static/` exclu par défense en
  profondeur — `WhiteNoiseMiddleware` intercepte déjà ces requêtes plus tôt
  dans la pile.
- **Pas de changement CORS/CSRF** : même origine que l'API désormais, ces
  réglages (pensés pour le serveur de dev Vite en local) restent
  inchangés et non pertinents en prod avec cette option.
- **Chemin de migration vers un hébergeur statique séparé (option C),
  gardé ouvert** : `frontend/src/api/client.js` lit déjà
  `import.meta.env.VITE_API_BASE_URL` (repli sur `/api` en même origine) et
  utilise déjà `credentials: 'include'` — migrer plus tard ne demanderait
  qu'une variable d'environnement au build (pas de changement de code
  frontend) plus, côté Django, `SESSION_COOKIE_SAMESITE = 'None'` et
  l'ajout du nouveau domaine à `CORS_ALLOWED_ORIGINS`/
  `CSRF_TRUSTED_ORIGINS`/`FRONTEND_URL`.
- **Variable Railway à ajouter** : `FRONTEND_URL` n'existait pas encore
  parmi les variables du service (vérifié via l'API Railway) — son défaut
  de dev (`http://127.0.0.1:5173`) ferait rediriger un login Google réussi
  vers `localhost` en prod. À fixer sur le domaine Railway du service
  avant/au moment du changement de Root Directory.

Vérifié dans ce bac à sable (venv reconstruit, Node 22 disponible) :
`npm run build` produit `dist/index.html` référençant
`/static/assets/index-HASH.js`/`.css` comme attendu ; `collectstatic`
copie ces fichiers sans erreur sous `staticfiles/assets/` ; test via le
client de test Django — route SPA profonde (`/spectacles/5`) → 200 avec le
HTML du build, `/api/venues/` → 403 (pas swallowed par le catch-all,
atteint bien la vue DRF), `/admin/login/` → 200, asset statique construit
→ 200. `flake8` propre, `makemigrations --check --dry-run` propre (aucun
changement de modèle), `inventory.test_project_access` (26 tests, la
suite la plus susceptible d'interagir avec le routing/permissions) au
vert. Suite complète non rejouée en entier ici (limite de temps du bac à
sable, comme les fois précédentes).

**Restait à faire au moment d'écrire cette note** : appliquer le
changement de Root Directory + Dockerfile côté service Railway (fait
depuis l'API par Claude avec confirmation de Samuel, ou par Samuel
lui-même dans le dashboard) et ajouter la variable `FRONTEND_URL` — voir
`suivi_projet.md` pour le statut à jour de cette étape.

## Mise à jour (2026-08-04) — Module transport : tournées multi-arrêts (backend)

**Décision de Samuel** : un transport n'est plus « lieu A → lieu B » mais une
**tournée** — une séquence ordonnée d'arrêts (arrêt 1 on ramasse du matériel,
arrêt 2 on en ajoute, arrêt 3 on décharge…). Trois options ont été comparées
(parent-enfant façon `Show.parent_show`, conteneur de segments chaînés,
tournée + arrêts) ; la troisième a été retenue parce que les segments d'une
tournée sont COUPLÉS (la destination du segment N est l'origine du N+1, même
camion, même équipe) : le parent-enfant aurait stocké chaque lieu
intermédiaire deux fois et forcé une ligne de matériel PAR SEGMENT — deux
vérités à synchroniser, exactement le doublon corrigé sur `display_title` le
2026-08-02. `transport_type` (livraison/ramassage) a été retiré en même temps
— Samuel n'en voyait pas l'utilité. Portée de cette étape : **backend
complet** ; le frontend suit dans une étape ultérieure (l'API garde un chemin
de compat pour l'interface actuelle, voir plus bas).

**Modèle** (migration `0025_transport_stops`, en trois temps comme la 0014 ;
irréversible) :
- Nouvelle table `transport_stops` : `venue` (PROTECT), `order` (0 = départ,
  `unique_together (transport, order)`), `travel_minutes_from_previous`
  (durée du segment, trajet + chargement — toujours 0 sur le premier arrêt).
- `Transport` perd `transport_type`/`origin_venue`/`destination_venue`/
  `estimated_duration_minutes` ; il garde `show`, `status`,
  `scheduled_datetime` (départ du premier arrêt) et `notes`. Horaire décidé
  par Samuel : UNE heure d'ancrage + durées par segment, les arrivées aux
  arrêts sont DÉRIVÉES (`Transport.arrival_at`) — décaler la tournée reste un
  seul champ (le drag du Dashboard en dépend). `origin_venue`/
  `destination_venue`/`total_duration_minutes`/`effective_end` deviennent des
  propriétés dérivées des arrêts.
- `TransportMaterial` gagne `load_stop`/`unload_stop` : chaque ligne pointe
  SA portion de la séquence — c'est la donnée qui associe chaque bloc de
  matériel à sa portion (l'affichage voulu par Samuel), pas une
  reconstruction. `unique_together` passe au quadruplet : un même matériel
  peut faire une répartition (8 chargées, 3 déposées à l'arrêt 1, 5 à
  l'arrêt 2) ou un relais (A→B puis B→C) dans la même tournée. La quantité
  est validée PAR LIGNE (pas de somme par matériel — un relais réutilise les
  mêmes unités ; le réalisme spatial reste au rapport de cohérence).
- Un ancien transport A→B = tournée à 2 arrêts (fenêtres identiques au pixel
  près) ; les lieux peuvent se répéter en positions non consécutives — une
  tournée aller-retour (entrepôt → salle → entrepôt) tient en une fiche.

**Logique adaptée** :
- `transport_coherence.py` : le grand livre raisonne par LIGNE — le matériel
  quitte son origine à l'arrivée du camion à l'arrêt de chargement et est
  livré à l'arrivée à l'arrêt de déchargement. `_ledger_before`, parcours,
  disponibilité et retour inchangés dans leur logique.
- `transport_autogen.py` : les propositions restent des tournées à 2 arrêts ;
  fusionner des propositions en une vraie tournée = geste manuel (phase
  ultérieure, décision Samuel). La couverture d'une livraison se juge sur
  l'arrêt de déchargement de la LIGNE, pas la destination finale.
- `conflicts.py` : fenêtre technicien = tournée entière (départ → arrivée au
  dernier arrêt). `get_transport_reference_shows` n'a plus `transport_type` :
  si le spectacle desservi se joue au lieu du DERNIER arrêt il est le
  spectacle d'arrivée (ancienne livraison), au PREMIER le spectacle de départ
  (ancien ramassage) — les arrêts intermédiaires ne bornent rien.
- `regenerate_signals.py` : signal ajouté sur `TransportStop` (déplacer un
  arrêt d'une tournée confirmée change la couverture).

**API** (`TransportSerializer`) : nouveau contrat `stops` (liste ordonnée de
`{venue, travel_minutes_from_previous?}` — l'ordre est la position, `order`
en lecture seule ; durée absente → estimation Google Routes par segment,
repli Settings ; segment au couple de lieux inchangé → durée conservée, même
règle que l'ancienne non-réestimation sur PATCH sans rapport) et `materials`
enrichi (`load_stop_order`/`unload_stop_order`, défaut = tournée entière).
Resynchronisation des arrêts EN PLACE par position (mêmes ids — les lignes
survivent à une retouche) ; retirer un arrêt encore utilisé par une ligne est
refusé sauf si `materials` est refourni dans la même requête. **Chemin de
compat pour le frontend actuel** : `origin_venue`/`destination_venue` en
écriture (création 2 arrêts / retouche premier-dernier arrêt),
`estimated_duration_minutes` en écriture sur une tournée à 2 arrêts (le
resize du Dashboard), refusé s'il changerait la valeur d'une tournée plus
longue et ignoré s'il la renvoie inchangée (la fiche renvoie tout son
formulaire). En lecture, `origin_venue*`/`destination_venue*`/
`estimated_duration_minutes` (= durée totale) restent exposés — l'interface
actuelle fonctionne telle quelle, `transport_type` disparaît simplement des
réponses. `material-availability` prend `?stop=<position>` (défaut : premier
arrêt, l'ancien comportement).

**Tests** : les fixtures A→B passent par deux fabriques (`_creer_transport`/
`_creer_ligne`, ancienne signature traduite vers transport + 2 arrêts) ; 14
nouveaux tests couvrent le multi-arrêts (création, portions, validations,
sync en place, disponibilité par arrêt, compat, cohérence par arrêt,
aller-retour). Suite complète : **354 tests OK** + flake8 propre (vérifié
dans le bac à sable cloud, venv reconstruit).

**Reste à faire (frontend, étape suivante)** : fiche Transport en liste
d'arrêts avec la liste unique de matériel par portion, Dashboard (bloc =
fenêtre totale de la tournée), Parcours Matériel (déjà servi par l'API
adaptée), modale matériel par arrêt (`?stop=`), et retrait des références à
`transport_type`.

## Mise à jour (2026-08-04, suite) — Tournées multi-arrêts : frontend

Second volet de la refonte transport (voir l'entrée précédente pour le
backend). Vérifié en sandbox : build Vite propre + parcours Playwright
(liste, fiche lecture/édition, modale par arrêt, Dashboard) sans erreur JS.

- **TransportDetailView.vue** — la fiche devient une fiche de tournée :
  - Éditeur de séquence : une ligne par arrêt (lieu, durée du segment,
    heure d'arrivée dérivée affichée en direct), réordonnable (↑/↓),
    ajout/retrait. Durée laissée vide = « auto » (estimée par le serveur —
    la clé n'est pas envoyée). La durée totale passe en lecture seule
    (somme des segments).
  - Chaque ligne de matériel porte sa portion : deux `<select>` d'arrêts
    (chargement/déchargement, options invalides désactivées) en édition, un
    libellé « 1. Entrepôt → 3. Prospero » en lecture. Retirer/réordonner un
    arrêt remappe les indexes des lignes (elles suivent leur arrêt) puis
    `fixupLines()` répare les combinaisons devenues invalides.
  - Modale « Ajouter du matériel » PAR ARRÊT : un `<select>` d'arrêt de
    chargement recharge `material-availability?stop=<n>` ; la modale ne
    pilote que les lignes chargées à cet arrêt (les autres sont préservées,
    même règle que le matériel hors catalogue). Le dernier arrêt est
    désactivé comme point de chargement (rien ne peut y monter).
  - Le toggle Livraison/Ramassage et le couple départ/arrivée disparaissent ;
    entête « Tournée — ENT → STA → PROS » (codes des arrêts).
- **TransportsView.vue** — trajet = séquence complète des codes, badge du
  nombre d'arrêts sur l'icône (neutre, teinte `--transport`) dès 3 arrêts.
  L'ajout rapide reste un simple A → B (chemin de compat, tournée à 2
  arrêts) — les arrêts s'ajoutent sur la fiche. Déduction locale des
  spectacles de référence alignée sur la nouvelle règle sans
  `transport_type` (le lieu du spectacle desservi décide du bout ancré).
- **DashboardView.vue** — le bloc d'une tournée apparaît sur la ligne de
  CHAQUE lieu desservi (arrêts intermédiaires compris, dédupliqués pour les
  allers-retours). Déplacer un bloc n'envoie plus que `scheduled_datetime`
  (une seule heure d'ancrage) ; le redimensionnement reste permis sur une
  tournée à 2 arrêts seulement — au-delà, message clair et ajustement
  segment par segment sur la fiche.
- **SpectacleDetailView / TechnicienDetailView / ConflitsView** — badge
  « Tournée » + trajet en séquence complète ; plus aucune référence à
  `transport_type` dans le code (les mentions restantes sont des
  commentaires historiques).
