"""
Django settings for config project — Gestion de matériel.

Voir /schema.md, /architecture.md et /security.md à la racine du repo
pour le contexte fonctionnel et les décisions de sécurité.
"""

from pathlib import Path
import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env()
# Le fichier .env attendu ici est backend/.env (jamais commité — voir /security.md)
environ.Env.read_env(BASE_DIR / '.env')

# SECURITY WARNING: garder la clé secrète hors du code source en production.
SECRET_KEY = env('DJANGO_SECRET_KEY', default='') or 'django-insecure-dev-only-change-me'

# SECURITY WARNING: ne jamais laisser DEBUG=True en production.
# Défaut à False (et non True) : depuis l'ajout de l'auth Google OAuth,
# SESSION_COOKIE_SECURE/CSRF_COOKIE_SECURE dépendent de DEBUG (voir plus bas) —
# une variable DJANGO_DEBUG oubliée sur Railway ne doit jamais faire retomber
# silencieusement la sécurité des cookies de session. En local, DJANGO_DEBUG=True
# est déjà explicitement défini dans .env (voir .env.example).
DEBUG = env.bool('DJANGO_DEBUG', default=False)

ALLOWED_HOSTS = env.list('DJANGO_ALLOWED_HOSTS', default=['localhost', '127.0.0.1'])

# Railway fournit un domaine *.up.railway.app — Django 4+ exige aussi ce domaine
# dans CSRF_TRUSTED_ORIGINS pour accepter les requêtes POST (ex. admin) en HTTPS.
CSRF_TRUSTED_ORIGINS = env.list('DJANGO_CSRF_TRUSTED_ORIGINS', default=[])

# Railway termine le TLS à sa frontière et transmet les requêtes en HTTP en
# clair au conteneur, avec l'en-tête `X-Forwarded-Proto` pour indiquer le
# protocole d'origine — sans cette ligne, Django considère TOUTE requête
# comme non sécurisée (`request.is_secure()` renvoie toujours `False`).
# Découvert le 2026-08-03 : ça cassait le callback OAuth Google, qui se
# construit avec `request.build_absolute_uri()` (django-allauth) — l'URI de
# redirection envoyée à Google était donc en `http://` au lieu de `https://`,
# et ne correspondait jamais à l'URI enregistrée dans Google Cloud Console
# (erreur `redirect_uri_mismatch`). Sûr uniquement parce que Railway (comme
# Heroku) est le seul point d'entrée réseau du conteneur — ne jamais ajouter
# ce réglage sur un serveur exposé directement, où l'en-tête pourrait être
# falsifié par n'importe quel client.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sites',
    'rest_framework',
    'corsheaders',
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.google',
    'dj_rest_auth',
    'inventory',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    # Requis par django-allauth (versions récentes) — doit suivre AuthenticationMiddleware.
    'allauth.account.middleware.AccountMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# django-allauth s'appuie sur django.contrib.sites pour associer les
# fournisseurs sociaux (Google) à un "site" — un seul site ici (usage interne).
SITE_ID = 1

# Ajoute le backend allauth SANS retirer ModelBackend : le superutilisateur
# Django existant (/admin/) continue de s'authentifier par mot de passe.
AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# Database
# MySQL 8.0 managé (Railway) en production — voir /schema.md pour le détail des tables.
# Driver PyMySQL choisi plutôt que mysqlclient : pur Python, pas de dépendance
# système à compiler, plus simple à installer en local comme sur Railway.

DATABASES = {
    'default': {
        'ENGINE': env('DB_ENGINE', default='') or 'django.db.backends.sqlite3',
        'NAME': env('DB_NAME', default='') or (BASE_DIR / 'db.sqlite3'),
        'HOST': env('DB_HOST', default=''),
        'PORT': env('DB_PORT', default=''),
        'USER': env('DB_USER', default=''),
        'PASSWORD': env('DB_PASSWORD', default=''),
    }
}


# Password validation

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


# Internationalization

LANGUAGE_CODE = 'fr-ca'
TIME_ZONE = 'America/Montreal'
USE_I18N = True
USE_TZ = True


# Static files
# Servis directement par WhiteNoise via Gunicorn — pas de Nginx séparé sur Railway.

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

