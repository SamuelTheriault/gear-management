"""
Tests pour le modèle `Settings` (singleton), le service `inventory.maps`
(Google Routes API) et l'auto-estimation de `Transport.estimated_duration_minutes` —
ajoutés le 2026-07-18 à la demande de Samuel (page de réglages + calcul de
temps de trajet).
"""

from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User as DjangoUser
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from .maps import estimate_travel_minutes
from .models import Settings, Show, Transport, Venue


def _dt(hour, day=1):
    """Petit helper pour construire des datetimes aware sur une même journée de test."""
    return timezone.make_aware(timezone.datetime(2026, 9, day, hour, 0))


class SettingsSingletonTests(TestCase):
    """Vérifie que `Settings` se comporte comme un vrai singleton."""

    def test_load_creates_default_row(self):
        self.assertEqual(Settings.objects.count(), 0)
        settings_row = Settings.load()
        self.assertEqual(Settings.objects.count(), 1)
        self.assertEqual(settings_row.default_buffer_before_minutes, 60)

    def test_load_returns_the_same_row_on_subsequent_calls(self):
        first = Settings.load()
        second = Settings.load()
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Settings.objects.count(), 1)

    def test_save_always_forces_pk_1(self):
        settings_row = Settings(default_buffer_before_minutes=45)
        settings_row.save()
        self.assertEqual(settings_row.pk, 1)

        another = Settings(default_buffer_after_minutes=30)
        another.save()
        self.assertEqual(Settings.objects.count(), 1)
        self.assertEqual(Settings.objects.get().default_buffer_after_minutes, 30)

    def test_delete_is_a_no_op(self):
        settings_row = Settings.load()
        settings_row.delete()
        self.assertEqual(Settings.objects.count(), 1)


class SettingsDrivenDefaultsTests(TestCase):
    """Vérifie que Show/Transport utilisent Settings comme source de leur
    valeur par défaut, plutôt qu'une constante codée en dur."""

    def setUp(self):
        settings_row = Settings.load()
        settings_row.default_buffer_before_minutes = 45
        settings_row.default_buffer_after_minutes = 20
        settings_row.default_transport_duration_minutes = 90
        settings_row.save()
        self.venue = Venue.objects.create(name="Salle test")

    def test_show_uses_settings_default_buffers(self):
        show = Show.objects.create(
            title="Show", venue=self.venue, event_type="performance",
            start_datetime=_dt(14), end_datetime=_dt(16),
        )
        self.assertEqual(show.buffer_before_minutes, 45)
        self.assertEqual(show.buffer_after_minutes, 20)

    def test_transport_uses_settings_default_duration(self):
        storage_venue = Venue.objects.create(name="Entrepôt", is_storage=True)
        show = Show.objects.create(
            title="Show", venue=self.venue, event_type="performance",
            start_datetime=_dt(14), end_datetime=_dt(16),
        )
        transport = Transport.objects.create(
            show=show, transport_type='delivery',
            origin_venue=storage_venue, destination_venue=self.venue,
            scheduled_datetime=_dt(10),
        )
        self.assertEqual(transport.estimated_duration_minutes, 90)

    def test_explicit_value_overrides_settings_default(self):
        show = Show.objects.create(
            title="Show", venue=self.venue, event_type="performance",
            start_datetime=_dt(14), end_datetime=_dt(16),
            buffer_before_minutes=5,
        )
        self.assertEqual(show.buffer_before_minutes, 5)


class MapsServiceTests(TestCase):
    """Teste `inventory.maps.estimate_travel_minutes` en isolant l'appel HTTP réel."""

    def setUp(self):
        self.origin = Venue.objects.create(name="Entrepôt", latitude=45.55, longitude=-73.6)
        self.destination = Venue.objects.create(name="Salle", latitude=45.52, longitude=-73.56)

    @override_settings(GOOGLE_MAPS_API_KEY='')
    def test_returns_none_without_api_key(self):
        self.assertIsNone(estimate_travel_minutes(self.origin, self.destination))

    @override_settings(GOOGLE_MAPS_API_KEY='fake-key')
    def test_returns_none_without_coordinates(self):
        venue_no_coords = Venue.objects.create(name="Sans coordonnées")
        self.assertIsNone(estimate_travel_minutes(self.origin, venue_no_coords))

    @override_settings(GOOGLE_MAPS_API_KEY='fake-key')
    @patch('inventory.maps.requests.post')
    def test_returns_minutes_on_success(self, mock_post):
        mock_response = MagicMock()
        mock_response.json.return_value = {'routes': [{'duration': '754s'}]}
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        minutes = estimate_travel_minutes(self.origin, self.destination)
        self.assertEqual(minutes, 13)  # round(754 / 60) == 13

    @override_settings(GOOGLE_MAPS_API_KEY='fake-key')
    @patch('inventory.maps.requests.post')
    def test_returns_none_on_request_exception(self, mock_post):
        mock_post.side_effect = Exception("network error")
        self.assertIsNone(estimate_travel_minutes(self.origin, self.destination))

    @override_settings(GOOGLE_MAPS_API_KEY='fake-key')
    @patch('inventory.maps.requests.post')
    def test_returns_none_when_no_routes_in_response(self, mock_post):
        mock_response = MagicMock()
        mock_response.json.return_value = {'routes': []}
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        self.assertIsNone(estimate_travel_minutes(self.origin, self.destination))


