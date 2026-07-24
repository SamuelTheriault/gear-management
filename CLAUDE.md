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
