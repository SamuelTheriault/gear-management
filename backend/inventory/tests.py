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
from django.test import TestCase
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import status
from rest_framework.test import APIClient

from .conflicts import (
    get_material_conflicts,
    get_project_conflicts,
    get_technician_conflicts,
    get_transport_conflicts,
    get_venue_conflicts,
)
from .models import (
    Material,
    MaterialCategory,
    Project,
    Show,
    ShowMaterial,
    ShowTechnician,
    Technician,
    Transport,
    TransportMaterial,
    TransportTechnician,
    Venue,
)
from .transport_autogen import regenerate_project_proposals
from .transport_coherence import (
    get_material_coherence_issues,
    get_project_coherence_report,
    get_project_horizon,
)


def _dt(hour, day=1):
    """Petit helper pour construire des datetimes aware sur une même journée de test."""
    return timezone.make_aware(timezone.datetime(2026, 9, day, hour, 0))


def _transport_avec_technicien(technician, **kwargs):
    """Crée un `Transport` et y affecte `technician`.

    Depuis le 2026-07-30, `Transport.technician` n'existe plus : les
    techniciens passent par la table de liaison `TransportTechnician` (un
    déplacement peut en mobiliser plusieurs). Ce helper garde les tests de
    conflit lisibles, où l'on ne veut qu'une personne.
    """
    transport = Transport.objects.create(**kwargs)
    TransportTechnician.objects.create(transport=transport, technician=technician)
    return transport


def _cat(project, name="Audio"):
    """Récupère la catégorie de matériel `name` du projet (voir MaterialCategory).

    Depuis le 2026-07-30, `Material.category` est une FK et non plus un slug
    figé : les tests passaient `category="audio"`. Les 9 catégories par défaut
    sont créées automatiquement à la création de chaque `Project` (signal
    `creer_categories_par_defaut`), donc un simple `get()` suffit ici — le
    `get_or_create` couvre le cas d'une catégorie de test hors défauts.
    """
    categorie, _ = MaterialCategory.objects.get_or_create(project=project, name=name)
    return categorie


