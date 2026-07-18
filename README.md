# RégiStock

*(nom de code technique du repo/dossier : `gear-management`)*

Application web interne pour gérer l'inventaire de matériel de production
(son, éclairage, rigging, mobilier), l'assigner aux spectacles/répétitions,
assigner les techniciens, et détecter automatiquement les conflits
d'utilisation (matériel comme techniciens).

Documentation fonctionnelle et technique complète :

- [`recapitulatif_projet.md`](./recapitulatif_projet.md) — objectif, scope V1, stack
- [`architecture.md`](./architecture.md) — logique de conflits, workflows
- [`schema.md`](./schema.md) — structure complète de la base de données
- [`agents_tools.md`](./agents_tools.md) — outils/agents par phase de dev
- [`security.md`](./security.md) — gestion des secrets, bonnes pratiques

## Stack

| Couche | Techno |
|---|---|
| Base de données | MySQL 8.0 managé (Railway) — SQLite en local par défaut |
| Backend / API | Django 5.2 + Django REST Framework |
| Frontend | Vue 3 (Vite) |
| Authentification | Google OAuth 2.0 (à venir — admin Django en mot de passe pour l'instant) |
| Hébergement | Railway (Ionos écarté : pas de runtime Node/WSGI persistant sur l'hébergement web standard) |

## Structure du repo

```
backend/     API Django (config = projet, inventory = app de base)
frontend/    Interface Vue 3 (Vite)
*.md         Documentation fonctionnelle/technique (racine)
```

## Démarrer en local

### Backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Sans configurer `DB_ENGINE`/`DB_HOST` dans `.env`, le projet retombe
automatiquement sur SQLite — pratique pour développer sans accès à MySQL.
Pour se connecter à MySQL (Railway ou local), remplir les variables `DB_*`
dans `.env` (voir `security.md`).

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Le serveur de dev Vite tourne par défaut sur `http://localhost:5173` — déjà
autorisé dans `CORS_ALLOWED_ORIGINS` côté Django.

## Déploiement

Backend déployé sur Railway : `https://gear-management-production.up.railway.app`.
Piège à retenir : Railway ne supporte pas la phase `release:` du `Procfile`
(style Heroku) — `collectstatic` et `migrate` tournent dans la commande
`web:` elle-même (voir `backend/Procfile`).

## État actuel

Backend déployé et fonctionnel sur Railway (MySQL managé connecté, admin
Django accessible). Frontend Vue scaffoldé mais vide. Pas encore de modèles
métier (les 8 tables de `schema.md`) ni d'endpoints — prochaine étape (voir
`recapitulatif_projet.md`).
