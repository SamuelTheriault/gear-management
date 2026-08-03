"""
Tests de l'accès multi-tenant par projet (2026-08-02) : `ProjectMembership`,
`HasProjectAccess`/`IsStaffGlobal` (permissions.py), `ProjectMembershipViewSet`
(invitations/rôles/retraits) et l'activation des invitations `pending` au
premier login Google (voir `signals.py`).

Suit le style de `test_oauth_provisioning.py` (APIClient +
`force_authenticate` sur un `django.contrib.auth.User`), avec un helper
`_make_member` pour créer en un appel le trio compte Django + profil
`inventory.User` + `ProjectMembership` que ce module teste sans arrêt.
"""

import importlib

from django.contrib.auth.models import User as DjangoUser
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .models import MaterialCategory, Project, ProjectMembership, Venue
from .models import User as InventoryUser


def _cat(project, name):
    return MaterialCategory.objects.get_or_create(project=project, name=name)[0]


def _dt(hour, day=1):
    """Petit helper pour construire des datetimes aware — même convention que `tests.py`."""
    return timezone.make_aware(timezone.datetime(2026, 9, day, hour, 0))


def _make_member(email, project=None, role=None, status=ProjectMembership.STATUS_ACTIVE, is_staff_global=False):
    """Crée un `django.contrib.auth.User` authentifiable, son profil
    `inventory.User` lié, et (si `role` est fourni) un `ProjectMembership`
    sur `project` avec ce rôle. Retourne `(django_user, inventory_user)`."""
    django_user = DjangoUser.objects.create_user(username=email, email=email, password='pw')
    inventory_user = InventoryUser.objects.create(
        email=email, name=email, django_user=django_user, is_staff_global=is_staff_global,
    )
    if role is not None:
        ProjectMembership.objects.create(project=project, user=inventory_user, role=role, status=status)
    return django_user, inventory_user


