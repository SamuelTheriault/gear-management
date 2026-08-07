"""
Tests du chantier 3 des travaux transport (2026-08-07) : suggestion d'ordre
optimal des arrêts (`transport_ordering.py` + action `order-suggestion`) et
réestimation des distances (`refresh-distances`).

Tout appel Google Routes est moqué — `estimate_travel` est patché À L'ENDROIT
où chaque module l'a importé (`inventory.transport_ordering.estimate_travel`
pour la suggestion, `inventory.views.estimate_travel` pour le refresh), même
convention que `test_settings_and_maps.py`.
"""

from unittest.mock import patch

from django.contrib.auth.models import User as DjangoUser
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from .models import Project, Transport, TransportStop, Venue
from .transport_ordering import OrderingUnavailable, suggest_stop_order


def _dt(hour, day=1):
    """Petit helper pour construire des datetimes aware sur une même journée de test."""
    return timezone.make_aware(timezone.datetime(2026, 9, day, hour, 0))


def _fake_matrix(minutes_by_names):
    """Fabrique un remplaçant d'`estimate_travel` piloté par un dict
    `{('A', 'B'): minutes}` (mètres = minutes × 1000, pour des assertions
    lisibles). Un couple absent du dict retourne None (inestimable)."""
    def fake(origin, destination):
        key = (origin.name, destination.name)
        if key not in minutes_by_names:
            return None
        minutes = minutes_by_names[key]
        return {'minutes': minutes, 'meters': minutes * 1000}
    return fake


# Matrice de référence des tests : 4 lieux, ordre actuel A→B→C→D (30+30+5=65
# min), optimum SANS contrainte A→C→B→D (10+10+10=30 min). Une précédence
# B-avant-C (matériel chargé en B, déchargé en C) interdit cet optimum et
# rend l'ordre actuel imbattable.
MATRICE = {
    ('A', 'B'): 30, ('B', 'A'): 50,
    ('A', 'C'): 10, ('C', 'A'): 50,
    ('A', 'D'): 50, ('D', 'A'): 50,
    ('B', 'C'): 30, ('C', 'B'): 10,
    ('B', 'D'): 10, ('D', 'B'): 50,
    ('C', 'D'): 5, ('D', 'C'): 50,
}


