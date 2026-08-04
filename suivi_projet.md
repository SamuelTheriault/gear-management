# Suivi de projet — gear-management

Tableau de bord manuel. À mettre à jour à chaque étape franchie ou décision
prise. Complète `recapitulatif_projet.md` (contenu fonctionnel) sans le
dupliquer — ce fichier ne suit que **l'avancement**, pas le scope.

Dernière mise à jour : 2026-08-04 — **toutes les étapes du plan initial
(1 à 16) sont faites, mergées et déployées.** Les deux derniers chantiers
(tournées multi-arrêts, onboarding de projet + suppression cascade) sont
passés par une revue `code-reviewer` avant merge, chacune ayant trouvé et
fait corriger un vrai problème avant qu'il n'atteigne la prod (voir étapes
15 et 16 ci-dessous).

## Statut global

Backend et frontend sont en ligne sur le même service Railway (Dockerfile,
WhiteNoise sert le build Vue — étape 13), à jour avec `main`, migrations
`0001`→`0026` appliquées. OAuth Google testé en vrai navigateur et
fonctionnel (étape 7).

**⚠️ Incident opérationnel du 2026-08-04, résolu sans perte de données :**
deux sessions Cowork ont travaillé sur le même dossier `gear-management` en
même temps (l'une sur les tournées transport, l'autre sur l'onboarding/CSV),
causant des symptômes déroutants — la branche courante changeait seule,
`suivi_projet.md` se modifiait sous nos yeux, un `git stash pop` de l'autre
session a été interrompu par erreur. Tout a été retrouvé intact (un stash
contenait bien tout ce qui semblait manquant) et le travail des deux
sessions a pu être mergé proprement. **Leçon à respecter à l'avenir : une
seule session Cowork à la fois doit toucher le dossier de travail.**

**Reste en dehors du dépôt principal** : `wip/checkpoint-2026-08-04`
contient un chantier non encore scindé en branche propre — export/
portabilité CSV (`portability.py`, `csv_export.py`) et le tooltip flottant
du Dashboard/Parcours (`FloatingTooltip.vue`). Samuel prépare une nouvelle
branche dédiée à l'import/export pour la suite ; le tooltip flottant reste
à trier séparément (voir « Prochaine action concrète »).

**Désync doc/code toujours présente** (voir « Points de vigilance ») :
`recapitulatif_projet.md`/`schema.md`/`architecture.md` restent en retard
sur plusieurs fonctionnalités déjà codées et déployées.

## Ordre à respecter (ne pas brûler d'étape)

| # | Étape | Statut | Date |
|---|---|---|---|
| 1 | Base de données confirmée (MySQL 8.0) | ✅ Fait | — |
| 2 | Stack backend/frontend confirmée (Django + Vue) | ✅ Fait | 2026-07-16 |
| 3 | Structure de repo (scaffold + Git init) | ✅ Fait | 2026-07-16 |
| 4 | Hébergement confirmé (Railway) | ✅ Fait | 2026-07-17 |
| 5 | Déploiement Railway fonctionnel (Django + Gunicorn + WhiteNoise) | ✅ Fait | 2026-07-18 |
| 6 | Superutilisateur Django créé | ✅ Fait | 2026-07-18 |
| 7 | Projet Google Cloud OAuth (config + intégration Django) | ✅ Fait, testé en vrai navigateur — corrigé un bug de schéma http/https derrière le proxy Railway (`SECURE_PROXY_SSL_HEADER`) et géré la liaison de compte (email partagé avec le superutilisateur Django existant, flux « connect » d'allauth) | 2026-08-03 |
| 8 | Modèles Django + migrations | ✅ Fait — migrations `0001`→`0026` | 2026-07-17 |
| 9 | API DRF + logique de conflits | ✅ Fait | 2026-07-17 |
| 9bis | Entreposage, transports, réglages, calcul de trajet (Google Routes API) | ✅ Fait, mergé (PR #2) | 2026-07-18 |
| 9ter | Couleur par département, quantité de matériel, `is_active`, isolation par projet (`Project`) + duplication | ✅ Fait, mergé (PR #3, #4, #5) | 2026-07-19 |
| 9quater | `Venue.code` (identification courte) | ✅ Fait, mergé (PR #6), déployé | 2026-07-24 |
| 9quinquies | Module transport : `TransportMaterial`, `Transport.status`, cohérence des emplacements, génération auto de propositions | ✅ Fait, mergé (PR #7, `e9cd546`) dans `main` | 2026-07-24 |
| 9sexies | Conflit de lieu entre spectacles (`get_venue_conflicts`, bloquant + `force`) | ✅ Mergé (PR #8) et déployé | 2026-07-25 |
| 9septies | Retrait du modèle `Department` (migration `0013`) | ✅ Mergé (PR #9) et déployé | 2026-07-29 |
| 9octies | Catégories de matériel éditables (`MaterialCategory`, migration `0014`) | ✅ Mergé (PR #9) et déployé | 2026-07-30 |
| 9nonies | Fenêtre départ/arrivée des transports (bloquant + `force`) | ✅ Mergé (PR #9) et déployé | 2026-07-30 |
| 9decies | Disponibilité du matériel au lieu de départ | ✅ Mergé (PR #9) et déployé | 2026-07-30 |
| 9undecies | Plusieurs techniciens par déplacement (`TransportTechnician`, migration `0015`) | ✅ Mergé (PR #9) et déployé | 2026-07-30 |
| 9duodecies | Blocs rattachés à un événement — montage/démontage/répétition (migrations `0016`+`0017`) | ✅ Mergé (PR #9) et déployé | 2026-07-31 |
| 10 | Frontend connecté à l'API | ✅ Fait, mergé (PR #9) | 2026-07-31 |
| 11 | Push + merge dans `main` | ✅ Fait, par Samuel depuis son poste (le bac à sable Claude n'a pas les credentials git) | 2026-08-01 |
| 12 | Déploiement Railway du backend à jour | ✅ Fait | 2026-08-01 |
| 13 | Décider et mettre en place le déploiement du frontend | ✅ Fait — option B (Django sert le build Vue via WhiteNoise, même service, Dockerfile) | 2026-08-03 |
| 14 | Gestion des accès par projet, kits, quantités, couleurs personnalisables, ordre des types réordonnable | ✅ Mergé et déployé — migrations `0018`→`0024` | 2026-08-03 |
| 15 | Module transport en tournées multi-arrêts : `TransportStop`, matériel par portion, retrait de `transport_type`, migration `0025`, manifeste par arrêt | ✅ Mergée dans `main` et déployée. Revue `code-reviewer` : 1 correctif (durée négative acceptée sur le chemin de compat A→B) | 2026-08-04 |
| 16 | Onboarding de projet (écran bloquant + garde de route), suppression cascade de projet/matériel/technicien | ✅ Mergée dans `main` et déployée — migration `0026` (renumérotée depuis `0025`, collision avec l'étape 15 résolue). Revue `code-reviewer` : 1 **bug bloquant** corrigé (`DELETE /api/projects/{id}/` en 500 sur tout projet réel) + exemption `/utilisateurs` de la garde d'onboarding | 2026-08-04 |

## Prochaine action concrète

Aucune étape bloquante en attente sur `main` — tout ce qui était en PR est
mergé et déployé.

→ **Samuel prépare `feature/import-export` (CSV) dans une nouvelle
branche.** Même routine que les deux dernières fois : vérif (flake8,
migrations, tests ciblés) puis revue `code-reviewer` avant merge.

→ **`wip/checkpoint-2026-08-04` à trier** : contient déjà du code pour
l'export/portabilité CSV (`portability.py`, `csv_export.py`,
`test_portability.py`) — à vérifier si ça peut nourrir directement
`feature/import-export`, plutôt que de repartir de zéro. Le tooltip flottant
du Dashboard/Parcours (`FloatingTooltip.vue`, remplace l'ancienne info-bulle
CSS-only piégée par le clipping du défilement zoomé) n'a pas de branche
dédiée — à extraire séparément si Samuel veut le garder.

→ **Désync doc/code** : `recapitulatif_projet.md`/`schema.md`/
`architecture.md` à rattraper sur plusieurs fonctionnalités déjà codées
(voir « Points de vigilance »).

## Points de vigilance

- **Un seul chantier de code à la fois dans ce dossier** — voir l'incident
  du 2026-08-04 en « Statut global ». Deux sessions Cowork simultanées sur
  le même dossier peuvent se marcher dessus (branche qui change seule,
  fichier modifié en double, lock git orphelin). Rien perdu cette fois, mais
  à éviter activement.
- **🟡 `wip/checkpoint-2026-08-04` non trié** — code pour CSV import/export
  et tooltip flottant, pas encore en branche propre. Voir « Prochaine action
  concrète ».
- **🔴 Désync doc/code** — `recapitulatif_projet.md` reste en retard sur
  `CLAUDE.md` pour plusieurs fonctionnalités déjà codées et déployées :
  puces ⌘+clic, fermeture des modales à Échap, zoom + défilement sur
  Dashboard/Parcours, thème clair, gestion des accès par projet
  (`ProjectMembership`), tournées multi-arrêts, onboarding de projet,
  suppression cascade. `Material.is_kit_parent` et les couleurs
  personnalisables de `Settings` restent absentes même de `CLAUDE.md`.
- **Filtres `?show`/`?material`/`?technician` toujours sans test** — présents
  dans `views.py` et utilisés par le frontend, mais aucun test ne les
  couvre. Régression silencieuse possible (le frontend renverrait toutes les
  assignations, tous projets confondus) — à couvrir en priorité.
- `HelloWorld.vue` : résidu du scaffold Vue, plus importé nulle part — à
  supprimer au passage.
- Railway ne supporte pas la phase `release:` — `migrate`/`collectstatic`
  restent dans le `CMD` du Dockerfile.
- Ne pas confondre `inventory.User` (modèle applicatif) et le superutilisateur
  Django (`django.contrib.auth`).
- Protection de branche `main` activée sur GitHub (confirmé le 2026-08-03) —
  PR obligatoire + 2 status checks, y compris pour un changement
  documentation seule.
- L'estimation automatique de trajet (Google Routes API) reste non testable
  en conditions réelles dans le bac à sable Claude (pas de réseau) — se
  dégrade silencieusement sur la valeur par défaut si la clé est absente.
- Branches déjà mergées, nettoyage optionnel : `feature/department-colors`,
  `feature/material-quantity`, `feature/production-scoping`,
  `feature/storage-transports-settings-maps`, `feature/venue-code`,
  `feature/module-transport`, `feature/venue-conflict`,
  `feature/transport-tournees`, `feature/project-onboarding`,
  `wip/checkpoint-2026-07-31`.

## Backlog

- **Invite à créer un projet quand aucun n'est actif** (trouvé le
  2026-08-03) : sur un compte neuf sans `Project`, le sélecteur de projet de
  `AppShell.vue` reste vide. Depuis l'écran d'onboarding (étape 16), ce cas
  précis est déjà couvert par un écran bloquant dédié — à revérifier si ce
  point est encore ouvert ou si l'onboarding l'a résolu.
- Listes de matériel par technicien (sortie terrain).
- Rôles admin/viewer une fois OAuth en place (OAuth est en place depuis
  l'étape 7 — les rôles par projet existent déjà via `ProjectMembership`,
  étape 14 ; à confirmer si ce point est encore distinct).
- Budget de location (explicitement reporté après V1).
- Géocodage automatique d'adresse pour `venues.latitude`/`longitude`
  (actuellement saisie manuelle uniquement).
