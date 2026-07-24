# Suivi de projet — gear-management

Tableau de bord manuel. À mettre à jour à chaque étape franchie ou décision
prise. Complète `recapitulatif_projet.md` (contenu fonctionnel) sans le
dupliquer — ce fichier ne suit que **l'avancement**, pas le scope.

Dernière mise à jour : 2026-07-24 (vérification automatisée — ⚠️ travail
important non commité détecté, voir "Points de vigilance")

## Statut global

**PR #6 (`feature/venue-code`) mergée et déployée sur Railway. Mais le
répertoire de travail est actuellement sur cette branche (déjà mergée) avec
~950 lignes non commitées d'un nouveau module (cohérence/génération auto de
transports), testées et fonctionnelles mais nulle part sauvegardées (pas de
commit, pas de push). Le frontend reste non branché.**

## Ordre à respecter (ne pas brûler d'étape)

| # | Étape | Statut | Date |
|---|---|---|---|
| 1 | Base de données confirmée (MySQL 8.0) | ✅ Fait | — |
| 2 | Stack backend/frontend confirmée (Django + Vue) | ✅ Fait | 2026-07-16 |
| 3 | Structure de repo (scaffold + Git init) | ✅ Fait | 2026-07-16 |
| 4 | Hébergement confirmé (Railway) | ✅ Fait | 2026-07-17 |
| 5 | Déploiement Railway fonctionnel (Django + Gunicorn + WhiteNoise) | ✅ Fait | 2026-07-18 |
| 6 | Superutilisateur Django créé | ✅ Fait | 2026-07-18 |
| 7 | Projet Google Cloud OAuth (config + intégration Django) | ✅ Fait, mergé (PR #2) | 2026-07-18 |
| 8 | Modèles Django (8 tables initiales) + migrations | ✅ Fait | 2026-07-17 |
| 9 | API DRF + logique de conflits | ✅ Fait | 2026-07-17 |
| 9bis | Entreposage, transports, réglages, calcul de trajet (Google Routes API) | ✅ Fait, mergé (PR #2) | 2026-07-18 |
| 9ter | Couleur par département, quantité de matériel, `is_active`, isolation par projet (`Project`) + duplication | ✅ Fait, mergé (PR #3, #4, #5) | 2026-07-19 |
| 9quater | `Venue.code` (identification courte) | ✅ Fait, mergé (PR #6), déployé sur Railway | 2026-07-24 |
| 9quinquies | Module transport : `TransportMaterial`, `Transport.status`, cohérence des emplacements, génération auto de propositions | ⚠️ Codé + testé (136 tests) mais **non commité, non poussé** | 2026-07-24 |
| 10 | Frontend connecté à l'API | ⬜ À faire — après la mise en sécurité de 9quinquies | — |

## Prochaine action concrète

→ **Mettre en sécurité le travail non commité avant toute autre chose.** Le
répertoire local est sur `feature/venue-code` — une branche déjà mergée dans
`main` (PR #6). Committer directement dessus recréerait un diff pollué par du
contenu déjà mergé. Recommandation : partir d'un `main` à jour
(`git fetch && git checkout main && git pull`), créer une nouvelle branche
(ex. `feature/transport-coherence`), puis rapatrier les fichiers modifiés/
non suivis du module transport dessus avant de committer et ouvrir une PR.
Une fois ce travail en sécurité : démarrer l'étape 10 (frontend), en
commençant par le login Google (`/api/auth/user/`, jamais testé en vrai
navigateur) puis l'UI du module transport (indicateur orange « à approuver »).

## État technique (vérifié dans le repo, 2026-07-24)

- Branche courante : `feature/venue-code` (à jour avec
  `origin/feature/venue-code`, commit `1663098`). Cette branche est déjà
  mergée dans `main` sur GitHub (PR #6, commit de merge `72062f1`) et
  **déployée sur Railway** (`get-status` : service `gear-management`,
  déploiement `SUCCESS`, 2026-07-24 04:40 UTC).
- `git fetch` a échoué depuis cet environnement (vérification d'hôte SSH
  refusée — limite de ce bac à sable, pas un problème du dépôt). L'état de
  `origin/main` a donc été confirmé indirectement via les métadonnées de
  déploiement Railway plutôt que par `git log`.
- Working tree **non propre** : 11 fichiers trackés modifiés (948
  insertions / 71 suppressions) + 5 fichiers non suivis — voir détail
  ci-dessous. Rien de tout ça n'est commité.
- Nouveau modèle `TransportMaterial` (table de liaison matériel ↔
  transport, quantité), `Transport.status` (`confirmed`/`to_approve`),
  `Transport.scheduled_datetime` devenu nullable. Migrations
  `0011_transportmaterial.py` et `0012_transport_status_scheduled_nullable.py`
  présentes mais non appliquées à un commit.
- Nouveaux fichiers non suivis : `transport_coherence.py` (293 lignes —
  timeline de position par matériel, rapport non bloquant :
  `materiel_non_livre`, `origine_incoherente`, `origine_inconnue`),
  `transport_autogen.py` (291 lignes — génère des propositions `to_approve`
  automatiquement), `regenerate_signals.py` (85 lignes — signaux Django qui
  déclenchent la regénération).
- Nouvelles routes (déjà dans `views.py`, non commitées) :
  `GET /api/shows/{id}/transport-coherence/` et
  `GET /api/projects/{id}/transport-coherence/`.
- Docs déjà mises à jour **localement mais non commitées** en cohérence
  avec ce code : `CLAUDE.md`, `architecture.md` (section 4quinquies),
  `schema.md` (sections 9 et 12), `recapitulatif_projet.md`.
- Tests : **136 tests, tous au vert** (`inventory/tests.py` : 113,
  `test_settings_and_maps.py` : 19, `test_oauth_provisioning.py` : 4) —
  vérifié en exécutant la suite dans cet environnement (SQLite,
  dépendances installées à la volée). `flake8` (config `backend/.flake8`)
  propre, aucune docstring manquante.
- Frontend : toujours le scaffold Vue par défaut (`App.vue` à 7 lignes,
  `components/HelloWorld.vue`) — aucun appel API, aucune logique d'auth.
  Inchangé.

## Points de vigilance

- **⚠️ Risque de perte de travail.** Le module transport
  (cohérence + génération auto), ~950 lignes, testé et fonctionnel, n'existe
  que dans ce répertoire de travail local — aucun commit, aucun push, aucune
  PR. À committer sur une branche propre dès que possible (voir "Prochaine
  action concrète").
- **Branche de départ inadaptée** : `feature/venue-code` est déjà mergée —
  ne pas committer le nouveau module dessus tel quel, repartir de `main`.
- `git fetch` impossible depuis ce bac à sable (host key verification
  failed) — la confirmation que `main` est bien à jour avec `origin/main`
  après le merge de PR #6 repose sur les métadonnées Railway, pas sur une
  vérification git directe. À reconfirmer avec un `git fetch` normal.
- Railway ne supporte pas la phase `release:` — `migrate`/`collectstatic`
  doivent rester dans la commande `web:`. À surveiller si le `Procfile` est
  retouché (pas touché par le module transport).
- Ne pas confondre `inventory.User` (modèle applicatif) et le
  superutilisateur Django (`django.contrib.auth`) — deux choses distinctes,
  voir note dans `recapitulatif_projet.md`.
- Protection de branche `main` non activée sur GitHub — repose sur la
  discipline du gabarit de PR pour l'instant.
- L'estimation automatique de trajet (Google Routes API) ne peut pas être
  testée en conditions réelles depuis un environnement de dev sans accès
  réseau à `routes.googleapis.com` — se dégrade silencieusement sur la
  valeur par défaut, donc pas d'erreur visible, juste un calcul manquant.
- Branches de feature déjà mergées (`feature/department-colors`,
  `feature/material-quantity`, `feature/production-scoping`,
  `feature/storage-transports-settings-maps`, et bientôt `feature/venue-code`
  une fois le module transport déplacé) encore présentes en local/remote —
  nettoyage optionnel.

## Backlog (après étape 10)

- Listes de matériel par technicien (sortie terrain).
- Rôles admin/viewer une fois OAuth en place.
- Budget de location (explicitement reporté après V1).
- Géocodage automatique d'adresse pour `venues.latitude`/`longitude`
  (actuellement saisie manuelle uniquement) — évoqué mais pas retenu pour
  cette itération.
