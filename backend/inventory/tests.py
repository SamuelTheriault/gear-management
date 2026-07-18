"""
Tests ciblés sur la logique de détection de conflits (matériel et
techniciens) — le cœur fonctionnel de l'app (voir architecture.md, section 4).

Deux niveaux :
- `ConflictLogicTests` : teste `conflicts.py` directement (chevauchement,
  limite de buffer, hiérarchie parent/enfant).
- `ConflictAPITests` : teste le comportement bloquant + override `force`
  au niveau des serializers/endpoints (`show-materials`, `show-technicians`).
"""

from datetime import timedelta

from django.contrib.auth.models import User as DjangoUser
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from .conflicts import get_material_conflicts, get_technician_conflicts
from .models import Department, Material, Show, ShowMaterial, ShowTechnician, Technician, Venue


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