class SuggestStopOrderTests(TestCase):
    """`transport_ordering.suggest_stop_order` en direct (unitaire)."""

    def setUp(self):
        self.project = Project.objects.create(name="Projet ordre")
        self.a = Venue.objects.create(project=self.project, name="A", is_storage=True)
        self.b = Venue.objects.create(project=self.project, name="B")
        self.c = Venue.objects.create(project=self.project, name="C")
        self.d = Venue.objects.create(project=self.project, name="D")

    def test_moins_de_trois_arrets_est_refuse(self):
        with self.assertRaises(ValueError):
            suggest_stop_order([self.a, self.b], [])

    @patch('inventory.transport_ordering.estimate_travel')
    def test_matrice_incomplete_leve_ordering_unavailable(self, mock_estimate):
        mock_estimate.return_value = None  # clé absente / lieu sans GPS
        with self.assertRaises(OrderingUnavailable):
            suggest_stop_order([self.a, self.b, self.c], [])

    @patch('inventory.transport_ordering.estimate_travel')
    def test_trouve_l_ordre_optimal_premier_arret_fixe(self, mock_estimate):
        mock_estimate.side_effect = _fake_matrix(MATRICE)
        resultat = suggest_stop_order([self.a, self.b, self.c, self.d], [])
        self.assertEqual(resultat['order'], [0, 2, 1, 3])  # A, C, B, D
        self.assertEqual(resultat['total_minutes'], 30)
        self.assertEqual(resultat['total_meters'], 30000)
        self.assertEqual(resultat['current_minutes'], 65)
        self.assertEqual(resultat['current_meters'], 65000)
        self.assertFalse(resultat['already_optimal'])
        # Segments alignés au NOUVEL ordre : A→C (10), C→B (10), B→D (10).
        self.assertEqual(resultat['segments'][0], {'minutes': None, 'meters': None})
        self.assertEqual([s['minutes'] for s in resultat['segments'][1:]], [10, 10, 10])

    @patch('inventory.transport_ordering.estimate_travel')
    def test_une_precedence_ecarte_l_optimum_brut(self, mock_estimate):
        mock_estimate.side_effect = _fake_matrix(MATRICE)
        # Matériel chargé à l'arrêt 1 (B) et déchargé à l'arrêt 2 (C) : B doit
        # rester avant C — l'optimum brut A,C,B,D devient illégal, et aucun
        # ordre légal ne bat l'actuel (65 min).
        resultat = suggest_stop_order([self.a, self.b, self.c, self.d], [(1, 2)])
        self.assertEqual(resultat['order'], [0, 1, 2, 3])
        self.assertTrue(resultat['already_optimal'])
        self.assertEqual(resultat['total_minutes'], 65)

    @patch('inventory.transport_ordering.estimate_travel')
    def test_lieu_repete_memoise_et_jamais_consecutif(self, mock_estimate):
        # A→B→A→C : le lieu A revient. La matrice ne se calcule qu'une fois
        # par couple ORIENTÉ de lieux distincts (3 lieux → 6 appels max), et
        # aucun candidat ne peut placer les deux passages en A côte à côte
        # (couple (A, A) absent de la matrice : ce serait un KeyError).
        mock_estimate.side_effect = _fake_matrix(MATRICE)
        resultat = suggest_stop_order([self.a, self.b, self.a, self.c], [])
        self.assertLessEqual(mock_estimate.call_count, 6)
        nouvel_ordre_ids = [[self.a, self.b, self.a, self.c][i].id for i in resultat['order']]
        for gauche, droite in zip(nouvel_ordre_ids, nouvel_ordre_ids[1:]):
            self.assertNotEqual(gauche, droite)


class OrderSuggestionAPITests(TestCase):
    """`POST /api/transports/order-suggestion/` — validation du corps, accès
    projet, et remontée d'`OrderingUnavailable` en 400 affichable."""

    def setUp(self):
        self.project = Project.objects.create(name="Projet suggestion")
        self.client = APIClient()
        self.django_user = DjangoUser.objects.create_superuser('admin', 'admin@example.com', 'pw')
        self.client.force_authenticate(user=self.django_user)

        self.a = Venue.objects.create(project=self.project, name="A", is_storage=True)
        self.b = Venue.objects.create(project=self.project, name="B")
        self.c = Venue.objects.create(project=self.project, name="C")
        self.d = Venue.objects.create(project=self.project, name="D")

    def _post(self, **overrides):
        payload = {
            'project': self.project.id,
            'stops': [self.a.id, self.b.id, self.c.id, self.d.id],
            'materials': [],
        }
        payload.update(overrides)
        return self.client.post('/api/transports/order-suggestion/', payload, format='json')

    def test_le_projet_est_requis(self):
        response = self._post(project=None)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('project', response.data)

    def test_moins_de_trois_arrets_en_400(self):
        response = self._post(stops=[self.a.id, self.b.id])
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('stops', response.data)

    def test_lieu_d_un_autre_projet_en_400(self):
        autre = Project.objects.create(name="Autre")
        ailleurs = Venue.objects.create(project=autre, name="Ailleurs")
        response = self._post(stops=[self.a.id, self.b.id, ailleurs.id])
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('stops', response.data)

    def test_portion_de_materiel_invalide_en_400(self):
        response = self._post(materials=[{'load': 2, 'unload': 1}])
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('materials', response.data)

    @patch('inventory.transport_ordering.estimate_travel')
    def test_matrice_inconstructible_en_400_avec_message(self, mock_estimate):
        mock_estimate.return_value = None
        response = self._post()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('detail', response.data)
        self.assertIn('Google Routes', response.data['detail'])

    @patch('inventory.transport_ordering.estimate_travel')
    def test_suggestion_complete(self, mock_estimate):
        mock_estimate.side_effect = _fake_matrix(MATRICE)
        response = self._post()
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['order'], [0, 2, 1, 3])
        self.assertEqual(response.data['total_minutes'], 30)
        self.assertEqual(response.data['current_minutes'], 65)
        self.assertFalse(response.data['already_optimal'])

    @patch('inventory.transport_ordering.estimate_travel')
    def test_les_precedences_du_materiel_sont_transmises(self, mock_estimate):
        mock_estimate.side_effect = _fake_matrix(MATRICE)
        response = self._post(materials=[{'load': 1, 'unload': 2}])
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertTrue(response.data['already_optimal'])

    def test_rien_n_est_ecrit(self):
        # STATELESS : aucune tournée créée ni modifiée, quel que soit l'issue.
        with patch('inventory.transport_ordering.estimate_travel', side_effect=_fake_matrix(MATRICE)):
            self._post()
        self.assertEqual(Transport.objects.count(), 0)


