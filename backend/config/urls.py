"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('inventory.urls')),
    # Login/logout pour l'API navigable DRF (pratique pour tester sans OAuth,
    # via le superutilisateur Django existant) — n'a aucun lien avec
    # l'authentification finale des utilisateurs de l'app (Google OAuth).
    path('api-auth/', include('rest_framework.urls')),
    # django-allauth : URLs de login social (ex. /accounts/google/login/) et
    # de callback OAuth (/accounts/google/login/callback/) — chemins fixes,
    # déjà enregistrés tels quels comme URIs de redirection dans Google Cloud.
    path('accounts/', include('allauth.urls')),
    # dj-rest-auth : endpoints DRF consommés par le frontend Vue une fois la
    # session Django établie (utilisateur courant, logout) — voir
    # config/settings.py pour le détail du flux.
    path('api/auth/', include('dj_rest_auth.urls')),
]