class ProjectAccessPermissionTests(TestCase):
    """Vérifie `HasProjectAccess` sur une ressource project-scoped ordinaire
    (`VenueViewSet`) : bypass staff, rôles owner/editor/viewer, non-membre."""

    def setUp(self):
        self.project = Project.objects.create(name="Projet test")
        self.venue = Venue.objects.create(project=self.project, name="Entrepôt", is_storage=True)
        self.client = APIClient()

    def test_staff_global_bypasses_membership_entirely(self):
        django_user, _profile = _make_member('staff@example.com', is_staff_global=True)
        self.client.force_authenticate(user=django_user)
        response = self.client.get(f'/api/venues/?project={self.project.id}')
        self.assertEqual(response.status_code, 200)
        self.assertIn("Entrepôt", [v['name'] for v in response.data])

    def test_owner_can_write(self):
        django_user, _profile = _make_member('owner@example.com', self.project, ProjectMembership.ROLE_OWNER)
        self.client.force_authenticate(user=django_user)
        response = self.client.patch(f'/api/venues/{self.venue.id}/', {'name': "Nouveau nom"}, format='json')
        self.assertEqual(response.status_code, 200)

    def test_editor_can_write(self):
        django_user, _profile = _make_member('editor@example.com', self.project, ProjectMembership.ROLE_EDITOR)
        self.client.force_authenticate(user=django_user)
        response = self.client.patch(f'/api/venues/{self.venue.id}/', {'name': "Nouveau nom"}, format='json')
        self.assertEqual(response.status_code, 200)

    def test_viewer_can_read(self):
        django_user, _profile = _make_member('viewer@example.com', self.project, ProjectMembership.ROLE_VIEWER)
        self.client.force_authenticate(user=django_user)
        response = self.client.get(f'/api/venues/{self.venue.id}/')
        self.assertEqual(response.status_code, 200)

    def test_viewer_cannot_write(self):
        django_user, _profile = _make_member('viewer2@example.com', self.project, ProjectMembership.ROLE_VIEWER)
        self.client.force_authenticate(user=django_user)
        response = self.client.patch(f'/api/venues/{self.venue.id}/', {'name': "Nouveau nom"}, format='json')
        self.assertEqual(response.status_code, 403)

    def test_pending_membership_does_not_count_as_access(self):
        django_user, _profile = _make_member(
            'pending@example.com', self.project, ProjectMembership.ROLE_OWNER,
            status=ProjectMembership.STATUS_PENDING,
        )
        self.client.force_authenticate(user=django_user)
        response = self.client.get(f'/api/venues/{self.venue.id}/')
        self.assertIn(response.status_code, (403, 404))

    def test_non_member_gets_403_or_404_on_detail_of_foreign_project(self):
        other_project = Project.objects.create(name="Autre projet")
        django_user, _profile = _make_member('outsider@example.com', other_project, ProjectMembership.ROLE_OWNER)
        self.client.force_authenticate(user=django_user)
        response = self.client.get(f'/api/venues/{self.venue.id}/')
        self.assertIn(response.status_code, (403, 404))

    def test_non_member_list_of_foreign_project_is_empty_not_leaked(self):
        other_project = Project.objects.create(name="Autre projet 2")
        django_user, _profile = _make_member('outsider2@example.com', other_project, ProjectMembership.ROLE_VIEWER)
        self.client.force_authenticate(user=django_user)
        response = self.client.get(f'/api/venues/?project={self.project.id}')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.data), [])

    def test_authenticated_user_without_inventory_profile_is_denied(self):
        django_user = DjangoUser.objects.create_user(username='noprofile', email='noprofile@example.com', password='pw')
        self.client.force_authenticate(user=django_user)
        response = self.client.get(f'/api/venues/?project={self.project.id}')
        self.assertEqual(response.status_code, 403)

    def test_show_material_resolves_project_via_show_relation(self):
        # ShowMaterial n'a pas de FK project directe — vérifie que
        # HasProjectAccess/ProjectMembershipQuerysetMixin la résolvent via
        # `show.project` (project_lookup='show__project_id').
        from .models import Material, Show

        show = Show.objects.create(
            project=self.project, title="Spectacle", venue=self.venue, event_type='performance',
            start_datetime=_dt(18), end_datetime=_dt(20),
        )
        material = Material.objects.create(
            project=self.project, name="Console", category=_cat(self.project, "Audio"), venue=self.venue,
        )
        django_user, _profile = _make_member('editorsm@example.com', self.project, ProjectMembership.ROLE_EDITOR)
        self.client.force_authenticate(user=django_user)
        response = self.client.post('/api/show-materials/', {'show': show.id, 'material': material.id}, format='json')
        self.assertEqual(response.status_code, 201)

        other_project = Project.objects.create(name="Autre projet 3")
        outsider, _ = _make_member('outsider3@example.com', other_project, ProjectMembership.ROLE_OWNER)
        self.client.force_authenticate(user=outsider)
        response = self.client.get(f'/api/show-materials/?show={show.id}')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.data), [])


class UserViewSetStaffOnlyTests(TestCase):
    """`UserViewSet` restreint aux comptes staff (`is_staff_global`) — point 8."""

    def test_non_staff_member_cannot_list_users(self):
        project = Project.objects.create(name="Projet test")
        django_user, _profile = _make_member('editor@example.com', project, ProjectMembership.ROLE_OWNER)
        client = APIClient()
        client.force_authenticate(user=django_user)
        response = client.get('/api/users/')
        self.assertEqual(response.status_code, 403)

    def test_staff_global_can_list_users(self):
        django_user, _profile = _make_member('staff@example.com', is_staff_global=True)
        client = APIClient()
        client.force_authenticate(user=django_user)
        response = client.get('/api/users/')
        self.assertEqual(response.status_code, 200)


