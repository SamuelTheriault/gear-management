# Suivi de projet — gear-management

Tableau de bord manuel. À mettre à jour à chaque étape franchie ou décision
prise. Complète `recapitulatif_projet.md` (contenu fonctionnel) sans le
dupliquer — ce fichier ne suit que **l'avancement**, pas le scope.

Dernière mise à jour : 2026-08-03, session interactive — **le frontend est
en ligne.** Mergé dans `main`, Root Directory Railway basculé vers la
racine (confirmation explicite de Samuel avant application), variable
`FRONTEND_URL` ajoutée, déploiement Dockerfile réussi et vérifié (build
Vue + backend dans la même image, 158 fichiers statiques copiés, migrations
à jour, `gunicorn` démarré, page d'accueil confirmée en ligne). Voir
CLAUDE.md pour le détail technique complet.

**`wip/checkpoint-2026-07-31` (PR #12) confirmée mergée dans `main`**
(vérifié par Samuel sur GitHub : « Ahead 0 » par rapport à `main` — plus
aucun commit propre à cette branche). Ce fichier note ci-dessous ne
reflétait plus cet état (indiquait encore des commits locaux non poussés) —
corrigé. **Nouvelle règle de travail adoptée** : ne plus réutiliser une seule
branche longue d'une PR à l'autre (c'est ce qui causait les conflits `push
--fetch first` à répétition) — chaque correction repart d'une branche
fraîche depuis `main`. `wip/checkpoint-2026-07-31` à supprimer (locale +
distante) une fois `main` repullé sur le poste de Samuel.

**Étape 7 (OAuth) testée en vrai navigateur et fonctionnelle** — corrigé au
passage un bug de schéma http/https derrière le proxy Railway
(`SECURE_PROXY_SSL_HEADER`) et géré la liaison de compte (le Google de Samuel
partageait l'email de son superutilisateur Django existant, flux « connect »
d'allauth utilisé plutôt qu'un nouveau compte).

**Bug (non-code) trouvé et expliqué le 2026-08-03 :** création de Lieu/
Technicien refusée en 400 sur l'app en ligne — cause : aucun projet actif
sélectionné (compte flambant neuf, aucun `Project` existant sur lequel il y
aurait un `ProjectMembership`), donc le formulaire envoyait `project: null`.
Pas un bug — comportement attendu tant qu'aucun projet n'existe. Voir
backlog : ajouter une invite à créer un projet quand la liste est vide.

## Statut global

**Le backend déployé sur Railway reste à jour par rapport à ce qui était
committé au 2026-08-01 02h03 UTC** (dernière vérification via l'API
Railway : déploiement `SUCCESS`, commit `6033e089` — merge PR #9 — aucun
nouveau déploiement depuis). `rootDirectory: backend` toujours en place :
Railway ne sert toujours que le backend, pas de service frontend (étape 13
toujours ouverte).

**Le répertoire de travail local est maintenant committé au complet** sur
`wip/checkpoint-2026-07-31` — gestion des accès par projet
(`ProjectMembership`, migrations `0018`→`0023`), kits (`Material.
is_kit_parent`), couleurs personnalisables (lieux, transport, types
d'événement), et ordre des types réordonnable (`Settings.event_type_order`,
migration `0024`). Cette branche n'est pas encore poussée vers `origin` —
seul exemplaire de ce travail commité sur ce poste tant que le push n'est
pas fait.

**Checkpoint du 2026-08-04** : le travail en cours non committé (onboarding
de projet, portabilité/export CSV, tooltip flottant) a été mis à l'abri sur
`wip/checkpoint-2026-08-04` avant d'entamer la refonte transport. La refonte
elle-même vit sur `feature/transport-tournees`, branchée de `main` (règle
« branches fraîches ») — backend ET frontend complets, voir étape 15 et les
deux entrées 2026-08-04 de CLAUDE.md. Ni l'une ni l'autre n'est poussée
vers `origin`.

**Désync doc/code toujours présente, non résolue par ce commit** (voir
« Points de vigilance ») : `recapitulatif_projet.md`/`schema.md`/
`architecture.md` restent en retard sur plusieurs fonctionnalités déjà
codées et maintenant committées.

## Ordre à respecter (ne pas brûler d'étape)

| # | Étape | Statut | Date |
|---|---|---|---|
| 1 | Base de données confirmée (MySQL 8.0) | ✅ Fait | — |
| 2 | Stack backend/frontend confirmée (Django + Vue) | ✅ Fait | 2026-07-16 |
| 3 | Structure de repo (scaffold + Git init) | ✅ Fait | 2026-07-16 |
| 4 | Hébergement confirmé (Railway) | ✅ Fait | 2026-07-17 |
| 5 | Déploiement Railway fonctionnel (Django + Gunicorn + WhiteNoise) | ✅ Fait | 2026-07-18 |
| 6 | Superutilisateur Django créé | ✅ Fait | 2026-07-18 |
| 7 | Projet Google Cloud OAuth (config + intégration Django) | ⚠️ Code fait et mergé (PR #2), mais `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` **toujours vides** dans `backend/.env` — le login ne peut pas fonctionner | 2026-07-18 |
| 8 | Modèles Django + migrations | ✅ Fait — 13 modèles, 16 migrations (+1 en attente, non générée) | 2026-07-17 |
| 9 | API DRF + logique de conflits | ✅ Fait | 2026-07-17 |
| 9bis | Entreposage, transports, réglages, calcul de trajet (Google Routes API) | ✅ Fait, mergé (PR #2) | 2026-07-18 |
| 9ter | Couleur par département, quantité de matériel, `is_active`, isolation par projet (`Project`) + duplication | ✅ Fait, mergé (PR #3, #4, #5) | 2026-07-19 |
| 9quater | `Venue.code` (identification courte) | ✅ Fait, mergé (PR #6), déployé | 2026-07-24 |
| 9quinquies | Module transport : `TransportMaterial`, `Transport.status`, cohérence des emplacements, génération auto de propositions | ✅ Fait, mergé (PR #7, `e9cd546`) dans `main` | 2026-07-24 |
| 9sexies | Conflit de lieu entre spectacles (`get_venue_conflicts`, bloquant + `force`) | ✅ Mergé (PR #8, `fcfa65c`) et déployé le 2026-07-25 (confirmé via l'historique de déploiements Railway — corrige une incohérence de ce tableau avec l'étape 11 ci-dessous, qui listait déjà PR #8 comme mergée) | 2026-07-24 |
| 9septies | Retrait du modèle `Department` (migration `0013`) | ✅ Mergé (PR #9) et déployé, migration appliquée en prod | 2026-07-29 |
| 9octies | Catégories de matériel éditables (`MaterialCategory`, migration `0014`, endpoint de suppression avec réassignation) | ✅ Mergé (PR #9) et déployé, `RunPython` de remappage appliqué sans erreur en prod | 2026-07-30 |
| 9nonies | Fenêtre départ/arrivée des transports (`find_departure_show`/`find_arrival_show`, bloquant + `force`) | ✅ Mergé (PR #9) et déployé | 2026-07-30 |
| 9decies | Disponibilité du matériel au lieu de départ (`GET /api/transports/{id}/material-availability/`) | ✅ Mergé (PR #9) et déployé | 2026-07-30 |
| 9undecies | Plusieurs techniciens par déplacement (`TransportTechnician`, migration `0015`) | ✅ Mergé (PR #9) et déployé | 2026-07-30 |
| 9duodecies | Blocs rattachés à un événement — montage/démontage/répétition (`Show.parent_show`, migrations `0016`+`0017`) | ✅ Mergé (PR #9) et déployé | 2026-07-31 |
| 10 | Frontend connecté à l'API | ✅ Codé (19 vues, 5 composants, 5 composables) et mergé dans `main` (PR #9) — 🔴 **mais pas déployé** (voir étape 13) | 2026-07-31 |
| 11 | Push + merge dans `main` | ✅ **Fait** (PR #8 puis PR #9), par Samuel depuis son poste — le bac à sable de Claude n'a jamais eu les credentials pour le faire | 2026-08-01 |
| 12 | Déploiement Railway du backend à jour | ✅ **Fait** — déploiement du 2026-08-01 02h03 UTC réussi, migrations `0013`→`0017` appliquées sur MySQL prod sans erreur | 2026-08-01 |
| 13 | Décider et mettre en place le déploiement du frontend | ✅ **Fait** — mergé, Root Directory Railway basculé sur la racine, `FRONTEND_URL` ajoutée, déploiement Dockerfile réussi (158 fichiers statiques copiés, `gunicorn` démarré), page d'accueil vérifiée en ligne | 2026-08-03 |
| 14 | Gestion des accès par projet, kits, quantités, couleurs personnalisables, ordre des types réordonnable | ✅ Mergé dans `main` et déployé — migrations `0018`→`0024` appliquées en prod sans erreur (vérifié via logs Railway) | 2026-08-03 |
| 15 | Module transport en tournées multi-arrêts (backend) : `TransportStop`, matériel par portion (`load_stop`/`unload_stop`), retrait de `transport_type`, migration `0025`, cohérence/autogen/conflits adaptés, chemin de compat API pour le frontend actuel | ✅ Backend ET frontend codés et testés (354 tests + flake8 ; build Vite + parcours Playwright sans erreur) sur la branche `feature/transport-tournees` (base `main`) — PR à ouvrir/merger par Samuel. ⚠️ Collision de numéro avec la migration `0025_project_cascade_delete` du chantier parallèle non commité — renuméroter l'une des deux au merge | 2026-08-04 |

## Prochaine action concrète

→ **Pousser `wip/checkpoint-2026-07-31` vers `origin`, puis merger dans
`main` — depuis le poste de Samuel.** Le travail est maintenant committé et
vérifié sain (voir État technique) ; le bac à sable Claude n'a toujours pas
les credentials git en écriture, donc le push/merge reste une action
manuelle :

```
git push -u origin wip/checkpoint-2026-07-31
```

Puis ouvrir/mettre à jour la PR sur GitHub et merger dans `main` quand
satisfait (revue via `code-reviewer` recommandée vu le volume — accès par
projet notamment touche à la sécurité). Le déploiement Railway suivra
automatiquement (comme pour PR #8/#9).

→ **Ensuite seulement, trancher la stratégie de déploiement du frontend
(étape 13).** Le backend est à jour et déployé, mais Railway ne sert que
`backend/` — sans ça, rien à tester en ligne au-delà de l'admin Django et
de l'API brute. Trois options, à choisir avec Samuel plutôt qu'à décider
seul :

- **2e service Railway** dédié au frontend (build Vite + serveur statique,
  ex. `serve` ou Nginx) — le plus proche de l'architecture actuelle (même
  projet Railway), mais un deuxième service à gérer/facturer.
- **Django sert le build Vue via WhiteNoise** (même service que le
  backend) — un seul déploiement, mais mélange les responsabilités
  build-time (`npm run build` doit tourner avant `collectstatic`) et n'est
  pas ce que `Procfile`/`CLAUDE.md` décrivent aujourd'hui.
- **Hébergeur statique séparé** (Vercel/Netlify/Cloudflare Pages) pointant
  vers l'API Railway (CORS déjà configuré pour un frontend séparé) —
  déploiements frontend indépendants du backend, mais un compte/service de
  plus à configurer.

Ensuite seulement : créer les identifiants OAuth dans Google Cloud (étape 7)
si ce n'est pas déjà fait — les slots `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET`
existent comme variables Railway mais leur contenu n'est pas vérifiable
depuis Claude (valeurs toujours masquées par l'API Railway) ; à confirmer
par Samuel directement dans le dashboard Railway. Le flux OAuth complet n'a
jamais été testé en vrai navigateur.

## État technique (vérifié dans le repo, 2026-08-03)

- Branche courante : `wip/checkpoint-2026-07-31`, **working tree propre** —
  tout committé (dernier commit `9dbc395`). La branche locale est en avance
  sur `origin/wip/checkpoint-2026-07-31` (plusieurs commits non poussés) ;
  push à faire depuis le poste de Samuel. `.env.example` n'apparaît plus
  dans le statut (résolu dans un commit précédent).
- `main` local (ref caché) == `e9cd546` (PR #7, 2026-07-24) — **cette valeur
  ne peut toujours pas être rafraîchie depuis ce bac à sable** (`git fetch`
  échoue toujours, host key verification failed, revérifié aujourd'hui).
  Elle ne contredit pas le merge des PR #8/#9 : ce constat-là vient de l'API
  Railway (canal indépendant de git), pas d'un fetch — revérifiée
  aujourd'hui, elle montre toujours le même dernier déploiement `SUCCESS`
  du 2026-08-01 02h03 UTC (commit `6033e089`, merge PR #9), aucun de plus
  récent.
- Modèles : **14 classes** (+1 depuis hier) — `ProjectMembership` s'ajoute à
  la liste déjà connue (`User`, `Settings`, `Project`, `Venue`,
  `MaterialCategory`, `Material`, `Show`, `ShowMaterial`, `Technician`,
  `ShowTechnician`, `Transport`, `TransportTechnician`,
  `TransportMaterial`). 23 fichiers de migration (`0001`→`0023`) sur disque,
  6 de plus qu'hier : `0018_alter_show_title`, `0019_project_access`,
  `0020_project_access_data`, `0021_venue_color`,
  `0022_material_is_kit_parent`, `0023_settings_colors`.
- `makemigrations --check --dry-run` : **propre** — aucun modèle en avance
  sur ses migrations, reconfirmé aujourd'hui malgré les 6 nouvelles
  migrations.
- `flake8` (docstrings D100/D101/D103) sur `backend/inventory/` : **propre**,
  revérifié aujourd'hui dans un venv reconstruit.
- Tests : **329 méthodes de test recensées** (était 288 hier, +41) —
  cohérent avec le compteur du test runner Django (« Found 329 test(s) »).
  **Suite complète toujours pas menée à terme dans ce bac à sable** (limite
  de temps d'exécution des commandes) : une exécution parallélisée est allée
  jusqu'au bout ou presque des 329 tests à deux reprises sans qu'aucune
  ligne d'échec (`F`/`E`, `FAILED`, `ERROR`) n'apparaisse — seule trace
  attendue, un appel mocké à l'API Google Routes qui échoue volontairement
  dans un test dédié. En complément, les deux classes de test couvrant les
  fonctionnalités les plus récentes ont été exécutées jusqu'au bout,
  isolément : `MaterialKitParentEligibilityTests` +
  `MaterialKitParentAssignmentInheritanceTests` (nouveau, `is_kit_parent`)
  et `test_project_access.py` en entier — **36/36 au vert**. À relancer en
  entier en session interactive ou sur un poste avec plus de marge de temps
  avant de déclarer la suite complète au vert avec certitude.
- Frontend : 19 vues, inchangé en nombre. Nouveaux fichiers **non
  committés**, en hausse par rapport à hier : `components/ZoomControls.vue`,
  `composables/useChipFilter.js`, `composables/useEscapeKey.js`,
  `composables/useZoomScroll.js`, `composables/useTheme.js` (nouveau depuis
  hier), `composables/useEventColors.js` (nouveau), `constants/` (nouveau),
  `utils/`, `views/ProjetDetailView.vue` (nouveau). Les 25 fichiers `.vue`/
  `.js` modifiés ou ajoutés compilent sans erreur (`@vue/compiler-sfc`,
  `compileScript` sur chacun — 0 erreur). `npm run build` toujours
  impossible dans ce bac à sable (binaire natif `rolldown` manquant) — à
  confirmer avec `npm run dev`/`build` en conditions réelles. `HelloWorld.vue`
  traîne toujours, non référencé.
- Railway (revérifié aujourd'hui via l'API) : projet `gear-management`,
  service unique `gear-management` (backend, `rootDirectory: backend`,
  branche `main`) + `MySQL` — toujours pas de second service pour le
  frontend. Dernier déploiement backend : `SUCCESS`, 2026-08-01T02:03 UTC,
  inchangé depuis le dernier check.
- `backend/.env` : `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` et
  `GOOGLE_MAPS_API_KEY` toujours **vides**, revérifié aujourd'hui.
- **Repo probablement en cours d'édition active pendant cette vérification**
  : le fichier `0023_settings_colors.py` a un horodatage disque tombant en
  plein milieu de la fenêtre d'exécution de ce check. Comportement normal
  pour un dossier de travail connecté en direct — mais ça veut dire que
  l'instantané ci-dessus peut déjà être légèrement en retard sur l'état réel
  au moment de la lecture.
- ~~Curiosité mineure : dates de `CLAUDE.md` en avance sur la date du
  check~~ — **résolu**, la date du jour a rattrapé celle des notes
  (2026-08-02 des deux côtés).

## Points de vigilance

- ~~Travail non committé qui grossissait d'un check à l'autre~~ —
  **résolu le 2026-08-03** : tout committé (`9dbc395`), working tree propre,
  vérifié sain. Reste un point de défaillance unique tant que le push vers
  `origin` n'est pas fait (voir « Prochaine action concrète »).
- **🔴 Le frontend n'est déployé nulle part** (inchangé) — Railway
  (`get-service-config` confirme `rootDirectory: backend`) ne construit et
  ne sert que le backend Django. Voir étape 13 et « Prochaine action
  concrète ».
- ~~Checkpoint commité mais pas poussé~~ — **résolu pour l'état au
  2026-07-31** (PR #8 et #9 mergées, déployées) — **mais un nouveau
  checkpoint non committé s'est reconstitué depuis** (voir point ci-dessus).
- ~~Modèle en avance sur sa propre migration~~ — **résolu** :
  `0017_alter_show_parent_show.py` générée, commitée et déployée (appliquée
  en prod le 2026-08-01), `makemigrations --check --dry-run` toujours
  propre aujourd'hui, y compris avec les modifications non committées
  actuelles.
- ~~Écart prod ↔ local, qui se creuse~~ — **partiellement résolu** : le
  backend Railway tourne sur le commit du merge PR #9, migrations
  `0013`→`0017` appliquées en prod — mais l'écart s'est recreusé depuis
  avec le nouveau travail non committé (point ci-dessus), sur backend ET
  frontend cette fois.
- **Filtres `?show`/`?material`/`?technician` toujours sans test** — présents
  dans `views.py` (`ShowMaterialViewSet`, `ShowTechnicianViewSet`,
  `TransportViewSet`) et utilisés par le frontend, mais aucun test ne les
  couvre. Régression silencieuse possible — le frontend renverrait alors
  toutes les assignations, tous projets confondus. Maintenant en prod sans
  ce filet — à couvrir en priorité.
- **🔴 Désync doc/code, deux niveaux distincts cette fois — l'écart s'est
  creusé plutôt que résorbé, et une partie n'est même pas dans `CLAUDE.md`.**
  1) `recapitulatif_projet.md` reste en retard sur `CLAUDE.md` : toujours
  rien sur puces ⌘+clic (`useChipFilter`), fermeture des modales à Échap,
  zoom + défilement sur Dashboard/Parcours, sous-lignes par lieu et filtres
  jour/lieu sur « Cette semaine », bifurcations/fusions/transports intégrés
  au Parcours Matériel, réorganisation de la fiche Transport, thème clair,
  ni sur la gestion des accès par projet (`ProjectMembership`) pourtant déjà
  documentée dans `CLAUDE.md` et (partiellement) dans `schema.md`. 2) **Plus
  nouveau et plus net : trois éléments de code vérifiés aujourd'hui
  n'apparaissent dans AUCUN des quatre documents de référence, pas même
  `CLAUDE.md`** — `Material.is_kit_parent` (migration `0022`, avec ses
  propres tests et son `help_text` détaillé dans le code, mais zéro note
  `CLAUDE.md`), les couleurs personnalisables de `Settings`
  (`event_color_*`/`transport_color`, migration `0023`, nouveau composable
  `useEventColors.js`), et `ProjetDetailView.vue` (l'écran qui donne accès
  à `ProjectMembershipViewSet`, déjà documenté côté backend/schéma mais
  jamais côté frontend). Aucun de ces trois n'a été modifié par cette
  vérification (consigne : ne pas toucher `recapitulatif_projet.md`/
  `schema.md`/`architecture.md` automatiquement) — à trancher avec Samuel :
  soit ce sont des changements en cours de rédaction de notes (le dossier
  semblait être édité en direct pendant ce check, voir État technique), soit
  il faut les documenter explicitement.
- **`.env.example` supprimé (non commité)** — le contenu semble avoir migré
  dans `backend/.env` (qui porte encore les commentaires du gabarit). Si la
  suppression est volontaire, le commit doit l'acter ; sinon, restaurer un
  gabarit à la racine pour un nouveau clone.
- ~~Migration `0014` avec `RunPython` non encore jouée en prod~~ —
  **résolu**, appliquée en prod le 2026-07-30 (voir étape 9octies). Le même
  type de risque existe maintenant sur la nouvelle migration
  `0020_project_access_data` (elle aussi un `RunPython`, sur `User`/
  `ProjectMembership` cette fois) — encore non committée, donc non jouée
  nulle part, à surveiller au moment du déploiement une fois poussée.
- `HelloWorld.vue` : résidu du scaffold Vue, plus importé nulle part —
  à supprimer au passage.
- Railway ne supporte pas la phase `release:` — `migrate`/`collectstatic`
  doivent rester dans la commande `web:`.
- Ne pas confondre `inventory.User` (modèle applicatif) et le superutilisateur
  Django (`django.contrib.auth`).
- Protection de branche `main` non activée sur GitHub — repose sur la
  discipline du gabarit de PR.
- L'estimation automatique de trajet (Google Routes API) reste non testable
  en conditions réelles (clé vide + pas de réseau) — se dégrade silencieusement
  sur la valeur par défaut.
- Branches de feature déjà mergées (`feature/department-colors`,
  `feature/material-quantity`, `feature/production-scoping`,
  `feature/storage-transports-settings-maps`, `feature/venue-code`,
  `feature/module-transport`) encore présentes en local/remote — nettoyage
  optionnel.

## Backlog (après étape 10)

- **Invite à créer un projet quand aucun n'est actif** (trouvé le
  2026-08-03) : sur un compte neuf sans `Project`, le sélecteur de projet de
  `AppShell.vue` reste vide et rien n'indique pourquoi les formulaires
  d'ajout (Lieu, Technicien, ...) échouent en 400 — `project` part `null`.
  Ajouter un état vide explicite (« Crée ton premier projet pour commencer »
  avec un lien vers Réglages) plutôt que de laisser échouer silencieusement.
- Listes de matériel par technicien (sortie terrain).
- Rôles admin/viewer une fois OAuth en place.
- Budget de location (explicitement reporté après V1).
- Géocodage automatique d'adresse pour `venues.latitude`/`longitude`
  (actuellement saisie manuelle uniquement).
