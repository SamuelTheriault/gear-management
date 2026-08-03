# Déploiement Railway — "option B" (2026-08-xx, voir CLAUDE.md et
# suivi_projet.md) : un seul service sert à la fois l'API Django et le
# build Vue, plutôt que deux services séparés ou un hébergeur statique
# distinct. Build multi-étapes : le frontend (Node) puis le backend
# (Python), qui récupère le build Vue déjà prêt.
#
# Root Directory du service Railway doit être la racine du repo (`/`) pour
# que ce Dockerfile ait accès à la fois à backend/ et frontend/ — Railway
# détecte automatiquement ce fichier à la racine du répertoire source (voir
# https://docs.railway.com/builds/dockerfiles).

# --- Étape 1 : build du frontend Vue ---
# `base: '/static/'` en mode build (voir frontend/vite.config.js) — les
# assets construits doivent correspondre au préfixe STATIC_URL de Django.
FROM node:22-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- Étape 2 : backend Django, qui sert aussi le build ci-dessus ---
FROM python:3.12-slim AS backend
WORKDIR /app/backend

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./

# STATIC_ROOT/STATICFILES_DIRS (config/settings.py) attendent le build Vue
# sous /app/frontend/dist — BASE_DIR.parent au sens de settings.py, puisque
# BASE_DIR pointe vers /app/backend dans cette image.
COPY --from=frontend-build /app/frontend/dist /app/frontend/dist

EXPOSE 8080

# collectstatic et migrate tournent au démarrage du conteneur, pas pendant
# le build : Railway ne supporte pas de phase `release:` séparée (piège
# déjà documenté dans CLAUDE.md), et `migrate` a de toute façon besoin d'un
# accès réseau à la base de données, indisponible pendant le build.
CMD python manage.py collectstatic --noinput && \
    python manage.py migrate --noinput && \
    gunicorn config.wsgi --bind 0.0.0.0:$PORT
