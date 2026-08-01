# Suivi de projet — gear-management

Tableau de bord manuel. À mettre à jour à chaque étape franchie ou décision
prise. Complète `recapitulatif_projet.md` (contenu fonctionnel) sans le
dupliquer — ce fichier ne suit que **l'avancement**, pas le scope.

Dernière mise à jour : 2026-07-31 (vérification automatisée — **rien n'a été
commité depuis le dernier check** : toujours sur `feature/venue-conflict`
(`908820f`), toujours 1 commit d'avance sur `main`. Le working tree a en
revanche continué de grossir : 22 fichiers modifiés (6 171 insertions / 806
suppressions, était ~2 790/698), et **4 migrations non commitées** au lieu de
2 (`0013`→`0016`). Nouveau : une 5e modification de modèle non capturée par
aucune migration (`0017` en attente). Voir « Points de vigilance ».)

## Statut global

**Toute l'app est fonctionnellement là : 13 modèles, 266 tests au vert
(vérifié en exécutant la suite), flake8 propre, et un frontend Vue complet —
19 vues, garde d'authentification, écran de login Google. MAIS rien de tout
ça n'est commité, et le retard grossit chaque jour.** Le dernier commit du
repo date toujours du **2026-07-24** (`908820f`, conflit de lieu) ; sept
jours de travail backend + frontend (dont 4 migrations : retrait de
`Department`, catégories éditables, techniciens multiples par transport,
blocs rattachés à un événement) n'existent que dans le working tree de
`feature/venue-conflict`. `main` (`e9cd546`, PR #7 module transport) est ce
qui tourne sur Railway — la prod a donc sept jours de retard sur le code
local, et 117 tests de moins.

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
| 9sexies | Conflit de lieu entre spectacles (`get_venue_conflicts`, bloquant + `force`) | ⚠️ Commité + poussé sur `feature/venue-conflict` (`908820f`) mais **pas mergé dans `main`, pas déployé** | 2026-07-24 |
| 9septies | Retrait du modèle `Department` (migration `0013`) | 🔴 Codé et testé, **non commité** | 2026-07-29 |
| 9octies | Catégories de matériel éditables (`MaterialCategory`, migration `0014`, endpoint de suppression avec réassignation) | 🔴 Codé et testé, **non commité** | 2026-07-30 |
| 9nonies | Fenêtre départ/arrivée des transports (`find_departure_show`/`find_arrival_show`, bloquant + `force`) | 🔴 Codé et testé, **non commité** | 2026-07-30 |
| 9decies | Disponibilité du matériel au lieu de départ (`GET /api/transports/{id}/material-availability/`) | 🔴 Codé et testé, **non commité** | 2026-07-30 |
| 9undecies | Plusieurs techniciens par déplacement (`TransportTechnician`, migration `0015`) | 🔴 Codé et testé, **non commité** | 2026-07-30 |
| 9duodecies | Blocs rattachés à un événement — montage/démontage/répétition (`Show.parent_show`, migration `0016`) | 🔴 Codé et testé, **non commité** — modèle légèrement en avance sur la migration (voir Points de vigilance) | 2026-07-31 |
| 10 | Frontend connecté à l'API | ✅ **Terminé** (3 phases + Parcours jour-par-jour) — 19 vues, 5 composants, 5 composables, client API session/CSRF, router avec garde d'auth. 🔴 **Intégralement non commité** | 2026-07-31 |
| 11 | Merge dans `main` + déploiement Railway de tout ce travail | ⬜ **À faire — bloque tout le reste, le retard s'aggrave chaque jour** | — |

## Prochaine action concrète

→ **Commiter, mettre en PR et merger. C'est la seule chose qui compte
maintenant — et ça devient plus urgent, pas moins.** Sept jours de travail
(backend + frontend + 4 migrations) ne sont ni commités ni sauvegardés
ailleurs que dans le working tree. Ordre proposé, en PR distinctes pour
rester relisibles :

1. Merger d'abord `feature/venue-conflict` (`908820f`, déjà poussé) dans
   `main` — c'est du backend isolé, déjà revu.
2. Commiter le backend non commité sur une ou plusieurs branches dédiées
   (`0013` à `0016`, `conflicts.py`, `serializers.py`, `views.py`,
   `transport_coherence.py`, `models.py`, `signals.py`, `duplication.py`,
   `admin.py`, `tests.py`). **Avant de commiter `0016`**, lancer
   `makemigrations` une dernière fois pour capturer l'écart de `help_text`
   sur `parent_show` (voir Points de vigilance) — sinon la migration part
   déjà désynchronisée du modèle. **Ajouter aussi des tests sur les filtres
   `?show`/`?material`/`?technician`** (voir Points de vigilance) et trancher
   le sort de `.env.example`.
3. Commiter le frontend sur `feature/frontend-portage`.
4. Invoquer `code-reviewer` avant chaque merge, vérifier la CI, puis
   confirmer le déploiement Railway (`migrate` tourne dans la commande
   `web:` — les migrations `0013`→`0016` passeront à ce moment-là, `0014`
   inclut un `RunPython` de remappage : à surveiller sur MySQL).

Ensuite seulement : créer les identifiants OAuth dans Google Cloud pour
débloquer le login (étape 7), qui n'a jamais été testé en vrai navigateur.

## État technique (vérifié dans le repo, 2026-07-31)

- Branche courante : `feature/venue-conflict` (HEAD = `908820f`, à jour avec
  `origin/feature/venue-conflict`), **1 commit d'avance sur `main`** —
  inchangé depuis le dernier check, le retard est entièrement dans le
  working tree, pas dans l'historique.
- `main` local == `origin/main` == `e9cd546` (PR #7, module transport), daté
  du 2026-07-24. C'est ce qui est sur Railway.
- **Working tree sale — 6 171 insertions / 806 suppressions sur 22 fichiers
  suivis**, plus les chemins non suivis ci-dessous (était 2 790/698 le
  2026-07-30 — plus que doublé) :
  - Backend modifié : `models.py`, `conflicts.py`, `serializers.py`,
    `views.py`, `signals.py`, `duplication.py`, `admin.py`,
    `transport_coherence.py`, `urls.py`, `tests.py`.
  - **Migrations non suivies : 4** — `0013_remove_department.py`,
    `0014_material_category.py`, `0015_transport_technicians.py`,
    `0016_show_phases.py`. Deux de plus que le dernier check ; le risque
    d'en perdre une sur un `git checkout`/`reset` malheureux augmente d'autant.
  - Frontend non suivi : `src/api/`, `src/router/`, `src/composables/`,
    `src/views/` (19 vues), `AppShell.vue`, `AssignerMaterielModal.vue`,
    `AssignerTechnicienModal.vue`, `ParcoursDayPicker.vue`, `frontend/design/`.
  - Frontend modifié : `App.vue`, `main.js`, `style.css`, `index.html`,
    `package.json`, `package-lock.json`.
  - Docs modifiées : `CLAUDE.md`, `recapitulatif_projet.md`, `schema.md`,
    `architecture.md`, ce fichier.
  - Supprimé : `.env.example` (toujours non commité).
- Modèles : **13 classes** — `User`, `Settings`, `Project`, `Venue`,
  `MaterialCategory`, `Material`, `Show`, `ShowMaterial`, `Technician`,
  `ShowTechnician`, `Transport`, `TransportTechnician`, `TransportMaterial`.
  `Department` retiré. 16 fichiers de migration (`0001`→`0016`) présents sur
  disque (non commités à partir de `0013`).
- Tests : **266, tous au vert** — vérifié en exécutant la suite dans cet
  environnement (SQLite, `--parallel 4`, ~40 s, via un venv reconstruit à la
  volée puisque le `venv/` du repo n'est pas utilisable depuis ce bac à
  sable). Était 196 au dernier check → **+70**.
- `flake8` (docstrings D100/D101/D103) : **propre**.
- `makemigrations --check --dry-run` : **🔴 signale un changement en
  attente** — `0017_alter_show_parent_show` (`AlterField` sur
  `Show.parent_show`). Écart cosmétique : le `help_text` du champ dans
  `models.py` a été reformulé après la génération de `0016_show_phases`
  (mention du matériel/techniciens retirée du texte, cohérent avec l'ajout
  de `inherits_resources` le même jour), mais la migration n'a pas été
  régénérée pour suivre. Aucun impact fonctionnel ou de données — `help_text`
  n'affecte que l'admin Django — mais c'est un vrai écart modèle/migration à
  corriger avant de commiter `0016` (voir Prochaine action concrète).
  Nouveau depuis le dernier check.
- Frontend : 19 vues (était 17), toutes avec de vrais appels API. Nouveaux
  composants depuis le dernier check : `ParcoursDayPicker.vue` (sélecteur de
  jour partagé par les deux écrans Parcours) et le composable
  `useParcours.js` retravaillé pour l'affichage jour-par-jour. `HelloWorld.vue`
  traîne toujours, plus référencé nulle part.
- `git fetch` échoue toujours depuis ce bac à sable (host key verification
  failed) — revérifié aujourd'hui, même erreur. Les égalités de SHA sont
  confirmées en local, pas par un fetch frais ; l'état des PR sur GitHub
  n'est pas vérifiable d'ici.
- `backend/.env` : `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` et
  `GOOGLE_MAPS_API_KEY` sont **vides**, revérifié aujourd'hui (les `DB_*`
  vides sont normaux en local → fallback SQLite).

## Points de vigilance

- **🔴 Sept jours de travail non commité, dont 4 migrations** — le risque
  continue d'augmenter check après check (2 migrations le 2026-07-30, 4
  aujourd'hui). Un `git checkout`/`reset` malheureux effacerait
  `0013`→`0016`, donc la seule trace du remappage `category` →
  `MaterialCategory`, des techniciens multiples par transport et des blocs
  rattachés. À commiter en priorité absolue.
- **🔴 Nouveau : modèle en avance sur sa propre migration** —
  `makemigrations --check` détecte un `AlterField` non généré sur
  `Show.parent_show` (`help_text` reformulé après coup). Sans gravité en soi
  (pas de données, pas de logique), mais si `0016_show_phases.py` est commité
  tel quel, le repo entre en historique avec un écart modèle/migration dès
  le premier commit — à corriger (`makemigrations`) avant l'étape 2 du plan
  ci-dessus, pas après.
- **🔴 Écart prod ↔ local, qui se creuse** — Railway tourne toujours sur
  `e9cd546` (2026-07-24) : ni le conflit de lieu, ni le retrait de
  `Department`, ni les catégories éditables, ni la fenêtre de transport, ni
  les techniciens multiples par transport, ni les blocs rattachés, ni le
  frontend. Tout écran ouvert en prod ne reflète plus rien du travail des
  sept derniers jours.
- **Filtres `?show`/`?material`/`?technician` toujours sans test** — présents
  dans `views.py` (`ShowMaterialViewSet`, `ShowTechnicianViewSet`,
  `TransportViewSet`) et utilisés par le frontend, mais aucun test ne les
  couvre. Régression silencieuse possible — le frontend renverrait alors
  toutes les assignations, tous projets confondus. À couvrir avant le merge.
- **Désync doc/code — `recapitulatif_projet.md` a progressé mais reste en
  retard sur `CLAUDE.md`** : il couvre maintenant jusqu'aux blocs rattachés
  et à l'autonomie des répétitions (2026-07-31), ce qui referme une partie
  de l'écart signalé le 2026-07-30. Il ne décrit en revanche toujours pas les
  cinq notes suivantes de `CLAUDE.md`, toutes datées « 2026-07-31, suite » :
  l'agrandissement des barres et l'info-bulle du Parcours, les transports
  confirmés affichés sur le Parcours Matériel (nouveau champ `transports` sur
  `get_material_journey`), l'affichage jour-par-jour des deux écrans Parcours
  (refonte de `useParcours.js`), la compaction des listes de matériel, et
  l'ajout de l'événement dans la chronologie des blocs d'une fiche spectacle.
  `architecture.md` et `schema.md` restent à jour côté backend (`parent_show`,
  `transport_technicians` vérifiés aujourd'hui). Non modifié automatiquement
  (cf. consignes) — à resynchroniser en session interactive.
- **`.env.example` supprimé (non commité)** — le contenu semble avoir migré
  dans `backend/.env` (qui porte encore les commentaires du gabarit). Si la
  suppression est volontaire, le commit doit l'acter ; sinon, restaurer un
  gabarit à la racine pour un nouveau clone.
- **Migration `0014` avec `RunPython` non encore jouée en prod** — première
  migration de données du projet, sur MySQL managé cette fois. À surveiller
  au déploiement.
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

- Listes de matériel par technicien (sortie terrain).
- Rôles admin/viewer une fois OAuth en place.
- Budget de location (explicitement reporté après V1).
- Géocodage automatique d'adresse pour `venues.latitude`/`longitude`
  (actuellement saisie manuelle uniquement).
