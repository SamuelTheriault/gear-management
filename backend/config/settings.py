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
DEBUG = env.bool('DJANGO_DEBUG', default=True)

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
    'rest_framework',
    'corsheaders',
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
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
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

# Django REST Framework — config de base, à affiner avec l'auth Google OAuth.
REST_FRAMEWORK = {
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
}