class ConflictLogicTests(TestCase):
    """Vérifie `conflicts.py` directement : chevauchement, limites de buffer, hiérarchie parent/enfant."""

    def setUp(self):
        self.project = Project.objects.create(name="Projet test")
        self.venue = Venue.objects.create(project=self.project, name="Salle test")
        self.material = Material.objects.create(project=self.project, name="Console son", category=_cat(self.project, "Audio"))
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
        kit = Material.objects.create(project=self.project, name="Kit Audio", category=_cat(self.project, "Audio"))
        mic = Material.objects.create(project=self.project, name="Micro sans fil", category=_cat(self.project, "Audio"), parent_material=kit)

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
        kit = Material.objects.create(project=self.project, name="Kit Audio", category=_cat(self.project, "Audio"))
        mic = Material.objects.create(project=self.project, name="Micro sans fil", category=_cat(self.project, "Audio"), parent_material=kit)

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
        kit = Material.objects.create(project=self.project, name="Kit Audio", category=_cat(self.project, "Audio"))
        mic = Material.objects.create(project=self.project, name="Micro sans fil", category=_cat(self.project, "Audio"), parent_material=kit)
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
        self.material = Material.objects.create(project=self.project, name="Rallonge électrique", category=_cat(self.project, "Autre"), quantity=20)
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
        simple_material = Material.objects.create(project=self.project, name="Console son", category=_cat(self.project, "Audio"))
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
        # Lieu d'origine obligatoire à la création depuis le 2026-07-30.
        self.entrepot = Venue.objects.create(project=self.project, name="Entrepôt", is_storage=True)
        self.client = APIClient()
        self.django_user = DjangoUser.objects.create_superuser('admin', 'admin@example.com', 'pw')
        self.client.force_authenticate(user=self.django_user)

    def test_cannot_create_material_with_quantity_and_parent(self):
        kit = Material.objects.create(project=self.project, name="Kit Audio", category=_cat(self.project, "Audio"))
        response = self.client.post('/api/materials/', {
            'project': self.project.id,
            'name': "Micro sans fil", 'category': _cat(self.project, "Audio").id,
            'venue': self.entrepot.id, 'parent_material': kit.id, 'quantity': 3,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_set_quantity_above_one_on_material_with_components(self):
        kit = Material.objects.create(project=self.project, name="Kit Audio", category=_cat(self.project, "Audio"))
        Material.objects.create(project=self.project, name="Micro sans fil", category=_cat(self.project, "Audio"), parent_material=kit)

        response = self.client.patch(f'/api/materials/{kit.id}/', {'quantity': 2}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_set_parent_to_material_with_quantity_above_one(self):
        multi = Material.objects.create(project=self.project, name="Rallonge électrique", category=_cat(self.project, "Autre"), quantity=20)
        response = self.client.post('/api/materials/', {
            'project': self.project.id,
            'name': "Composant", 'category': _cat(self.project, "Autre").id,
            'venue': self.entrepot.id, 'parent_material': multi.id,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_standalone_material_can_have_quantity_above_one(self):
        response = self.client.post('/api/materials/', {
            'project': self.project.id,
            'name': "Rallonge électrique", 'category': _cat(self.project, "Autre").id,
            'venue': self.entrepot.id, 'quantity': 20,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['quantity'], 20)


class MaterialKitParentEligibilityTests(TestCase):
    """Vérifie `Material.is_kit_parent` (ajouté le 2026-08-02, demande de
    Samuel) : un matériel doit être explicitement activé comme parent avant
    qu'un autre puisse le choisir — décision actée avec lui : pas de bascule
    automatique sur les kits existants, à réactiver manuellement au cas par
    cas (voir la migration 0022, purement additive)."""

    def setUp(self):
        self.project = Project.objects.create(name="Projet test")
        self.entrepot = Venue.objects.create(project=self.project, name="Entrepôt", is_storage=True)
        self.client = APIClient()
        self.django_user = DjangoUser.objects.create_superuser('admin', 'admin@example.com', 'pw')
        self.client.force_authenticate(user=self.django_user)

    def test_cannot_set_parent_that_is_not_flagged_as_kit_parent(self):
        # Défaut : is_kit_parent=False, même pour un matériel qui a déjà des
        # composants créés directement en base (hors API) — voir schema.md.
        kit = Material.objects.create(project=self.project, name="Kit Audio", quantity=1, venue=self.entrepot)
        response = self.client.post('/api/materials/', {
            'project': self.project.id,
            'name': "Micro sans fil", 'category': _cat(self.project, "Audio").id,
            'venue': self.entrepot.id, 'parent_material': kit.id,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('parent_material', response.data)

    def test_can_set_parent_once_flagged_as_kit_parent(self):
        kit = Material.objects.create(
            project=self.project, name="Kit Audio", quantity=1, venue=self.entrepot, is_kit_parent=True,
        )
        response = self.client.post('/api/materials/', {
            'project': self.project.id,
            'name': "Micro sans fil", 'category': _cat(self.project, "Audio").id,
            'venue': self.entrepot.id, 'parent_material': kit.id,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['parent_material'], kit.id)

    def test_cannot_flag_material_as_kit_parent_with_quantity_above_one(self):
        response = self.client.post('/api/materials/', {
            'project': self.project.id,
            'name': "Rallonges", 'category': _cat(self.project, "Autre").id,
            'venue': self.entrepot.id, 'quantity': 20, 'is_kit_parent': True,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('is_kit_parent', response.data)

    def test_is_kit_parent_defaults_to_false_and_is_exposed(self):
        response = self.client.post('/api/materials/', {
            'project': self.project.id,
            'name': "Console", 'category': _cat(self.project, "Audio").id,
            'venue': self.entrepot.id,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertFalse(response.data['is_kit_parent'])


class MaterialKitParentAssignmentInheritanceTests(TestCase):
    """Vérifie l'héritage d'assignations spectacle (ajouté le 2026-08-02,
    demande de Samuel) : un composant qui vient de se faire rattacher à un kit
    déjà assigné à un ou plusieurs spectacles hérite automatiquement des mêmes
    assignations (ShowMaterial, quantity=1), qu'il vienne d'être créé ou
    qu'on l'y rattache plus tard — voir
    `_mirror_parent_show_material_assignments` dans serializers.py."""

    def setUp(self):
        self.project = Project.objects.create(name="Projet test")
        self.entrepot = Venue.objects.create(project=self.project, name="Entrepôt", is_storage=True)
        self.salle = Venue.objects.create(project=self.project, name="Chapelle")
        self.client = APIClient()
        self.django_user = DjangoUser.objects.create_superuser('admin', 'admin@example.com', 'pw')
        self.client.force_authenticate(user=self.django_user)
        self.kit = Material.objects.create(
            project=self.project, name="Kit son", quantity=1, venue=self.entrepot, is_kit_parent=True,
        )
        self.show = Show.objects.create(
            project=self.project, title="Vertiges", venue=self.salle,
            event_type='performance', start_datetime=_dt(20), end_datetime=_dt(22),
        )
        self.autre_show = Show.objects.create(
            project=self.project, title="Vertiges (relâche)", venue=self.salle,
            event_type='performance', start_datetime=_dt(20, day=2), end_datetime=_dt(22, day=2),
        )

    def test_new_component_inherits_parent_assignments_on_create(self):
        ShowMaterial.objects.create(show=self.show, material=self.kit, quantity=1, is_rental=True, rental_vendor="Solotech")
        response = self.client.post('/api/materials/', {
            'project': self.project.id,
            'name': "Micro sans fil", 'category': _cat(self.project, "Audio").id,
            'venue': self.entrepot.id, 'parent_material': self.kit.id,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        micro = Material.objects.get(id=response.data['id'])
        assignment = ShowMaterial.objects.get(show=self.show, material=micro)
        self.assertEqual(assignment.quantity, 1)
        self.assertTrue(assignment.is_rental)
        self.assertEqual(assignment.rental_vendor, "Solotech")

    def test_new_component_inherits_all_parent_shows(self):
        ShowMaterial.objects.create(show=self.show, material=self.kit)
        ShowMaterial.objects.create(show=self.autre_show, material=self.kit)
        response = self.client.post('/api/materials/', {
            'project': self.project.id,
            'name': "Micro sans fil", 'category': _cat(self.project, "Audio").id,
            'venue': self.entrepot.id, 'parent_material': self.kit.id,
        }, format='json')
        micro = Material.objects.get(id=response.data['id'])
        self.assertEqual(
            set(ShowMaterial.objects.filter(material=micro).values_list('show_id', flat=True)),
            {self.show.id, self.autre_show.id},
        )

    def test_component_without_prior_assignment_inherits_nothing(self):
        # Le kit n'est encore assigné nulle part : aucune ligne à copier.
        response = self.client.post('/api/materials/', {
            'project': self.project.id,
            'name': "Micro sans fil", 'category': _cat(self.project, "Audio").id,
            'venue': self.entrepot.id, 'parent_material': self.kit.id,
        }, format='json')
        micro = Material.objects.get(id=response.data['id'])
        self.assertEqual(ShowMaterial.objects.filter(material=micro).count(), 0)

    def test_attaching_existing_material_to_kit_later_also_inherits(self):
        ShowMaterial.objects.create(show=self.show, material=self.kit)
        libre = Material.objects.create(project=self.project, name="Micro", quantity=1, venue=self.entrepot)
        response = self.client.patch(f'/api/materials/{libre.id}/', {
            'parent_material': self.kit.id,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(ShowMaterial.objects.filter(show=self.show, material=libre).exists())

    def test_patch_without_changing_parent_does_not_duplicate_or_reinherit(self):
        # Retirer une assignation copiée puis re-sauvegarder la fiche (sans
        # toucher au parent) ne doit pas la faire réapparaître.
        ShowMaterial.objects.create(show=self.show, material=self.kit)
        micro = Material.objects.create(
            project=self.project, name="Micro", quantity=1, venue=self.entrepot, parent_material=self.kit,
        )
        ShowMaterial.objects.create(show=self.show, material=micro)
        ShowMaterial.objects.get(show=self.show, material=micro).delete()

        response = self.client.patch(f'/api/materials/{micro.id}/', {'notes': "RAS"}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(ShowMaterial.objects.filter(show=self.show, material=micro).exists())

    def test_does_not_duplicate_if_component_already_assigned_to_same_show(self):
        ShowMaterial.objects.create(show=self.show, material=self.kit)
        libre = Material.objects.create(project=self.project, name="Micro", quantity=1, venue=self.entrepot)
        ShowMaterial.objects.create(show=self.show, material=libre, quantity=1, is_rental=True)

        response = self.client.patch(f'/api/materials/{libre.id}/', {
            'parent_material': self.kit.id,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        assignment = ShowMaterial.objects.get(show=self.show, material=libre)
        # L'assignation déjà existante n'est pas écrasée par la copie.
        self.assertTrue(assignment.is_rental)


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

    def test_patch_code_only_on_existing_venue(self):
        # Cas du frontend (fiche lieu) : renseigner après coup le code d'un
        # lieu créé sans code, avec un PATCH ne portant que ce champ — donc
        # sans `project` dans les données, que `validate_code` doit alors
        # retrouver depuis l'instance.
        venue = Venue.objects.create(project=self.project, name="Chapelle")
        response = self.client.patch(f'/api/venues/{venue.id}/', {'code': "chap"}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        venue.refresh_from_db()
        self.assertEqual(venue.code, "CHAP")

    def test_patch_code_unchanged_is_not_a_duplicate_of_itself(self):
        venue = Venue.objects.create(project=self.project, name="Chapelle", code="CHAP")
        response = self.client.patch(f'/api/venues/{venue.id}/', {'code': "CHAP"}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_patch_code_rejected_if_taken_by_another_venue(self):
        Venue.objects.create(project=self.project, name="Chapelle", code="CHAP")
        autre = Venue.objects.create(project=self.project, name="Salle 2")
        response = self.client.patch(f'/api/venues/{autre.id}/', {'code': "chap"}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('code', response.data)

    def test_patch_can_clear_code(self):
        venue = Venue.objects.create(project=self.project, name="Chapelle", code="CHAP")
        response = self.client.patch(f'/api/venues/{venue.id}/', {'code': ""}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        venue.refresh_from_db()
        self.assertEqual(venue.code, "")

    def test_patch_full_venue_fields(self):
        # Cas du frontend (bouton « Modifier la fiche ») : un seul PATCH qui
        # porte sur tous les champs éditables du lieu à la fois.
        venue = Venue.objects.create(project=self.project, name="Chapelle")
        response = self.client.patch(f'/api/venues/{venue.id}/', {
            'name': "Chapelle historique",
            'code': "chap",
            'address': "100 rue Sainte-Catherine, Montréal",
            'contact_name': "Marie Tremblay",
            'contact_info': "514-555-0100",
            'notes': "Quai de chargement à l'arrière.",
            'is_storage': False,
            'latitude': "45.508888",
            'longitude': "-73.561668",
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        venue.refresh_from_db()
        self.assertEqual(venue.name, "Chapelle historique")
        self.assertEqual(venue.code, "CHAP")
        self.assertEqual(venue.contact_name, "Marie Tremblay")
        self.assertEqual(str(venue.latitude), "45.508888")
        self.assertEqual(str(venue.longitude), "-73.561668")

    def test_patch_can_clear_gps_coordinates(self):
        # Le frontend envoie `null` (pas la chaîne vide) quand on vide les
        # champs latitude/longitude — ils sont nullables côté modèle.
        venue = Venue.objects.create(
            project=self.project, name="Chapelle",
            latitude="45.508888", longitude="-73.561668",
        )
        response = self.client.patch(f'/api/venues/{venue.id}/', {
            'latitude': None, 'longitude': None,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        venue.refresh_from_db()
        self.assertIsNone(venue.latitude)
        self.assertIsNone(venue.longitude)

    def test_patch_can_toggle_is_storage(self):
        venue = Venue.objects.create(project=self.project, name="Chapelle")
        response = self.client.patch(f'/api/venues/{venue.id}/', {'is_storage': True}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        venue.refresh_from_db()
        self.assertTrue(venue.is_storage)

    def test_patch_rejects_blank_name(self):
        venue = Venue.objects.create(project=self.project, name="Chapelle")
        response = self.client.patch(f'/api/venues/{venue.id}/', {'name': ""}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('name', response.data)

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
        material = Material.objects.create(project=self.project, name="Console son", category=_cat(self.project, "Audio"))
        self.assertTrue(material.is_active)

    def test_inactive_material_excluded_from_list_by_default(self):
        Material.objects.create(project=self.project, name="Rideau", category=_cat(self.project, "Décor"), is_active=False)
        active = Material.objects.create(project=self.project, name="Console son", category=_cat(self.project, "Audio"))

        response = self.client.get('/api/materials/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [m['name'] for m in response.data]
        self.assertIn(active.name, names)
        self.assertNotIn("Rideau", names)

    def test_include_inactive_returns_everything(self):
        Material.objects.create(project=self.project, name="Rideau", category=_cat(self.project, "Décor"), is_active=False)
        Material.objects.create(project=self.project, name="Console son", category=_cat(self.project, "Audio"))

        response = self.client.get('/api/materials/?include_inactive=true')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [m['name'] for m in response.data]
        self.assertIn("Rideau", names)
        self.assertIn("Console son", names)

    def test_retrieve_inactive_material_by_id_still_works(self):
        material = Material.objects.create(project=self.project, name="Rideau", category=_cat(self.project, "Décor"), is_active=False)

        response = self.client.get(f'/api/materials/{material.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['name'], "Rideau")
        self.assertFalse(response.data['is_active'])


class VenueConflictTests(TestCase):
    """Vérifie `get_venue_conflicts` et la validation bloquante correspondante
    sur `ShowSerializer` (décision du 2026-07-19) : deux spectacles ne
    peuvent pas se chevaucher dans le même lieu, indépendamment de tout
    matériel/technicien partagé — sauf exemption d'entreposage."""

    def setUp(self):
        self.client = APIClient()
        self.django_user = DjangoUser.objects.create_superuser('admin', 'admin@example.com', 'pw')
        self.client.force_authenticate(user=self.django_user)
        self.project = Project.objects.create(name="Projet test")
        self.venue = Venue.objects.create(project=self.project, name="Chapelle")
        # 14h-16h, buffers par défaut (60 min) -> fenêtre effective 13h-17h
        self.show_a = Show.objects.create(
            project=self.project, title="Show A", venue=self.venue, event_type="rehearsal",
            start_datetime=_dt(14), end_datetime=_dt(16),
        )

    def test_no_conflict_when_venue_unused(self):
        other_venue = Venue.objects.create(project=self.project, name="Autre salle")
        self.assertEqual(get_venue_conflicts(other_venue, _dt(14), _dt(16)), [])

    def test_conflict_detected_on_overlap_same_venue(self):
        # 15h-17h chevauche la fenêtre effective 13h-17h de Show A
        conflicts = get_venue_conflicts(self.venue, _dt(15), _dt(17))
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].id, self.show_a.id)

    def test_no_conflict_beyond_buffers(self):
        conflicts = get_venue_conflicts(self.venue, _dt(20), _dt(22))
        self.assertEqual(conflicts, [])

    def test_no_conflict_different_venue_even_if_overlapping(self):
        other_venue = Venue.objects.create(project=self.project, name="Autre salle")
        conflicts = get_venue_conflicts(other_venue, _dt(14), _dt(16))
        self.assertEqual(conflicts, [])

    def test_exclude_id_excludes_the_show_itself(self):
        conflicts = get_venue_conflicts(self.venue, _dt(14), _dt(16), exclude_id=self.show_a.id)
        self.assertEqual(conflicts, [])

    def test_storage_venue_is_exempt(self):
        storage_venue = Venue.objects.create(project=self.project, name="Entrepôt", is_storage=True)
        Show.objects.create(
            project=self.project, title="Rangement A", venue=storage_venue, event_type="storage",
            start_datetime=_dt(14), end_datetime=_dt(16),
        )
        conflicts = get_venue_conflicts(storage_venue, _dt(14), _dt(16))
        self.assertEqual(conflicts, [])

    def test_api_blocks_overlapping_show_in_same_venue(self):
        response = self.client.post('/api/shows/', {
            'project': self.project.id, 'title': "Show B", 'venue': self.venue.id, 'event_type': 'rehearsal',
            'start_datetime': _dt(15).isoformat(), 'end_datetime': _dt(17).isoformat(),
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('conflicts', response.data)

    def test_api_allows_overlapping_show_with_force(self):
        response = self.client.post('/api/shows/', {
            'project': self.project.id, 'title': "Show B", 'venue': self.venue.id, 'event_type': 'rehearsal',
            'start_datetime': _dt(15).isoformat(), 'end_datetime': _dt(17).isoformat(), 'force': True,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_api_allows_overlapping_show_in_different_venue(self):
        other_venue = Venue.objects.create(project=self.project, name="Autre salle")
        response = self.client.post('/api/shows/', {
            'project': self.project.id, 'title': "Show B", 'venue': other_venue.id, 'event_type': 'rehearsal',
            'start_datetime': _dt(15).isoformat(), 'end_datetime': _dt(17).isoformat(),
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_api_allows_non_overlapping_show_same_venue(self):
        response = self.client.post('/api/shows/', {
            'project': self.project.id, 'title': "Show B", 'venue': self.venue.id, 'event_type': 'rehearsal',
            'start_datetime': _dt(20).isoformat(), 'end_datetime': _dt(22).isoformat(),
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_updating_show_does_not_conflict_with_itself(self):
        response = self.client.patch(f'/api/shows/{self.show_a.id}/', {
            'notes': "mise à jour sans changement d'horaire",
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_show_conflicts_endpoint_lists_venue_conflict(self):
        self.client.post('/api/shows/', {
            'project': self.project.id, 'title': "Show B", 'venue': self.venue.id, 'event_type': 'rehearsal',
            'start_datetime': _dt(15).isoformat(), 'end_datetime': _dt(17).isoformat(), 'force': True,
        }, format='json')
        response = self.client.get(f'/api/shows/{self.show_a.id}/conflicts/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['venue_conflicts']), 1)


class StorageExemptionTests(TestCase):
    """Vérifie l'exemption d'entreposage (Venue.is_storage) — décision du 2026-07-18 :
    le matériel assigné à un Show dont le venue est un entrepôt ne déclenche et ne
    subit jamais de conflit matériel. Les techniciens, eux, restent soumis à la
    détection normale même sur un Show d'entrepôt."""

    def setUp(self):
        self.project = Project.objects.create(name="Projet test")
        self.real_venue = Venue.objects.create(project=self.project, name="Salle test")
        self.storage_venue = Venue.objects.create(project=self.project, name="Entrepôt Rosemont", is_storage=True)
        self.material = Material.objects.create(project=self.project, name="Console son", category=_cat(self.project, "Audio"))
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
        _transport_avec_technicien(
            show=self.show, transport_type='delivery',
            origin_venue=self.venue_b, destination_venue=self.venue_a,
            scheduled_datetime=_dt(12), estimated_duration_minutes=90,
            technician=self.technician,
        )
        conflicts = get_technician_conflicts(self.show, self.technician)
        self.assertEqual(len(conflicts), 1)

    def test_two_transports_for_same_technician_conflict(self):
        _transport_avec_technicien(
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
        transport = _transport_avec_technicien(
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


class TransportWindowValidationAPITests(TestCase):
    """Vérifie la fenêtre départ/arrivée d'un déplacement (décision Samuel du
    2026-07-30, voir conflicts.py : `find_departure_show`/`find_arrival_show`/
    `validate_transport_window`) — le déplacement doit avoir lieu entre la fin
    effective du spectacle de départ et le début effectif du spectacle
    d'arrivée, bloquant + `force`."""

    def setUp(self):
        self.project = Project.objects.create(name="Projet test")
        self.user = DjangoUser.objects.create_superuser('admin', 'admin@test.com', 'testpass123')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        self.venue_a = Venue.objects.create(project=self.project, name="Salle A")
        self.venue_b = Venue.objects.create(project=self.project, name="Salle B")
        self.storage = Venue.objects.create(project=self.project, name="Entrepôt", is_storage=True)

        # 14h-16h, buffers par défaut (60 min) -> fenêtre effective 13h-17h
        self.departure_show = Show.objects.create(
            project=self.project, title="Départ", venue=self.venue_a, event_type="rehearsal",
            start_datetime=_dt(14), end_datetime=_dt(16),
        )
        # 20h-22h -> fenêtre effective 19h-23h
        self.arrival_show = Show.objects.create(
            project=self.project, title="Arrivée", venue=self.venue_b, event_type="rehearsal",
            start_datetime=_dt(20), end_datetime=_dt(22),
        )

    def _post(self, **overrides):
        payload = {
            'show': self.arrival_show.id, 'transport_type': 'delivery',
            'origin_venue': self.venue_a.id, 'destination_venue': self.venue_b.id,
            'scheduled_datetime': _dt(17).isoformat(), 'estimated_duration_minutes': 60,
        }
        payload.update(overrides)
        return self.client.post('/api/transports/', payload, format='json')

    def test_scheduled_right_at_departure_effective_end_succeeds(self):
        # Fin effective du départ = 17h00 pile -> "tout de suite après" est permis.
        response = self._post(scheduled_datetime=_dt(17).isoformat())
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_scheduled_before_departure_effective_end_blocked(self):
        response = self._post(scheduled_datetime=_dt(16).isoformat(), estimated_duration_minutes=30)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('departure_show', response.data)
        # `response.data` sur une erreur 400 passe par `ValidationError`, qui
        # enveloppe récursivement les valeurs en `ErrorDetail` (str) — voir
        # aussi le pattern déjà en place pour `conflicts` ailleurs (material_id/
        # show_id). Comparaison en texte, pas en int, pour cette raison.
        self.assertEqual(str(response.data['departure_show']['id']), str(self.departure_show.id))

    def test_ends_after_arrival_effective_start_blocked(self):
        # 18h + 90 min = fenêtre jusqu'à 19h30, dépasse le début effectif de l'arrivée (19h00)
        response = self._post(scheduled_datetime=_dt(18).isoformat(), estimated_duration_minutes=90)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('arrival_show', response.data)
        self.assertEqual(str(response.data['arrival_show']['id']), str(self.arrival_show.id))

    def test_force_bypasses_window_violation(self):
        response = self._post(scheduled_datetime=_dt(16).isoformat(), estimated_duration_minutes=30, force=True)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_storage_origin_has_no_lower_bound(self):
        # Origine = entrepôt : pas de spectacle de départ, donc pas de borne basse.
        response = self._post(origin_venue=self.storage.id, scheduled_datetime=_dt(1).isoformat())
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_pickup_uses_show_as_departure_and_deduces_arrival(self):
        # Ramassage : `show` = spectacle de départ ; l'arrivée est déduite du
        # lieu de destination (venue_b, où se trouve `arrival_show`).
        response = self.client.post('/api/transports/', {
            'show': self.departure_show.id, 'transport_type': 'pickup',
            'origin_venue': self.venue_a.id, 'destination_venue': self.venue_b.id,
            'scheduled_datetime': _dt(18).isoformat(), 'estimated_duration_minutes': 30,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Trop tard : dépasse le début effectif de l'arrivée.
        response = self.client.post('/api/transports/', {
            'show': self.departure_show.id, 'transport_type': 'pickup',
            'origin_venue': self.venue_a.id, 'destination_venue': self.venue_b.id,
            'scheduled_datetime': (_dt(18) + timedelta(hours=1, minutes=30)).isoformat(),
            'estimated_duration_minutes': 30,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('arrival_show', response.data)

    def test_reference_shows_exposed_on_read(self):
        transport = Transport.objects.create(
            show=self.arrival_show, transport_type='delivery',
            origin_venue=self.venue_a, destination_venue=self.venue_b,
            scheduled_datetime=_dt(17), estimated_duration_minutes=60,
        )
        response = self.client.get(f'/api/transports/{transport.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['departure_show']['id'], self.departure_show.id)
        self.assertEqual(response.data['arrival_show']['id'], self.arrival_show.id)

    def test_reference_shows_null_when_no_show_at_venue(self):
        # Origine = entrepôt : aucun spectacle de départ à déduire.
        transport = Transport.objects.create(
            show=self.arrival_show, transport_type='delivery',
            origin_venue=self.storage, destination_venue=self.venue_b,
            scheduled_datetime=_dt(10), estimated_duration_minutes=60,
        )
        response = self.client.get(f'/api/transports/{transport.id}/')
        self.assertIsNone(response.data['departure_show'])
        self.assertEqual(response.data['arrival_show']['id'], self.arrival_show.id)


class ConflictAPITests(TestCase):
    """Vérifie le comportement bloquant + override au niveau de l'API (squelette DRF)."""

    def setUp(self):
        self.project = Project.objects.create(name="Projet test")
        self.user = DjangoUser.objects.create_superuser('admin', 'admin@test.com', 'testpass123')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        self.venue = Venue.objects.create(project=self.project, name="Salle test")
        self.material = Material.objects.create(project=self.project, name="Console son", category=_cat(self.project, "Audio"))
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
            'technicians': [{'technician': self.technician.id}],
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('conflicts', response.data)

    def test_transport_succeeds_with_force(self):
        storage_venue = Venue.objects.create(project=self.project, name="Entrepôt", is_storage=True)
        response = self.client.post('/api/transports/', {
            'show': self.show_a.id, 'transport_type': 'delivery',
            'origin_venue': storage_venue.id, 'destination_venue': self.venue.id,
            'scheduled_datetime': _dt(12).isoformat(), 'estimated_duration_minutes': 90,
            'technicians': [{'technician': self.technician.id}], 'force': True,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_material_quantity_partial_allocation_succeeds(self):
        # 20 rallonges en inventaire, déjà 12 assignées à show_a (14h-16h).
        # En demander 5 de plus sur show_b (chevauche) reste sous la capacité.
        multi = Material.objects.create(project=self.project, name="Rallonge électrique", category=_cat(self.project, "Autre"), quantity=20)
        ShowMaterial.objects.create(show=self.show_a, material=multi, quantity=12)
        response = self.client.post('/api/show-materials/', {
            'show': self.show_b.id, 'material': multi.id, 'quantity': 5,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_material_quantity_exceeding_capacity_blocked(self):
        multi = Material.objects.create(project=self.project, name="Rallonge électrique", category=_cat(self.project, "Autre"), quantity=20)
        ShowMaterial.objects.create(show=self.show_a, material=multi, quantity=12)
        response = self.client.post('/api/show-materials/', {
            'show': self.show_b.id, 'material': multi.id, 'quantity': 10,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('conflicts', response.data)

    def test_material_quantity_exceeding_capacity_succeeds_with_force(self):
        multi = Material.objects.create(project=self.project, name="Rallonge électrique", category=_cat(self.project, "Autre"), quantity=20)
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
        multi = Material.objects.create(project=self.project, name="Rallonge électrique", category=_cat(self.project, "Autre"), quantity=20)
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


class ProjectConflictsAPITests(TestCase):
    """Vérifie `GET /api/projects/{id}/conflicts/` (`ProjectViewSet.conflicts` →
    `get_project_conflicts`, conflicts.py, ajouté le 2026-07-30) — vue
    d'ensemble dédupliquée des conflits pour l'écran « Conflits » du
    frontend, distincte de `ShowViewSet.conflicts` qui répond par spectacle."""

    def setUp(self):
        self.project = Project.objects.create(name="Projet test")
        self.user = DjangoUser.objects.create_superuser('admin', 'admin@test.com', 'testpass123')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        self.venue = Venue.objects.create(project=self.project, name="Salle test")
        self.other_venue = Venue.objects.create(project=self.project, name="Autre salle")
        self.material = Material.objects.create(project=self.project, name="Console son", category=_cat(self.project, "Audio"))
        self.technician = Technician.objects.create(project=self.project, name="Alex Dupont", specialty="son")

        # Lieux différents par défaut : les tests matériel/technicien ne
        # doivent pas hériter d'un conflit de lieu involontaire. Le test dédié
        # au conflit de lieu recrée sa propre paire de shows au même lieu.
        self.show_a = Show.objects.create(
            project=self.project, title="Show A", venue=self.venue, event_type="rehearsal",
            start_datetime=_dt(14), end_datetime=_dt(16),
        )
        self.show_b = Show.objects.create(
            project=self.project, title="Show B", venue=self.other_venue, event_type="rehearsal",
            start_datetime=_dt(16) + timedelta(minutes=30), end_datetime=_dt(18),
        )

    def test_no_conflicts_returns_empty_report(self):
        response = self.client.get(f'/api/projects/{self.project.id}/conflicts/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['conflict_count'], 0)
        self.assertEqual(response.data['venue_conflicts'], [])
        self.assertEqual(response.data['material_conflicts'], [])
        self.assertEqual(response.data['technician_conflicts'], [])

    def test_material_conflict_appears_once_not_twice(self):
        ShowMaterial.objects.create(show=self.show_a, material=self.material)
        self.client.post('/api/show-materials/', {
            'show': self.show_b.id, 'material': self.material.id, 'force': True,
        }, format='json')

        response = self.client.get(f'/api/projects/{self.project.id}/conflicts/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Une seule paire, pas une par show malgré le chevauchement bidirectionnel.
        self.assertEqual(len(response.data['material_conflicts']), 1)
        pair = response.data['material_conflicts'][0]
        show_ids = {pair['a']['show_id'], pair['b']['show_id']}
        self.assertEqual(show_ids, {self.show_a.id, self.show_b.id})
        self.assertEqual(response.data['conflict_count'], 1)

    def test_technician_conflict_appears_once(self):
        ShowTechnician.objects.create(show=self.show_a, technician=self.technician)
        self.client.post('/api/show-technicians/', {
            'show': self.show_b.id, 'technician': self.technician.id, 'force': True,
        }, format='json')

        response = self.client.get(f'/api/projects/{self.project.id}/conflicts/')
        self.assertEqual(len(response.data['technician_conflicts']), 1)

    def test_venue_conflict_appears_once(self):
        # Deux shows créés directement via l'ORM (donc sans passer par
        # ShowSerializer.validate()) partageant le même lieu et se
        # chevauchant (16h30 < 17h, fenêtres effectives bufferisées).
        Show.objects.create(
            project=self.project, title="Show C", venue=self.venue, event_type="rehearsal",
            start_datetime=_dt(16) + timedelta(minutes=30), end_datetime=_dt(18),
        )
        response = self.client.get(f'/api/projects/{self.project.id}/conflicts/')
        self.assertEqual(len(response.data['venue_conflicts']), 1)
        self.assertEqual(response.data['conflict_count'], 1)

    def test_conflicts_scoped_to_project(self):
        # Un conflit dans un autre projet ne doit jamais apparaître ici.
        other_project = Project.objects.create(name="Autre projet")
        other_venue = Venue.objects.create(project=other_project, name="Salle autre projet")
        other_material = Material.objects.create(project=other_project, name="Autre console", category=_cat(other_project, "Audio"))
        show_x = Show.objects.create(
            project=other_project, title="Show X", venue=other_venue, event_type="rehearsal",
            start_datetime=_dt(14), end_datetime=_dt(16),
        )
        show_y = Show.objects.create(
            project=other_project, title="Show Y", venue=other_venue, event_type="rehearsal",
            start_datetime=_dt(15), end_datetime=_dt(17),
        )
        ShowMaterial.objects.create(show=show_x, material=other_material)
        ShowMaterial.objects.create(show=show_y, material=other_material)

        response = self.client.get(f'/api/projects/{self.project.id}/conflicts/')
        self.assertEqual(response.data['conflict_count'], 0)


class MaterialCategorySerializerTests(TestCase):
    """Vérifie que `Material.category` est correctement propagé par les serializers
    (voir serializers.py) — remplace `DepartmentColorTests`, retirée le 2026-07-29 avec
    le modèle `Department` (voir migration `0013_remove_department`)."""

    def setUp(self):
        self.project = Project.objects.create(name="Projet test")
        self.client = APIClient()
        self.django_user = DjangoUser.objects.create_superuser('admin', 'admin@example.com', 'pw')
        self.client.force_authenticate(user=self.django_user)
        self.venue = Venue.objects.create(project=self.project, name="Salle test")

    def test_show_material_serializer_exposes_material_category(self):
        material = Material.objects.create(project=self.project, name="Projecteur", category=_cat(self.project, "Vidéo"))
        show = Show.objects.create(
            project=self.project, title="Show catégorie", venue=self.venue, event_type="rehearsal",
            start_datetime=_dt(14), end_datetime=_dt(16),
        )

        response = self.client.post('/api/show-materials/', {
            'show': show.id, 'material': material.id,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['material_category'], _cat(self.project, "Vidéo").id)
        self.assertEqual(response.data['material_category_name'], "Vidéo")


class ProjectScopingTests(TestCase):
    """Vérifie l'isolation par projet (`Project`, ajouté le 2026-07-19 à la demande de
    Samuel) : Venue/Material/Technician/Show isolés, blocage de tout mélange entre deux
    projets, filtrage `?project=<id>`."""

    def setUp(self):
        self.client = APIClient()
        self.django_user = DjangoUser.objects.create_superuser('admin', 'admin@example.com', 'pw')
        self.client.force_authenticate(user=self.django_user)

        self.project_a = Project.objects.create(name="Projet A")
        self.project_b = Project.objects.create(name="Projet B")

        self.venue_a = Venue.objects.create(project=self.project_a, name="Salle A")
        self.venue_b = Venue.objects.create(project=self.project_b, name="Salle B")
        self.material_a = Material.objects.create(project=self.project_a, name="Console A", category=_cat(self.project_a, "Audio"))
        self.material_b = Material.objects.create(project=self.project_b, name="Console B", category=_cat(self.project_b, "Audio"))
        self.technician_a = Technician.objects.create(project=self.project_a, name="Alex")
        self.technician_b = Technician.objects.create(project=self.project_b, name="Sam")
        self.show_a = Show.objects.create(
            project=self.project_a, title="Show A", venue=self.venue_a, event_type="rehearsal",
            start_datetime=_dt(14), end_datetime=_dt(16),
        )

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
            'project': self.project_a.id, 'name': "Composant", 'category': _cat(self.project_a, "Audio").id,
            'venue': self.venue_a.id, 'parent_material': self.material_b.id,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('parent_material', response.data)

    def test_cannot_set_storage_venue_from_other_project_on_material(self):
        response = self.client.post('/api/materials/', {
            'project': self.project_a.id, 'name': "Console rangée", 'category': _cat(self.project_a, "Audio").id,
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

        self.storage_venue = Venue.objects.create(
            project=self.source, name="Entrepôt", is_storage=True,
        )
        self.stage_venue = Venue.objects.create(project=self.source, name="Salle principale")

        self.kit = Material.objects.create(
            project=self.source, name="Kit Audio", category=_cat(self.source, "Audio"),
            venue=self.storage_venue,
        )
        self.mic = Material.objects.create(
            project=self.source, name="Micro sans fil", category=_cat(self.source, "Audio"),
            parent_material=self.kit, venue=self.storage_venue,
        )
        self.standalone = Material.objects.create(
            project=self.source, name="Rallonge", category=_cat(self.source, "Autre"),
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
        # `material_categories` s'est ajouté au décompte le 2026-07-30 :
        # les catégories sont devenues une table par projet, la duplication
        # doit donc les recopier aussi (ici les 9 catégories par défaut).
        self.assertEqual(response.data['copied'], {
            'venues': 2, 'materials': 3, 'technicians': 1, 'material_categories': 9,
        })

    def test_no_assignments_are_copied(self):
        response = self.client.post(f'/api/projects/{self.source.id}/duplicate/', {
            'name': "Furies 2027",
        }, format='json')
        new_project_id = response.data['project']['id']
        self.assertEqual(Show.objects.filter(project_id=new_project_id).count(), 0)
        # Aucun déplacement (ni confirmé ni proposition auto) ne doit exister
        # dans le nouveau projet — il n'a aucun spectacle.
        self.assertEqual(Transport.objects.filter(show__project_id=new_project_id).count(), 0)
        # Le show/l'assignation source, eux, doivent rester intacts.
        self.assertEqual(Show.objects.filter(project=self.source).count(), 1)
        self.assertEqual(ShowMaterial.objects.count(), 1)
        self.assertEqual(ShowTechnician.objects.count(), 1)
        # Le transport confirmé source reste (les propositions auto générées par
        # la régénération ne sont pas des données copiées).
        self.assertEqual(Transport.objects.filter(status=Transport.STATUS_CONFIRMED).count(), 1)

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


class TransportCoherenceLogicTests(TestCase):
    """Vérifie `transport_coherence.py` directement (module transport, ajouté le
    2026-07-24) : suivi des emplacements du matériel, détection de matériel non
    livré et d'origine de transport incohérente, exemption d'entreposage,
    quantités, et cas du matériel sans lieu d'entreposage."""

    def setUp(self):
        self.project = Project.objects.create(name="Projet test")
        self.entrepot = Venue.objects.create(project=self.project, name="Entrepôt", code="ENTR", is_storage=True)
        self.salle = Venue.objects.create(project=self.project, name="Chapelle", code="CHAP")
        # Console son entreposée à l'entrepôt (venue = home).
        self.console = Material.objects.create(
            project=self.project, name="Console son", category=_cat(self.project, "Audio"), venue=self.entrepot,
        )
        # Show à la Chapelle, 14h-16h -> fenêtre effective 13h-17h.
        self.show = Show.objects.create(
            project=self.project, title="Show", venue=self.salle, event_type="performance",
            start_datetime=_dt(14), end_datetime=_dt(16),
        )

    def _delivery(self, material, quantity=1, origin=None, destination=None, scheduled=None, duration=60):
        transport = Transport.objects.create(
            show=self.show, transport_type='delivery',
            origin_venue=origin or self.entrepot, destination_venue=destination or self.salle,
            scheduled_datetime=scheduled or _dt(8), estimated_duration_minutes=duration,
        )
        TransportMaterial.objects.create(transport=transport, material=material, quantity=quantity)
        return transport

    def test_material_required_without_transport_is_flagged(self):
        # Console requise à la Chapelle, mais aucun transport ne l'y amène.
        ShowMaterial.objects.create(show=self.show, material=self.console)
        issues = get_material_coherence_issues(self.console)
        types = [i['type'] for i in issues]
        self.assertIn('materiel_non_livre', types)

    def test_material_delivered_before_show_is_coherent(self):
        ShowMaterial.objects.create(show=self.show, material=self.console)
        # Livraison 8h-9h (arrivée 9h <= 13h, début de la fenêtre du show).
        self._delivery(self.console, scheduled=_dt(8), duration=60)
        self.assertEqual(get_material_coherence_issues(self.console), [])

    def test_material_already_at_venue_needs_no_transport(self):
        # Le matériel est entreposé DANS la salle du show : déjà sur place,
        # aucun transport requis, aucune incohérence.
        local = Material.objects.create(
            project=self.project, name="Pied de micro", category=_cat(self.project, "Audio"), venue=self.salle,
        )
        ShowMaterial.objects.create(show=self.show, material=local)
        self.assertEqual(get_material_coherence_issues(local), [])

    def test_delivery_arriving_after_show_starts_is_flagged(self):
        ShowMaterial.objects.create(show=self.show, material=self.console)
        # Livraison 13h30-14h30 : arrive à 14h30, après le début de la fenêtre
        # effective (13h) -> le matériel n'est pas là à temps.
        self._delivery(self.console, scheduled=_dt(13) + timedelta(minutes=30), duration=60)
        types = [i['type'] for i in get_material_coherence_issues(self.console)]
        self.assertIn('materiel_non_livre', types)

    def test_insufficient_quantity_delivered_is_flagged(self):
        multi = Material.objects.create(
            project=self.project, name="Rallonge", category=_cat(self.project, "Autre"), venue=self.entrepot, quantity=20,
        )
        ShowMaterial.objects.create(show=self.show, material=multi, quantity=10)
        # On n'en livre que 4 sur les 10 requises.
        self._delivery(multi, quantity=4, scheduled=_dt(8), duration=60)
        issues = get_material_coherence_issues(multi)
        missing = [i for i in issues if i['type'] == 'materiel_non_livre']
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0]['quantite_presente'], 4)
        self.assertEqual(missing[0]['quantite_requise'], 10)

    def test_transport_origin_impossible_is_flagged(self):
        # Un transport part de la Chapelle (pas le home) alors que la console est
        # à l'entrepôt à ce moment -> origine incohérente.
        transport = Transport.objects.create(
            show=self.show, transport_type='delivery',
            origin_venue=self.salle, destination_venue=self.entrepot,
            scheduled_datetime=_dt(8), estimated_duration_minutes=60,
        )
        TransportMaterial.objects.create(transport=transport, material=self.console, quantity=1)
        types = [i['type'] for i in get_material_coherence_issues(self.console)]
        self.assertIn('origine_incoherente', types)

    def test_transport_from_home_has_coherent_origin(self):
        # Livraison depuis l'entrepôt (home) : la console y est bien -> pas
        # d'incohérence d'origine (et le show est couvert).
        ShowMaterial.objects.create(show=self.show, material=self.console)
        self._delivery(self.console, scheduled=_dt(8), duration=60)
        types = [i['type'] for i in get_material_coherence_issues(self.console)]
        self.assertNotIn('origine_incoherente', types)

    def test_storage_show_requires_no_delivery(self):
        # Matériel « rangé » à l'entrepôt (show d'entreposage) : aucune livraison
        # exigée, exemption d'entreposage.
        storage_show = Show.objects.create(
            project=self.project, title="Rangement", venue=self.entrepot, event_type="storage",
            start_datetime=_dt(14), end_datetime=_dt(16),
        )
        ShowMaterial.objects.create(show=storage_show, material=self.console)
        self.assertEqual(get_material_coherence_issues(self.console), [])

    def test_material_without_home_is_flagged_once(self):
        orphan = Material.objects.create(project=self.project, name="Matériel sans entrepôt", category=_cat(self.project, "Autre"))
        ShowMaterial.objects.create(show=self.show, material=orphan)
        issues = get_material_coherence_issues(orphan)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]['type'], 'origine_inconnue')

    def test_material_without_home_and_no_usage_is_silent(self):
        # Sans lieu d'entreposage NI aucune assignation/transport, rien à suivre.
        orphan = Material.objects.create(project=self.project, name="Inutilisé", category=_cat(self.project, "Autre"))
        self.assertEqual(get_material_coherence_issues(orphan), [])

    def test_relocation_between_two_venues_needs_a_transport(self):
        # Le matériel est livré et utilisé à la Chapelle, puis requis dans une
        # 2e salle plus tard sans transport entre les deux -> non livré à la 2e.
        autre_salle = Venue.objects.create(project=self.project, name="Salle 2", code="SAL2")
        ShowMaterial.objects.create(show=self.show, material=self.console)
        self._delivery(self.console, scheduled=_dt(8), duration=60)  # entrepôt -> Chapelle
        show2 = Show.objects.create(
            project=self.project, title="Show 2", venue=autre_salle, event_type="performance",
            start_datetime=_dt(20), end_datetime=_dt(22),
        )
        ShowMaterial.objects.create(show=show2, material=self.console)
        missing = [
            i for i in get_material_coherence_issues(self.console)
            if i['type'] == 'materiel_non_livre' and i['show_id'] == show2.id
        ]
        self.assertEqual(len(missing), 1)


class TransportMaterialAPITests(TestCase):
    """Vérifie l'écriture imbriquée du matériel transporté (`materials`) sur
    `TransportSerializer` et les endpoints de rapport de cohérence
    (`/shows/{id}/transport-coherence/`, `/projects/{id}/transport-coherence/`)."""

    def setUp(self):
        self.client = APIClient()
        self.django_user = DjangoUser.objects.create_superuser('admin', 'admin@example.com', 'pw')
        self.client.force_authenticate(user=self.django_user)

        self.project = Project.objects.create(name="Projet test")
        self.entrepot = Venue.objects.create(project=self.project, name="Entrepôt", is_storage=True)
        self.salle = Venue.objects.create(project=self.project, name="Chapelle")
        self.console = Material.objects.create(
            project=self.project, name="Console son", category=_cat(self.project, "Audio"), venue=self.entrepot,
        )
        self.show = Show.objects.create(
            project=self.project, title="Show", venue=self.salle, event_type="performance",
            start_datetime=_dt(14), end_datetime=_dt(16),
        )

    def _create_transport_payload(self, **overrides):
        payload = {
            'show': self.show.id, 'transport_type': 'delivery',
            'origin_venue': self.entrepot.id, 'destination_venue': self.salle.id,
            'scheduled_datetime': _dt(8).isoformat(), 'estimated_duration_minutes': 60,
            'materials': [{'material': self.console.id, 'quantity': 1}],
        }
        payload.update(overrides)
        return payload

    def test_create_transport_with_material_lines(self):
        response = self.client.post('/api/transports/', self._create_transport_payload(), format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(response.data['materials']), 1)
        self.assertEqual(response.data['materials'][0]['material'], self.console.id)
        self.assertFalse(response.data['is_empty'])
        self.assertEqual(TransportMaterial.objects.count(), 1)

    def test_empty_transport_is_flagged(self):
        # Un déplacement sans aucune ligne de matériel est signalé « vide ».
        response = self.client.post('/api/transports/', self._create_transport_payload(materials=[]), format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data['is_empty'])

    def test_material_line_from_other_project_rejected(self):
        other_project = Project.objects.create(name="Autre")
        foreign_material = Material.objects.create(project=other_project, name="Ampli", category=_cat(other_project, "Audio"))
        response = self.client.post(
            '/api/transports/',
            self._create_transport_payload(materials=[{'material': foreign_material.id, 'quantity': 1}]),
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('materials', response.data)

    def test_duplicate_material_line_rejected(self):
        response = self.client.post(
            '/api/transports/',
            self._create_transport_payload(materials=[
                {'material': self.console.id, 'quantity': 1},
                {'material': self.console.id, 'quantity': 2},
            ]),
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('materials', response.data)

    def test_quantity_above_owned_rejected(self):
        response = self.client.post(
            '/api/transports/',
            self._create_transport_payload(materials=[{'material': self.console.id, 'quantity': 5}]),
            format='json',
        )
        # console.quantity == 1 par défaut -> transporter 5 est une erreur de données.
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('materials', response.data)

    def test_update_replaces_material_lines(self):
        create = self.client.post('/api/transports/', self._create_transport_payload(), format='json')
        transport_id = create.data['id']
        autre = Material.objects.create(
            project=self.project, name="Pied", category=_cat(self.project, "Audio"), venue=self.entrepot,
        )
        response = self.client.patch(
            f'/api/transports/{transport_id}/',
            {'materials': [{'material': autre.id, 'quantity': 1}]},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        materials = TransportMaterial.objects.filter(transport_id=transport_id)
        self.assertEqual(materials.count(), 1)
        self.assertEqual(materials.first().material_id, autre.id)

    def test_patch_without_materials_keeps_lines(self):
        create = self.client.post('/api/transports/', self._create_transport_payload(), format='json')
        transport_id = create.data['id']
        response = self.client.patch(
            f'/api/transports/{transport_id}/', {'notes': "Prévu tôt"}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(TransportMaterial.objects.filter(transport_id=transport_id).count(), 1)

    def test_show_coherence_endpoint_flags_missing_delivery(self):
        # Console requise au show, aucun transport -> l'endpoint doit lister une issue.
        ShowMaterial.objects.create(show=self.show, material=self.console)
        response = self.client.get(f'/api/shows/{self.show.id}/transport-coherence/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['issue_count'], 1)
        self.assertEqual(response.data['issues'][0]['type'], 'materiel_non_livre')

    def test_show_coherence_endpoint_clean_after_delivery(self):
        ShowMaterial.objects.create(show=self.show, material=self.console)
        self.client.post('/api/transports/', self._create_transport_payload(), format='json')
        response = self.client.get(f'/api/shows/{self.show.id}/transport-coherence/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['issue_count'], 0)

    def test_project_coherence_endpoint_aggregates(self):
        ShowMaterial.objects.create(show=self.show, material=self.console)
        response = self.client.get(f'/api/projects/{self.project.id}/transport-coherence/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(response.data['issue_count'], 1)


class TransportAutogenTests(TestCase):
    """Vérifie la génération automatique des propositions de transport (module
    transport, 2026-07-24) : création par signal à l'assignation, origine
    chaînée, groupage, idempotence, suppression sur désassignation, couverture
    par un transport confirmé, cas matériel sans entrepôt / show d'entrepôt."""

    def setUp(self):
        self.project = Project.objects.create(name="Projet test")
        self.entrepot = Venue.objects.create(project=self.project, name="Entrepôt", is_storage=True)
        self.salle1 = Venue.objects.create(project=self.project, name="Salle 1")
        self.salle2 = Venue.objects.create(project=self.project, name="Salle 2")
        self.console = Material.objects.create(
            project=self.project, name="Console son", category=_cat(self.project, "Audio"), venue=self.entrepot,
        )

    def _show(self, venue, hour, title="Show"):
        return Show.objects.create(
            project=self.project, title=title, venue=venue, event_type="performance",
            start_datetime=_dt(hour), end_datetime=_dt(hour) + timedelta(hours=2),
        )

    def _proposals(self):
        return Transport.objects.filter(status=Transport.STATUS_TO_APPROVE)

    def test_assignment_creates_proposal(self):
        show = self._show(self.salle1, 14)
        ShowMaterial.objects.create(show=show, material=self.console)
        proposals = self._proposals()
        self.assertEqual(proposals.count(), 1)
        proposal = proposals.first()
        self.assertEqual(proposal.origin_venue_id, self.entrepot.id)
        self.assertEqual(proposal.destination_venue_id, self.salle1.id)
        self.assertIsNone(proposal.scheduled_datetime)
        self.assertEqual(proposal.transport_type, Transport.TYPE_DELIVERY)
        self.assertEqual(
            list(proposal.transport_materials.values_list('material_id', flat=True)),
            [self.console.id],
        )

    def test_chained_origin_for_second_move(self):
        show1 = self._show(self.salle1, 10, "Show 1")
        show2 = self._show(self.salle2, 20, "Show 2")
        ShowMaterial.objects.create(show=show1, material=self.console)
        ShowMaterial.objects.create(show=show2, material=self.console)
        # Deux propositions : entrepôt->salle1 puis salle1->salle2 (origine chaînée).
        move2 = self._proposals().get(destination_venue=self.salle2)
        self.assertEqual(move2.origin_venue_id, self.salle1.id)
        move1 = self._proposals().get(destination_venue=self.salle1)
        self.assertEqual(move1.origin_venue_id, self.entrepot.id)

    def test_multiple_materials_grouped_in_one_proposal(self):
        ampli = Material.objects.create(
            project=self.project, name="Ampli", category=_cat(self.project, "Audio"), venue=self.entrepot,
        )
        show = self._show(self.salle1, 14)
        ShowMaterial.objects.create(show=show, material=self.console)
        ShowMaterial.objects.create(show=show, material=ampli)
        # Même origine (entrepôt) + même destination -> une seule proposition, 2 lignes.
        self.assertEqual(self._proposals().count(), 1)
        proposal = self._proposals().first()
        self.assertEqual(proposal.transport_materials.count(), 2)

    def test_regeneration_is_idempotent(self):
        show = self._show(self.salle1, 14)
        ShowMaterial.objects.create(show=show, material=self.console)
        first_id = self._proposals().first().id
        # Relancer la régénération ne doit pas dupliquer ni recréer la proposition.
        counts = regenerate_project_proposals(self.project)
        self.assertEqual(self._proposals().count(), 1)
        self.assertEqual(self._proposals().first().id, first_id)
        self.assertEqual(counts['created'], 0)
        self.assertEqual(counts['deleted'], 0)

    def test_unassigning_material_removes_proposal(self):
        show = self._show(self.salle1, 14)
        sm = ShowMaterial.objects.create(show=show, material=self.console)
        self.assertEqual(self._proposals().count(), 1)
        sm.delete()
        self.assertEqual(self._proposals().count(), 0)

    def test_confirmed_transport_suppresses_proposal(self):
        show = self._show(self.salle1, 14)
        ShowMaterial.objects.create(show=show, material=self.console)
        self.assertEqual(self._proposals().count(), 1)
        # Un transport confirmé qui dessert la console à ce spectacle supprime la proposition.
        confirmed = Transport.objects.create(
            show=show, transport_type=Transport.TYPE_DELIVERY, status=Transport.STATUS_CONFIRMED,
            origin_venue=self.entrepot, destination_venue=self.salle1,
            scheduled_datetime=_dt(8), estimated_duration_minutes=60,
        )
        TransportMaterial.objects.create(transport=confirmed, material=self.console, quantity=1)
        self.assertEqual(self._proposals().count(), 0)

    def test_material_without_home_generates_no_proposal(self):
        orphan = Material.objects.create(project=self.project, name="Sans entrepôt", category=_cat(self.project, "Autre"))
        show = self._show(self.salle1, 14)
        ShowMaterial.objects.create(show=show, material=orphan)
        self.assertFalse(self._proposals().filter(transport_materials__material=orphan).exists())

    def test_storage_show_generates_no_proposal(self):
        storage_show = Show.objects.create(
            project=self.project, title="Rangement", venue=self.entrepot, event_type="storage",
            start_datetime=_dt(14), end_datetime=_dt(16),
        )
        ShowMaterial.objects.create(show=storage_show, material=self.console)
        self.assertEqual(self._proposals().count(), 0)

    def test_missing_delivery_issue_is_orange_when_proposal_exists(self):
        show = self._show(self.salle1, 14)
        ShowMaterial.objects.create(show=show, material=self.console)
        issues = get_material_coherence_issues(self.console)
        missing = [i for i in issues if i['type'] == 'materiel_non_livre']
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0]['etat'], 'propose')
        self.assertIsNotNone(missing[0]['proposal_transport_id'])


class TransportStatusAPITests(TestCase):
    """Vérifie le cycle de vie `status` du Transport via l'API : une création
    manuelle confirmée exige une heure, une proposition se confirme en la
    complétant, et l'indicateur `has_technician_conflict` reflète un
    chevauchement (sans bloquer, décision Samuel du 2026-07-24)."""

    def setUp(self):
        self.client = APIClient()
        self.django_user = DjangoUser.objects.create_superuser('admin', 'admin@example.com', 'pw')
        self.client.force_authenticate(user=self.django_user)

        self.project = Project.objects.create(name="Projet test")
        self.entrepot = Venue.objects.create(project=self.project, name="Entrepôt", is_storage=True)
        self.salle = Venue.objects.create(project=self.project, name="Salle")
        self.console = Material.objects.create(
            project=self.project, name="Console son", category=_cat(self.project, "Audio"), venue=self.entrepot,
        )
        self.technician = Technician.objects.create(project=self.project, name="Alex", specialty="son")
        self.show = Show.objects.create(
            project=self.project, title="Show", venue=self.salle, event_type="performance",
            start_datetime=_dt(14), end_datetime=_dt(16),
        )

    def test_manual_confirmed_transport_requires_scheduled_datetime(self):
        response = self.client.post('/api/transports/', {
            'show': self.show.id, 'transport_type': 'delivery',
            'origin_venue': self.entrepot.id, 'destination_venue': self.salle.id,
            # pas de scheduled_datetime, status confirmed par défaut
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('scheduled_datetime', response.data)

    def test_completing_a_proposal_confirms_it_and_clears_alert(self):
        # Assigner la console crée une proposition (signal).
        ShowMaterial.objects.create(show=self.show, material=self.console)
        proposal = Transport.objects.filter(status=Transport.STATUS_TO_APPROVE).first()
        self.assertIsNotNone(proposal)

        # Confirmer sans heure -> refus.
        refused = self.client.patch(f'/api/transports/{proposal.id}/', {
            'status': 'confirmed',
        }, format='json')
        self.assertEqual(refused.status_code, status.HTTP_400_BAD_REQUEST)

        # Confirmer avec une heure -> OK, et l'alerte de cohérence disparaît.
        ok = self.client.patch(f'/api/transports/{proposal.id}/', {
            'status': 'confirmed',
            'scheduled_datetime': _dt(8).isoformat(),
            'estimated_duration_minutes': 60,
        }, format='json')
        self.assertEqual(ok.status_code, status.HTTP_200_OK)
        coherence = self.client.get(f'/api/shows/{self.show.id}/transport-coherence/')
        self.assertEqual(coherence.data['issue_count'], 0)

    def test_has_technician_conflict_indicator(self):
        # Deux déplacements qui se chevauchent pour le même technicien.
        first = self.client.post('/api/transports/', {
            'show': self.show.id, 'transport_type': 'delivery',
            'origin_venue': self.entrepot.id, 'destination_venue': self.salle.id,
            'scheduled_datetime': _dt(8).isoformat(), 'estimated_duration_minutes': 120,
            'technicians': [{'technician': self.technician.id}],
        }, format='json')
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        # Le second chevauche 8h-10h ; on force pour passer outre le blocage.
        second = self.client.post('/api/transports/', {
            'show': self.show.id, 'transport_type': 'pickup',
            'origin_venue': self.salle.id, 'destination_venue': self.entrepot.id,
            'scheduled_datetime': _dt(9).isoformat(), 'estimated_duration_minutes': 60,
            'technicians': [{'technician': self.technician.id}], 'force': True,
        }, format='json')
        self.assertEqual(second.status_code, status.HTTP_201_CREATED)

        detail = self.client.get(f"/api/transports/{first.data['id']}/")
        self.assertTrue(detail.data['has_technician_conflict'])


class FicheEditionPatchAPITests(TestCase):
    """Vérifie les PATCH déclenchés par le bouton « Modifier la fiche » du frontend.

    Depuis le 2026-07-30, les fiches de détail (lieu, matériel, technicien,
    spectacle) basculent en entier en mode édition et enregistrent en **un
    seul PATCH** groupé (voir `frontend/src/composables/useFicheEdition.js`).
    Les cas couverts ici sont ceux que ce formulaire produit réellement :
    mise à jour multi-champs, FK nullables remises à `null`, et champ `notes`
    — jusque-là éditable nulle part côté Vue. Le PATCH d'un lieu est couvert
    à part, dans `VenueCodeTests`.
    """

    def setUp(self):
        self.client = APIClient()
        self.django_user = DjangoUser.objects.create_superuser('admin', 'admin@example.com', 'pw')
        self.client.force_authenticate(user=self.django_user)
        self.project = Project.objects.create(name="Projet test")
        self.entrepot = Venue.objects.create(project=self.project, name="Entrepôt", is_storage=True)
        self.salle = Venue.objects.create(project=self.project, name="Chapelle")

    # --- Matériel ---

    def test_patch_full_material_fields(self):
        material = Material.objects.create(project=self.project, name="Console", quantity=1)
        response = self.client.patch(f'/api/materials/{material.id}/', {
            'name': "Console Yamaha CL5",
            'description': "Console numérique 72 canaux",
            'category': _cat(self.project, "Audio").id,
            'ownership_status': 'rental',
            'quantity': 2,
            'venue': self.entrepot.id,
            'parent_material': None,
            'is_active': True,
            'notes': "Retour de location le 12.",
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        material.refresh_from_db()
        self.assertEqual(material.name, "Console Yamaha CL5")
        self.assertEqual(material.category, _cat(self.project, "Audio"))
        self.assertEqual(material.ownership_status, 'rental')
        self.assertEqual(material.quantity, 2)
        self.assertEqual(material.venue, self.entrepot)
        self.assertEqual(material.notes, "Retour de location le 12.")

    def test_patch_material_can_clear_parent(self):
        # Le formulaire envoie `null` (option « Aucun ») et non une chaîne vide.
        kit = Material.objects.create(project=self.project, name="Kit son", quantity=1, venue=self.entrepot)
        material = Material.objects.create(
            project=self.project, name="Micro", quantity=1,
            venue=self.entrepot, parent_material=kit,
        )
        response = self.client.patch(f'/api/materials/{material.id}/', {
            'parent_material': None,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        material.refresh_from_db()
        self.assertIsNone(material.parent_material)

    def test_patch_material_cannot_clear_venue(self):
        # Le lieu d'origine est obligatoire depuis le 2026-07-30 : sans point de
        # départ, la timeline de position ne peut plus rien vérifier (ni la
        # disponibilité au départ d'un transport, ni le retour en fin de projet).
        material = Material.objects.create(
            project=self.project, name="Micro", quantity=1, venue=self.entrepot,
        )
        response = self.client.patch(f'/api/materials/{material.id}/', {
            'venue': None,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('venue', response.data)

    def test_patch_material_rejects_venue_from_another_project(self):
        # Isolation par projet (MaterialSerializer.validate) : le formulaire ne
        # propose que les lieux du projet, mais l'API doit refuser quand même.
        autre_projet = Project.objects.create(name="Autre projet")
        autre_lieu = Venue.objects.create(project=autre_projet, name="Ailleurs")
        material = Material.objects.create(project=self.project, name="Console", quantity=1)
        response = self.client.patch(f'/api/materials/{material.id}/', {
            'venue': autre_lieu.id,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('venue', response.data)

    def test_patch_material_can_deactivate(self):
        material = Material.objects.create(project=self.project, name="Vieux rideau", quantity=1)
        response = self.client.patch(f'/api/materials/{material.id}/', {'is_active': False}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        material.refresh_from_db()
        self.assertFalse(material.is_active)

    # --- Technicien ---

    def test_patch_full_technician_fields(self):
        technician = Technician.objects.create(project=self.project, name="Alex")
        response = self.client.patch(f'/api/technicians/{technician.id}/', {
            'name': "Alex Gagnon",
            'specialty': "Éclairage",
            'contact_info': "alex@example.com",
            'notes': "Disponible en soirée seulement.",
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        technician.refresh_from_db()
        self.assertEqual(technician.name, "Alex Gagnon")
        self.assertEqual(technician.specialty, "Éclairage")
        self.assertEqual(technician.contact_info, "alex@example.com")
        self.assertEqual(technician.notes, "Disponible en soirée seulement.")

    def test_patch_technician_rejects_blank_name(self):
        technician = Technician.objects.create(project=self.project, name="Alex")
        response = self.client.patch(f'/api/technicians/{technician.id}/', {'name': ""}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('name', response.data)

    # --- Spectacle ---

    def test_patch_show_notes_only(self):
        # `notes` était exposé par ShowSerializer mais absent du formulaire Vue
        # avant le 2026-07-30 — donc jamais modifiable depuis l'app.
        show = Show.objects.create(
            project=self.project, title="Vertiges", venue=self.salle,
            event_type='performance', start_datetime=_dt(20), end_datetime=_dt(22),
        )
        response = self.client.patch(f'/api/shows/{show.id}/', {
            'notes': "Prévoir 3 techniciens au montage.",
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        show.refresh_from_db()
        self.assertEqual(show.notes, "Prévoir 3 techniciens au montage.")

    def test_patch_full_show_fields(self):
        autre_salle = Venue.objects.create(project=self.project, name="Salle 2")
        show = Show.objects.create(
            project=self.project, title="Vertiges", venue=self.salle,
            event_type='rehearsal', start_datetime=_dt(20), end_datetime=_dt(22),
            buffer_before_minutes=60, buffer_after_minutes=60,
        )
        response = self.client.patch(f'/api/shows/{show.id}/', {
            'title': "Vertiges — générale",
            'venue': autre_salle.id,
            'event_type': 'performance',
            'start_datetime': _dt(19).isoformat(),
            'end_datetime': _dt(21).isoformat(),
            'buffer_before_minutes': 90,
            'buffer_after_minutes': 30,
            'notes': "Générale technique.",
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        show.refresh_from_db()
        self.assertEqual(show.title, "Vertiges — générale")
        self.assertEqual(show.venue, autre_salle)
        self.assertEqual(show.event_type, 'performance')
        self.assertEqual(show.buffer_before_minutes, 90)
        self.assertEqual(show.notes, "Générale technique.")

    def test_patch_show_venue_conflict_is_blocking_then_forceable(self):
        # Le bandeau « Forcer malgré le conflit » du frontend rejoue le même
        # PATCH avec `force: true` — les deux réponses sont testées ici.
        Show.objects.create(
            project=self.project, title="Autre spectacle", venue=self.salle,
            event_type='performance', start_datetime=_dt(20), end_datetime=_dt(22),
            buffer_before_minutes=0, buffer_after_minutes=0,
        )
        show = Show.objects.create(
            project=self.project, title="Vertiges", venue=self.salle,
            event_type='rehearsal', start_datetime=_dt(10), end_datetime=_dt(12),
            buffer_before_minutes=0, buffer_after_minutes=0,
        )
        payload = {
            'start_datetime': _dt(21).isoformat(),
            'end_datetime': _dt(23).isoformat(),
        }
        refused = self.client.patch(f'/api/shows/{show.id}/', payload, format='json')
        self.assertEqual(refused.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('conflicts', refused.data)

        forced = self.client.patch(f'/api/shows/{show.id}/', {**payload, 'force': True}, format='json')
        self.assertEqual(forced.status_code, status.HTTP_200_OK)


class MaterialCategoryAPITests(TestCase):
    """Vérifie la gestion des catégories de matériel (`MaterialCategory`, 2026-07-30).

    Jusque-là `Material.category` était un slug figé parmi 9 valeurs codées en
    dur dans le modèle. C'est désormais une FK vers une table éditable, isolée
    par projet, avec une suppression qui passe par une réassignation explicite
    du matériel concerné (voir `MaterialCategoryViewSet.destroy`).
    """

    def setUp(self):
        self.client = APIClient()
        self.django_user = DjangoUser.objects.create_superuser('admin', 'admin@example.com', 'pw')
        self.client.force_authenticate(user=self.django_user)
        self.project = Project.objects.create(name="Projet test")
        # Lieu d'origine obligatoire sur le matériel depuis le 2026-07-30.
        self.entrepot = Venue.objects.create(project=self.project, name="Entrepôt", is_storage=True)

    # --- Création automatique et CRUD ---

    def test_new_project_gets_default_categories(self):
        # Signal `creer_categories_par_defaut` : une production ne démarre pas
        # sur une liste vide.
        noms = set(self.project.material_categories.values_list('name', flat=True))
        self.assertEqual(noms, {nom for nom, _ in MaterialCategory.DEFAULTS})

    def test_create_category(self):
        response = self.client.post('/api/material-categories/', {
            'project': self.project.id, 'name': "Machinerie", 'color': 'oklch(0.7 0.14 300)',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['name'], "Machinerie")
        self.assertEqual(response.data['material_count'], 0)

    def test_categories_listed_case_and_accent_insensitively(self):
        # Bug signalé par Samuel le 2026-07-30 : sur SQLite, `Meta.ordering =
        # ['name']` trie par octets — une catégorie commençant par une
        # minuscule non accentuée atterrit après TOUTES les majuscules,
        # indépendamment de l'alphabet ; un nom accentué après tout l'ASCII.
        # `MaterialCategoryViewSet.list()` retrie donc explicitement en
        # Python (NFKD + casefold) plutôt que de compter sur l'ORDER BY.
        import unicodedata

        self.client.post('/api/material-categories/', {
            'project': self.project.id, 'name': "abricot",
        }, format='json')
        self.client.post('/api/material-categories/', {
            'project': self.project.id, 'name': "étagères",
        }, format='json')
        response = self.client.get('/api/material-categories/', {'project': self.project.id})
        names = [c['name'] for c in response.data]
        expected = sorted(names, key=lambda n: unicodedata.normalize('NFKD', n).casefold())
        self.assertEqual(names, expected)
        # Ni l'un ni l'autre ne doit être relégué en fin de liste malgré la
        # casse/l'accent — c'était exactement le bug signalé.
        self.assertNotEqual(names[-1], "abricot")
        self.assertNotEqual(names[-1], "étagères")

    def test_duplicate_name_rejected_within_same_project(self):
        response = self.client.post('/api/material-categories/', {
            'project': self.project.id, 'name': "audio",
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('name', response.data)

    def test_same_name_allowed_in_another_project(self):
        autre = Project.objects.create(name="Autre projet")
        # Les défauts des deux projets portent déjà les mêmes noms — c'est
        # précisément ce que la contrainte (project, name) doit autoriser.
        self.assertEqual(
            MaterialCategory.objects.filter(name="Audio").count(), 2,
        )
        self.assertTrue(autre.material_categories.filter(name="Audio").exists())

    def test_patch_name_and_color(self):
        categorie = _cat(self.project, "Audio")
        response = self.client.patch(f'/api/material-categories/{categorie.id}/', {
            'name': "Son", 'color': 'oklch(0.7 0.16 35)',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        categorie.refresh_from_db()
        self.assertEqual(categorie.name, "Son")
        self.assertEqual(categorie.color, 'oklch(0.7 0.16 35)')

    def test_list_is_filtered_by_project(self):
        autre = Project.objects.create(name="Autre projet")
        response = self.client.get('/api/material-categories/', {'project': autre.id})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {c['project'] for c in response.data}
        self.assertEqual(ids, {autre.id})

    def test_material_count_reflects_usage(self):
        categorie = _cat(self.project, "Audio")
        Material.objects.create(project=self.project, name="Console", category=categorie)
        Material.objects.create(project=self.project, name="Micro", category=categorie)
        response = self.client.get(f'/api/material-categories/{categorie.id}/')
        self.assertEqual(response.data['material_count'], 2)

    # --- Isolation par projet sur le matériel ---

    def test_material_cannot_use_category_from_another_project(self):
        autre = Project.objects.create(name="Autre projet")
        response = self.client.post('/api/materials/', {
            'project': self.project.id, 'name': "Console",
            'venue': self.entrepot.id,
            'category': _cat(autre, "Audio").id,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('category', response.data)

    def test_material_serializer_exposes_category_name_and_color(self):
        categorie = _cat(self.project, "Audio")
        material = Material.objects.create(project=self.project, name="Console", category=categorie)
        response = self.client.get(f'/api/materials/{material.id}/')
        self.assertEqual(response.data['category'], categorie.id)
        self.assertEqual(response.data['category_name'], "Audio")
        self.assertEqual(response.data['category_color'], categorie.color)

    # --- Suppression ---

    def test_delete_unused_category(self):
        categorie = _cat(self.project, "Machinerie")
        response = self.client.delete(f'/api/material-categories/{categorie.id}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(MaterialCategory.objects.filter(id=categorie.id).exists())

    def test_delete_used_category_without_target_is_refused(self):
        categorie = _cat(self.project, "Audio")
        Material.objects.create(project=self.project, name="Console", category=categorie)
        response = self.client.delete(f'/api/material-categories/{categorie.id}/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['material_count'], 1)
        self.assertTrue(MaterialCategory.objects.filter(id=categorie.id).exists())

    def test_delete_used_category_reassigns_material(self):
        source = _cat(self.project, "Audio")
        cible = _cat(self.project, "Réseau")
        material = Material.objects.create(project=self.project, name="Console", category=source)
        response = self.client.delete(
            f'/api/material-categories/{source.id}/?reassign_to={cible.id}',
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        material.refresh_from_db()
        self.assertEqual(material.category, cible)
        self.assertFalse(MaterialCategory.objects.filter(id=source.id).exists())

    def test_delete_used_category_can_leave_material_uncategorized(self):
        # `?reassign_to=` (vide) = laisser le matériel sans catégorie, la FK
        # étant nullable — plutôt que de le forcer dans un fourre-tout.
        source = _cat(self.project, "Audio")
        material = Material.objects.create(project=self.project, name="Console", category=source)
        response = self.client.delete(f'/api/material-categories/{source.id}/?reassign_to=')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        material.refresh_from_db()
        self.assertIsNone(material.category)

    def test_delete_rejects_target_from_another_project(self):
        autre = Project.objects.create(name="Autre projet")
        source = _cat(self.project, "Audio")
        Material.objects.create(project=self.project, name="Console", category=source)
        response = self.client.delete(
            f'/api/material-categories/{source.id}/?reassign_to={_cat(autre, "Réseau").id}',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('reassign_to', response.data)

    def test_delete_rejects_reassign_to_itself(self):
        source = _cat(self.project, "Audio")
        Material.objects.create(project=self.project, name="Console", category=source)
        response = self.client.delete(
            f'/api/material-categories/{source.id}/?reassign_to={source.id}',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('reassign_to', response.data)

    # --- Duplication de projet ---

    def test_duplicate_project_remaps_material_categories(self):
        source = _cat(self.project, "Machinerie")
        source.color = 'oklch(0.7 0.14 300)'
        source.save(update_fields=['color'])
        Material.objects.create(project=self.project, name="Palan", category=source)

        response = self.client.post(f'/api/projects/{self.project.id}/duplicate/', {
            'name': "Édition suivante",
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        nouveau = Project.objects.get(id=response.data['project']['id'])
        copie = nouveau.material_categories.get(name="Machinerie")
        # La catégorie du matériel copié doit pointer vers la copie, pas vers
        # la catégorie du projet source.
        palan = nouveau.materials.get(name="Palan")
        self.assertEqual(palan.category, copie)
        self.assertEqual(copie.color, 'oklch(0.7 0.14 300)')


class TransportMaterialAvailabilityAPITests(TestCase):
    """Vérifie `GET /api/transports/{id}/material-availability/` (2026-07-30).

    Demande de Samuel : la modale « ajouter du matériel » d'un transport ne
    doit proposer que ce qui se trouve réellement au lieu de DÉPART à l'heure
    du départ. La disponibilité vient du grand livre de positions de
    `transport_coherence.py` (entrepôt + transports confirmés antérieurs), pas
    d'une comparaison naïve avec `Material.venue`.
    """

    def setUp(self):
        self.client = APIClient()
        self.django_user = DjangoUser.objects.create_superuser('admin', 'admin@example.com', 'pw')
        self.client.force_authenticate(user=self.django_user)
        self.project = Project.objects.create(name="Projet test")
        self.entrepot = Venue.objects.create(project=self.project, name="Entrepôt", is_storage=True)
        self.salle = Venue.objects.create(project=self.project, name="Chapelle")
        self.show = Show.objects.create(
            project=self.project, title="Vertiges", venue=self.salle,
            event_type='performance', start_datetime=_dt(20), end_datetime=_dt(22),
        )
        self.console = Material.objects.create(
            project=self.project, name="Console", venue=self.entrepot, quantity=1,
        )
        self.rallonges = Material.objects.create(
            project=self.project, name="Rallonges", venue=self.entrepot, quantity=20,
        )

    def _availability(self, transport):
        response = self.client.get(f'/api/transports/{transport.id}/material-availability/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return {m['name']: m for m in response.data['materials']}

    def _transport(self, origin, destination, hour, status_value=Transport.STATUS_CONFIRMED):
        return Transport.objects.create(
            show=self.show, transport_type='delivery',
            origin_venue=origin, destination_venue=destination,
            scheduled_datetime=_dt(hour), estimated_duration_minutes=60,
            status=status_value,
        )

    def test_material_at_origin_is_available(self):
        transport = self._transport(self.entrepot, self.salle, 8)
        rows = self._availability(transport)
        self.assertEqual(rows['Console']['available'], 1)
        self.assertEqual(rows['Rallonges']['available'], 20)

    def test_material_elsewhere_is_zero(self):
        # Départ depuis la salle alors que tout est encore à l'entrepôt.
        transport = self._transport(self.salle, self.entrepot, 8)
        rows = self._availability(transport)
        self.assertEqual(rows['Console']['available'], 0)
        # Le matériel indisponible est renvoyé quand même (le frontend le grise).
        self.assertEqual(rows['Console']['venue_name'], "Entrepôt")

    def test_earlier_confirmed_transport_moves_the_material(self):
        # Un premier transport confirmé amène la console en salle à 9h ;
        # un second partant de la salle à 12h doit donc l'y trouver.
        premier = self._transport(self.entrepot, self.salle, 8)
        TransportMaterial.objects.create(transport=premier, material=self.console, quantity=1)

        second = self._transport(self.salle, self.entrepot, 12)
        rows = self._availability(second)
        self.assertEqual(rows['Console']['available'], 1)

        # …et le même départ depuis l'entrepôt ne l'y trouve plus.
        depuis_entrepot = self._transport(self.entrepot, self.salle, 14)
        rows = self._availability(depuis_entrepot)
        self.assertEqual(rows['Console']['available'], 0)

    def test_partial_quantity_moved(self):
        premier = self._transport(self.entrepot, self.salle, 8)
        TransportMaterial.objects.create(transport=premier, material=self.rallonges, quantity=12)

        reste = self._transport(self.entrepot, self.salle, 14)
        rows = self._availability(reste)
        self.assertEqual(rows['Rallonges']['available'], 8)

    def test_unconfirmed_transport_does_not_move_material(self):
        # Une proposition auto ('to_approve') ne livre rien tant qu'elle n'est
        # pas confirmée — même règle que le reste de transport_coherence.py.
        proposition = self._transport(
            self.entrepot, self.salle, 8, status_value=Transport.STATUS_TO_APPROVE,
        )
        TransportMaterial.objects.create(transport=proposition, material=self.console, quantity=1)

        depuis_salle = self._transport(self.salle, self.entrepot, 12)
        rows = self._availability(depuis_salle)
        self.assertEqual(rows['Console']['available'], 0)

    def test_transport_does_not_count_against_itself(self):
        # Rouvrir la modale d'un transport déjà rempli ne doit pas montrer son
        # propre chargement comme « déjà parti ».
        transport = self._transport(self.entrepot, self.salle, 8)
        TransportMaterial.objects.create(transport=transport, material=self.console, quantity=1)
        rows = self._availability(transport)
        self.assertEqual(rows['Console']['available'], 1)

    def test_without_scheduled_datetime_everything_is_available(self):
        transport = Transport.objects.create(
            show=self.show, transport_type='delivery',
            origin_venue=self.salle, destination_venue=self.entrepot,
            scheduled_datetime=None, estimated_duration_minutes=60,
            status=Transport.STATUS_TO_APPROVE,
        )
        response = self.client.get(f'/api/transports/{transport.id}/material-availability/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data['at'])
        rows = {m['name']: m for m in response.data['materials']}
        # Position non calculable : on n'invente pas de restriction.
        self.assertEqual(rows['Console']['available'], 1)
        self.assertEqual(rows['Rallonges']['available'], 20)

    def test_inactive_material_is_excluded(self):
        Material.objects.create(
            project=self.project, name="Vieux rideau", venue=self.entrepot,
            quantity=1, is_active=False,
        )
        transport = self._transport(self.entrepot, self.salle, 8)
        rows = self._availability(transport)
        self.assertNotIn("Vieux rideau", rows)

    def test_material_from_another_project_is_excluded(self):
        autre = Project.objects.create(name="Autre projet")
        autre_entrepot = Venue.objects.create(project=autre, name="Entrepôt B", is_storage=True)
        Material.objects.create(project=autre, name="Console B", venue=autre_entrepot, quantity=1)
        transport = self._transport(self.entrepot, self.salle, 8)
        rows = self._availability(transport)
        self.assertNotIn("Console B", rows)


class TransportMultipleTechniciansAPITests(TestCase):
    """Vérifie qu'un déplacement peut mobiliser plusieurs techniciens (2026-07-30).

    `Transport.technician` (FK unique) a été remplacé par la table de liaison
    `TransportTechnician`, exposée en écriture imbriquée sur
    `TransportSerializer.technicians` — même pattern que `materials`. La
    détection de conflit doit désormais vérifier CHAQUE personne affectée.
    """

    def setUp(self):
        self.client = APIClient()
        self.django_user = DjangoUser.objects.create_superuser('admin', 'admin@example.com', 'pw')
        self.client.force_authenticate(user=self.django_user)
        self.project = Project.objects.create(name="Projet test")
        self.entrepot = Venue.objects.create(project=self.project, name="Entrepôt", is_storage=True)
        self.salle = Venue.objects.create(project=self.project, name="Chapelle")
        self.show = Show.objects.create(
            project=self.project, title="Vertiges", venue=self.salle,
            event_type='performance', start_datetime=_dt(20), end_datetime=_dt(22),
        )
        self.alex = Technician.objects.create(project=self.project, name="Alex")
        self.brigitte = Technician.objects.create(project=self.project, name="Brigitte")

    def _payload(self, technicians, hour=8, **extra):
        payload = {
            'show': self.show.id, 'transport_type': 'delivery',
            'origin_venue': self.entrepot.id, 'destination_venue': self.salle.id,
            'scheduled_datetime': _dt(hour).isoformat(), 'estimated_duration_minutes': 60,
            'technicians': [{'technician': t.id} for t in technicians],
        }
        payload.update(extra)
        return payload

    def test_create_with_two_technicians(self):
        response = self.client.post('/api/transports/', self._payload([self.alex, self.brigitte]), format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(response.data['technicians']), 2)
        self.assertEqual(set(response.data['technician_names']), {"Alex", "Brigitte"})

    def test_create_without_technician_is_allowed(self):
        # Une proposition auto peut rester sans personne affectée.
        response = self.client.post('/api/transports/', self._payload([]), format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['technicians'], [])

    def test_same_technician_twice_is_rejected(self):
        response = self.client.post('/api/transports/', self._payload([self.alex, self.alex]), format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('technicians', response.data)

    def test_technician_from_another_project_is_rejected(self):
        autre = Project.objects.create(name="Autre projet")
        etranger = Technician.objects.create(project=autre, name="Étranger")
        response = self.client.post('/api/transports/', self._payload([etranger]), format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('technicians', response.data)

    def test_patch_replaces_the_whole_list(self):
        created = self.client.post('/api/transports/', self._payload([self.alex, self.brigitte]), format='json')
        response = self.client.patch(
            f"/api/transports/{created.data['id']}/",
            {'technicians': [{'technician': self.brigitte.id}]},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['technician_names'], ["Brigitte"])

    def test_patch_without_technicians_leaves_them_untouched(self):
        created = self.client.post('/api/transports/', self._payload([self.alex]), format='json')
        response = self.client.patch(
            f"/api/transports/{created.data['id']}/", {'notes': "Quai arrière"}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['technician_names'], ["Alex"])

    # --- Conflits ---

    def test_conflict_detected_on_any_of_the_technicians(self):
        # Alex est libre, Brigitte est déjà sur le spectacle (20h-22h).
        ShowTechnician.objects.create(show=self.show, technician=self.brigitte)
        response = self.client.post(
            '/api/transports/', self._payload([self.alex, self.brigitte], hour=20), format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('conflicts', response.data)

    def test_conflict_is_forceable(self):
        ShowTechnician.objects.create(show=self.show, technician=self.brigitte)
        response = self.client.post(
            '/api/transports/',
            self._payload([self.alex, self.brigitte], hour=20, force=True),
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_no_conflict_when_every_technician_is_free(self):
        response = self.client.post(
            '/api/transports/', self._payload([self.alex, self.brigitte], hour=8), format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_has_technician_conflict_true_if_any_is_busy(self):
        ShowTechnician.objects.create(show=self.show, technician=self.brigitte)
        created = self.client.post(
            '/api/transports/',
            self._payload([self.alex, self.brigitte], hour=20, force=True),
            format='json',
        )
        detail = self.client.get(f"/api/transports/{created.data['id']}/")
        self.assertTrue(detail.data['has_technician_conflict'])

    def test_project_conflicts_reports_each_technician_separately(self):
        # Les deux personnes du déplacement sont aussi sur le spectacle : deux
        # engagements distincts, donc deux conflits distincts.
        ShowTechnician.objects.create(show=self.show, technician=self.alex)
        ShowTechnician.objects.create(show=self.show, technician=self.brigitte)
        self.client.post(
            '/api/transports/',
            self._payload([self.alex, self.brigitte], hour=20, force=True),
            format='json',
        )
        response = self.client.get(f'/api/projects/{self.project.id}/conflicts/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['technician_conflicts']), 2)

    def test_filter_by_technician_traverses_the_link_table(self):
        self.client.post('/api/transports/', self._payload([self.alex, self.brigitte]), format='json')
        response = self.client.get('/api/transports/', {'technician': self.brigitte.id})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)


class AssignmentRemovalAPITests(TestCase):
    """Vérifie le retrait d'une assignation depuis les modales (2026-07-30).

    Les modales « Assigner du matériel » et « Assigner des techniciens » d'un
    spectacle permettent depuis cette date de **décocher** une ligne déjà
    assignée pour la retirer, appliqué à la validation. Côté API c'est un
    simple `DELETE` sur la table de liaison — jusque-là jamais couvert par un
    test, alors que le frontend en dépend maintenant.
    """

    def setUp(self):
        self.client = APIClient()
        self.django_user = DjangoUser.objects.create_superuser('admin', 'admin@example.com', 'pw')
        self.client.force_authenticate(user=self.django_user)
        self.project = Project.objects.create(name="Projet test")
        self.salle = Venue.objects.create(project=self.project, name="Chapelle")
        self.show = Show.objects.create(
            project=self.project, title="Vertiges", venue=self.salle,
            event_type='performance', start_datetime=_dt(20), end_datetime=_dt(22),
        )
        self.console = Material.objects.create(project=self.project, name="Console", quantity=1)
        self.alex = Technician.objects.create(project=self.project, name="Alex")

    def test_delete_show_technician(self):
        assignment = ShowTechnician.objects.create(show=self.show, technician=self.alex)
        response = self.client.delete(f'/api/show-technicians/{assignment.id}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(ShowTechnician.objects.filter(id=assignment.id).exists())

    def test_delete_show_material(self):
        assignment = ShowMaterial.objects.create(show=self.show, material=self.console, quantity=1)
        response = self.client.delete(f'/api/show-materials/{assignment.id}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(ShowMaterial.objects.filter(id=assignment.id).exists())

    def test_removing_frees_capacity_for_another_show(self):
        # C'est la raison pour laquelle la modale applique les retraits AVANT
        # les ajouts : libérer une ressource peut lever le conflit qui
        # bloquerait l'ajout suivant dans la même fournée.
        autre_show = Show.objects.create(
            project=self.project, title="Autre", venue=self.salle,
            event_type='rehearsal', start_datetime=_dt(20), end_datetime=_dt(22),
            buffer_before_minutes=0, buffer_after_minutes=0,
        )
        assignment = ShowMaterial.objects.create(show=self.show, material=self.console, quantity=1)

        refuse = self.client.post('/api/show-materials/', {
            'show': autre_show.id, 'material': self.console.id, 'quantity': 1,
        }, format='json')
        self.assertEqual(refuse.status_code, status.HTTP_400_BAD_REQUEST)

        self.client.delete(f'/api/show-materials/{assignment.id}/')
        ok = self.client.post('/api/show-materials/', {
            'show': autre_show.id, 'material': self.console.id, 'quantity': 1,
        }, format='json')
        self.assertEqual(ok.status_code, status.HTTP_201_CREATED)


class MaterialReturnToOriginTests(TestCase):
    """Vérifie le contrôle de retour à l'origine en fin de projet (2026-07-30).

    Demande de Samuel : « à la fin du dernier événement, le matériel doit être
    de retour à son origine ». C'est un renversement partiel de la portée
    « aller seulement » décidée le 2026-07-24 — on ne vérifie toujours pas
    qu'un `pickup` précis existe pour chaque livraison, mais on contrôle le
    **résultat net** à l'horizon du projet. Non bloquant : une entrée de plus
    dans le rapport de cohérence (`retour_manquant`).
    """

    def setUp(self):
        self.client = APIClient()
        self.django_user = DjangoUser.objects.create_superuser('admin', 'admin@example.com', 'pw')
        self.client.force_authenticate(user=self.django_user)
        self.project = Project.objects.create(name="Projet test")
        self.entrepot = Venue.objects.create(project=self.project, name="Entrepôt", is_storage=True)
        self.salle = Venue.objects.create(project=self.project, name="Chapelle")
        self.show = Show.objects.create(
            project=self.project, title="Vertiges", venue=self.salle,
            event_type='performance', start_datetime=_dt(20), end_datetime=_dt(22),
            buffer_before_minutes=0, buffer_after_minutes=0,
        )
        self.console = Material.objects.create(
            project=self.project, name="Console", venue=self.entrepot, quantity=1,
        )

    def _transport(self, origin, destination, hour, material=None, quantity=1, day=1):
        transport = Transport.objects.create(
            show=self.show, transport_type='delivery',
            origin_venue=origin, destination_venue=destination,
            scheduled_datetime=_dt(hour, day=day), estimated_duration_minutes=60,
            status=Transport.STATUS_CONFIRMED,
        )
        if material is not None:
            TransportMaterial.objects.create(
                transport=transport, material=material, quantity=quantity,
            )
        return transport

    def _return_issues(self):
        return [
            issue for issue in get_project_coherence_report(self.project)
            if issue['type'] == 'retour_manquant'
        ]

    def test_material_never_moved_is_not_reported(self):
        # Jamais sorti du bercail : rien à signaler.
        self.assertEqual(self._return_issues(), [])

    def test_material_left_at_venue_is_reported(self):
        self._transport(self.entrepot, self.salle, 8, material=self.console)
        issues = self._return_issues()
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]['material_name'], "Console")
        self.assertEqual(issues[0]['quantity_missing'], 1)
        self.assertEqual(issues[0]['locations'][0]['venue_name'], "Chapelle")

    def test_material_brought_back_is_not_reported(self):
        self._transport(self.entrepot, self.salle, 8, material=self.console)
        self._transport(self.salle, self.entrepot, 23, material=self.console)
        self.assertEqual(self._return_issues(), [])

    def test_partial_return_is_reported(self):
        rallonges = Material.objects.create(
            project=self.project, name="Rallonges", venue=self.entrepot, quantity=20,
        )
        self._transport(self.entrepot, self.salle, 8, material=rallonges, quantity=12)
        self._transport(self.salle, self.entrepot, 23, material=rallonges, quantity=5)
        issues = [i for i in self._return_issues() if i['material_name'] == "Rallonges"]
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]['quantity_missing'], 7)
        self.assertEqual(issues[0]['quantity_home'], 13)

    def test_return_after_project_end_date_does_not_count(self):
        # La date de fin du projet fait foi : un retour prévu APRÈS ne compte
        # pas — c'est précisément ce que Samuel veut détecter.
        self.project.end_date = _dt(23).date()
        self.project.save(update_fields=['end_date'])
        self._transport(self.entrepot, self.salle, 8, material=self.console)
        self._transport(self.salle, self.entrepot, 10, material=self.console, day=2)
        self.assertEqual(len(self._return_issues()), 1)

    def test_return_before_project_end_date_counts(self):
        self.project.end_date = _dt(23, day=3).date()
        self.project.save(update_fields=['end_date'])
        self._transport(self.entrepot, self.salle, 8, material=self.console)
        self._transport(self.salle, self.entrepot, 10, material=self.console, day=2)
        self.assertEqual(self._return_issues(), [])

    def test_horizon_falls_back_to_last_event(self):
        # Sans `end_date`, l'horizon est la fin du dernier événement du projet.
        self.assertIsNone(self.project.end_date)
        horizon = get_project_horizon(self.project)
        self.assertIsNotNone(horizon)
        self.assertGreaterEqual(horizon, self.show.effective_end)

    def test_horizon_is_none_without_dates_or_events(self):
        vide = Project.objects.create(name="Projet vide")
        self.assertIsNone(get_project_horizon(vide))

    def test_report_exposes_the_issue_through_the_api(self):
        self._transport(self.entrepot, self.salle, 8, material=self.console)
        response = self.client.get(f'/api/projects/{self.project.id}/transport-coherence/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        types = {issue['type'] for issue in response.data['issues']}
        self.assertIn('retour_manquant', types)


class KitCascadeAssignmentTests(TestCase):
    """Verrouille l'hypothèse derrière la sélection en cascade des kits (2026-07-30).

    Les modales d'assignation cochent automatiquement les composants d'un kit
    qu'on coche. Ça ne tient que si assigner le kit ET ses composants au MÊME
    spectacle n'est pas vu comme un conflit de hiérarchie — ce qui est le cas
    parce que `get_material_conflicts` exclut le spectacle courant de ses
    candidats. Ce test fige ce comportement : le casser ferait échouer la
    cascade côté frontend, sans que rien d'autre ne le signale.
    """

    def setUp(self):
        self.client = APIClient()
        self.django_user = DjangoUser.objects.create_superuser('admin', 'admin@example.com', 'pw')
        self.client.force_authenticate(user=self.django_user)
        self.project = Project.objects.create(name="Projet test")
        self.entrepot = Venue.objects.create(project=self.project, name="Entrepôt", is_storage=True)
        self.salle = Venue.objects.create(project=self.project, name="Chapelle")
        self.show = Show.objects.create(
            project=self.project, title="Vertiges", venue=self.salle,
            event_type='performance', start_datetime=_dt(20), end_datetime=_dt(22),
        )
        self.kit = Material.objects.create(
            project=self.project, name="Kit son", venue=self.entrepot, quantity=1,
        )
        self.micro = Material.objects.create(
            project=self.project, name="Micro", venue=self.entrepot, quantity=1,
            parent_material=self.kit,
        )

    def test_kit_and_its_component_on_the_same_show(self):
        premier = self.client.post('/api/show-materials/', {
            'show': self.show.id, 'material': self.kit.id, 'quantity': 1,
        }, format='json')
        self.assertEqual(premier.status_code, status.HTTP_201_CREATED)

        second = self.client.post('/api/show-materials/', {
            'show': self.show.id, 'material': self.micro.id, 'quantity': 1,
        }, format='json')
        self.assertEqual(second.status_code, status.HTTP_201_CREATED)

    def test_component_on_another_overlapping_show_still_conflicts(self):
        # La cascade ne doit pas affaiblir la règle : le kit ici, son composant
        # ailleurs au même moment, reste un conflit.
        autre_show = Show.objects.create(
            project=self.project, title="Autre", venue=self.salle,
            event_type='rehearsal', start_datetime=_dt(20), end_datetime=_dt(22),
            buffer_before_minutes=0, buffer_after_minutes=0,
        )
        ShowMaterial.objects.create(show=self.show, material=self.kit, quantity=1)
        response = self.client.post('/api/show-materials/', {
            'show': autre_show.id, 'material': self.micro.id, 'quantity': 1,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('conflicts', response.data)

    def test_component_ids_exposed_for_the_frontend_cascade(self):
        # Le frontend construit la cascade à partir de `parent_material` du
        # catalogue ; `component_ids` reste exposé côté kit pour la fiche.
        response = self.client.get(f'/api/materials/{self.kit.id}/')
        self.assertEqual(response.data['component_ids'], [self.micro.id])
        composant = self.client.get(f'/api/materials/{self.micro.id}/')
        self.assertEqual(composant.data['parent_material'], self.kit.id)


class SuppressionFicheAPITests(TestCase):
    """Vérifie la suppression d'un lieu, d'un spectacle et d'un déplacement (2026-07-30).

    Demande de Samuel : un bouton Supprimer avec confirmation sur ces trois
    fiches. Les trois entités ne se comportent PAS pareil, et c'est
    volontaire :

    - **Lieu** : refusé tant qu'il est référencé (`Show.venue` et les FK de
      `Transport` sont en `PROTECT`, et le matériel qui en fait son origine
      bloque aussi depuis que le lieu d'origine est obligatoire). Sans ce
      garde-fou, Django lèverait un `ProtectedError` rendu en 500 par DRF.
    - **Spectacle** : autorisé, emporte en cascade ses assignations et ses
      déplacements — d'où `deletion_impact`, affiché dans la confirmation.
    - **Déplacement** : autorisé, emporte ses lignes de matériel et de
      techniciens.
    """

    def setUp(self):
        self.client = APIClient()
        self.django_user = DjangoUser.objects.create_superuser('admin', 'admin@example.com', 'pw')
        self.client.force_authenticate(user=self.django_user)
        self.project = Project.objects.create(name="Projet test")
        self.entrepot = Venue.objects.create(project=self.project, name="Entrepôt", is_storage=True)
        self.salle = Venue.objects.create(project=self.project, name="Chapelle")
        self.show = Show.objects.create(
            project=self.project, title="Vertiges", venue=self.salle,
            event_type='performance', start_datetime=_dt(20), end_datetime=_dt(22),
        )

    # --- Lieu ---

    def test_delete_unused_venue(self):
        libre = Venue.objects.create(project=self.project, name="Salle inutilisée")
        response = self.client.delete(f'/api/venues/{libre.id}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Venue.objects.filter(id=libre.id).exists())

    def test_delete_venue_used_by_a_show_is_refused(self):
        response = self.client.delete(f'/api/venues/{self.salle.id}/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['shows'], 1)
        self.assertTrue(Venue.objects.filter(id=self.salle.id).exists())

    def test_delete_venue_used_by_a_transport_is_refused(self):
        Transport.objects.create(
            show=self.show, transport_type='delivery',
            origin_venue=self.entrepot, destination_venue=self.salle,
            scheduled_datetime=_dt(8), estimated_duration_minutes=60,
        )
        response = self.client.delete(f'/api/venues/{self.entrepot.id}/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['transports'], 1)

    def test_delete_venue_used_as_material_origin_is_refused(self):
        # `Material.venue` est en SET_NULL côté modèle, mais laisser vider
        # silencieusement l'origine contredirait la règle du 2026-07-30.
        Material.objects.create(
            project=self.project, name="Console", venue=self.entrepot, quantity=1,
        )
        response = self.client.delete(f'/api/venues/{self.entrepot.id}/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['materials'], 1)

    # --- Spectacle ---

    def test_deletion_impact_is_exposed(self):
        console = Material.objects.create(
            project=self.project, name="Console", venue=self.entrepot, quantity=1,
        )
        alex = Technician.objects.create(project=self.project, name="Alex")
        ShowMaterial.objects.create(show=self.show, material=console, quantity=1)
        ShowTechnician.objects.create(show=self.show, technician=alex)
        Transport.objects.create(
            show=self.show, transport_type='delivery',
            origin_venue=self.entrepot, destination_venue=self.salle,
            scheduled_datetime=_dt(8), estimated_duration_minutes=60,
        )
        response = self.client.get(f'/api/shows/{self.show.id}/')
        impact = response.data['deletion_impact']
        self.assertEqual(impact['materials'], 1)
        self.assertEqual(impact['technicians'], 1)
        # 2 et non 1 : assigner du matériel déclenche la génération automatique
        # d'une proposition de déplacement (`transport_autogen`), qui compte
        # elle aussi dans ce qui disparaîtra. Le décompte doit refléter la
        # réalité de la base, pas seulement ce que Samuel a saisi à la main.
        self.assertEqual(impact['transports'], Transport.objects.filter(show=self.show).count())
        self.assertGreaterEqual(impact['transports'], 1)

    def test_delete_show_cascades(self):
        console = Material.objects.create(
            project=self.project, name="Console", venue=self.entrepot, quantity=1,
        )
        ShowMaterial.objects.create(show=self.show, material=console, quantity=1)
        transport = Transport.objects.create(
            show=self.show, transport_type='delivery',
            origin_venue=self.entrepot, destination_venue=self.salle,
            scheduled_datetime=_dt(8), estimated_duration_minutes=60,
        )
        response = self.client.delete(f'/api/shows/{self.show.id}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Show.objects.filter(id=self.show.id).exists())
        self.assertFalse(Transport.objects.filter(id=transport.id).exists())
        self.assertFalse(ShowMaterial.objects.filter(show_id=self.show.id).exists())
        # Le matériel lui-même survit : seule l'assignation disparaît.
        self.assertTrue(Material.objects.filter(id=console.id).exists())

    # --- Déplacement ---

    def test_delete_transport_cascades_its_lines(self):
        console = Material.objects.create(
            project=self.project, name="Console", venue=self.entrepot, quantity=1,
        )
        alex = Technician.objects.create(project=self.project, name="Alex")
        transport = Transport.objects.create(
            show=self.show, transport_type='delivery',
            origin_venue=self.entrepot, destination_venue=self.salle,
            scheduled_datetime=_dt(8), estimated_duration_minutes=60,
        )
        TransportMaterial.objects.create(transport=transport, material=console, quantity=1)
        TransportTechnician.objects.create(transport=transport, technician=alex)

        response = self.client.delete(f'/api/transports/{transport.id}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(TransportMaterial.objects.filter(transport_id=transport.id).exists())
        self.assertFalse(TransportTechnician.objects.filter(transport_id=transport.id).exists())
        # Ni le matériel ni le technicien ne sont supprimés.
        self.assertTrue(Material.objects.filter(id=console.id).exists())
        self.assertTrue(Technician.objects.filter(id=alex.id).exists())


class ParcoursAPITests(TestCase):
    """Vérifie les endpoints « parcours » matériel et techniciens (2026-07-30).

    Demande de Samuel : des écrans pour voir le cheminement du matériel et des
    techniciens sur toute la durée de la production, avec sélection
    individuelle. Le parcours matériel réutilise le grand livre de positions de
    `transport_coherence.py` — même source de vérité que la cohérence des
    emplacements, les deux écrans ne peuvent donc pas se contredire.
    """

    def setUp(self):
        self.client = APIClient()
        self.django_user = DjangoUser.objects.create_superuser('admin', 'admin@example.com', 'pw')
        self.client.force_authenticate(user=self.django_user)
        self.project = Project.objects.create(name="Projet test")
        self.entrepot = Venue.objects.create(project=self.project, name="Entrepôt", is_storage=True)
        self.salle = Venue.objects.create(project=self.project, name="Chapelle")
        self.show = Show.objects.create(
            project=self.project, title="Vertiges", venue=self.salle,
            event_type='performance', start_datetime=_dt(20), end_datetime=_dt(22),
            buffer_before_minutes=0, buffer_after_minutes=0,
        )
        self.console = Material.objects.create(
            project=self.project, name="Console", venue=self.entrepot, quantity=1,
        )
        self.alex = Technician.objects.create(project=self.project, name="Alex", specialty="Son")

    def _livraison(self, hour, origin, destination, material=None, day=1):
        transport = Transport.objects.create(
            show=self.show, transport_type='delivery',
            origin_venue=origin, destination_venue=destination,
            scheduled_datetime=_dt(hour, day=day), estimated_duration_minutes=60,
            status=Transport.STATUS_CONFIRMED,
        )
        if material is not None:
            TransportMaterial.objects.create(transport=transport, material=material, quantity=1)
        return transport

    # --- Matériel ---

    def test_material_journey_starts_at_home(self):
        response = self.client.get(f'/api/projects/{self.project.id}/material-journey/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ligne = next(m for m in response.data['materials'] if m['name'] == "Console")
        self.assertEqual(ligne['home_venue_name'], "Entrepôt")
        self.assertEqual(len(ligne['stays']), 1)
        self.assertEqual(ligne['stays'][0]['venue_name'], "Entrepôt")

    def test_material_journey_splits_on_transport(self):
        self._livraison(8, self.entrepot, self.salle, material=self.console)
        response = self.client.get(f'/api/projects/{self.project.id}/material-journey/')
        ligne = next(m for m in response.data['materials'] if m['name'] == "Console")
        lieux = [s['venue_name'] for s in ligne['stays']]
        self.assertEqual(lieux, ["Entrepôt", "Chapelle"])

    def test_material_journey_simple_relocation_has_no_fork_fields(self):
        # Déplacement complet (sans division) vers un lieu encore inoccupé :
        # même ligne renommée, ni bifurcation ni fusion à signaler.
        self._livraison(8, self.entrepot, self.salle, material=self.console)
        response = self.client.get(f'/api/projects/{self.project.id}/material-journey/')
        ligne = next(m for m in response.data['materials'] if m['name'] == "Console")
        stays = ligne['stays']
        self.assertEqual(len(stays), 2)
        self.assertEqual(stays[0]['lane'], stays[1]['lane'])
        self.assertIsNone(stays[0]['parent_lane'])
        self.assertIsNone(stays[0]['merge_from_lane'])
        self.assertIsNone(stays[1]['parent_lane'])
        self.assertIsNone(stays[1]['merge_from_lane'])

    def test_material_journey_forks_into_two_venues(self):
        # Demande de Samuel (2026-08-01) : un matériel à quantité multiple
        # scindé entre deux lieux à la fois doit créer une bifurcation, pas
        # s'aplatir sur le lieu majoritaire.
        caisse = Material.objects.create(
            project=self.project, name="Caisse", venue=self.entrepot, quantity=3,
        )
        transport = Transport.objects.create(
            show=self.show, transport_type='delivery',
            origin_venue=self.entrepot, destination_venue=self.salle,
            scheduled_datetime=_dt(8), estimated_duration_minutes=60,
            status=Transport.STATUS_CONFIRMED,
        )
        TransportMaterial.objects.create(transport=transport, material=caisse, quantity=2)

        response = self.client.get(f'/api/projects/{self.project.id}/material-journey/')
        ligne = next(m for m in response.data['materials'] if m['name'] == "Caisse")
        stays = ligne['stays']

        entrepot_stays = sorted((s for s in stays if s['venue_name'] == "Entrepôt"), key=lambda s: s['start'])
        chapelle_stays = [s for s in stays if s['venue_name'] == "Chapelle"]
        self.assertEqual(len(entrepot_stays), 2)
        self.assertEqual(len(chapelle_stays), 1)

        # L'origine garde la même ligne avant/après la bifurcation.
        self.assertEqual(entrepot_stays[0]['lane'], entrepot_stays[1]['lane'])
        self.assertEqual(entrepot_stays[0]['quantity'], 3)
        self.assertEqual(entrepot_stays[1]['quantity'], 1)

        # La partie qui part occupe une NOUVELLE ligne, distincte de l'origine.
        self.assertNotEqual(chapelle_stays[0]['lane'], entrepot_stays[0]['lane'])
        self.assertEqual(chapelle_stays[0]['quantity'], 2)
        self.assertEqual(chapelle_stays[0]['parent_lane'], entrepot_stays[0]['lane'])
        self.assertIsNone(chapelle_stays[0]['merge_from_lane'])

    def test_material_journey_cascading_fork(self):
        # Prévu explicitement par Samuel : une ligne née d'une bifurcation
        # doit pouvoir elle-même se scinder plus loin, sans limite de niveau.
        studio = Venue.objects.create(project=self.project, name="Studio")
        caisse = Material.objects.create(
            project=self.project, name="Caisse", venue=self.entrepot, quantity=5,
        )
        premier = Transport.objects.create(
            show=self.show, transport_type='delivery',
            origin_venue=self.entrepot, destination_venue=self.salle,
            scheduled_datetime=_dt(8), estimated_duration_minutes=60,
            status=Transport.STATUS_CONFIRMED,
        )
        TransportMaterial.objects.create(transport=premier, material=caisse, quantity=3)
        second = Transport.objects.create(
            show=self.show, transport_type='delivery',
            origin_venue=self.salle, destination_venue=studio,
            scheduled_datetime=_dt(10), estimated_duration_minutes=30,
            status=Transport.STATUS_CONFIRMED,
        )
        TransportMaterial.objects.create(transport=second, material=caisse, quantity=1)

        response = self.client.get(f'/api/projects/{self.project.id}/material-journey/')
        ligne = next(m for m in response.data['materials'] if m['name'] == "Caisse")
        stays = ligne['stays']
        lanes = {s['lane'] for s in stays}
        self.assertEqual(len(lanes), 3)

        entrepot_stays = sorted((s for s in stays if s['venue_name'] == "Entrepôt"), key=lambda s: s['start'])
        chapelle_stays = sorted((s for s in stays if s['venue_name'] == "Chapelle"), key=lambda s: s['start'])
        studio_stays = [s for s in stays if s['venue_name'] == "Studio"]
        self.assertEqual(len(entrepot_stays), 2)
        self.assertEqual(len(chapelle_stays), 2)
        self.assertEqual(len(studio_stays), 1)

        lane_entrepot = entrepot_stays[0]['lane']
        lane_chapelle = chapelle_stays[0]['lane']
        lane_studio = studio_stays[0]['lane']
        self.assertEqual({lane_entrepot, lane_chapelle, lane_studio}, lanes)

        # Bifurcation n°1 : Entrepôt (5) → Entrepôt continue (2) + Chapelle naît (3).
        self.assertEqual(entrepot_stays[0]['quantity'], 5)
        self.assertEqual(entrepot_stays[1]['quantity'], 2)
        self.assertEqual(chapelle_stays[0]['quantity'], 3)
        self.assertEqual(chapelle_stays[0]['parent_lane'], lane_entrepot)

        # Bifurcation n°2 : Chapelle (3) → Chapelle continue (2) + Studio naît (1).
        self.assertEqual(chapelle_stays[1]['quantity'], 2)
        self.assertEqual(studio_stays[0]['quantity'], 1)
        self.assertEqual(studio_stays[0]['parent_lane'], lane_chapelle)

        # L'Entrepôt n'est jamais reconcerné par la seconde bifurcation.
        self.assertNotEqual(lane_entrepot, lane_chapelle)
        self.assertNotEqual(lane_chapelle, lane_studio)

    def test_material_journey_merges_back_into_existing_lane(self):
        # Symétrique du test de bifurcation : une ligne qui revient vers un
        # lieu déjà occupé par une autre ligne doit fusionner dedans, pas
        # ouvrir une troisième ligne indépendante.
        caisse = Material.objects.create(
            project=self.project, name="Caisse", venue=self.entrepot, quantity=3,
        )
        depart = Transport.objects.create(
            show=self.show, transport_type='delivery',
            origin_venue=self.entrepot, destination_venue=self.salle,
            scheduled_datetime=_dt(8), estimated_duration_minutes=60,
            status=Transport.STATUS_CONFIRMED,
        )
        TransportMaterial.objects.create(transport=depart, material=caisse, quantity=2)
        retour = Transport.objects.create(
            show=self.show, transport_type='pickup',
            origin_venue=self.salle, destination_venue=self.entrepot,
            scheduled_datetime=_dt(10), estimated_duration_minutes=30,
            status=Transport.STATUS_CONFIRMED,
        )
        TransportMaterial.objects.create(transport=retour, material=caisse, quantity=2)

        response = self.client.get(f'/api/projects/{self.project.id}/material-journey/')
        ligne = next(m for m in response.data['materials'] if m['name'] == "Caisse")
        stays = ligne['stays']
        self.assertEqual(len(stays), 4)

        entrepot_stays = sorted((s for s in stays if s['venue_name'] == "Entrepôt"), key=lambda s: s['start'])
        chapelle_stays = [s for s in stays if s['venue_name'] == "Chapelle"]
        self.assertEqual(len(entrepot_stays), 3)
        self.assertEqual(len(chapelle_stays), 1)

        lane_entrepot = entrepot_stays[0]['lane']
        lane_chapelle = chapelle_stays[0]['lane']
        self.assertTrue(all(s['lane'] == lane_entrepot for s in entrepot_stays))

        self.assertEqual(entrepot_stays[0]['quantity'], 3)
        self.assertEqual(entrepot_stays[1]['quantity'], 1)
        self.assertEqual(entrepot_stays[2]['quantity'], 3)
        self.assertEqual(chapelle_stays[0]['quantity'], 2)
        self.assertEqual(chapelle_stays[0]['parent_lane'], lane_entrepot)

        # La fusion est annotée sur le tronçon d'arrivée, pas ailleurs.
        self.assertEqual(entrepot_stays[2]['merge_from_lane'], lane_chapelle)
        self.assertIsNone(entrepot_stays[0]['merge_from_lane'])
        self.assertIsNone(entrepot_stays[1]['merge_from_lane'])

    def test_material_journey_includes_confirmed_transports(self):
        self._livraison(8, self.entrepot, self.salle, material=self.console)
        response = self.client.get(f'/api/projects/{self.project.id}/material-journey/')
        ligne = next(m for m in response.data['materials'] if m['name'] == "Console")
        self.assertEqual(len(ligne['transports']), 1)
        self.assertEqual(ligne['transports'][0]['origin_venue_name'], "Entrepôt")
        self.assertEqual(ligne['transports'][0]['destination_venue_name'], "Chapelle")
        self.assertEqual(ligne['transports'][0]['quantity'], 1)
        self.assertEqual(ligne['transports'][0]['show_title'], "Vertiges")

    def test_material_journey_excludes_unconfirmed_transports(self):
        transport = Transport.objects.create(
            show=self.show, transport_type='delivery',
            origin_venue=self.entrepot, destination_venue=self.salle,
            scheduled_datetime=_dt(8), estimated_duration_minutes=60,
            status=Transport.STATUS_TO_APPROVE,
        )
        TransportMaterial.objects.create(transport=transport, material=self.console, quantity=1)
        response = self.client.get(f'/api/projects/{self.project.id}/material-journey/')
        ligne = next(m for m in response.data['materials'] if m['name'] == "Console")
        self.assertEqual(ligne['transports'], [])

    def test_material_journey_includes_assignments(self):
        ShowMaterial.objects.create(show=self.show, material=self.console, quantity=1)
        response = self.client.get(f'/api/projects/{self.project.id}/material-journey/')
        ligne = next(m for m in response.data['materials'] if m['name'] == "Console")
        self.assertEqual(len(ligne['assignments']), 1)
        self.assertEqual(ligne['assignments'][0]['show_title'], "Vertiges")

    def test_material_journey_filter(self):
        autre = Material.objects.create(
            project=self.project, name="Micro", venue=self.entrepot, quantity=1,
        )
        response = self.client.get(
            f'/api/projects/{self.project.id}/material-journey/', {'materials': str(autre.id)},
        )
        noms = [m['name'] for m in response.data['materials']]
        self.assertEqual(noms, ["Micro"])

    def test_window_is_empty_without_dates_or_events(self):
        vide = Project.objects.create(name="Projet vide")
        response = self.client.get(f'/api/projects/{vide.id}/material-journey/')
        self.assertIsNone(response.data['window'])
        self.assertEqual(response.data['materials'], [])

    # --- Techniciens ---

    def test_technician_journey_mixes_shows_and_transports(self):
        ShowTechnician.objects.create(show=self.show, technician=self.alex)
        transport = self._livraison(8, self.entrepot, self.salle)
        TransportTechnician.objects.create(transport=transport, technician=self.alex)

        response = self.client.get(f'/api/projects/{self.project.id}/technician-journey/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ligne = next(t for t in response.data['technicians'] if t['name'] == "Alex")
        kinds = [e['kind'] for e in ligne['engagements']]
        self.assertEqual(sorted(kinds), ['show', 'transport'])
        # Trié chronologiquement : le déplacement de 8h précède le spectacle de 20h.
        self.assertEqual(ligne['engagements'][0]['kind'], 'transport')

    def test_technician_journey_flags_conflicts(self):
        # Déplacement 20h-21h pendant le spectacle 20h-22h : conflit.
        ShowTechnician.objects.create(show=self.show, technician=self.alex)
        transport = self._livraison(20, self.entrepot, self.salle)
        TransportTechnician.objects.create(transport=transport, technician=self.alex)

        response = self.client.get(f'/api/projects/{self.project.id}/technician-journey/')
        ligne = next(t for t in response.data['technicians'] if t['name'] == "Alex")
        self.assertTrue(all(e['conflict'] for e in ligne['engagements']))

    def test_technician_journey_filter(self):
        autre = Technician.objects.create(project=self.project, name="Brigitte")
        response = self.client.get(
            f'/api/projects/{self.project.id}/technician-journey/', {'technicians': str(autre.id)},
        )
        noms = [t['name'] for t in response.data['technicians']]
        self.assertEqual(noms, ["Brigitte"])


class ShowPhasesAPITests(TestCase):
    """Vérifie les blocs rattachés à un événement (`Show.parent_show`, 2026-07-31).

    Demande de Samuel : pouvoir accrocher une plage de montage/répétition en
    amont d'un événement et une de démontage en aval. Choix de conception : un
    bloc est un `Show` complet rattaché par `parent_show`, plutôt qu'un modèle
    parallèle — il profite ainsi des conflits, des transports, du parcours et
    de la cohérence sans qu'on réécrive quoi que ce soit.

    Le point délicat couvert ici : un bloc collé à son événement ne doit PAS
    être vu comme un conflit de lieu avec lui. Leurs fenêtres effectives se
    chevauchent dès qu'un buffer est renseigné.
    """

    def setUp(self):
        self.client = APIClient()
        self.django_user = DjangoUser.objects.create_superuser('admin', 'admin@example.com', 'pw')
        self.client.force_authenticate(user=self.django_user)
        self.project = Project.objects.create(name="Projet test")
        self.salle = Venue.objects.create(project=self.project, name="Chapelle")
        self.autre_salle = Venue.objects.create(project=self.project, name="Salle 2")
        self.show = Show.objects.create(
            project=self.project, title="Vertiges", venue=self.salle,
            event_type='performance', start_datetime=_dt(20), end_datetime=_dt(22),
            buffer_before_minutes=60, buffer_after_minutes=60,
        )

    def _bloc(self, event_type='setup', debut=16, fin=19, **extra):
        payload = {
            'project': self.project.id, 'title': "Montage Vertiges",
            'venue': self.salle.id, 'event_type': event_type,
            'start_datetime': _dt(debut).isoformat(), 'end_datetime': _dt(fin).isoformat(),
            'buffer_before_minutes': 0, 'buffer_after_minutes': 0,
            'parent_show': self.show.id,
        }
        payload.update(extra)
        return self.client.post('/api/shows/', payload, format='json')

    def test_create_setup_block(self):
        response = self._bloc()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['parent_show'], self.show.id)
        self.assertEqual(response.data['event_type'], 'setup')

    def test_block_is_adjacent_to_its_show_without_conflict(self):
        # Le montage finit à 19h, le spectacle a un buffer avant de 60 min :
        # sa fenêtre effective commence à 19h. Sans l'exclusion de famille, ce
        # serait signalé comme conflit de lieu.
        response = self._bloc(debut=16, fin=19)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertNotIn('conflicts', response.data)

    def test_block_overlapping_another_show_still_conflicts(self):
        # L'exclusion ne vaut que pour la famille : un vrai voisin reste détecté.
        Show.objects.create(
            project=self.project, title="Autre", venue=self.salle,
            event_type='rehearsal', start_datetime=_dt(16), end_datetime=_dt(18),
            buffer_before_minutes=0, buffer_after_minutes=0,
        )
        response = self._bloc(debut=17, fin=19)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('conflicts', response.data)

    def test_phases_are_exposed_on_the_parent(self):
        self._bloc(event_type='setup', debut=16, fin=19)
        self._bloc(event_type='teardown', debut=22, fin=23)
        response = self.client.get(f'/api/shows/{self.show.id}/')
        types = [p['event_type'] for p in response.data['phases']]
        self.assertEqual(types, ['setup', 'teardown'])

    def test_a_block_has_no_phases_of_its_own(self):
        bloc = self._bloc()
        response = self.client.get(f"/api/shows/{bloc.data['id']}/")
        self.assertEqual(response.data['phases'], [])
        self.assertEqual(response.data['parent_show_title'], "Vertiges")

    def test_cannot_attach_a_block_to_a_block(self):
        bloc = self._bloc()
        response = self.client.post('/api/shows/', {
            'project': self.project.id, 'title': "Sous-bloc", 'venue': self.salle.id,
            'event_type': 'setup', 'start_datetime': _dt(14).isoformat(),
            'end_datetime': _dt(15).isoformat(), 'parent_show': bloc.data['id'],
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('parent_show', response.data)

    def test_block_must_share_the_venue_of_its_show(self):
        response = self._bloc(venue=self.autre_salle.id)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('venue', response.data)

    def test_block_must_share_the_project_of_its_show(self):
        autre_projet = Project.objects.create(name="Autre projet")
        autre_lieu = Venue.objects.create(project=autre_projet, name="Ailleurs")
        response = self.client.post('/api/shows/', {
            'project': autre_projet.id, 'title': "Montage", 'venue': autre_lieu.id,
            'event_type': 'setup', 'start_datetime': _dt(16).isoformat(),
            'end_datetime': _dt(19).isoformat(), 'parent_show': self.show.id,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('parent_show', response.data)

    def test_deleting_the_show_deletes_its_blocks(self):
        bloc = self._bloc()
        self.client.delete(f'/api/shows/{self.show.id}/')
        self.assertFalse(Show.objects.filter(id=bloc.data['id']).exists())

    def test_assigning_directly_to_a_setup_block_is_refused(self):
        # Depuis le 2026-07-31, un bloc de montage/démontage utilise le
        # matériel et l'équipe de son événement : l'assignation directe est
        # refusée pour éviter deux vérités concurrentes. (Un bloc de
        # répétition, lui, est autonome — voir RehearsalPhaseAutonomyTests.)
        bloc_id = self._bloc().data['id']
        alex = Technician.objects.create(project=self.project, name="Alex")
        response = self.client.post('/api/show-technicians/', {
            'show': bloc_id, 'technician': alex.id,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('show', response.data)

        console = Material.objects.create(
            project=self.project, name="Console", venue=self.salle, quantity=1,
        )
        response = self.client.post('/api/show-materials/', {
            'show': bloc_id, 'material': console.id, 'quantity': 1,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('show', response.data)


class ShowPhaseInheritanceTests(TestCase):
    """L'équipe et le matériel d'un événement couvrent ses blocs (2026-07-31).

    Demande de Samuel : « pour le montage et le démontage, le matériel et le
    technicien sont considérés comme étant les mêmes que le spectacle ».
    Implémenté par une **fenêtre d'engagement étendue** (`Show.engagement_start`
    /`engagement_end`) plutôt qu'en recopiant les assignations dans chaque
    bloc : une seule vérité, qui ne peut pas diverger quand on modifie
    l'événement après coup.

    Ne vaut que pour le montage et le démontage — un bloc de RÉPÉTITION est
    autonome (voir `RehearsalPhaseAutonomyTests`).

    À distinguer de `effective_start`/`effective_end`, qui restent la fenêtre
    du seul créneau et servent au conflit de LIEU.
    """

    def setUp(self):
        self.client = APIClient()
        self.django_user = DjangoUser.objects.create_superuser('admin', 'admin@example.com', 'pw')
        self.client.force_authenticate(user=self.django_user)
        self.project = Project.objects.create(name="Projet test")
        self.salle = Venue.objects.create(project=self.project, name="Chapelle")
        self.autre_salle = Venue.objects.create(project=self.project, name="Salle 2")
        self.entrepot = Venue.objects.create(project=self.project, name="Entrepôt", is_storage=True)

        # Spectacle 20h-22h, sans buffer pour que les fenêtres soient lisibles.
        self.show = Show.objects.create(
            project=self.project, title="Vertiges", venue=self.salle,
            event_type='performance', start_datetime=_dt(20), end_datetime=_dt(22),
            buffer_before_minutes=0, buffer_after_minutes=0,
        )
        # Montage 16h-19h, rattaché.
        self.montage = Show.objects.create(
            project=self.project, title="Montage", venue=self.salle,
            event_type='setup', start_datetime=_dt(16), end_datetime=_dt(19),
            buffer_before_minutes=0, buffer_after_minutes=0,
            parent_show=self.show,
        )
        self.alex = Technician.objects.create(project=self.project, name="Alex")
        self.console = Material.objects.create(
            project=self.project, name="Console", venue=self.entrepot, quantity=1,
        )

    def test_engagement_window_covers_the_blocks(self):
        self.show.refresh_from_db()
        self.assertEqual(self.show.engagement_start, self.montage.effective_start)
        self.assertEqual(self.show.engagement_end, self.show.effective_end)
        # La fenêtre du créneau, elle, ne bouge pas — c'est celle du conflit de lieu.
        self.assertEqual(self.show.effective_start, _dt(20))

    def test_technician_is_busy_during_the_setup(self):
        ShowTechnician.objects.create(show=self.show, technician=self.alex)
        # Autre engagement pendant le MONTAGE (17h-18h), ailleurs.
        ailleurs = Show.objects.create(
            project=self.project, title="Ailleurs", venue=self.autre_salle,
            event_type='rehearsal', start_datetime=_dt(17), end_datetime=_dt(18),
            buffer_before_minutes=0, buffer_after_minutes=0,
        )
        response = self.client.post('/api/show-technicians/', {
            'show': ailleurs.id, 'technician': self.alex.id,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('conflicts', response.data)

    def test_material_is_reserved_during_the_setup(self):
        ShowMaterial.objects.create(show=self.show, material=self.console, quantity=1)
        ailleurs = Show.objects.create(
            project=self.project, title="Ailleurs", venue=self.autre_salle,
            event_type='rehearsal', start_datetime=_dt(17), end_datetime=_dt(18),
            buffer_before_minutes=0, buffer_after_minutes=0,
        )
        response = self.client.post('/api/show-materials/', {
            'show': ailleurs.id, 'material': self.console.id, 'quantity': 1,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('conflicts', response.data)

    def test_no_conflict_outside_the_extended_window(self):
        # Avant le montage : la ressource est libre.
        ShowTechnician.objects.create(show=self.show, technician=self.alex)
        avant = Show.objects.create(
            project=self.project, title="Tôt le matin", venue=self.autre_salle,
            event_type='rehearsal', start_datetime=_dt(9), end_datetime=_dt(10),
            buffer_before_minutes=0, buffer_after_minutes=0,
        )
        response = self.client.post('/api/show-technicians/', {
            'show': avant.id, 'technician': self.alex.id,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_a_show_without_blocks_keeps_its_own_window(self):
        # Pas de régression pour les événements sans bloc : engagement = créneau.
        seul = Show.objects.create(
            project=self.project, title="Seul", venue=self.autre_salle,
            event_type='performance', start_datetime=_dt(14), end_datetime=_dt(15),
            buffer_before_minutes=30, buffer_after_minutes=30,
        )
        self.assertEqual(seul.engagement_start, seul.effective_start)
        self.assertEqual(seul.engagement_end, seul.effective_end)

    def test_api_exposes_engagement_window(self):
        # La fiche a besoin de la fenêtre RÉELLEMENT mobilisée (montage
        # compris) pour l'afficher — distincte de `effective_start`/`_end`,
        # qui reste le créneau seul et sert au conflit de lieu (2026-08-01,
        # demande de Samuel : corriger l'affichage de la fenêtre effective
        # sur la fiche spectacle pour inclure montage/démontage + buffer).
        response = self.client.get(f'/api/shows/{self.show.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            parse_datetime(response.data['engagement_start']), self.montage.effective_start,
        )
        self.assertEqual(
            parse_datetime(response.data['engagement_end']), self.show.effective_end,
        )
        # Sur ce spectacle, le montage recule bien le début par rapport au
        # seul créneau — sinon le test ne prouverait rien.
        self.assertNotEqual(
            response.data['engagement_start'], response.data['effective_start'],
        )

    def test_display_title_reflects_current_parent_name(self):
        # Signalé par Samuel (2026-08-02) : le titre d'un bloc était généré
        # UNE FOIS à sa création et ne bougeait plus si l'événement était
        # renommé ensuite. `display_title` recalcule à chaque lecture depuis
        # `parent_show.title` — rien n'est jamais recopié.
        bloc = Show.objects.create(
            project=self.project, venue=self.salle, event_type='teardown',
            start_datetime=_dt(22), end_datetime=_dt(23),
            buffer_before_minutes=0, buffer_after_minutes=0,
            parent_show=self.show,
        )
        self.assertEqual(bloc.display_title, "Démontage — Vertiges")
        self.show.title = "Vertiges (reprise)"
        self.show.save()
        bloc.refresh_from_db()
        self.assertEqual(bloc.display_title, "Démontage — Vertiges (reprise)")

    def test_display_title_with_optional_suffix(self):
        # `title`, pour un bloc, n'est plus le nom complet mais une précision
        # optionnelle ajoutée après le type.
        bloc = Show.objects.create(
            project=self.project, venue=self.salle, event_type='rehearsal',
            title="technique", start_datetime=_dt(10), end_datetime=_dt(12),
            buffer_before_minutes=0, buffer_after_minutes=0,
            parent_show=self.show,
        )
        self.assertEqual(bloc.display_title, "Répétition technique — Vertiges")

    def test_title_optional_for_a_block_but_required_for_a_top_level_show(self):
        # Un bloc peut être créé sans titre (2026-08-02, cas par défaut côté
        # frontend depuis cette même demande de Samuel).
        response = self.client.post('/api/shows/', {
            'project': self.project.id, 'venue': self.salle.id,
            'event_type': 'teardown', 'title': '',
            'start_datetime': _dt(22).isoformat(), 'end_datetime': _dt(23).isoformat(),
            'buffer_before_minutes': 0, 'buffer_after_minutes': 0,
            'parent_show': self.show.id,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['display_title'], "Démontage — Vertiges")

        # Un événement top-level, lui, exige toujours un titre — `blank=True`
        # côté modèle ne devait rendre `title` optionnel QUE pour un bloc.
        response = self.client.post('/api/shows/', {
            'project': self.project.id, 'venue': self.autre_salle.id,
            'event_type': 'performance', 'title': '',
            'start_datetime': _dt(9).isoformat(), 'end_datetime': _dt(10).isoformat(),
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('title', response.data)


class RehearsalPhaseAutonomyTests(TestCase):
    """Un bloc de répétition rattaché a SES ressources (2026-07-31, Samuel).

    Précision apportée après coup : « le bloc répétition n'obtient pas de
    matériel et de technicien du spectacle parent. On va copier les infos lors
    de la création mais on permet d'éditer par la suite ». Un montage manipule
    forcément le matériel du spectacle avec son équipe ; une répétition est un
    vrai temps de travail, où l'on n'utilise pas nécessairement tout, ni avec
    les mêmes personnes.

    Trois conséquences vérifiées ici :

    - la copie a lieu **à la création**, et une fois seulement (ce qu'on ajoute
      plus tard à l'événement ne redescend pas) ;
    - les assignations du bloc s'éditent comme celles de n'importe quel
      événement, sans toucher à celles de l'événement ;
    - l'événement ne se met pas en conflit avec sa propre répétition, alors
      qu'ils réclament le même matériel sur des fenêtres qui se touchent —
      c'est l'exclusion de famille de `get_material_conflicts`.
    """

    def setUp(self):
        self.client = APIClient()
        self.django_user = DjangoUser.objects.create_superuser('admin', 'admin@example.com', 'pw')
        self.client.force_authenticate(user=self.django_user)
        self.project = Project.objects.create(name="Projet test")
        self.salle = Venue.objects.create(project=self.project, name="Chapelle")
        self.autre_salle = Venue.objects.create(project=self.project, name="Salle 2")
        self.entrepot = Venue.objects.create(project=self.project, name="Entrepôt", is_storage=True)

        # Spectacle 20h-22h, avec un buffer avant d'une heure : la fenêtre
        # effective de l'événement démarre donc à 19h, et mord sur la
        # répétition ci-dessous — c'est exactement le cas qui produirait un
        # faux conflit sans exclusion de famille.
        self.show = Show.objects.create(
            project=self.project, title="Vertiges", venue=self.salle,
            event_type='performance', start_datetime=_dt(20), end_datetime=_dt(22),
            buffer_before_minutes=60, buffer_after_minutes=0,
        )
        self.alex = Technician.objects.create(project=self.project, name="Alex")
        self.console = Material.objects.create(
            project=self.project, name="Console", venue=self.entrepot, quantity=1,
        )
        ShowTechnician.objects.create(show=self.show, technician=self.alex)
        ShowMaterial.objects.create(show=self.show, material=self.console, quantity=1)

    def _bloc(self, event_type='rehearsal', debut=16, fin=19):
        return self.client.post('/api/shows/', {
            'project': self.project.id, 'title': "Répétition Vertiges",
            'venue': self.salle.id, 'event_type': event_type,
            'start_datetime': _dt(debut).isoformat(), 'end_datetime': _dt(fin).isoformat(),
            'buffer_before_minutes': 0, 'buffer_after_minutes': 0,
            'parent_show': self.show.id,
        }, format='json')

    def test_creating_a_rehearsal_block_copies_the_assignments(self):
        bloc_id = self._bloc().data['id']
        self.assertEqual(
            list(ShowMaterial.objects.filter(show_id=bloc_id).values_list('material_id', flat=True)),
            [self.console.id],
        )
        self.assertEqual(
            list(ShowTechnician.objects.filter(show_id=bloc_id).values_list('technician_id', flat=True)),
            [self.alex.id],
        )

    def test_creating_a_setup_block_copies_nothing(self):
        # Le montage n'a rien à recopier : il puise en permanence dans les
        # ressources de l'événement (fenêtre d'engagement).
        bloc_id = self._bloc(event_type='setup').data['id']
        self.assertFalse(ShowMaterial.objects.filter(show_id=bloc_id).exists())
        self.assertFalse(ShowTechnician.objects.filter(show_id=bloc_id).exists())

    def test_later_assignments_on_the_event_do_not_reach_the_block(self):
        # La copie est un point de départ, pas un lien permanent.
        bloc_id = self._bloc().data['id']
        gradateur = Material.objects.create(
            project=self.project, name="Gradateur", venue=self.entrepot, quantity=1,
        )
        ShowMaterial.objects.create(show=self.show, material=gradateur, quantity=1)
        self.assertEqual(ShowMaterial.objects.filter(show_id=bloc_id).count(), 1)

    def test_the_block_accepts_its_own_assignments(self):
        bloc_id = self._bloc().data['id']
        sam = Technician.objects.create(project=self.project, name="Sam")
        response = self.client.post('/api/show-technicians/', {
            'show': bloc_id, 'technician': sam.id,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_removing_from_the_block_leaves_the_event_intact(self):
        bloc_id = self._bloc().data['id']
        copie = ShowMaterial.objects.get(show_id=bloc_id, material=self.console)
        response = self.client.delete(f'/api/show-materials/{copie.id}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertTrue(ShowMaterial.objects.filter(show=self.show, material=self.console).exists())

    def test_the_engagement_window_ignores_a_rehearsal_block(self):
        # Contrairement à un montage, une répétition rattachée n'étire pas la
        # fenêtre d'engagement de l'événement : elle répond pour elle-même.
        self._bloc()
        self.show.refresh_from_db()
        self.assertEqual(self.show.engagement_start, self.show.effective_start)
        self.assertEqual(self.show.engagement_end, self.show.effective_end)

    def test_the_copy_is_not_a_conflict_with_its_own_event(self):
        # La répétition finit à 19h30, l'événement démarre effectivement à 19h :
        # les deux réclament la console sur une demi-heure commune. Un même
        # événement et ses blocs forment une seule unité de travail.
        self._bloc(debut=16, fin=19)
        bloc = Show.objects.get(parent_show=self.show)
        bloc.end_datetime = _dt(20)
        bloc.save()
        rapport = get_project_conflicts(self.project)
        self.assertEqual(rapport['material_conflicts'], [])
        self.assertEqual(rapport['technician_conflicts'], [])

    def test_a_third_show_still_conflicts_with_the_block(self):
        # L'exclusion ne vaut que dans la famille : une demande extérieure
        # pendant la répétition reste bloquée.
        self._bloc(debut=16, fin=19)
        ailleurs = Show.objects.create(
            project=self.project, title="Ailleurs", venue=self.autre_salle,
            event_type='rehearsal', start_datetime=_dt(17), end_datetime=_dt(18),
            buffer_before_minutes=0, buffer_after_minutes=0,
        )
        response = self.client.post('/api/show-materials/', {
            'show': ailleurs.id, 'material': self.console.id, 'quantity': 1,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('conflicts', response.data)

    def test_phases_expose_their_resource_mode(self):
        self._bloc(event_type='rehearsal', debut=16, fin=19)
        self._bloc(event_type='teardown', debut=22, fin=23)
        response = self.client.get(f'/api/shows/{self.show.id}/')
        repetition, demontage = response.data['phases']
        self.assertFalse(repetition['inherits_resources'])
        self.assertEqual(repetition['material_count'], 1)
        self.assertEqual(repetition['technician_count'], 1)
        self.assertTrue(demontage['inherits_resources'])
        self.assertIsNone(demontage['material_count'])


class MaterialScheduleAPITests(TestCase):
    """Agenda d'un matériel — `GET /api/materials/{id}/schedule/` (2026-08-01).

    Demande de Samuel : la fiche matériel doit montrer, en plus des
    assignations à des spectacles, les montages, démontages, répétitions et
    déplacements, dans l'ordre chronologique.

    Le point qui justifie de calculer ça côté backend : un montage n'a AUCUNE
    assignation propre — il utilise le matériel de son événement (voir
    `Show.inherits_resources`). Le déduire côté Vue reviendrait à y recopier
    une règle métier.
    """

    def setUp(self):
        self.client = APIClient()
        self.django_user = DjangoUser.objects.create_superuser('admin', 'admin@example.com', 'pw')
        self.client.force_authenticate(user=self.django_user)
        self.project = Project.objects.create(name="Projet test")
        self.salle = Venue.objects.create(project=self.project, name="Chapelle")
        self.autre_salle = Venue.objects.create(project=self.project, name="Salle 2")
        self.console = Material.objects.create(
            project=self.project, name="Console", venue=self.salle, quantity=2,
        )
        self.show = Show.objects.create(
            project=self.project, title="Vertiges", venue=self.salle,
            event_type='performance', start_datetime=_dt(20), end_datetime=_dt(22),
            buffer_before_minutes=0, buffer_after_minutes=0,
        )

    def _agenda(self):
        response = self.client.get(f'/api/materials/{self.console.id}/schedule/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.data['entries']

    def test_an_assignment_appears_with_its_schedule(self):
        ShowMaterial.objects.create(show=self.show, material=self.console, quantity=2)
        entree = next(e for e in self._agenda() if e['id'] == self.show.id)
        self.assertEqual(entree['kind'], 'show')
        self.assertEqual(entree['event_type'], 'performance')
        self.assertEqual(entree['quantity'], 2)
        self.assertEqual(entree['venue_name'], "Chapelle")
        self.assertFalse(entree['inherited'])

    def test_setup_and_teardown_appear_without_being_assigned(self):
        ShowMaterial.objects.create(show=self.show, material=self.console, quantity=1)
        montage = Show.objects.create(
            project=self.project, title="Montage", venue=self.salle,
            event_type='setup', start_datetime=_dt(16), end_datetime=_dt(19),
            buffer_before_minutes=0, buffer_after_minutes=0, parent_show=self.show,
        )
        demontage = Show.objects.create(
            project=self.project, title="Démontage", venue=self.salle,
            event_type='teardown', start_datetime=_dt(22), end_datetime=_dt(23),
            buffer_before_minutes=0, buffer_after_minutes=0, parent_show=self.show,
        )
        # Aucun de ces blocs ne porte de ShowMaterial : c'est bien la règle
        # d'héritage qui les fait apparaître.
        self.assertFalse(ShowMaterial.objects.filter(show_id=montage.id).exists())
        agenda = {e['id']: e for e in self._agenda() if e['kind'] == 'show'}
        self.assertTrue(agenda[montage.id]['inherited'])
        self.assertEqual(agenda[montage.id]['parent_title'], "Vertiges")
        self.assertTrue(agenda[demontage.id]['inherited'])

    def test_an_attached_rehearsal_appears_once_and_is_not_inherited(self):
        # Le bloc de répétition porte SA copie (2026-07-31) : il doit compter
        # comme une assignation à part entière, pas comme un bloc hérité.
        ShowMaterial.objects.create(show=self.show, material=self.console, quantity=1)
        repetition = Show.objects.create(
            project=self.project, title="Répétition", venue=self.salle,
            event_type='rehearsal', start_datetime=_dt(14), end_datetime=_dt(16),
            buffer_before_minutes=0, buffer_after_minutes=0, parent_show=self.show,
        )
        ShowMaterial.objects.create(show=repetition, material=self.console, quantity=1)
        lignes = [e for e in self._agenda() if e['id'] == repetition.id and e['kind'] == 'show']
        self.assertEqual(len(lignes), 1)
        self.assertFalse(lignes[0]['inherited'])

    def test_entries_are_sorted_chronologically(self):
        # Titre du bloc laissé vide à dessein (2026-08-02) : sur un bloc,
        # `title` n'est plus qu'une précision optionnelle — voir
        # `Show.display_title`, qui calcule "Montage — Vertiges" tout seul.
        ShowMaterial.objects.create(show=self.show, material=self.console, quantity=1)
        Show.objects.create(
            project=self.project, venue=self.salle,
            event_type='setup', start_datetime=_dt(16), end_datetime=_dt(19),
            buffer_before_minutes=0, buffer_after_minutes=0, parent_show=self.show,
        )
        titres = [e['title'] for e in self._agenda() if e['kind'] == 'show']
        self.assertEqual(titres, ["Montage — Vertiges", "Vertiges"])

    def test_a_transport_appears_in_the_timeline(self):
        transport = Transport.objects.create(
            show=self.show, transport_type='delivery',
            origin_venue=self.autre_salle, destination_venue=self.salle,
            scheduled_datetime=_dt(12), estimated_duration_minutes=60,
            status='confirmed',
        )
        TransportMaterial.objects.create(transport=transport, material=self.console, quantity=2)
        entree = next(e for e in self._agenda() if e['kind'] == 'transport')
        self.assertEqual(entree['id'], transport.id)
        self.assertEqual(entree['quantity'], 2)
        self.assertIn("Salle 2", entree['title'])

    def test_an_unscheduled_proposal_is_listed_last_without_a_date(self):
        # Une proposition à approuver n'a pas d'heure : la masquer cacherait
        # justement ce qu'il reste à compléter.
        ShowMaterial.objects.create(show=self.show, material=self.console, quantity=1)
        proposition = Transport.objects.create(
            show=self.show, transport_type='delivery',
            origin_venue=self.autre_salle, destination_venue=self.salle,
            scheduled_datetime=None, estimated_duration_minutes=60,
            status='to_approve',
        )
        TransportMaterial.objects.create(transport=proposition, material=self.console, quantity=1)
        agenda = self._agenda()
        sans_heure = [e for e in agenda if e['start'] is None]
        self.assertTrue(sans_heure)
        self.assertEqual(agenda[-1]['start'], None)

    def test_the_window_follows_the_project_dates(self):
        # Fenêtre bornée aux dates du projet (2026-08-01) — la même que les
        # écrans « Parcours », pour que les deux racontent la même période.
        self.project.start_date = _dt(0).date()
        self.project.end_date = _dt(0).date()
        self.project.save()
        response = self.client.get(f'/api/materials/{self.console.id}/schedule/')
        self.assertIsNotNone(response.data['window']['start'])
        self.assertIsNotNone(response.data['window']['end'])

    def test_an_entry_outside_the_project_dates_is_set_aside(self):
        # Écartée, mais comptée : une assignation qui disparaîtrait sans un mot
        # ferait douter de l'écran plutôt que des dates du projet.
        ShowMaterial.objects.create(show=self.show, material=self.console, quantity=1)
        hors_projet = Show.objects.create(
            project=self.project, title="L'an prochain", venue=self.salle,
            event_type='performance',
            start_datetime=_dt(20, day=28), end_datetime=_dt(22, day=28),
            buffer_before_minutes=0, buffer_after_minutes=0,
        )
        ShowMaterial.objects.create(show=hors_projet, material=self.console, quantity=1)
        self.project.start_date = _dt(0).date()
        self.project.end_date = _dt(0).date()
        self.project.save()

        response = self.client.get(f'/api/materials/{self.console.id}/schedule/')
        ids = {e['id'] for e in response.data['entries'] if e['kind'] == 'show'}
        self.assertIn(self.show.id, ids)
        self.assertNotIn(hors_projet.id, ids)
        self.assertEqual(response.data['outside_window'], 1)

    def test_an_unscheduled_proposal_survives_the_window(self):
        # Sans heure, rien à comparer à la fenêtre — et c'est justement ce
        # qu'il reste à planifier, donc on la garde.
        self.project.start_date = _dt(0).date()
        self.project.end_date = _dt(0).date()
        self.project.save()
        proposition = Transport.objects.create(
            show=self.show, transport_type='delivery',
            origin_venue=self.autre_salle, destination_venue=self.salle,
            scheduled_datetime=None, estimated_duration_minutes=60,
            status='to_approve',
        )
        TransportMaterial.objects.create(transport=proposition, material=self.console, quantity=1)
        response = self.client.get(f'/api/materials/{self.console.id}/schedule/')
        self.assertIn(
            proposition.id,
            {e['id'] for e in response.data['entries'] if e['kind'] == 'transport'},
        )

    def test_a_conflict_is_reported_on_the_assignment(self):
        ShowMaterial.objects.create(show=self.show, material=self.console, quantity=2)
        ailleurs = Show.objects.create(
            project=self.project, title="Ailleurs", venue=self.autre_salle,
            event_type='rehearsal', start_datetime=_dt(21), end_datetime=_dt(23),
            buffer_before_minutes=0, buffer_after_minutes=0,
        )
        ShowMaterial.objects.create(show=ailleurs, material=self.console, quantity=1)
        conflits = [e for e in self._agenda() if e.get('conflict')]
        self.assertEqual({e['id'] for e in conflits}, {self.show.id, ailleurs.id})


class MaterialDistributionAPITests(TestCase):
    """Répartition d'un matériel entre les lieux — `GET /api/materials/{id}/distribution/`.

    Ajoutée le 2026-08-01 à la demande de Samuel : un matériel possédé en
    plusieurs exemplaires peut se séparer entre plusieurs lieux, et la fiche
    n'affichait que son lieu d'ORIGINE — faux dès qu'un transport en a bougé
    une partie. Affiché sur toute la durée du projet (deuxième précision de
    Samuel, même jour), une barre par lieu, plutôt qu'une photo à un instant.

    L'endpoint réutilise `get_material_journey`/`get_material_transports` : les
    tests portent donc sur le contrat de la réponse et sur la fenêtre, pas sur
    l'algorithme des séjours, déjà couvert par `ParcoursAPITests`.
    """

    def setUp(self):
        self.client = APIClient()
        self.django_user = DjangoUser.objects.create_superuser('admin', 'admin@example.com', 'pw')
        self.client.force_authenticate(user=self.django_user)
        self.project = Project.objects.create(name="Projet test")
        self.entrepot = Venue.objects.create(
            project=self.project, name="Entrepôt", code="ENTR", is_storage=True,
        )
        self.salle = Venue.objects.create(project=self.project, name="Chapelle", code="CHAP")
        self.rallonges = Material.objects.create(
            project=self.project, name="Rallonges", venue=self.entrepot, quantity=20,
        )
        self.show = Show.objects.create(
            project=self.project, title="Vertiges", venue=self.salle,
            event_type='performance', start_datetime=_dt(20), end_datetime=_dt(22),
            buffer_before_minutes=0, buffer_after_minutes=0,
        )

    def _transport(self, quantity, depart, duree=60, statut='confirmed'):
        transport = Transport.objects.create(
            show=self.show, transport_type='delivery',
            origin_venue=self.entrepot, destination_venue=self.salle,
            scheduled_datetime=depart, estimated_duration_minutes=duree,
            status=statut,
        )
        TransportMaterial.objects.create(
            transport=transport, material=self.rallonges, quantity=quantity,
        )
        return transport

    def _repartition(self):
        response = self.client.get(f'/api/materials/{self.rallonges.id}/distribution/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.data

    def test_the_window_covers_the_whole_project(self):
        data = self._repartition()
        self.assertEqual(data['total'], 20)
        self.assertIsNotNone(data['window']['start'])
        self.assertIsNotNone(data['window']['end'])

    def test_everything_sits_at_its_origin_before_any_transport(self):
        data = self._repartition()
        lieux = {s['venue_id'] for s in data['stays']}
        self.assertEqual(lieux, {self.entrepot.id})
        self.assertEqual(data['stays'][0]['quantity'], 20)

    def test_a_partial_transport_splits_the_stock_between_two_venues(self):
        self._transport(quantity=8, depart=_dt(10))
        data = self._repartition()
        # Les deux lieux détiennent une part du stock après le déplacement.
        apres = [s for s in data['stays'] if s['venue_id'] == self.salle.id]
        self.assertTrue(apres)
        self.assertEqual(apres[0]['quantity'], 8)
        reste = [
            s for s in data['stays']
            if s['venue_id'] == self.entrepot.id and s['quantity'] == 12
        ]
        self.assertTrue(reste)

    def test_a_confirmed_transport_is_returned_alongside_the_stays(self):
        transport = self._transport(quantity=8, depart=_dt(10))
        data = self._repartition()
        self.assertEqual([t['transport_id'] for t in data['transports']], [transport.id])

    def test_an_unconfirmed_proposal_moves_nothing(self):
        # Même règle que le reste du module : seule une confirmation déplace.
        self._transport(quantity=8, depart=_dt(10), statut='to_approve')
        data = self._repartition()
        self.assertEqual({s['venue_id'] for s in data['stays']}, {self.entrepot.id})
        self.assertEqual(data['transports'], [])

    def test_a_project_without_dates_or_events_has_no_window(self):
        vide = Project.objects.create(name="Projet vide")
        lieu = Venue.objects.create(project=vide, name="Ailleurs")
        materiel = Material.objects.create(
            project=vide, name="Câbles", venue=lieu, quantity=5,
        )
        response = self.client.get(f'/api/materials/{materiel.id}/distribution/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data['window'])
        self.assertEqual(response.data['stays'], [])

    def test_an_inactive_material_still_answers(self):
        # On arrive ici depuis la fiche, qui reste consultable pour un matériel
        # désactivé — contrairement à la liste du parcours, filtrée sur actif.
        self.rallonges.is_active = False
        self.rallonges.save()
        response = self.client.get(f'/api/materials/{self.rallonges.id}/distribution/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['stays'])
