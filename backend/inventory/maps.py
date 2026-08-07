"""
Intégration Google Routes API — estime le temps de trajet entre deux lieux
(Venue) ayant des coordonnées GPS, pour pré-remplir automatiquement la durée
ET la distance d'un segment de tournée (`TransportStop.travel_minutes_from_previous`/`travel_distance_meters` — voir
`TransportSerializer.validate` ; la distance alimente le km estimé du camion,
2026-08-06).

Décision du 2026-07-18 : utiliser l'endpoint "Compute Routes" (un trajet
simple, une origine et une destination) plutôt que "Compute Route Matrix"
(plusieurs origines/destinations) — un segment de tournée relie toujours
exactement deux arrêts consécutifs, donc ça tombe dans le SKU "Essentials"
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
from decimal import Decimal

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

ROUTES_API_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
GEOCODING_API_URL = "https://maps.googleapis.com/maps/api/geocode/json"
REQUEST_TIMEOUT_SECONDS = 5


def geocode_address(address):
    """Retourne `{'latitude': Decimal, 'longitude': Decimal}` pour une adresse
    postale via l'API Google Geocoding, ou `None` si le géocodage n'est pas
    possible (clé absente, adresse vide/introuvable, appel en échec).

    Ajouté le 2026-08-07 (décision de Samuel — passe de corrections) : les
    coordonnées GPS des lieux se saisissaient uniquement à la main, donc la
    plupart des lieux n'en avaient pas et TOUT ce qui dépend de la matrice de
    trajets (durées, distances/km camion, suggestion d'ordre) échouait.
    Nécessite d'activer « Geocoding API » sur la même clé Google Cloud que
    Routes (`GOOGLE_MAPS_API_KEY`) — étape manuelle côté Samuel, même tier
    gratuit. `region=ca` : biais de région Canada (un nom de rue ambigu
    résout à Montréal plutôt qu'en France), sans exclure les adresses
    étrangères (tournées hors pays).

    Appelants : `VenueSerializer.save` (géocode à l'enregistrement d'une
    fiche Lieu) et `_ensure_coordinates` ci-dessous (filet au vol pour les
    lieux créés avant cette date). Les `Decimal` sont quantifiés à
    6 décimales — la précision exacte des champs `Venue.latitude/longitude`.
    """
    api_key = getattr(settings, 'GOOGLE_MAPS_API_KEY', '') or ''
    address = (address or '').strip()
    if not api_key or not address:
        return None
    try:
        response = requests.get(
            GEOCODING_API_URL,
            params={'address': address, 'key': api_key, 'region': 'ca'},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data = response.json()
    except Exception:
        logger.warning("Échec de l'appel Google Geocoding pour « %s »", address, exc_info=True)
        return None

    results = data.get('results') or []
    if data.get('status') != 'OK' or not results:
        return None
    location = (results[0].get('geometry') or {}).get('location') or {}
    lat, lng = location.get('lat'), location.get('lng')
    if lat is None or lng is None:
        return None
    quantum = Decimal('0.000001')
    return {
        'latitude': Decimal(str(lat)).quantize(quantum),
        'longitude': Decimal(str(lng)).quantize(quantum),
    }


def _ensure_coordinates(venue):
    """Filet de géocodage au vol (2026-08-07) : un lieu sans GPS mais avec
    une adresse est géocodé et SAUVÉ ici même, au moment où une estimation
    de trajet en a besoin. C'est volontairement un effet de bord d'écriture
    dans un module de lecture : les lieux d'avant le géocodage automatique
    n'ont pas de coordonnées, et sans ce filet il faudrait rouvrir et
    resauver chaque fiche Lieu pour en profiter — un géocodage réussi est un
    cache permanent, jamais recalculé. Retourne True si le lieu a des
    coordonnées utilisables."""
    if venue.latitude is not None and venue.longitude is not None:
        return True
    coords = geocode_address(venue.address)
    if coords is None:
        return False
    venue.latitude = coords['latitude']
    venue.longitude = coords['longitude']
    venue.save(update_fields=['latitude', 'longitude'])
    return True


def estimate_travel_minutes(origin_venue, destination_venue):
    """Retourne la durée de trajet estimée (minutes) — voir `estimate_travel`.

    Enveloppe de compatibilité : les appelants qui ne veulent que la durée
    (ex. `transport_autogen.estimate_travel_minutes_by_id`) continuent de
    passer par ici ; `estimate_travel` retourne durée ET distance depuis le
    2026-08-06 (km estimé du camion, chantier 2)."""
    result = estimate_travel(origin_venue, destination_venue)
    return result['minutes'] if result else None


def estimate_travel(origin_venue, destination_venue):
    """Retourne `{'minutes': int, 'meters': int|None}` pour le trajet en
    voiture entre `origin_venue` et `destination_venue` via l'API Google
    Routes, ou `None` si le calcul n'est pas possible (clé API absente,
    coordonnées manquantes sur l'une des deux venues, ou appel en échec).

    `meters` vient de `routes.distanceMeters` (ajouté au FieldMask le
    2026-08-06 — même appel, même coût, une donnée de plus) et alimente
    `TransportStop.travel_distance_meters` pour le km estimé du camion.

    Depuis le 2026-08-07, un lieu sans coordonnées mais avec une adresse est
    géocodé au vol (et sauvé) avant l'estimation — voir `_ensure_coordinates`."""
    api_key = getattr(settings, 'GOOGLE_MAPS_API_KEY', '') or ''
    if not api_key:
        return None
    if not _ensure_coordinates(origin_venue) or not _ensure_coordinates(destination_venue):
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
        "X-Goog-FieldMask": "routes.duration,routes.distanceMeters",
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

    meters = routes[0].get('distanceMeters')
    if not isinstance(meters, int) or meters < 0:
        meters = None

    return {'minutes': max(1, round(seconds / 60)), 'meters': meters}
