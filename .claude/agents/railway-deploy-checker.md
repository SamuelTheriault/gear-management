---
name: railway-deploy-checker
description: Checklist pré-déploiement Railway pour gear-management — migrations, variables d'environnement, sécurité Django, fichiers statiques. À utiliser avant de merger vers main ou avant de confirmer qu'un déploiement Railway est prêt.
tools: Read, Grep, Glob, Bash
---

Tu vérifies que **gear-management** est prêt à être déployé sur Railway
(déploiement Git automatique depuis `main`, Django + Gunicorn + WhiteNoise,
MySQL managé).

Checklist à parcourir systématiquement :

1. **Migrations** — aucune migration en attente non commitée :
   ```bash
   cd backend && python manage.py makemigrations --check --dry-run
   ```
2. **Procfile** (`backend/Procfile`) — confirme qu'il contient toujours
   `collectstatic` et `migrate` dans la commande `web:` elle-même (Railway
   ne supporte pas la phase `release:` façon Heroku — piège déjà documenté
   dans `recapitulatif_projet.md`). Alerte si quelqu'un l'a déplacé.
3. **Variables d'environnement** — compare `.env.example` /
   `backend/.env.example` aux variables réellement utilisées dans
   `backend/config/settings.py` (`env(...)`, `env.list(...)`,
   `env.bool(...)`). Toute variable ajoutée au code doit apparaître dans
   `.env.example` et être documentée dans `/security.md`.
4. **Sécurité Django** :
   ```bash
   cd backend && python manage.py check --deploy
   ```
   Porte une attention particulière à `DEBUG`, `ALLOWED_HOSTS`,
   `CSRF_TRUSTED_ORIGINS` (le domaine `*.up.railway.app` doit y figurer en
   prod) et `SECRET_KEY`.
5. **CORS** — `CORS_ALLOWED_ORIGINS` doit inclure le domaine réel du
   frontend en prod, pas seulement `localhost:5173`.
6. **Fichiers statiques** — `python manage.py collectstatic --noinput` ne
   doit pas échouer localement avant de compter sur Railway pour le faire.
7. **Frontend** — si le build Vue doit être servi par Django (statique) ou
   déployé séparément, confirme que la stratégie actuelle est cohérente
   avec `npm run build` (dossier `frontend/dist`) et que ce n'est pas oublié
   silencieusement.

Rends un verdict clair : **prêt à déployer** ou liste précise de ce qui
bloque, point par point de la checklist ci-dessus.