class RefreshDistancesAPITests(TestCase):
    """`POST /api/transports/{id}/refresh-distances/` — remplit
    `travel_distance_meters` segment par segment, durées INTACTES."""

    def setUp(self):
        self.project = Project.objects.create(name="Projet refresh")
        self.client = APIClient()
        self.django_user = DjangoUser.objects.create_superuser('admin', 'admin@example.com', 'pw')
        self.client.force_authenticate(user=self.django_user)

        self.a = Venue.objects.create(project=self.project, name="A", is_storage=True)
        self.b = Venue.objects.create(project=self.project, name="B")
        self.c = Venue.objects.create(project=self.project, name="C")

        # Tournée « d'avant la migration 0029 » : durées connues (dont une
        # manuelle), AUCUNE distance stockée.
        self.transport = Transport.objects.create(
            project=self.project,
            truck=self.project.trucks.order_by('id').first(),
            scheduled_datetime=_dt(8),
        )
        TransportStop.objects.create(transport=self.transport, venue=self.a, order=0)
        TransportStop.objects.create(
            transport=self.transport, venue=self.b, order=1, travel_minutes_from_previous=90,
        )
        TransportStop.objects.create(
            transport=self.transport, venue=self.c, order=2, travel_minutes_from_previous=25,
        )

    def _refresh(self):
        return self.client.post(f'/api/transports/{self.transport.id}/refresh-distances/', {}, format='json')

    @patch('inventory.views.estimate_travel')
    def test_remplit_les_distances_sans_toucher_aux_durees(self, mock_estimate):
        mock_estimate.side_effect = _fake_matrix({('A', 'B'): 30, ('B', 'C'): 25})
        response = self._refresh()
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['refreshed'], 2)
        self.assertEqual(response.data['unavailable'], 0)

        stops = list(self.transport.stops.order_by('order'))
        self.assertIsNone(stops[0].travel_distance_meters)
        self.assertEqual(stops[1].travel_distance_meters, 30000)
        self.assertEqual(stops[2].travel_distance_meters, 25000)
        # Les durées — y compris les 90 min manuelles — n'ont pas bougé.
        self.assertEqual(stops[1].travel_minutes_from_previous, 90)
        self.assertEqual(stops[2].travel_minutes_from_previous, 25)
        # La fiche sérialisée retournée reflète les nouvelles distances.
        self.assertEqual(response.data['transport']['stops'][1]['travel_distance_meters'], 30000)

    @patch('inventory.views.estimate_travel')
    def test_segment_inestimable_compte_en_unavailable(self, mock_estimate):
        mock_estimate.side_effect = _fake_matrix({('A', 'B'): 30})  # B→C inestimable
        response = self._refresh()
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['refreshed'], 1)
        self.assertEqual(response.data['unavailable'], 1)
        stops = list(self.transport.stops.order_by('order'))
        self.assertEqual(stops[1].travel_distance_meters, 30000)
        self.assertIsNone(stops[2].travel_distance_meters)
