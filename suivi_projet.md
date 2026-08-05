# Suivi de projet — gear-management

Tableau de bord manuel. À mettre à jour à chaque étape franchie ou décision
prise. Complète `recapitulatif_projet.md` (contenu fonctionnel) sans le
dupliquer — ce fichier ne suit que **l'avancement**, pas le scope.

Dernière mise à jour : 2026-08-05 (suite) — **étape 20 prête** (tests des
filtres `?show`/`?material`/`?technician` + correctif de renvoi
`schema.md`/`architecture.md`) sur `chore/schema-xref-filter-tests-2026-08-05`,
en attente de push/PR/merge par Samuel.

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

**`wip/checkpoint-2026-08-04` entièrement traité** : tout ce qui était
récupérable en a été extrait — CSV import/export (étape 17) et tooltip
flottant (étape 18). Le reste du checkpoint est périmé (prédate les
tournées multi-arrêts) — la branche peut être nettoyée à l'occasion.

**Doc de référence rattrapée** (étape 18, 2026-08-05) :
`schema.md`/`architecture.md`/`recapitulatif_projet.md` ont été mis à jour
sur les étapes 14-17 (accès par projet, tournées multi-arrêts, suppression
cascade, export/import CSV+JSON, `Venue.color`, `Material.is_kit_parent`.
Reste volontairement non documenté (fonctionnalités frontend pures, sans
modèle backend) : voir « Points de vigilance ».

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
| 17 | Export/import CSV par section (matériel/lieux/techniciens/spectacles) + export/import JSON complet du projet (réimportable) et XML (lecture seule) | ✅ Mergée dans `main` (PR #17) et déployée. `portability.py` réparé pour `TransportStop` (remappage des arrêts par position, pas par id). Revue `code-reviewer` : 1 bug corrigé (import replace des lieux ne bloquait pas sur le matériel qui en fait son origine, contrairement à `VenueViewSet.destroy`) + 2 suggestions de tests ajoutées (permissions `export-csv`, tournée à 3 arrêts). Suite à 393 tests, flake8 propre, aucune migration | 2026-08-05 |
| 18 | Info-bulle flottante Dashboard/Parcours (`FloatingTooltip.vue`, remplace l'ancienne info-bulle CSS-only piégée par le clipping du défilement zoomé) + rattrapage de `schema.md`/`architecture.md`/`recapitulatif_projet.md` sur les étapes 14-17 | ✅ Mergée dans `main` (PR #18) et déployée. Extrait à la main de `wip/checkpoint-2026-08-04` (périmé — prédate les tournées, aurait régressé Transport/Dashboard si appliqué tel quel). Revue `code-reviewer` : code propre (aucune régression du checkpoint périmé), 1 oubli corrigé (doc rattrapée pas committée avec le code au premier passage). Frontend + doc seulement, aucun changement backend | 2026-08-05 |
| 19 | Interface Import/Export (étape 17 côté frontend) : section « Import / Export » sur Réglages — export JSON/XML complet d'un projet, export CSV par section (matériel/lieux/techniciens/spectacles), import JSON (nouveau projet), import CSV par section (append/remplace, confirmé par modale) | ✅ Mergée dans `main` (PR #22) et déployée. Brouillon retrouvé déjà présent, non committé, dans l'arbre de travail — complété par le seul chaînon manquant (`api.downloadUrl()` dans `client.js`) plutôt que réécrit, après vérification champ par champ contre l'API réelle. Inclut au passage le rattrapage `CLAUDE.md` de l'étape 18 (tooltip), resté non committé lui aussi. Revue `code-reviewer` : rien à corriger, 3 suggestions mineures non bloquantes. Frontend + doc seulement, aucun changement backend | 2026-08-05 |
| 20 | Correctif de renvoi `schema.md`/`architecture.md` (section 12 → 9 pour `transport_materials`) + tests des filtres `?show`/`?material`/`?technician` (`ShowMaterialViewSet`/`ShowTechnicianViewSet`/`TransportViewSet`) et `?project=` (`TransportViewSet`), jusqu'ici sans couverture | 🟡 Prête sur `chore/schema-xref-filter-tests-2026-08-05`, en attente de push/PR/merge. 8 tests ajoutés (`QueryParamFilterAPITests`), suite à 401 tests, flake8 propre, aucune migration | 2026-08-05 |

## Prochaine action concrète

**Étape 20 à pousser/merger.** Reste en approche ouverte (backlog, non
prioritaire pour l'instant — voir section Backlog) : listes de matériel par
technicien, budget de location, géocodage d'adresse.

## Points de vigilance

- **🔴 `manage.py test` casse actuellement dans l'arbre de travail** :
  `test_csv_import.py` (untracked) importe `csv_export.py` qui n'est pas
  dans l'arbre (seulement sur `wip/checkpoint-2026-08-04`) — le découvreur
  de tests Django échoue en ImportError. Se résout en assemblant
  `feature/import-export` (ou en déplaçant temporairement les deux fichiers
  untracked hors du package).
- **🟡 `main` local a divergé de GitHub** : les étapes 15-16 ont été mergées
  localement (merges directs) PUIS via les PR #15/#16 sur GitHub (commits de
  merge différents, `9cd1d42` en tête là-bas) ; les étapes 17 et 18 ont
  ensuite été mergées directement sur GitHub sans passer par un merge local
  équivalent — le `main` local du bac à sable est donc encore plus en
  retard sur `origin/main` (contenu identique jusqu'à `9cd1d42`, divergent
  ensuite). Chaque nouvelle branche de travail continue de partir du dernier
  état connu localement (pas de `main` fraîchement fetché) — sans incident
  jusqu'ici (le contenu reste identique, seuls les SHA de merge diffèrent),
  mais à garder en tête. Au prochain accès réseau : `git fetch` puis
  réaligner le `main` local sur `origin/main` plutôt que de pousser
  par-dessus. (Le `git fetch` est impossible depuis le bac à sable Claude —
  confirmé à nouveau le 2026-08-05 : « Host key verification failed » ; le
  statut de déploiement est vérifié via l'API Railway, pas via git.)
- **Un seul chantier de code à la fois dans ce dossier** — voir l'incident
  du 2026-08-04 en « Statut global ». Deux sessions Cowork simultanées sur
  le même dossier peuvent se marcher dessus (branche qui change seule,
  fichier modifié en double, lock git orphelin). Rien perdu cette fois, mais
  à éviter activement.
- **`wip/checkpoint-2026-08-04` entièrement vidé de ce qui était récupérable**
  — CSV import/export rapatrié dans l'étape 17, tooltip flottant dans
  l'étape 18. Le reste du checkpoint est périmé (prédate les tournées
  multi-arrêts) — plus rien à en extraire, la branche peut être nettoyée à
  l'occasion.
- **🟡 `schema.md`/`architecture.md`/`recapitulatif_projet.md` rattrapés sur
  la plupart des étapes 14-17** (étape 18, 2026-08-05) — accès par projet,
  tournées multi-arrêts, suppression cascade, export/import CSV+JSON,
  `Venue.color`, `Material.is_kit_parent`. **Reste volontairement non
  documenté** (fonctionnalités frontend pures, sans modèle backend à
  décrire) : puces ⌘+clic, fermeture des modales à Échap, zoom + défilement
  Dashboard/Parcours, thème clair, info-bulle flottante — `CLAUDE.md` reste
  la seule trace de ces détails d'implémentation Vue. Le renvoi cassé vers
  `transport_materials` (`architecture.md`, ~ligne 210) est corrigé (étape
  20) — `schema.md` garde volontairement son saut de numérotation (11 → 13,
  pas de section 12) puisque plus rien n'y renvoie, pas de raison de
  renuméroter.
- `HelloWorld.vue` : résidu du scaffold Vue, plus importé nulle part — à
  supprimer au passage.
- Railway ne supporte pas la phase `release:` — `migrate`/`collectstatic`
  restent dans le `CMD` du Dockerfile.
- Ne pas confondre `inventory.User` (modèle applicatif) et le superutilisateur
  Django (`django.contrib.auth`).
- Protection de branche `main` activée sur GitHub (confirmé le 2026-08-03) —
  PR obligatoire + 2 status checks, y compris pour un changement
  documentation seule.
- ~~Protection de branche `main` non activée sur GitHub~~ — **résolu**,
  confirmé activée le 2026-08-03 (push direct sur `main` refusé : « Changes
  must be made through a pull request », 2 status checks requis). Tout
  changement, même documentation seule, passe maintenant par une PR.
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