class ProjectCreationMembershipTests(TestCase):
    """`POST /api/projects/` et `POST /api/projects/{id}/duplicate/` donnent
    automatiquement un accès `owner` actif à l'appelant sur le projet obtenu."""

    def test_creating_a_project_grants_owner_membership(self):
        django_user, profile = _make_member('createur@example.com')
        client = APIClient()
        client.force_authenticate(user=django_user)
        response = client.post('/api/projects/', {'name': "Nouveau mandat"}, format='json')
        self.assertEqual(response.status_code, 201)
        project_id = response.data['id']
        self.assertTrue(
            ProjectMembership.objects.filter(
                project_id=project_id, user=profile,
                role=ProjectMembership.ROLE_OWNER, status=ProjectMembership.STATUS_ACTIVE,
            ).exists()
        )

    def test_duplicate_grants_owner_membership_on_new_project(self):
        source = Project.objects.create(name="Projet source")
        django_user, profile = _make_member('dupli@example.com', source, ProjectMembership.ROLE_EDITOR)
        client = APIClient()
        client.force_authenticate(user=django_user)
        response = client.post(f'/api/projects/{source.id}/duplicate/', {'name': "Copie"}, format='json')
        self.assertEqual(response.status_code, 201)
        new_project_id = response.data['project']['id']
        self.assertTrue(
            ProjectMembership.objects.filter(
                project_id=new_project_id, user=profile,
                role=ProjectMembership.ROLE_OWNER, status=ProjectMembership.STATUS_ACTIVE,
            ).exists()
        )

    def test_project_list_only_shows_projects_with_active_membership(self):
        visible = Project.objects.create(name="Visible")
        Project.objects.create(name="Invisible")
        django_user, _profile = _make_member('lister@example.com', visible, ProjectMembership.ROLE_VIEWER)
        client = APIClient()
        client.force_authenticate(user=django_user)
        response = client.get('/api/projects/')
        self.assertEqual(response.status_code, 200)
        names = [p['name'] for p in response.data]
        self.assertIn("Visible", names)
        self.assertNotIn("Invisible", names)


class ProjectMembershipViewSetTests(TestCase):
    """`ProjectMembershipViewSet` : invitation, changement de rôle, retrait,
    garde du dernier owner — réservés owner/staff (`owner_only_actions`)."""

    def setUp(self):
        self.project = Project.objects.create(name="Projet test")
        self.client = APIClient()
        self.owner_django, self.owner_profile = _make_member(
            'owner@example.com', self.project, ProjectMembership.ROLE_OWNER,
        )
        self.client.force_authenticate(user=self.owner_django)

    def _owner_membership(self):
        return ProjectMembership.objects.get(project=self.project, user=self.owner_profile)

    def test_owner_can_invite_new_email_as_pending(self):
        response = self.client.post('/api/project-memberships/', {
            'project': self.project.id, 'email': 'nouveau@example.com', 'role': 'editor',
        }, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['status'], ProjectMembership.STATUS_PENDING)
        self.assertEqual(response.data['role'], 'editor')

    def test_invite_of_already_google_linked_email_is_active_immediately(self):
        existing_django = DjangoUser.objects.create_user(username='deja', email='deja@example.com', password='pw')
        InventoryUser.objects.create(email='deja@example.com', name='Déjà', django_user=existing_django)
        response = self.client.post('/api/project-memberships/', {
            'project': self.project.id, 'email': 'deja@example.com', 'role': 'viewer',
        }, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['status'], ProjectMembership.STATUS_ACTIVE)

    def test_pending_invitation_activates_on_first_google_login(self):
        from allauth.account.signals import user_logged_in

        self.client.post('/api/project-memberships/', {
            'project': self.project.id, 'email': 'futur@example.com', 'role': 'viewer',
        }, format='json')
        membership = ProjectMembership.objects.get(project=self.project, user__email='futur@example.com')
        self.assertEqual(membership.status, ProjectMembership.STATUS_PENDING)

        django_user = DjangoUser.objects.create_user(username='futur', email='futur@example.com')
        user_logged_in.send(sender=DjangoUser, request=None, user=django_user)

        membership.refresh_from_db()
        self.assertEqual(membership.status, ProjectMembership.STATUS_ACTIVE)

    def test_editor_cannot_manage_memberships(self):
        editor_django, _profile = _make_member('editor2@example.com', self.project, ProjectMembership.ROLE_EDITOR)
        self.client.force_authenticate(user=editor_django)
        response = self.client.post('/api/project-memberships/', {
            'project': self.project.id, 'email': 'invite@example.com', 'role': 'viewer',
        }, format='json')
        self.assertEqual(response.status_code, 403)

    def test_viewer_can_see_membership_list(self):
        viewer_django, _profile = _make_member('viewer3@example.com', self.project, ProjectMembership.ROLE_VIEWER)
        self.client.force_authenticate(user=viewer_django)
        response = self.client.get(f'/api/project-memberships/?project={self.project.id}')
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(response.data), 1)

    def test_cannot_remove_last_active_owner(self):
        response = self.client.delete(f'/api/project-memberships/{self._owner_membership().id}/')
        self.assertEqual(response.status_code, 400)
        self.assertTrue(ProjectMembership.objects.filter(id=self._owner_membership().id).exists())

    def test_cannot_demote_last_active_owner(self):
        response = self.client.patch(
            f'/api/project-memberships/{self._owner_membership().id}/', {'role': 'editor'}, format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self._owner_membership().role, ProjectMembership.ROLE_OWNER)

    def test_can_remove_owner_when_another_owner_remains(self):
        _make_member('owner2@example.com', self.project, ProjectMembership.ROLE_OWNER)
        response = self.client.delete(f'/api/project-memberships/{self._owner_membership().id}/')
        self.assertEqual(response.status_code, 204)

    def test_owner_can_change_a_viewer_to_editor(self):
        _django_user, profile = _make_member('viewer4@example.com', self.project, ProjectMembership.ROLE_VIEWER)
        membership = ProjectMembership.objects.get(project=self.project, user=profile)
        response = self.client.patch(f'/api/project-memberships/{membership.id}/', {'role': 'editor'}, format='json')
        self.assertEqual(response.status_code, 200)
        membership.refresh_from_db()
        self.assertEqual(membership.role, ProjectMembership.ROLE_EDITOR)


