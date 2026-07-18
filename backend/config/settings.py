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
}

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
}

# --- Google Routes API (calcul du temps de trajet, inventory/maps.py) ---
# Clé API distincte du GOOGLE_CLIENT_ID/SECRET de l'OAuth ci-dessus — projet
# Google Cloud avec facturation activée et "Routes API" activée (voir
# inventory/maps.py pour le détail des étapes). Jamais en dur : voir
# security.md. Si vide, l'estimation automatique de trajet est simplement
# désactivée (fallback sur Settings.default_transport_duration_minutes) —
# aucune erreur au démarrage.
GOOGLE_MAPS_API_KEY = env('GOOGLE_MAPS_API_KEY', default='')