STORAGES = {
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
    },
}

# --- Frontend Vue servi par ce même service (déploiement "option B",
# 2026-08-xx — voir CLAUDE.md et Dockerfile à la racine du repo) ---
# `npm run build` (frontend/, base='/static/' — voir vite.config.js) produit
# frontend/dist/ : index.html + assets/ hashés. Seul assets/ passe par le
# pipeline STATICFILES_DIRS/collectstatic/WhiteNoise (sous le préfixe
# 'assets', donc servi à /static/assets/... — exactement ce que le HTML
# construit référence). index.html est servi tel quel par une vue dédiée
# (inventory.frontend_views.spa_index), PAS par collectstatic : le faire
# passer par ManifestStaticFilesStorage le renommerait avec un hash, cassant
# l'URL stable dont ce catch-all a besoin.
FRONTEND_DIST_DIR = BASE_DIR.parent / 'frontend' / 'dist'

STATICFILES_DIRS = []
_frontend_assets_dir = FRONTEND_DIST_DIR / 'assets'
if _frontend_assets_dir.is_dir():
    # Répertoire absent tant que `npm run build` n'a pas tourné (dev local
    # sans frontend construit, ou avant la première étape du Dockerfile) —
    # STATICFILES_DIRS lève ImproperlyConfigured sur un chemin inexistant,
    # d'où la garde plutôt qu'une déclaration inconditionnelle.
    STATICFILES_DIRS.append(('assets', _frontend_assets_dir))

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# CORS — le frontend Vue (dev server Vite) doit pouvoir appeler l'API.
CORS_ALLOWED_ORIGINS = env.list(
    'CORS_ALLOWED_ORIGINS',
    default=['http://localhost:5173', 'http://127.0.0.1:5173'],
)

# Le flux OAuth classique (session cookie Django) exige que le navigateur
# renvoie le cookie de session sur les appels API du frontend Vue — voir
# security.md section "Authentification (Google OAuth)".
CORS_ALLOW_CREDENTIALS = True

# Cookies de session/CSRF en HTTPS obligatoire hors DEBUG (voir security.md,
# section 4 "Transport") — jamais transmis en clair une fois en production.
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG

# Django REST Framework — config de base, à affiner avec l'auth Google OAuth.
REST_FRAMEWORK = {
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    # Limites de débit — voir inventory/public_views.py. Seule la portée
    # 'public-report' est définie : le reste de l'API exige une session, où
    # le contrôle d'accès par projet fait déjà le travail. Le taux est
    # généreux à dessein — toute une équipe derrière le wifi d'une salle
    # partage une seule IP publique, et une limite serrée les bloquerait
    # tous parce qu'un technicien a rechargé trois fois.
    'DEFAULT_THROTTLE_RATES': {
        'public-report': env('PUBLIC_REPORT_THROTTLE', default='120/hour'),
    },
}

# Origine publique utilisée pour construire les URL encodées dans les codes
# QR imprimés (voir inventory/report_shares.build_share_url). À renseigner en
# production : sans elle, l'URL est déduite de la requête courante, ce qui
# suffit tant qu'un PDF est toujours produit dans un cycle requête/réponse —
# mais donnerait « http://testserver/... » depuis une commande de gestion ou
# une tâche planifiée. Un QR faux imprimé en quarante exemplaires ne se
# rattrape pas.
PUBLIC_BASE_URL = env('PUBLIC_BASE_URL', default='')

# --- Google OAuth 2.0 (django-allauth + dj-rest-auth) ---
# Flux "classique" côté serveur : le frontend redirige le navigateur vers
# /accounts/google/login/, Google redirige vers le callback allauth
# (URI exactes déjà enregistrées dans Google Cloud — ne pas modifier les
# chemins ci-dessous sans mettre à jour la config Google en parallèle),
# qui crée une session Django. dj-rest-auth expose ensuite /api/auth/user/
# et /api/auth/logout/ consommés par le frontend via cookies de session.

