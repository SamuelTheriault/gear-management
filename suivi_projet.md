# Suivi de projet — gear-management

Tableau de bord manuel. À mettre à jour à chaque étape franchie ou décision
prise. Complète `recapitulatif_projet.md` (contenu fonctionnel) sans le
dupliquer — ce fichier ne suit que **l'avancement**, pas le scope.

Dernière mise à jour : 2026-07-18 (entreposage, transports, réglages et calcul
de trajet ajoutés — voir note en bas)

## Statut global

**Phase actuelle : backend fonctionnellement riche, tout est prêt localement
mais RIEN n'est encore commité/déployé (voir "À faire immédiatement" ci-dessous).**
Le frontend n'est toujours pas branché — prochaine grosse étape une fois le
backend poussé et mergé.

## Ordre à respecter (ne pas brûler d'étape)

| # | Étape | Statut | Date |
|---|---|---|---|
| 1 | Base de données confirmée (MySQL 8.0) | ✅ Fait | — |
| 2 | Stack backend/frontend confirmée (Django + Vue) | ✅ Fait | 2026-07-16 |
| 3 | Structure de repo (scaffold + Git init) | ✅ Fait | 2026-07-16 |
| 4 | Hébergement confirmé (Railway) | ✅ Fait | 2026-07-17 |
| 5 | Déploiement Railway fonctionnel (Django + Gunicorn + WhiteNoise) | ✅ Fait | 2026-07-18 |
| 6 | Superutilisateur Django créé | ✅ Fait | 2026-07-18 |
| 7 | Projet Google Cloud OAuth (config + intégration Django) | ✅ Fait (code prêt, non commité) | 2026-07-18 |
| 8 | Modèles Django (8 tables initiales) + migrations | ✅ Fait | 2026-07-17 |
| 9 | API DRF + logique de conflits | ✅ Fait, puis étendue (entreposage, transports) | 2026-07-17/18 |
| 9bis | Entreposage (`Venue.is_storage`), transports, réglages (`Settings`), calcul de trajet (Google Routes API) | ✅ Fait (code prêt, non commité) | 2026-07-18 |
| — | **Commit + PR + merge de tout ce qui précède** | ⬜ À faire immédiatement | — |
| 10 | Frontend connecté à l'API | ⬜ À faire — bloqué par le commit/merge ci-dessus | — |

**Pourquoi cet ordre :** le frontend a besoin d'un flux d'auth stable avant
d'être branché (sinon on recâble deux fois). Mais avant même ça, tout le
travail backend (OAuth + entreposage/transports/réglages/maps) doit être
commité, revu (`code-reviewer`) et mergé — sinon rien de tout ça n'existe sur
Railway, et impossible de tester l'intégration Google Routes en conditions
réelles (le bac à sable de dev n'a pas accès réseau à `routes.googleapis.com`).

## Prochaine action concrète

→ **Commit/push/PR** de tout le travail accumulé (OAuth + entreposage +
transports + réglages + maps), revue via `code-reviewer`, puis Samuel merge
quand satisfait. Une fois déployé sur Railway : (a) tester l'estimation
automatique de trajet en conditions réelles (clé `GOOGLE_MAPS_API_KEY` déjà
configurée par Samuel sur Railway et en local), (b) démarrer l'étape 10 —
brancher le frontend Vue, en commençant par le bouton de login Google et la
lecture de `/api/auth/user/` (flux OAuth complet pas encore testé dans un
vrai navigateur, seulement par revue de code + tests unitaires).

## État technique (vérifié dans le repo, 2026-07-18)

- Backend : 10 modèles Django dans `inventory/models.py` (8 initiaux +
  `Transport` + `Settings`, singleton), synchronisés avec `schema.md`.
- Tests : 48 tests (`inventory/tests.py`, `test_oauth_provisioning.py`,
  `test_settings_and_maps.py`) — conflits (matériel/technicien/transport),
  exemption d'entreposage, provisioning OAuth, defaults dynamiques via
  `Settings`, service `maps.py` mocké.
- API : `/api/<ressource>/` pour les 10 modèles + `/api/settings/`
  (singleton) + `/api/shows/{id}/conflicts/`.
- Frontend : scaffold Vue par défaut (`App.vue`, `components/`) — pas encore
  connecté à l'API.
- CI : job `flake8` actif (docstrings obligatoires backend), propre sur tout
  le nouveau code. Pas de blocage de merge GitHub configuré (protection de
  branche à activer manuellement, accès admin requis — hors portée de Claude
  Code).
- Déploiement : `gear-management-production.up.railway.app` — **ne reflète
  pas encore le travail décrit ici**, tant que le commit/PR/merge n'est pas fait.

## Points de vigilance

- Railway ne supporte pas la phase `release:` — `migrate`/`collectstatic` doivent rester dans la commande `web:`. Déjà corrigé une fois (2026-07-17), à surveiller si le `Procfile` est retouché.
- Ne pas confondre `inventory.User` (modèle applicatif) et le superutilisateur Django (`django.contrib.auth`) — deux choses distinctes, voir note dans `recapitulatif_projet.md`.
- Protection de branche `main` non activée — repose sur la discipline du gabarit de PR pour l'instant.
- `requirements.txt` a eu un bug corrigé (2026-07-18) : `requests`/`PyJWT`/`cryptography` manquants, requis par django-allauth dès le démarrage de Django — aurait fait planter tout déploiement Railway. Vérifier que ça déploie proprement au prochain push.
- L'estimation automatique de trajet (Google Routes API) ne peut pas être testée en conditions réelles depuis un environnement de dev sans accès réseau à `routes.googleapis.com` — se dégrade silencieusement sur la valeur par défaut (`Settings.default_transport_duration_minutes`) dans ce cas, donc pas d'erreur visible, juste un calcul manquant. À valider une fois déployé sur Railway.

## Backlog (après étape 10)

- Listes de matériel par technicien (sortie terrain).
- Rôles admin/viewer une fois OAuth en place.
- Budget de location (explicitement reporté après V1).
- Géocodage automatique d'adresse pour `venues.latitude`/`longitude` (actuellement saisie manuelle uniquement) — évoqué mais pas retenu pour cette itération.