class DataMigrationLogicTests(TestCase):
    """Vérifie la fonction `RunPython` de la migration de données `0020`
    directement (pas via un test de migration historique — l'infra
    `django-test-migrations` n'est pas installée dans ce projet, et les
    modèles réels ont exactement la même forme que dans l'état historique de
    cette migration puisque c'est la dernière migration de schéma touchant
    ces tables). Importée dynamiquement : `0020_project_access_data` n'est
    pas un identifiant Python valide pour un `import` direct.
    """

    def test_promotes_admin_role_and_grants_samuel_ownership_of_existing_projects(self):
        module = importlib.import_module('inventory.migrations.0020_project_access_data')

        admin_user = InventoryUser.objects.create(
            email='ancien.admin@example.com', name='Ancien Admin', role=InventoryUser.ROLE_ADMIN,
        )
        preexisting_project = Project.objects.create(name="Projet préexistant")

        class _FakeApps:
            def get_model(self, app_label, model_name):
                return {'User': InventoryUser, 'Project': Project, 'ProjectMembership': ProjectMembership}[model_name]

        module.provisionner_acces_existants(_FakeApps(), None)

        admin_user.refresh_from_db()
        self.assertTrue(admin_user.is_staff_global)

        samuel = InventoryUser.objects.get(email='samueltheriault@gmail.com')
        self.assertTrue(samuel.is_staff_global)
        self.assertTrue(
            ProjectMembership.objects.filter(
                project=preexisting_project, user=samuel,
                role=ProjectMembership.ROLE_OWNER, status=ProjectMembership.STATUS_ACTIVE,
            ).exists()
        )

    def test_noop_on_a_fresh_database_with_no_projects(self):
        # Garde nécessaire pour ne pas polluer chaque base de test fraîche
        # (voir le docstring de la migration) — vérifiée explicitement ici.
        module = importlib.import_module('inventory.migrations.0020_project_access_data')

        class _FakeApps:
            def get_model(self, app_label, model_name):
                return {'User': InventoryUser, 'Project': Project, 'ProjectMembership': ProjectMembership}[model_name]

        module.provisionner_acces_existants(_FakeApps(), None)
        self.assertFalse(InventoryUser.objects.filter(email='samueltheriault@gmail.com').exists())
