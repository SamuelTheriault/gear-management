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
from .models import (
    Department,
    Material,
    Project,
    Show,
    ShowMaterial,
    ShowTechnician,
    Technician,
    Transport,
    Venue,
)


def _dt(hour, day=1):
    """Petit helper pour construire des datetimes aware sur une même journée de test."""
    return timezone.make_aware(timezone.datetime(2026, 9, day, hour, 0))


class ConflictLogicTests(TestCase):
    """Vérifie `conflicts.py` directement : chevauchement, limites de buffer, hiérarchie parent/enfant."""

    def setUp(self):
        self.project = Project.objects.create(name="Projet test")
        self.venue = Venue.objects.create(project=self.project, name="Salle test")
        self.material = Material.objects.create(project=self.project, name="Console son", category="audio")
        # 14h-16h, buffers par défaut (60 min) -> fenêtre effective 13h-17h
        self.show_a = Show.objects.create(
            project=self.project, title="Show A", venue=self.venue, event_type="rehearsal",
            start_datetime=_dt(14), end_datetime=_dt(16),
        )

    def test_no_conflict_when_material_unassigned(self):
        self.assertEqual(get_material_conflicts(self.show_a, self.material), [])

    def test_conflict_detected_on_overlap(self):
        # Show B : 16h30-18h -> fenêtre effective 15h30-19h -> chevauche 13h-17h de Show A
        show_b = Show.objects.create(
            project=self.project, title="Show B", venue=self.venue, event_type="rehearsal",
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
            project=self.project, title="Show B", venue=self.venue, event_type="rehearsal",
            start_datetime=_dt(18), end_datetime=_dt(20),
            buffer_before_minutes=60,  # fenêtre effective : 17h-21h
        )
        ShowMaterial.objects.create(show=self.show_a, material=self.material)

        self.assertEqual(get_material_conflicts(show_b, self.material), [])

    def test_no_conflict_beyond_buffers(self):
        # Show B largement après Show A, aucun chevauchement même avec buffers
        show_b = Show.objects.create(
            project=self.project, title="Show B", venue=self.venue, event_type="rehearsal",
            start_datetime=_dt(20), end_datetime=_dt(22),
        )
        ShowMaterial.objects.create(show=self.show_a, material=self.material)

        self.assertEqual(get_material_conflicts(show_b, self.material), [])

    def test_conflict_propagates_from_parent_to_child(self):
        kit = Material.objects.create(project=self.project, name="Kit Audio", category="audio")
        mic = Material.objects.create(project=self.project, name="Micro sans fil", category="audio", parent_material=kit)

        show_b = Show.objects.create(
            project=self.project, title="Show B", venue=self.venue, event_type="rehearsal",
            start_datetime=_dt(16, day=1) + timedelta(minutes=30), end_datetime=_dt(18),
        )
        # Le kit complet est assigné à Show A
        ShowMaterial.objects.create(show=self.show_a, material=kit)

        # Assigner un composant du kit (le micro) à Show B doit être signalé en conflit
        conflicts = get_material_conflicts(show_b, mic)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].material_id, kit.id)

    def test_conflict_propagates_from_child_to_parent(self):
        kit = Material.objects.create(project=self.project, name="Kit Audio", category="audio")
        mic = Material.objects.create(project=self.project, name="Micro sans fil", category="audio", parent_material=kit)

        show_b = Show.objects.create(
            project=self.project, title="Show B", venue=self.venue, event_type="rehearsal",
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
        kit = Material.objects.create(project=self.project, name="Kit Audio", category="audio")
        mic = Material.objects.create(project=self.project, name="Micro sans fil", category="audio", parent_material=kit)
        ShowMaterial.objects.create(show=self.show_a, material=mic)

        self.assertEqual(get_material_conflicts(self.show_a, kit), [])

    def test_technician_conflict_on_overlap(self):
        tech = Technician.objects.create(project=self.project, name="Alex Dupont", specialty="son")
        show_b = Show.objects.create(
            project=self.project, title="Show B", venue=self.venue, event_type="rehearsal",
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
            project=self.project, title="Show B", venue=self.venue, event_type="rehearsal",
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


class MaterialQuantityConflictTests(TestCase):
    """Vérifie la logique de capacité pour du matériel possédé en plusieurs
    exemplaires (`Material.quantity` / `ShowMaterial.quantity`, ajoutés le
    2026-07-19) : allocation partielle, dépassement, et non-régression du
    comportement binaire pour quantity=1 et pour la hiérarchie kit."""

    def setUp(self):
        self.project = Project.objects.create(name="Projet test")
        self.venue = Venue.objects.create(project=self.project, name="Salle test")
        # 20 rallonges électriques identiques en inventaire.
        self.material = Material.objects.create(project=self.project, name="Rallonge électrique", category="autre", quantity=20)
        # 14h-16h, buffers par défaut (60 min) -> fenêtre effective 13h-17h
        self.show_a = Show.objects.create(
            project=self.project, title="Show A", venue=self.venue, event_type="rehearsal",
            start_datetime=_dt(14), end_datetime=_dt(16),
        )

    def test_partial_allocation_within_capacity_is_not_a_conflict(self):
        # 12 assignées à Show A, on en demande 5 de plus sur une fenêtre qui
        # chevauche (12 + 5 = 17 <= 20) -> pas de conflit.
        ShowMaterial.objects.create(show=self.show_a, material=self.material, quantity=12)
        show_b = Show.objects.create(
            project=self.project, title="Show B", venue=self.venue, event_type="rehearsal",
            start_datetime=_dt(16, day=1) + timedelta(minutes=30), end_datetime=_dt(18),
        )
        conflicts = get_material_conflicts(show_b, self.material, quantity=5)
        self.assertEqual(conflicts, [])

    def test_allocation_exceeding_capacity_is_a_conflict(self):
        # 12 assignées à Show A, on en demande 10 de plus sur une fenêtre qui
        # chevauche (12 + 10 = 22 > 20) -> conflit, avec l'assignation de
        # Show A listée comme contributrice.
        sm = ShowMaterial.objects.create(show=self.show_a, material=self.material, quantity=12)
        show_b = Show.objects.create(
            project=self.project, title="Show B", venue=self.venue, event_type="rehearsal",
            start_datetime=_dt(16, day=1) + timedelta(minutes=30), end_datetime=_dt(18),
        )
        conflicts = get_material_conflicts(show_b, self.material, quantity=10)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].id, sm.id)

    def test_no_overlap_means_full_capacity_available_regardless_of_other_allocations(self):
        # 12 assignées à Show A ; Show C ne chevauche pas du tout -> les 20
        # unités sont disponibles pour Show C, peu importe Show A.
        ShowMaterial.objects.create(show=self.show_a, material=self.material, quantity=12)
        show_c = Show.objects.create(
            project=self.project, title="Show C", venue=self.venue, event_type="rehearsal",
            start_datetime=_dt(20), end_datetime=_dt(22),
        )
        conflicts = get_material_conflicts(show_c, self.material, quantity=20)
        self.assertEqual(conflicts, [])

    def test_default_quantity_of_one_preserves_binary_behaviour(self):
        # Non-régression : un matériel simple (quantity=1 par défaut) doit se
        # comporter exactement comme avant — tout chevauchement est un conflit.
        simple_material = Material.objects.create(project=self.project, name="Console son", category="audio")
        ShowMaterial.objects.create(show=self.show_a, material=simple_material)
        show_b = Show.objects.create(
            project=self.project, title="Show B", venue=self.venue, event_type="rehearsal",
            start_datetime=_dt(16, day=1) + timedelta(minutes=30), end_datetime=_dt(18),
        )
        conflicts = get_material_conflicts(show_b, simple_material)
        self.assertEqual(len(conflicts), 1)

    def test_exclude_id_ignores_own_allocation_when_updating_quantity(self):
        # Mettre à jour la quantité d'une assignation existante ne doit pas se
        # "conflicter" avec elle-même.
        sm = ShowMaterial.objects.create(show=self.show_a, material=self.material, quantity=12)
        conflicts = get_material_conflicts(self.show_a, self.material, exclude_id=sm.id, quantity=18)
        self.assertEqual(conflicts, [])


