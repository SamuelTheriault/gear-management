"""
Intégration Google Routes API — estime le temps de trajet entre deux lieux
(Venue) ayant des coordonnées GPS, pour pré-remplir automatiquement
`Transport.estimated_duration_minutes` (voir `TransportSerializer.validate`).

Décision du 2026-07-18 : utiliser l'endpoint "Compute Routes" (un trajet
simple, une origine et une destination) plutôt que "Compute Route Matrix"
(plusieurs origines/destinations) — un `Transport` a toujours exactement un
lieu de départ et un lieu d'arrivée, donc ça tombe dans le SKU "Essentials"
de l'API Routes, avec 10 000 requêtes gratuites par mois (juillet 2026),
largement suffisant à l'échelle d'un directeur technique freelance.
Documentation : https://developers.google.com/maps/documentation/routes

Nécessite la variable d'environnement `GOOGLE_MAPS_API_KEY` (voir
security.md — jamais en dur, toujours par variable d'environnement / Railway
Variables). Étapes manuelles requises côté Samuel avant que ça fonctionne :
1. Créer/choisir un projet Google Cloud, activer la facturation (le tier
   gratuit couvre largement l'usage prévu ici).
2. Activer "Routes API" dans ce projet.
3. Créer une clé API, la restreindre à "Routes API" (et idéalement par IP si
   Railway le permet), puis l'ajouter comme `GOOGLE_MAPS_API_KEY` dans les
   Variables Railway (et dans `backend/.env` en local).

Tant que la clé n'est pas configurée — ou si l'appel échoue (réseau, quota,
timeout) — `estimate_travel_minutes` retourne `None` silencieusement (avec un
log d'avertissement) : l'appelant se rabat alors sur
`Settings.load().default_transport_duration_minutes`.
"""

import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

ROUTES_API_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
REQUEST_TIMEOUT_SECONDS = 5


def estimate_travel_minutes(origin_venue, destination_venue):
    """Retourne la durée de trajet estimée (minutes, arrondie à l'entier) en
    voiture entre `origin_venue` et `destination_venue` via l'API Google
    Routes, ou `None` si le calcul n'est pas possible (clé API absente,
    coordonnées manquantes sur l'une des deux venues, ou appel en échec)."""
    api_key = getattr(settings, 'GOOGLE_MAPS_API_KEY', '') or ''
    if not api_key:
        return None
    if origin_venue.latitude is None or origin_venue.longitude is None:
        return None
    if destination_venue.latitude is None or destination_venue.longitude is None:
        return None

    payload = {
        "origin": {"location": {"latLng": {
            "latitude": float(origin_venue.latitude),
            "longitude": float(origin_venue.longitude),
        }}},
        "destination": {"location": {"latLng": {
            "latitude": float(destination_venue.latitude),
            "longitude": float(destination_venue.longitude),
        }}},
        "travelMode": "DRIVE",
    }
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        # FieldMask requis par l'API Routes (contrairement à l'ancienne
        # Distance Matrix) — on ne demande que la durée, pas la géométrie
        # complète du trajet, pour garder la réponse minimale.
        "X-Goog-FieldMask": "routes.duration",
    }

    try:
        response = requests.post(
            ROUTES_API_URL, json=payload, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data = response.json()
    except Exception:
        logger.warning(
            "Échec de l'appel Google Routes API pour estimer le trajet %s -> %s",
            origin_venue, destination_venue, exc_info=True,
        )
        return None

    routes = data.get('routes') or []
    if not routes:
        return None

    duration_str = routes[0].get('duration')  # ex. "1234s"
    if not duration_str or not duration_str.endswith('s'):
        return None

    try:
        seconds = int(duration_str[:-1])
    except ValueError:
        return None

    return max(1, round(seconds / 60))
