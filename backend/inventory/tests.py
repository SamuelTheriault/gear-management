"""
Tests ciblés sur la logique de détection de conflits (matériel, techniciens
et déplacements) — le cœur fonctionnel de l'app (voir architecture.md,
section 4).

Niveaux :
- `ConflictLogicTests` : teste `conflicts.py` directement (chevauchement,
  limite de buffer, hiérarchie parent/enfant).
- `StorageExemptionTests` : exemption d'entreposage (`Venue.is_storage`).
- `TransportConflictTests` : croisement `ShowTechnician` / `Transport` pour
  un même technicien.
- `ConflictAPITests` : teste le comportement bloquant + override `force`
  au niveau des serializers/endpoints (`show-materials`, `show-technicians`,
  `transports`).
"""

from datetime import timedelta

from django.contrib.auth.models import User as DjangoUser
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from .conflicts import get_material_conflicts, get_technician_conflicts, get_transport_conflicts
from .models import Department, Material, Show, ShowMaterial, ShowTechnician, Technician, Transport, Venue


def _dt(hour, day=1):
    """Petit helper pour construire des datetimes aware sur une même journée de test."""
    return timezone.make_aware(timezone.datetime(2026, 9, day, hour, 0))


class ConflictLogicTests(TestCase):
    """Vérifie `conflicts.py` directement : chevauchement, limites de buffer, hiérarchie parent/enfant."""

    def setUp(self):
        self.venue = Venue.objects.create(name="Salle test")
        self.material = Material.objects.create(name="Console son", category="audio")
        # 14h-16h, buffers par défaut (60 min) -> fenêtre effective 13h-17h
        self.show_a = Show.objects.create(
            title="Show A", venue=self.venue, event_type="rehearsal",
            start_datetime=_dt(14), end_datetime=_dt(16),
        )

    def test_no_conflict_when_material_unassigned(self):
        self.assertEqual(get_material_conflicts(self.show_a, self.material), [])

    def test_conflict_detected_on_overlap(self):
        # Show B : 16h30-18h -> fenêtre effective 15h30-19h -> chevauche 13h-17h de Show A
        show_b = Show.objects.create(
            title="Show B", venue=self.venue, event_type="rehearsal",
            start_datetime=_dt(16, day=1) + timedelta(minutes=30), end_datetime=_dt(18),
        )
        ShowMaterial.objects.create(show=self.show_a, material=self.material)

        conflicts = get_material_conflicts(show_b, self.material)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].show_id, self.show_a.id)

    def test_no_conflict_when_windows_only_touch_at_boundary(self):
        # Show B commence exactement quand la fenêtre effective de Show A se termine (17h)
        # -> pas de chevauchement (intervalle semi-ouvert, convention documentée dans conflicts.py)
        show_b = Show.objects.create(
            title="Show B", venue=self.venue, event_type="rehearsal",
            start_datetime=_dt(18), end_datetime=_dt(20),
            buffer_before_minutes=60,  # fenêtre effective : 17h-21h
        )
        ShowMaterial.objects.create(show=self.show_a, material=self.material)

        self.assertEqual(get_material_conflicts(show_b, self.material), [])

    def test_no_conflict_beyond_buffers(self):
        # Show B largement après Show A, aucun chevauchement même avec buffers
        show_b = Show.objects.create(
            title="Show B", venue=self.venue, event_type="rehearsal",
            start_datetime=_dt(20), end_datetime=_dt(22),
        )
        ShowMaterial.objects.create(show=self.show_a, material=self.material)

        self.assertEqual(get_material_conflicts(show_b, self.material), [])

    def test_conflict_propagates_from_parent_to_child(self):
        kit = Material.objects.create(name="Kit Audio", category="audio")
        mic = Material.objects.create(name="Micro sans fil", category="audio", parent_material=kit)

        show_b = Show.objects.create(
            title="Show B", venue=self.venue, event_type="rehearsal",
            start_datetime=_dt(16, day=1) + timedelta(minutes=30), end_datetime=_dt(18),
        )
        # Le kit complet est assigné à Show A
        ShowMaterial.objects.create(show=self.show_a, material=kit)

        # Assigner un composant du kit (le micro) à Show B doit être signalé en conflit
        conflicts = get_material_conflicts(show_b, mic)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].material_id, kit.id)

    def test_conflict_propagates_from_child_to_parent(self):
        kit = Material.objects.create(name="Kit Audio", category="audio")
        mic = Material.objects.create(name="Micro sans fil", category="audio", parent_material=kit)

        show_b = Show.objects.create(
            title="Show B", venue=self.venue, event_type="rehearsal",
            start_datetime=_dt(16, day=1) + timedelta(minutes=30), end_datetime=_dt(18),
        )
        # Le micro (composant) est assigné à Show A
        ShowMaterial.objects.create(show=self.show_a, material=mic)

        # Assigner le kit parent à Show B doit aussi être signalé en conflit
        conflicts = get_material_conflicts(show_b, kit)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].material_id, mic.id)

    def test_same_show_never_conflicts_with_itself(self):
        # Assigner le même matériel (ou un parent/enfant) une deuxième fois DANS
        # le même spectacle n'est pas un conflit d'horaire.
        kit = Material.objects.create(name="Kit Audio", category="audio")
        mic = Material.objects.create(name="Micro sans fil", category="audio", parent_material=kit)
        ShowMaterial.objects.create(show=self.show_a, material=mic)

        self.assertEqual(get_material_conflicts(self.show_a, kit), [])

    def test_technician_conflict_on_overlap(self):
        tech = Technician.objects.create(name="Alex Dupont", specialty="son")
        show_b = Show.objects.create(
            title="Show B", venue=self.venue, event_type="rehearsal",
            start_datetime=_dt(16, day=1) + timedelta(minutes=30), end_datetime=_dt(18),
        )
        ShowTechnician.objects.create(show=self.show_a, technician=tech)

        conflicts = get_technician_conflicts(show_b, tech)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].show_id, self.show_a.id)

    def test_exclude_id_does_not_hide_conflicts_on_other_rows(self):
        # exclude_id ne doit exclure QUE l'assignation précisée, pas les autres
        # conflits réels — utilisé lors d'un update pour ignorer l'assignation
        # qu'on est en train de modifier, sans masquer les vrais conflits.
        sm = ShowMaterial.objects.create(show=self.show_a, material=self.material)
        show_b = Show.objects.create(
            title="Show B", venue=self.venue, event_type="rehearsal",
            start_datetime=_dt(16, day=1) + timedelta(minutes=30), end_datetime=_dt(18),
        )
        conflicts = get_material_conflicts(show_b, self.material, exclude_id=sm.id)
        # sm est la seule assignation existante pour ce matériel ; en l'excluant,
        # il ne doit plus rester aucun conflit.
        self.assertEqual(conflicts, [])

        # Sans exclude_id, le conflit avec `sm` doit bien être détecté.
        conflicts_without_exclude = get_material_conflicts(show_b, self.material)
        self.assertEqual(len(conflicts_without_exclude), 1)
        self.assertEqual(conflicts_without_exclude[0].id, sm.id)


