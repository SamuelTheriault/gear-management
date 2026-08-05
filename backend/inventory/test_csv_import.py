"""Tests de l'import CSV par section (`csv_import.py`,
`MaterialViewSet.import_csv`/`VenueViewSet.import_csv`/
`TechnicianViewSet.import_csv`/`ShowViewSet.import_csv`, views.py) —
ajoutés le 2026-08-04.

Suit le style de `test_portability.py` (fixture `_build_full_project`,
réutilisée telle quelle) et de `test_project_access.py` (`_make_member` pour
les tests de permission). Quatre classes :
- `CsvImportHeaderValidationTests` : en-têtes manquants rejetés AVANT toute
  écriture, comme demandé par Samuel.
- `CsvImportAppendModeTests` : les lignes s'ajoutent, rien d'existant n'est
  touché.
- `CsvImportReplaceModeTests` : le remplacement supprime bien tout le
  contenu existant de la liste visée (cascade comprise), sauf pour les lieux
  où une référence encore active (`PROTECT`) doit bloquer sans rien
  supprimer.
- `CsvImportPermissionTests` : `can_edit_project` (permissions.py) — un
  viewer ou un non-membre ne peut pas importer.
"""

from django.contrib.auth.models import User as DjangoUser
from rest_framework import status
from rest_framework.test import APIClient
from django.test import TestCase

from .models import Material, Project, ProjectMembership, Show, ShowMaterial, Technician, Venue
from .test_portability import _build_full_project
from .test_project_access import _make_member


def _make_csv(header, rows):
    """Construit un CSV brut (séparateur `;`, comme les exports — voir
    csv_export.py) à partir d'un en-tête et d'une liste de lignes."""
    lines = [';'.join(header)]
    for row in rows:
        lines.append(';'.join(str(v) for v in row))
    return '\n'.join(lines) + '\n'