class MaterialQuantityHierarchyValidationTests(TestCase):
    """Vérifie que quantity > 1 est rejeté pour tout matériel qui participe à
    une hiérarchie kit (parent/enfant) — décision prise avec Samuel le
    2026-07-19 : un kit reste une unité conceptuelle unique."""

    def setUp(self):
        self.project = Project.objects.create(name="Projet test")
        self.client = APIClient()
        self.django_user = DjangoUser.objects.create_superuser('admin', 'admin@example.com', 'pw')
        self.client.force_authenticate(user=self.django_user)

    def test_cannot_create_material_with_quantity_and_parent(self):
        kit = Material.objects.create(project=self.project, name="Kit Audio", category="audio")
        response = self.client.post('/api/materials/', {
            'project': self.project.id,
            'name': "Micro sans fil", 'category': "audio", 'parent_material': kit.id, 'quantity': 3,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_set_quantity_above_one_on_material_with_components(self):
        kit = Material.objects.create(project=self.project, name="Kit Audio", category="audio")
        Material.objects.create(project=self.project, name="Micro sans fil", category="audio", parent_material=kit)

        response = self.client.patch(f'/api/materials/{kit.id}/', {'quantity': 2}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_set_parent_to_material_with_quantity_above_one(self):
        multi = Material.objects.create(project=self.project, name="Rallonge électrique", category="autre", quantity=20)
        response = self.client.post('/api/materials/', {
            'project': self.project.id,
            'name': "Composant", 'category': "autre", 'parent_material': multi.id,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_standalone_material_can_have_quantity_above_one(self):
        response = self.client.post('/api/materials/', {
            'project': self.project.id,
            'name': "Rallonge électrique", 'category': "autre", 'quantity': 20,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['quantity'], 20)


class VenueCodeTests(TestCase):
    """Vérifie `Venue.code` (ajouté le 2026-07-19) : normalisation en
    majuscules, unicité par projet (pas de contrainte DB — plusieurs codes
    vides doivent coexister), et exposition sur `TransportSerializer` pour un
    affichage compact départ/arrivée."""

    def setUp(self):
        self.client = APIClient()
        self.django_user = DjangoUser.objects.create_superuser('admin', 'admin@example.com', 'pw')
        self.client.force_authenticate(user=self.django_user)
        self.project = Project.objects.create(name="Projet test")

    def test_code_is_normalized_to_uppercase(self):
        venue = Venue.objects.create(project=self.project, name="Chapelle", code="chap")
        venue.refresh_from_db()
        self.assertEqual(venue.code, "CHAP")

    def test_code_defaults_to_blank(self):
        venue = Venue.objects.create(project=self.project, name="Salle test")
        self.assertEqual(venue.code, "")

    def test_duplicate_code_rejected_within_same_project(self):
        Venue.objects.create(project=self.project, name="Chapelle", code="CHAP")
        response = self.client.post('/api/venues/', {
            'project': self.project.id, 'name': "Chapelle annexe", 'code': "chap",
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('code', response.data)

    def test_same_code_allowed_in_different_projects(self):
        other_project = Project.objects.create(name="Autre projet")
        Venue.objects.create(project=self.project, name="Chapelle", code="CHAP")
        response = self.client.post('/api/venues/', {
            'project': other_project.id, 'name': "Chapelle", 'code': "CHAP",
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_multiple_venues_without_code_coexist(self):
        Venue.objects.create(project=self.project, name="Salle A")
        response = self.client.post('/api/venues/', {
            'project': self.project.id, 'name': "Salle B",
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_transport_serializer_exposes_venue_codes(self):
        origin = Venue.objects.create(project=self.project, name="Entrepôt", code="ENTR", is_storage=True)
        destination = Venue.objects.create(project=self.project, name="Chapelle", code="CHAP")
        show = Show.objects.create(
            project=self.project, title="Show", venue=destination, event_type="performance",
            start_datetime=_dt(14), end_datetime=_dt(16),
        )
        response = self.client.post('/api/transports/', {
            'show': show.id, 'transport_type': 'delivery',
            'origin_venue': origin.id, 'destination_venue': destination.id,
            'scheduled_datetime': _dt(8).isoformat(), 'estimated_duration_minutes': 60,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['origin_venue_code'], "ENTR")
        self.assertEqual(response.data['destination_venue_code'], "CHAP")


class MaterialActiveFlagTests(TestCase):
    """Vérifie `Material.is_active` (ajouté le 2026-07-19) : masqué de la
    liste par défaut, visible avec `?include_inactive=true`, toujours
    consultable individuellement par id peu importe son statut."""

    def setUp(self):
        self.project = Project.objects.create(name="Projet test")
        self.client = APIClient()
        self.django_user = DjangoUser.objects.create_superuser('admin', 'admin@example.com', 'pw')
        self.client.force_authenticate(user=self.django_user)

    def test_material_defaults_to_active(self):
        material = Material.objects.create(project=self.project, name="Console son", category="audio")
        self.assertTrue(material.is_active)

    def test_inactive_material_excluded_from_list_by_default(self):
        Material.objects.create(project=self.project, name="Rideau", category="decor", is_active=False)
        active = Material.objects.create(project=self.project, name="Console son", category="audio")

        response = self.client.get('/api/materials/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [m['name'] for m in response.data]
        self.assertIn(active.name, names)
        self.assertNotIn("Rideau", names)

    def test_include_inactive_returns_everything(self):
        Material.objects.create(project=self.project, name="Rideau", category="decor", is_active=False)
        Material.objects.create(project=self.project, name="Console son", category="audio")

        response = self.client.get('/api/materials/?include_inactive=true')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [m['name'] for m in response.data]
        self.assertIn("Rideau", names)
        self.assertIn("Console son", names)

    def test_retrieve_inactive_material_by_id_still_works(self):
        material = Material.objects.create(project=self.project, name="Rideau", category="decor", is_active=False)

        response = self.client.get(f'/api/materials/{material.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['name'], "Rideau")
        self.assertFalse(response.data['is_active'])


class StorageExemptionTests(TestCase):
    """Vérifie l'exemption d'entreposage (Venue.is_storage) — décision du 2026-07-18 :
    le matériel assigné à un Show dont le venue est un entrepôt ne déclenche et ne
    subit jamais de conflit matériel. Les techniciens, eux, restent soumis à la
    détection normale même sur un Show d'entrepôt."""

    def setUp(self):
        self.project = Project.objects.create(name="Projet test")
        self.real_venue = Venue.objects.create(project=self.project, name="Salle test")
        self.storage_venue = Venue.objects.create(project=self.project, name="Entrepôt Rosemont", is_storage=True)
        self.material = Material.objects.create(project=self.project, name="Console son", category="audio")
        self.technician = Technician.objects.create(project=self.project, name="Alex Dupont", specialty="son")

        # Show réel 14h-16h -> fenêtre effective 13h-17h
        self.show_real = Show.objects.create(
            project=self.project, title="Show réel", venue=self.real_venue, event_type="rehearsal",
            start_datetime=_dt(14), end_datetime=_dt(16),
        )
        # Show d'entrepôt qui chevauche complètement la fenêtre du show réel
        self.show_storage = Show.objects.create(
            project=self.project, title="Rangement", venue=self.storage_venue, event_type="storage",
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
            project=self.project, title="Autre show réel", venue=self.real_venue, event_type="performance",
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
        self.project = Project.objects.create(name="Projet test")
        self.venue_a = Venue.objects.create(project=self.project, name="Salle A")
        self.venue_b = Venue.objects.create(project=self.project, name="Entrepôt", is_storage=True)
        self.technician = Technician.objects.create(project=self.project, name="Alex Dupont", specialty="son")
        # Show 14h-16h -> fenêtre effective 13h-17h
        self.show = Show.objects.create(
            project=self.project, title="Show", venue=self.venue_a, event_type="performance",
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
        self.project = Project.objects.create(name="Projet test")
        self.user = DjangoUser.objects.create_superuser('admin', 'admin@test.com', 'testpass123')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        self.venue = Venue.objects.create(project=self.project, name="Salle test")
        self.material = Material.objects.create(project=self.project, name="Console son", category="audio")
        self.technician = Technician.objects.create(project=self.project, name="Alex Dupont", specialty="son")

        self.show_a = Show.objects.create(
            project=self.project, title="Show A", venue=self.venue, event_type="rehearsal",
            start_datetime=_dt(14), end_datetime=_dt(16),
        )
        self.show_b = Show.objects.create(
            project=self.project, title="Show B", venue=self.venue, event_type="rehearsal",
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
            project=self.project, title="Show C", venue=self.venue, event_type="rehearsal",
            start_datetime=_dt(20), end_datetime=_dt(22),
        )
        response = self.client.post('/api/show-materials/', {
            'show': show_c.id, 'material': self.material.id,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_transport_blocked_when_technician_already_on_show(self):
        # self.technician est déjà assigné à show_a (14h-16h, fenêtre 13h-17h)
        storage_venue = Venue.objects.create(project=self.project, name="Entrepôt", is_storage=True)
        response = self.client.post('/api/transports/', {
            'show': self.show_a.id, 'transport_type': 'delivery',
            'origin_venue': storage_venue.id, 'destination_venue': self.venue.id,
            'scheduled_datetime': _dt(12).isoformat(), 'estimated_duration_minutes': 90,
            'technician': self.technician.id,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('conflicts', response.data)

    def test_transport_succeeds_with_force(self):
        storage_venue = Venue.objects.create(project=self.project, name="Entrepôt", is_storage=True)
        response = self.client.post('/api/transports/', {
            'show': self.show_a.id, 'transport_type': 'delivery',
            'origin_venue': storage_venue.id, 'destination_venue': self.venue.id,
            'scheduled_datetime': _dt(12).isoformat(), 'estimated_duration_minutes': 90,
            'technician': self.technician.id, 'force': True,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_material_quantity_partial_allocation_succeeds(self):
        # 20 rallonges en inventaire, déjà 12 assignées à show_a (14h-16h).
        # En demander 5 de plus sur show_b (chevauche) reste sous la capacité.
        multi = Material.objects.create(project=self.project, name="Rallonge électrique", category="autre", quantity=20)
        ShowMaterial.objects.create(show=self.show_a, material=multi, quantity=12)
        response = self.client.post('/api/show-materials/', {
            'show': self.show_b.id, 'material': multi.id, 'quantity': 5,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_material_quantity_exceeding_capacity_blocked(self):
        multi = Material.objects.create(project=self.project, name="Rallonge électrique", category="autre", quantity=20)
        ShowMaterial.objects.create(show=self.show_a, material=multi, quantity=12)
        response = self.client.post('/api/show-materials/', {
            'show': self.show_b.id, 'material': multi.id, 'quantity': 10,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('conflicts', response.data)

    def test_material_quantity_exceeding_capacity_succeeds_with_force(self):
        multi = Material.objects.create(project=self.project, name="Rallonge électrique", category="autre", quantity=20)
        ShowMaterial.objects.create(show=self.show_a, material=multi, quantity=12)
        response = self.client.post('/api/show-materials/', {
            'show': self.show_b.id, 'material': multi.id, 'quantity': 10, 'force': True,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_material_quantity_above_total_owned_rejected_even_without_overlap(self):
        # Aucune autre assignation ne chevauche show_c : le rejet vient
        # uniquement du fait que 25 > quantité totale possédée (20), pas d'un
        # chevauchement — ce cas n'est pas overridable par force (voir
        # ShowMaterialSerializer.validate()).
        multi = Material.objects.create(project=self.project, name="Rallonge électrique", category="autre", quantity=20)
        show_c = Show.objects.create(
            project=self.project, title="Show C", venue=self.venue, event_type="rehearsal",
            start_datetime=_dt(20), end_datetime=_dt(22),
        )
        response = self.client.post('/api/show-materials/', {
            'show': show_c.id, 'material': multi.id, 'quantity': 25, 'force': True,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('quantity', response.data)

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
        self.project = Project.objects.create(name="Projet test")
        self.client = APIClient()
        self.django_user = DjangoUser.objects.create_superuser('admin', 'admin@example.com', 'pw')
        self.client.force_authenticate(user=self.django_user)
        self.venue = Venue.objects.create(project=self.project, name="Salle test")

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
        material = Material.objects.create(project=self.project, name="Console", category="audio", department=dept)

        response = self.client.get(f'/api/materials/{material.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['department_color'], "#F97316")

    def test_material_serializer_department_color_none_when_no_department(self):
        material = Material.objects.create(project=self.project, name="Console sans département", category="audio")

        response = self.client.get(f'/api/materials/{material.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data['department_color'])

    def test_show_material_serializer_exposes_department_color(self):
        dept = Department.objects.create(name="Vidéo", color="#22C55E")
        material = Material.objects.create(project=self.project, name="Projecteur", category="video", department=dept)
        show = Show.objects.create(
            project=self.project, title="Show couleur", venue=self.venue, event_type="rehearsal",
            start_datetime=_dt(14), end_datetime=_dt(16),
        )

        response = self.client.post('/api/show-materials/', {
            'show': show.id, 'material': material.id,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['department_color'], "#22C55E")


class ProjectScopingTests(TestCase):
    """Vérifie l'isolation par projet (`Project`, ajouté le 2026-07-19 à la demande de
    Samuel) : Venue/Material/Technician/Show isolés, Department resté global, blocage
    de tout mélange entre deux projets, filtrage `?project=<id>`."""

    def setUp(self):
        self.client = APIClient()
        self.django_user = DjangoUser.objects.create_superuser('admin', 'admin@example.com', 'pw')
        self.client.force_authenticate(user=self.django_user)

        self.project_a = Project.objects.create(name="Projet A")
        self.project_b = Project.objects.create(name="Projet B")

        self.venue_a = Venue.objects.create(project=self.project_a, name="Salle A")
        self.venue_b = Venue.objects.create(project=self.project_b, name="Salle B")
        self.material_a = Material.objects.create(project=self.project_a, name="Console A", category="audio")
        self.material_b = Material.objects.create(project=self.project_b, name="Console B", category="audio")
        self.technician_a = Technician.objects.create(project=self.project_a, name="Alex")
        self.technician_b = Technician.objects.create(project=self.project_b, name="Sam")
        self.show_a = Show.objects.create(
            project=self.project_a, title="Show A", venue=self.venue_a, event_type="rehearsal",
            start_datetime=_dt(14), end_datetime=_dt(16),
        )

    # --- Département : seul élément volontairement global (décision Samuel) ---

    def test_department_is_shared_across_projects(self):
        dept = Department.objects.create(name="Son")
        material_a = Material.objects.create(
            project=self.project_a, name="Console A2", category="audio", department=dept,
        )
        material_b = Material.objects.create(
            project=self.project_b, name="Console B2", category="audio", department=dept,
        )
        self.assertEqual(material_a.department_id, material_b.department_id)

    # --- Isolation : filtrage ?project=<id> ---

    def test_venue_list_filtered_by_project(self):
        response = self.client.get(f'/api/venues/?project={self.project_a.id}')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [v['name'] for v in response.data]
        self.assertIn("Salle A", names)
        self.assertNotIn("Salle B", names)

    def test_material_list_filtered_by_project(self):
        response = self.client.get(f'/api/materials/?project={self.project_b.id}')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [m['name'] for m in response.data]
        self.assertIn("Console B", names)
        self.assertNotIn("Console A", names)

    def test_list_without_project_filter_returns_everything(self):
        # Pas de filtre = pas de restriction — le frontend passera toujours
        # ?project=, mais l'API brute reste utilisable sans (voir ProjectFilteredMixin).
        response = self.client.get('/api/venues/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [v['name'] for v in response.data]
        self.assertIn("Salle A", names)
        self.assertIn("Salle B", names)

    # --- Isolation : blocage du mélange entre deux projets ---

    def test_cannot_assign_material_from_other_project_to_show(self):
        response = self.client.post('/api/show-materials/', {
            'show': self.show_a.id, 'material': self.material_b.id,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('material', response.data)

    def test_cannot_assign_technician_from_other_project_to_show(self):
        response = self.client.post('/api/show-technicians/', {
            'show': self.show_a.id, 'technician': self.technician_b.id,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('technician', response.data)

    def test_cannot_create_show_with_venue_from_other_project(self):
        response = self.client.post('/api/shows/', {
            'project': self.project_a.id, 'title': "Show mixte", 'venue': self.venue_b.id,
            'event_type': 'rehearsal',
            'start_datetime': _dt(14).isoformat(), 'end_datetime': _dt(16).isoformat(),
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('venue', response.data)

    def test_cannot_set_parent_material_from_other_project(self):
        response = self.client.post('/api/materials/', {
            'project': self.project_a.id, 'name': "Composant", 'category': "audio",
            'parent_material': self.material_b.id,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('parent_material', response.data)

    def test_cannot_set_storage_venue_from_other_project_on_material(self):
        response = self.client.post('/api/materials/', {
            'project': self.project_a.id, 'name': "Console rangée", 'category': "audio",
            'venue': self.venue_b.id,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('venue', response.data)

    def test_cannot_use_transport_venue_from_other_project(self):
        storage_a = Venue.objects.create(project=self.project_a, name="Entrepôt A", is_storage=True)
        response = self.client.post('/api/transports/', {
            'show': self.show_a.id, 'transport_type': 'delivery',
            'origin_venue': storage_a.id, 'destination_venue': self.venue_b.id,
            'scheduled_datetime': _dt(8).isoformat(), 'estimated_duration_minutes': 30,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # --- Same-project assignment still works normally ---

    def test_same_project_assignment_succeeds(self):
        response = self.client.post('/api/show-materials/', {
            'show': self.show_a.id, 'material': self.material_a.id,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    # --- Suppression protégée ---

    def test_cannot_delete_project_with_existing_data(self):
        from django.db.models import ProtectedError
        with self.assertRaises(ProtectedError):
            self.project_a.delete()

    def test_project_can_be_archived_instead_of_deleted(self):
        response = self.client.patch(f'/api/projects/{self.project_a.id}/', {
            'status': Project.STATUS_ARCHIVED,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.project_a.refresh_from_db()
        self.assertEqual(self.project_a.status, Project.STATUS_ARCHIVED)


class ProjectDuplicationTests(TestCase):
    """Vérifie `POST /api/projects/{id}/duplicate/` (ajouté le 2026-07-19) :
    copie lieux/matériel/techniciens vers un nouveau projet, hiérarchie de
    matériel préservée, AUCUNE assignation (shows/show_materials/
    show_technicians/transports) copiée, projet source intact."""

    def setUp(self):
        self.client = APIClient()
        self.django_user = DjangoUser.objects.create_superuser('admin', 'admin@example.com', 'pw')
        self.client.force_authenticate(user=self.django_user)

        self.source = Project.objects.create(name="Furies 2026", client_name="Festival Furies", notes="Notes 2026")
        self.dept = Department.objects.create(name="Son")

        self.storage_venue = Venue.objects.create(
            project=self.source, name="Entrepôt", is_storage=True,
        )
        self.stage_venue = Venue.objects.create(project=self.source, name="Salle principale")

        self.kit = Material.objects.create(
            project=self.source, name="Kit Audio", category="audio",
            venue=self.storage_venue, department=self.dept,
        )
        self.mic = Material.objects.create(
            project=self.source, name="Micro sans fil", category="audio",
            parent_material=self.kit, venue=self.storage_venue,
        )
        self.standalone = Material.objects.create(
            project=self.source, name="Rallonge", category="autre",
            quantity=20, is_active=False,
        )

        self.technician = Technician.objects.create(
            project=self.source, name="Alex Dupont", specialty="son", contact_info="alex@example.com",
        )

        self.show = Show.objects.create(
            project=self.source, title="Répétition générale", venue=self.stage_venue,
            event_type="rehearsal", start_datetime=_dt(14), end_datetime=_dt(16),
        )
        ShowMaterial.objects.create(show=self.show, material=self.kit)
        ShowTechnician.objects.create(show=self.show, technician=self.technician)
        Transport.objects.create(
            show=self.show, transport_type='delivery',
            origin_venue=self.storage_venue, destination_venue=self.stage_venue,
            scheduled_datetime=_dt(10), estimated_duration_minutes=30,
        )

    def test_name_is_required(self):
        response = self.client.post(f'/api/projects/{self.source.id}/duplicate/', {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('name', response.data)

    def test_creates_new_project_with_client_name_copied_by_default(self):
        response = self.client.post(f'/api/projects/{self.source.id}/duplicate/', {
            'name': "Furies 2027",
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        new_project_data = response.data['project']
        self.assertEqual(new_project_data['name'], "Furies 2027")
        self.assertEqual(new_project_data['client_name'], "Festival Furies")
        self.assertEqual(new_project_data['status'], Project.STATUS_ACTIVE)
        self.assertIsNone(new_project_data['start_date'])
        self.assertIsNone(new_project_data['end_date'])

    def test_notes_and_dates_are_not_copied(self):
        # Décision Samuel (2026-07-19) : contrairement à client_name, les notes
        # et les dates repartent à vide — spécifiques à chaque édition.
        response = self.client.post(f'/api/projects/{self.source.id}/duplicate/', {
            'name': "Furies 2027",
        }, format='json')
        self.assertEqual(response.data['project']['notes'], '')

    def test_client_name_override_is_respected(self):
        response = self.client.post(f'/api/projects/{self.source.id}/duplicate/', {
            'name': "Coproduction 2027", 'client_name': "Autre client",
        }, format='json')
        self.assertEqual(response.data['project']['client_name'], "Autre client")

    def test_copies_venues_materials_and_technicians_counts(self):
        response = self.client.post(f'/api/projects/{self.source.id}/duplicate/', {
            'name': "Furies 2027",
        }, format='json')
        self.assertEqual(response.data['copied'], {'venues': 2, 'materials': 3, 'technicians': 1})

    def test_no_assignments_are_copied(self):
        response = self.client.post(f'/api/projects/{self.source.id}/duplicate/', {
            'name': "Furies 2027",
        }, format='json')
        new_project_id = response.data['project']['id']
        self.assertEqual(Show.objects.filter(project_id=new_project_id).count(), 0)
        # Le show/l'assignation source, eux, doivent rester intacts.
        self.assertEqual(Show.objects.filter(project=self.source).count(), 1)
        self.assertEqual(ShowMaterial.objects.count(), 1)
        self.assertEqual(ShowTechnician.objects.count(), 1)
        self.assertEqual(Transport.objects.count(), 1)

    def test_material_hierarchy_is_preserved_with_remapped_ids(self):
        response = self.client.post(f'/api/projects/{self.source.id}/duplicate/', {
            'name': "Furies 2027",
        }, format='json')
        new_project_id = response.data['project']['id']

        new_kit = Material.objects.get(project_id=new_project_id, name="Kit Audio")
        new_mic = Material.objects.get(project_id=new_project_id, name="Micro sans fil")
        self.assertEqual(new_mic.parent_material_id, new_kit.id)
        # La hiérarchie copiée ne doit JAMAIS pointer vers du matériel du projet source.
        self.assertNotEqual(new_kit.id, self.kit.id)

    def test_material_venue_is_remapped_to_the_new_project(self):
        response = self.client.post(f'/api/projects/{self.source.id}/duplicate/', {
            'name': "Furies 2027",
        }, format='json')
        new_project_id = response.data['project']['id']

        new_kit = Material.objects.get(project_id=new_project_id, name="Kit Audio")
        new_storage_venue = Venue.objects.get(project_id=new_project_id, name="Entrepôt")
        self.assertEqual(new_kit.venue_id, new_storage_venue.id)
        self.assertNotEqual(new_kit.venue_id, self.storage_venue.id)

    def test_department_is_kept_as_is_not_duplicated(self):
        # Department est un référentiel commun à tous les projets — jamais remappé.
        response = self.client.post(f'/api/projects/{self.source.id}/duplicate/', {
            'name': "Furies 2027",
        }, format='json')
        new_project_id = response.data['project']['id']

        new_kit = Material.objects.get(project_id=new_project_id, name="Kit Audio")
        self.assertEqual(new_kit.department_id, self.dept.id)
        self.assertEqual(Department.objects.count(), 1)

    def test_inactive_material_is_copied_with_same_status(self):
        response = self.client.post(f'/api/projects/{self.source.id}/duplicate/', {
            'name': "Furies 2027",
        }, format='json')
        new_project_id = response.data['project']['id']

        new_standalone = Material.objects.get(project_id=new_project_id, name="Rallonge")
        self.assertFalse(new_standalone.is_active)
        self.assertEqual(new_standalone.quantity, 20)

    def test_source_project_is_left_untouched(self):
        materials_before = Material.objects.filter(project=self.source).count()
        venues_before = Venue.objects.filter(project=self.source).count()
        technicians_before = Technician.objects.filter(project=self.source).count()

        self.client.post(f'/api/projects/{self.source.id}/duplicate/', {'name': "Furies 2027"}, format='json')

        self.assertEqual(Material.objects.filter(project=self.source).count(), materials_before)
        self.assertEqual(Venue.objects.filter(project=self.source).count(), venues_before)
        self.assertEqual(Technician.objects.filter(project=self.source).count(), technicians_before)
        self.assertEqual(self.source.notes, "Notes 2026")