class StorageExemptionTests(TestCase):
    """Vérifie l'exemption d'entreposage (Venue.is_storage) — décision du 2026-07-18 :
    le matériel assigné à un Show dont le venue est un entrepôt ne déclenche et ne
    subit jamais de conflit matériel. Les techniciens, eux, restent soumis à la
    détection normale même sur un Show d'entrepôt."""

    def setUp(self):
        self.real_venue = Venue.objects.create(name="Salle test")
        self.storage_venue = Venue.objects.create(name="Entrepôt Rosemont", is_storage=True)
        self.material = Material.objects.create(name="Console son", category="audio")
        self.technician = Technician.objects.create(name="Alex Dupont", specialty="son")

        # Show réel 14h-16h -> fenêtre effective 13h-17h
        self.show_real = Show.objects.create(
            title="Show réel", venue=self.real_venue, event_type="rehearsal",
            start_datetime=_dt(14), end_datetime=_dt(16),
        )
        # Show d'entrepôt qui chevauche complètement la fenêtre du show réel
        self.show_storage = Show.objects.create(
            title="Rangement", venue=self.storage_venue, event_type="storage",
            start_datetime=_dt(14), end_datetime=_dt(16),
        )

    def test_assigning_to_storage_show_never_conflicts(self):
        # Le matériel est déjà utilisé sur le show réel au même moment ; l'assigner
        # AUSSI à un show d'entrepôt qui se chevauche ne doit jamais être bloqué.
        ShowMaterial.objects.create(show=self.show_real, material=self.material)
        conflicts = get_material_conflicts(self.show_storage, self.material)
        self.assertEqual(conflicts, [])

    def test_existing_storage_assignment_is_not_a_conflict_source(self):
        # Le matériel est déjà "rangé" (assigné à un show d'entrepôt) ; l'assigner
        # à un vrai show qui chevauche cette période ne doit pas être bloqué non plus.
        ShowMaterial.objects.create(show=self.show_storage, material=self.material)
        conflicts = get_material_conflicts(self.show_real, self.material)
        self.assertEqual(conflicts, [])

    def test_two_real_shows_still_conflict_despite_unrelated_storage(self):
        # Non-régression : l'exemption d'entreposage ne doit pas masquer un vrai
        # conflit entre deux shows réels.
        other_real_show = Show.objects.create(
            title="Autre show réel", venue=self.real_venue, event_type="performance",
            start_datetime=_dt(15), end_datetime=_dt(17),
        )
        ShowMaterial.objects.create(show=self.show_real, material=self.material)
        conflicts = get_material_conflicts(other_real_show, self.material)
        self.assertEqual(len(conflicts), 1)

    def test_technician_conflicts_are_not_exempted_by_storage(self):
        # Un technicien assigné à un show d'entrepôt (ex. inventaire) reste un
        # vrai engagement d'horaire : la détection normale s'applique toujours.
        ShowTechnician.objects.create(show=self.show_real, technician=self.technician)
        conflicts = get_technician_conflicts(self.show_storage, self.technician)
        self.assertEqual(len(conflicts), 1)