class CsvImportHeaderValidationTests(TestCase):
    """Les en-têtes sont vérifiés AVANT toute écriture — rien ne doit être
    créé si une colonne attendue manque."""

    def setUp(self):
        self.client = APIClient()
        self.django_user = DjangoUser.objects.create_superuser('admin', 'admin@example.com', 'pw')
        self.client.force_authenticate(user=self.django_user)
        self.project, self.refs = _build_full_project()

    def test_missing_header_column_rejected_without_writing(self):
        # Colonne "Quantité" manquante.
        csv_text = _make_csv(
            ['Nom', 'Catégorie', 'Propriété', 'Lieu', 'Actif', 'Kit parent', 'Fait partie du kit', 'Description', 'Notes'],
            [['Câble XLR', 'Audio', 'Propriété', 'Entrepôt', 'Oui', 'Non', '', '', '']],
        )
        count_before = Material.objects.filter(project=self.project).count()
        response = self.client.post(
            '/api/materials/import-csv/',
            {'project': self.project.id, 'mode': 'append', 'csv': csv_text},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Quantité', response.data['detail'])
        self.assertEqual(Material.objects.filter(project=self.project).count(), count_before)

    def test_empty_file_rejected(self):
        response = self.client.post(
            '/api/materials/import-csv/',
            {'project': self.project.id, 'mode': 'append', 'csv': ''},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_mode_rejected(self):
        csv_text = _make_csv(
            ['Nom', 'Catégorie', 'Quantité', 'Propriété', 'Lieu', 'Actif', 'Kit parent', 'Fait partie du kit', 'Description', 'Notes'],
            [['Câble XLR', 'Audio', '10', 'Propriété', 'Entrepôt', 'Oui', 'Non', '', '', '']],
        )
        response = self.client.post(
            '/api/materials/import-csv/',
            {'project': self.project.id, 'mode': 'ecrase-tout', 'csv': csv_text},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_missing_project_rejected(self):
        csv_text = _make_csv(['Nom', 'Coordonnées', 'Spécialité', 'Notes'], [['Sam', '', 'Son', '']])
        response = self.client.post(
            '/api/technicians/import-csv/', {'mode': 'append', 'csv': csv_text}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class CsvImportAppendModeTests(TestCase):
    """`mode=append` ajoute les lignes du fichier sans toucher au contenu existant."""

    def setUp(self):
        self.client = APIClient()
        self.django_user = DjangoUser.objects.create_superuser('admin', 'admin@example.com', 'pw')
        self.client.force_authenticate(user=self.django_user)
        self.project, self.refs = _build_full_project()

    def test_append_materials_keeps_existing(self):
        csv_text = _make_csv(
            ['Nom', 'Catégorie', 'Quantité', 'Propriété', 'Lieu', 'Actif', 'Kit parent', 'Fait partie du kit', 'Description', 'Notes'],
            [['Câble XLR', 'Audio', '10', 'Propriété', 'Entrepôt', 'Oui', 'Non', '', '', '']],
        )
        response = self.client.post(
            '/api/materials/import-csv/', {'project': self.project.id, 'mode': 'append', 'csv': csv_text}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['imported']['materials'], 1)
        self.assertEqual(Material.objects.filter(project=self.project).count(), 3)
        self.assertTrue(Material.objects.filter(project=self.project, name='Câble XLR', quantity=10).exists())
        # Le matériel préexistant (fixture) n'a pas bougé.
        self.assertTrue(Material.objects.filter(project=self.project, name='Kit Audio').exists())

    def test_append_technicians_keeps_existing(self):
        csv_text = _make_csv(['Nom', 'Coordonnées', 'Spécialité', 'Notes'], [['Alex', '514-555-0000', 'Éclairage', '']])
        response = self.client.post(
            '/api/technicians/import-csv/', {'project': self.project.id, 'mode': 'append', 'csv': csv_text}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Technician.objects.filter(project=self.project).count(), 2)

    def test_append_venues_keeps_existing(self):
        csv_text = _make_csv(
            ['Nom', 'Code', 'Adresse', 'Contact', 'Coordonnées contact', 'Entrepôt', 'Latitude', 'Longitude', 'Notes'],
            [['Studio B', 'STUB', '', '', '', 'Non', '', '', '']],
        )
        response = self.client.post(
            '/api/venues/import-csv/', {'project': self.project.id, 'mode': 'append', 'csv': csv_text}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Venue.objects.filter(project=self.project).count(), 3)


class CsvImportReplaceModeTests(TestCase):
    """`mode=replace` supprime le contenu existant de la liste visée avant
    d'importer — sauf pour les lieux, où une référence active bloque sans
    rien supprimer (`PROTECT`, voir `csv_import.import_venues_csv`)."""

    def setUp(self):
        self.client = APIClient()
        self.django_user = DjangoUser.objects.create_superuser('admin', 'admin@example.com', 'pw')
        self.client.force_authenticate(user=self.django_user)
        self.project, self.refs = _build_full_project()

    def test_replace_materials_deletes_existing_and_cascades(self):
        spectacle = self.refs['shows'][0]
        self.assertEqual(ShowMaterial.objects.filter(show=spectacle).count(), 1)

        csv_text = _make_csv(
            ['Nom', 'Catégorie', 'Quantité', 'Propriété', 'Lieu', 'Actif', 'Kit parent', 'Fait partie du kit', 'Description', 'Notes'],
            [['Câble XLR', 'Audio', '10', 'Propriété', 'Entrepôt', 'Oui', 'Non', '', '', '']],
        )
        response = self.client.post(
            '/api/materials/import-csv/', {'project': self.project.id, 'mode': 'replace', 'csv': csv_text}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Material.objects.filter(project=self.project).count(), 1)
        self.assertFalse(Material.objects.filter(project=self.project, name='Kit Audio').exists())
        # Cascade : l'assignation qui référençait l'ancien matériel a disparu.
        self.assertEqual(ShowMaterial.objects.filter(show=spectacle).count(), 0)

    def test_replace_technicians_deletes_existing_and_cascades(self):
        spectacle = self.refs['shows'][0]
        csv_text = _make_csv(['Nom', 'Coordonnées', 'Spécialité', 'Notes'], [['Alex', '', 'Éclairage', '']])
        response = self.client.post(
            '/api/technicians/import-csv/', {'project': self.project.id, 'mode': 'replace', 'csv': csv_text}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Technician.objects.filter(project=self.project).count(), 1)
        self.assertEqual(spectacle.show_technicians.count(), 0)

    def test_replace_shows_deletes_existing_and_cascades(self):
        venue = self.refs['venues'][1]
        csv_text = _make_csv(
            ["Titre", "Type d'événement", 'Lieu', 'Début', 'Fin', 'Notes'],
            [['Filage', 'Répétition', venue.name, '2026-09-05 10:00', '2026-09-05 12:00', '']],
        )
        response = self.client.post(
            '/api/shows/import-csv/', {'project': self.project.id, 'mode': 'replace', 'csv': csv_text}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Show.objects.filter(project=self.project).count(), 1)
        self.assertEqual(Show.objects.get(project=self.project).title, 'Filage')

    def test_replace_venues_blocked_when_still_referenced(self):
        """Le premier lieu de la fixture (`entrepot`) est encore le lieu
        d'origine du matériel existant — le remplacement doit être refusé
        SANS rien supprimer, plutôt que de lever une `ProtectedError` en base."""
        venues_before = Venue.objects.filter(project=self.project).count()
        csv_text = _make_csv(
            ['Nom', 'Code', 'Adresse', 'Contact', 'Coordonnées contact', 'Entrepôt', 'Latitude', 'Longitude', 'Notes'],
            [['Studio B', 'STUB', '', '', '', 'Non', '', '', '']],
        )
        response = self.client.post(
            '/api/venues/import-csv/', {'project': self.project.id, 'mode': 'replace', 'csv': csv_text}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Venue.objects.filter(project=self.project).count(), venues_before)

    def test_replace_venues_blocked_when_only_referenced_by_material(self):
        """Un lieu qui n'est référencé QUE comme origine de matériel (aucun
        spectacle, aucun arrêt de tournée) doit aussi bloquer le remplacement
        — le lieu de la fixture ci-dessus (`entrepot`) est *aussi* un arrêt
        de transport, ce qui masquait ce cas isolé (bug trouvé en revue de
        code le 2026-08-04 : le premier passage de `import_venues_csv` ne
        vérifiait que spectacles/transports, laissant `Material.venue` se
        faire vider silencieusement — `SET_NULL` — à l'import)."""
        lonely_venue = Venue.objects.create(project=self.project, name="Local isolé", code="ISOL")
        material = Material.objects.create(project=self.project, name="Ampli", venue=lonely_venue, quantity=1)
        venues_before = Venue.objects.filter(project=self.project).count()
        csv_text = _make_csv(
            ['Nom', 'Code', 'Adresse', 'Contact', 'Coordonnées contact', 'Entrepôt', 'Latitude', 'Longitude', 'Notes'],
            [['Studio B', 'STUB', '', '', '', 'Non', '', '', '']],
        )
        response = self.client.post(
            '/api/venues/import-csv/', {'project': self.project.id, 'mode': 'replace', 'csv': csv_text}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Venue.objects.filter(project=self.project).count(), venues_before)
        material.refresh_from_db()
        self.assertEqual(material.venue_id, lonely_venue.id)


class CsvImportPermissionTests(TestCase):
    """`can_edit_project` (permissions.py) gate ces actions — un viewer ou un
    non-membre ne peut pas importer, un editor/owner peut."""

    def setUp(self):
        self.project = Project.objects.create(name="Projet test")
        Venue.objects.create(project=self.project, name="Entrepôt", is_storage=True)
        self.client = APIClient()
        self.csv_text = _make_csv(['Nom', 'Coordonnées', 'Spécialité', 'Notes'], [['Alex', '', 'Éclairage', '']])

    def test_editor_can_import(self):
        django_user, _profile = _make_member('editor@example.com', self.project, ProjectMembership.ROLE_EDITOR)
        self.client.force_authenticate(user=django_user)
        response = self.client.post(
            '/api/technicians/import-csv/', {'project': self.project.id, 'mode': 'append', 'csv': self.csv_text}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_viewer_cannot_import(self):
        django_user, _profile = _make_member('viewer@example.com', self.project, ProjectMembership.ROLE_VIEWER)
        self.client.force_authenticate(user=django_user)
        response = self.client.post(
            '/api/technicians/import-csv/', {'project': self.project.id, 'mode': 'append', 'csv': self.csv_text}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(Technician.objects.filter(project=self.project).exists())

    def test_non_member_cannot_import(self):
        django_user, _profile = _make_member('etranger@example.com')
        self.client.force_authenticate(user=django_user)
        response = self.client.post(
            '/api/technicians/import-csv/', {'project': self.project.id, 'mode': 'append', 'csv': self.csv_text}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_staff_global_can_import(self):
        django_user, _profile = _make_member('staff@example.com', is_staff_global=True)
        self.client.force_authenticate(user=django_user)
        response = self.client.post(
            '/api/technicians/import-csv/', {'project': self.project.id, 'mode': 'append', 'csv': self.csv_text}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