class TransportAutoEstimationTests(TestCase):
    """Vérifie que `TransportSerializer` appelle `estimate_travel_minutes` pour
    pré-remplir `estimated_duration_minutes` quand le client ne le fournit pas."""

    def setUp(self):
        self.user = DjangoUser.objects.create_superuser('admin', 'admin@test.com', 'testpass123')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        self.origin = Venue.objects.create(
            name="Entrepôt", is_storage=True, latitude=45.55, longitude=-73.6,
        )
        self.destination = Venue.objects.create(name="Salle", latitude=45.52, longitude=-73.56)
        self.show = Show.objects.create(
            title="Show", venue=self.destination, event_type="performance",
            start_datetime=_dt(14), end_datetime=_dt(16),
        )

    @patch('inventory.serializers.estimate_travel_minutes')
    def test_auto_fills_duration_when_not_provided(self, mock_estimate):
        mock_estimate.return_value = 22
        response = self.client.post('/api/transports/', {
            'show': self.show.id, 'transport_type': 'delivery',
            'origin_venue': self.origin.id, 'destination_venue': self.destination.id,
            'scheduled_datetime': _dt(8).isoformat(),
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['estimated_duration_minutes'], 22)
        mock_estimate.assert_called_once()

    @patch('inventory.serializers.estimate_travel_minutes')
    def test_explicit_duration_is_not_overridden(self, mock_estimate):
        mock_estimate.return_value = 999
        response = self.client.post('/api/transports/', {
            'show': self.show.id, 'transport_type': 'delivery',
            'origin_venue': self.origin.id, 'destination_venue': self.destination.id,
            'scheduled_datetime': _dt(8).isoformat(), 'estimated_duration_minutes': 30,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['estimated_duration_minutes'], 30)
        mock_estimate.assert_not_called()

    @patch('inventory.serializers.estimate_travel_minutes')
    def test_falls_back_to_settings_default_when_maps_returns_none(self, mock_estimate):
        mock_estimate.return_value = None
        response = self.client.post('/api/transports/', {
            'show': self.show.id, 'transport_type': 'delivery',
            'origin_venue': self.origin.id, 'destination_venue': self.destination.id,
            'scheduled_datetime': _dt(8).isoformat(),
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['estimated_duration_minutes'], 60)

    @patch('inventory.serializers.estimate_travel_minutes')
    def test_unrelated_patch_does_not_recompute_or_overwrite_duration(self, mock_estimate):
        """Régression (trouvée en revue de code, 2026-07-18) : un PATCH qui ne
        touche ni au trajet ni à la durée ne doit ni rappeler l'API Google ni
        écraser une durée déjà en place (ex. corrigée manuellement)."""
        mock_estimate.return_value = 22
        create_response = self.client.post('/api/transports/', {
            'show': self.show.id, 'transport_type': 'delivery',
            'origin_venue': self.origin.id, 'destination_venue': self.destination.id,
            'scheduled_datetime': _dt(8).isoformat(), 'estimated_duration_minutes': 45,
        }, format='json')
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        transport_id = create_response.data['id']
        mock_estimate.assert_not_called()  # durée fournie explicitement à la création

        mock_estimate.return_value = 999
        patch_response = self.client.patch(f'/api/transports/{transport_id}/', {
            'notes': 'mise à jour sans rapport avec le trajet',
        }, format='json')
        self.assertEqual(patch_response.status_code, status.HTTP_200_OK)
        self.assertEqual(patch_response.data['estimated_duration_minutes'], 45)
        mock_estimate.assert_not_called()

    @patch('inventory.serializers.estimate_travel_minutes')
    def test_patch_changing_destination_venue_recomputes_duration(self, mock_estimate):
        """Si le trajet change réellement (nouvelle destination) et qu'aucune
        durée explicite n'est fournie, on doit recalculer."""
        mock_estimate.return_value = 22
        create_response = self.client.post('/api/transports/', {
            'show': self.show.id, 'transport_type': 'delivery',
            'origin_venue': self.origin.id, 'destination_venue': self.destination.id,
            'scheduled_datetime': _dt(8).isoformat(),
        }, format='json')
        transport_id = create_response.data['id']

        other_destination = Venue.objects.create(name="Autre salle", latitude=45.50, longitude=-73.58)
        mock_estimate.return_value = 37
        patch_response = self.client.patch(f'/api/transports/{transport_id}/', {
            'destination_venue': other_destination.id,
        }, format='json')
        self.assertEqual(patch_response.status_code, status.HTTP_200_OK)
        self.assertEqual(patch_response.data['estimated_duration_minutes'], 37)


class SettingsAPITests(TestCase):
    """Vérifie l'endpoint singleton `GET`/`PATCH` sur `/api/settings/`."""

    def setUp(self):
        self.user = DjangoUser.objects.create_superuser('admin', 'admin@test.com', 'testpass123')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_get_returns_defaults(self):
        response = self.client.get('/api/settings/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['default_buffer_before_minutes'], 60)

    def test_patch_updates_the_singleton(self):
        response = self.client.patch('/api/settings/', {
            'default_buffer_before_minutes': 30,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Settings.load().default_buffer_before_minutes, 30)
        self.assertEqual(Settings.objects.count(), 1)