class TransportConflictTests(TestCase):
    """Vérifie que `ShowTechnician` et `Transport` sont croisés ensemble pour un
    même technicien — décision du 2026-07-18 (voir conflicts.py)."""

    def setUp(self):
        self.venue_a = Venue.objects.create(name="Salle A")
        self.venue_b = Venue.objects.create(name="Entrepôt", is_storage=True)
        self.technician = Technician.objects.create(name="Alex Dupont", specialty="son")
        # Show 14h-16h -> fenêtre effective 13h-17h
        self.show = Show.objects.create(
            title="Show", venue=self.venue_a, event_type="performance",
            start_datetime=_dt(14), end_datetime=_dt(16),
        )

    def test_transport_conflicts_with_existing_show_assignment(self):
        ShowTechnician.objects.create(show=self.show, technician=self.technician)
        # Livraison à midi, 90 min -> fenêtre 12h-13h30, chevauche 13h-17h (Show)
        conflicts = get_transport_conflicts(
            _dt(12), 90, self.technician,
        )
        self.assertEqual(len(conflicts), 1)

    def test_no_conflict_when_transport_is_well_before_show(self):
        ShowTechnician.objects.create(show=self.show, technician=self.technician)
        # Livraison à 8h, 60 min -> fenêtre 8h-9h, largement avant 13h-17h
        conflicts = get_transport_conflicts(_dt(8), 60, self.technician)
        self.assertEqual(conflicts, [])

    def test_show_assignment_conflicts_with_existing_transport(self):
        # Sens inverse : le technicien a déjà un transport qui chevauche la
        # fenêtre du show -> l'assigner au show doit être signalé en conflit.
        Transport.objects.create(
            show=self.show, transport_type='delivery',
            origin_venue=self.venue_b, destination_venue=self.venue_a,
            scheduled_datetime=_dt(12), estimated_duration_minutes=90,
            technician=self.technician,
        )
        conflicts = get_technician_conflicts(self.show, self.technician)
        self.assertEqual(len(conflicts), 1)

    def test_two_transports_for_same_technician_conflict(self):
        Transport.objects.create(
            show=self.show, transport_type='delivery',
            origin_venue=self.venue_b, destination_venue=self.venue_a,
            scheduled_datetime=_dt(10), estimated_duration_minutes=60,
            technician=self.technician,
        )
        # Deuxième transport qui chevauche le premier (10h-11h) : 10h30-11h30
        conflicts = get_transport_conflicts(
            _dt(10) + timedelta(minutes=30), 60, self.technician,
        )
        self.assertEqual(len(conflicts), 1)

    def test_exclude_id_excludes_the_transport_itself(self):
        transport = Transport.objects.create(
            show=self.show, transport_type='delivery',
            origin_venue=self.venue_b, destination_venue=self.venue_a,
            scheduled_datetime=_dt(10), estimated_duration_minutes=60,
            technician=self.technician,
        )
        # Mettre à jour ce même transport (même horaire) ne doit pas se
        # "conflicter" avec lui-même.
        conflicts = get_transport_conflicts(
            _dt(10), 60, self.technician, exclude_id=transport.id,
        )
        self.assertEqual(conflicts, [])