# URL du frontend Vue vers laquelle rediriger une fois la session Django
# établie (login) ou terminée (logout). Défaut raisonnable pour le dev local
# avec Vite — voir .env.example.
FRONTEND_URL = env('FRONTEND_URL', default='http://127.0.0.1:5173')
LOGIN_REDIRECT_URL = FRONTEND_URL
ACCOUNT_LOGOUT_REDIRECT_URL = FRONTEND_URL

# Config du provider Google lue depuis l'environnement — pas de SocialApp
# créé manuellement en base (méthode supportée nativement par allauth via
# ce dict de settings depuis la 0.51+, plus simple à synchroniser avec
# Railway que des lignes en base de données).
SOCIALACCOUNT_PROVIDERS = {
    'google': {
        'APP': {
            'client_id': env('GOOGLE_CLIENT_ID', default=''),
            'secret': env('GOOGLE_CLIENT_SECRET', default=''),
            'key': '',
        },
        'SCOPE': ['profile', 'email'],
        'AUTH_PARAMS': {'access_type': 'online'},
    },
}

# Email déjà vérifié par Google — inutile de refaire une vérification par courriel.
ACCOUNT_EMAIL_VERIFICATION = 'none'
# Identifiant de connexion = email (pas de mot de passe local pour ce flux).
ACCOUNT_LOGIN_METHODS = {'email'}
ACCOUNT_SIGNUP_FIELDS = ['email*']
# Provisioning auto du compte django.contrib.auth.User au premier login Google
# réussi — le provisioning de l'inventory.User applicatif se fait ensuite via
# le signal `user_logged_in` (voir inventory/signals.py).
SOCIALACCOUNT_AUTO_SIGNUP = True
# Saute la page de confirmation intermédiaire d'allauth : un clic sur le lien
# de login redirige directement vers Google (flux "classique" voulu ici).
SOCIALACCOUNT_LOGIN_ON_GET = True

# dj-rest-auth : uniquement la session Django (cookie), pas de token DRF
# (`rest_framework.authtoken`) ni de JWT — cohérent avec le flux "classique"
# décrit plus haut (pas de flux token / Google Identity Services côté client).
REST_AUTH = {
    'SESSION_LOGIN': True,
    'USE_JWT': False,
    'TOKEN_MODEL': None,
    # Expose `is_staff_global` (accès de dépannage plateforme, voir
    # inventory/permissions.py) sur GET /api/auth/user/ — le frontend en a
    # besoin pour savoir si le compte connecté peut gérer les accès d'un
    # projet même sans y être `owner` (2026-08-02).
    'USER_DETAILS_SERIALIZER': 'inventory.serializers.CurrentUserDetailsSerializer',
}

# --- Google Routes API (calcul du temps de trajet, inventory/maps.py) ---
# Clé API distincte du GOOGLE_CLIENT_ID/SECRET de l'OAuth ci-dessus — projet
# Google Cloud avec facturation activée et "Routes API" activée (voir
# inventory/maps.py pour le détail des étapes). Jamais en dur : voir
# security.md. Si vide, l'estimation automatique de trajet est simplement
# désactivée (fallback sur Settings.default_transport_duration_minutes) —
# aucune erreur au démarrage.
GOOGLE_MAPS_API_KEY = env('GOOGLE_MAPS_API_KEY', default='')

# --- Journalisation applicative (2026-08-07, soir) ---
# Ajoutée pendant le débogage du géocodage : sans config LOGGING, les
# `logger.info(...)` du code applicatif ne sortent JAMAIS en production
# (le handler « dernier recours » de Python ne laisse passer que
# WARNING et plus), ce qui a rendu un incident indiagnosticable dans les
# logs Railway — impossible de savoir si un appel Google avait eu lieu.
# Handler stdout sans filtre de DEBUG : Railway capture stdout/stderr.
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'simple': {'format': '[{asctime}] {levelname} {name} — {message}', 'style': '{'},
    },
    'handlers': {
        'console': {'class': 'logging.StreamHandler', 'formatter': 'simple'},
    },
    'loggers': {
        # Tout le code applicatif (inventory.maps, inventory.views, …) en
        # INFO — le volume reste faible, ce sont des événements ponctuels
        # (géocodage, estimation de trajet), pas du par-requête.
        'inventory': {'handlers': ['console'], 'level': 'INFO', 'propagate': False},
    },
}