class ConflictAPITests(TestCase):
    """Vérifie le comportement bloquant + override au niveau de l'API (squelette DRF)."""

    def setUp(self):
        self.user = DjangoUser.objects.create_superuser('admin', 'admin@test.com', 'testpass123')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        self.venue = Venue.objects.create(name="Salle test")
        self.material = Material.objects.create(name="Console son", category="audio")
        self.technician = Technician.objects.create(name="Alex Dupont", specialty="son")

        self.show_a = Show.objects.create(
            title="Show A", venue=self.venue, event_type="rehearsal",
            start_datetime=_dt(14), end_datetime=_dt(16),
        )
        self.show_b = Show.objects.create(
            title="Show B", venue=self.venue, event_type="rehearsal",
            start_datetime=_dt(16, day=1) + timedelta(minutes=30), end_datetime=_dt(18),
        )
        ShowMaterial.objects.create(show=self.show_a, material=self.material)
        ShowTechnician.objects.create(show=self.show_a, technician=self.technician)

    def test_material_assignment_blocked_on_conflict(self):
        response = self.client.post('/api/show-materials/', {
            'show': self.show_b.id, 'material': self.material.id,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('conflicts', response.data)

    def test_material_assignment_succeeds_with_force(self):
        response = self.client.post('/api/show-materials/', {
            'show': self.show_b.id, 'material': self.material.id, 'force': True,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_technician_assignment_blocked_on_conflict(self):
        response = self.client.post('/api/show-technicians/', {
            'show': self.show_b.id, 'technician': self.technician.id,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('conflicts', response.data)

    def test_technician_assignment_succeeds_with_force(self):
        response = self.client.post('/api/show-technicians/', {
            'show': self.show_b.id, 'technician': self.technician.id, 'force': True,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_show_conflicts_endpoint_lists_forced_conflict(self):
        self.client.post('/api/show-materials/', {
            'show': self.show_b.id, 'material': self.material.id, 'force': True,
        }, format='json')

        response = self.client.get(f'/api/shows/{self.show_a.id}/conflicts/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['material_conflicts']), 1)

    def test_no_false_positive_when_no_overlap(self):
        show_c = Show.objects.create(
            title="Show C", venue=self.venue, event_type="rehearsal",
            start_datetime=_dt(20), end_datetime=_dt(22),
        )
        response = self.client.post('/api/show-materials/', {
            'show': show_c.id, 'material': self.material.id,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_transport_blocked_when_technician_already_on_show(self):
        # self.technician est déjà assigné à show_a (14h-16h, fenêtre 13h-17h)
        storage_venue = Venue.objects.create(name="Entrepôt", is_storage=True)
        response = self.client.post('/api/transports/', {
            'show': self.show_a.id, 'transport_type': 'delivery',
            'origin_venue': storage_venue.id, 'destination_venue': self.venue.id,
            'scheduled_datetime': _dt(12).isoformat(), 'estimated_duration_minutes': 90,
            'technician': self.technician.id,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('conflicts', response.data)

    def test_transport_succeeds_with_force(self):
        storage_venue = Venue.objects.create(name="Entrepôt", is_storage=True)
        response = self.client.post('/api/transports/', {
            'show': self.show_a.id, 'transport_type': 'delivery',
            'origin_venue': storage_venue.id, 'destination_venue': self.venue.id,
            'scheduled_datetime': _dt(12).isoformat(), 'estimated_duration_minutes': 90,
            'technician': self.technician.id, 'force': True,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_transport_rejects_identical_origin_and_destination(self):
        response = self.client.post('/api/transports/', {
            'show': self.show_a.id, 'transport_type': 'delivery',
            'origin_venue': self.venue.id, 'destination_venue': self.venue.id,
            'scheduled_datetime': _dt(8).isoformat(), 'estimated_duration_minutes': 60,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('destination_venue', response.data)


class DepartmentColorTests(TestCase):
    """Vérifie `Department.color` : validation du format hex + propagation aux sous-sections
    (matériel, assignations show/matériel) via les serializers (voir serializers.py)."""

    def setUp(self):
        self.client = APIClient()
        self.django_user = DjangoUser.objects.create_superuser('admin', 'admin@example.com', 'pw')
        self.client.force_authenticate(user=self.django_user)
        self.venue = Venue.objects.create(name="Salle test")

    def test_department_gets_default_color_when_not_specified(self):
        dept = Department.objects.create(name="Son")
        self.assertEqual(dept.color, Department.DEFAULT_COLOR)

    def test_valid_hex_color_accepted(self):
        dept = Department(name="Éclairage", color="#3B82F6")
        dept.full_clean()  # ne doit pas lever

    def test_invalid_hex_color_rejected(self):
        dept = Department(name="Décor", color="bleu")
        with self.assertRaises(ValidationError):
            dept.full_clean()

    def test_short_hex_color_rejected(self):
        # #RGB (3 caractères) n'est pas accepté — on exige la forme longue #RRGGBB,
        # cohérente avec un <input type="color"> HTML.
        dept = Department(name="Vidéo", color="#FFF")
        with self.assertRaises(ValidationError):
            dept.full_clean()

    def test_material_serializer_exposes_department_color(self):
        dept = Department.objects.create(name="Audio", color="#F97316")
        material = Material.objects.create(name="Console", category="audio", department=dept)

        response = self.client.get(f'/api/materials/{material.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['department_color'], "#F97316")

    def test_material_serializer_department_color_none_when_no_department(self):
        material = Material.objects.create(name="Console sans département", category="audio")

        response = self.client.get(f'/api/materials/{material.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data['department_color'])

    def test_show_material_serializer_exposes_department_color(self):
        dept = Department.objects.create(name="Vidéo", color="#22C55E")
        material = Material.objects.create(name="Projecteur", category="video", department=dept)
        show = Show.objects.create(
            title="Show couleur", venue=self.venue, event_type="rehearsal",
            start_datetime=_dt(14), end_datetime=_dt(16),
        )

        response = self.client.post('/api/show-materials/', {
            'show': show.id, 'material': material.id,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['department_color'], "#22C55E")
