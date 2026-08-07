"""Tests de l'export/import complet d'un projet (`portability.py`) et des
exports CSV par section (`csv_export.py`) — ajoutés le 2026-08-04.

Deux niveaux, comme `test_project_access.py`/`test_settings_and_maps.py` :
- `PortabilityRoundTripTests` : `export_project_data`/`import_project_data`
  directement, sans passer par l'API — round-trip complet (hiérarchies
  matériel/spectacles, transports, catégories) et erreurs de format.
- `ProjectExportImportAPITests` : les endpoints eux-mêmes
  (`GET /api/projects/{id}/export/`, `POST /api/projects/import/`).
- `SectionCsvExportTests` : les exports CSV par section (matériel, lieux,
  techniciens, spectacles).
"""

import json

from django.contrib.auth.models import User as DjangoUser
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from .models import (
    Material,
    MaterialCategory,
    Project,
    ProjectMembership,
    Show,
    ShowMaterial,
    ShowTechnician,
    Technician,
    Transport,
    TransportMaterial,
    TransportStop,
    TransportTechnician,
    Venue,
)
from .portability import (
    PortabilityError,
    export_project_data,
    import_project_data,
)
from .test_project_access import _make_member


def _build_full_project():
    """Construit un projet couvrant toutes les tables (hiérarchie matériel,
    bloc de spectacle rattaché, assignations, transport avec technicien ET
    matériel) — sert de fixture aux deux classes de tests round-trip."""
    project = Project.objects.create(
        name="Vertiges", client_name="Compagnie X", status=Project.STATUS_ACTIVE,
        start_date="2026-09-01", end_date="2026-09-10", notes="Tournée automne",
    )
    entrepot = Venue.objects.create(project=project, name="Entrepôt", is_storage=True, code="ENT")
    salle = Venue.objects.create(
        project=project, name="Salle principale", code="SALL",
        latitude="45.501690", longitude="-73.567253",
    )
    # "Audio" fait partie des 9 catégories par défaut créées automatiquement
    # à la création du projet (signal `creer_categories_par_defaut`,
    # signals.py) — la récupérer plutôt que la recréer (contrainte d'unicité
    # project+name, voir MaterialCategory.Meta.constraints).
    categorie = MaterialCategory.objects.get(project=project, name="Audio")

    kit = Material.objects.create(
        project=project, name="Kit Audio", category=categorie, venue=entrepot,
        is_kit_parent=True, quantity=1,
    )
    composant = Material.objects.create(
        project=project, name="Micro sans fil", category=categorie, venue=entrepot,
        parent_material=kit, quantity=4,
    )

    technicien = Technician.objects.create(project=project, name="Sam", specialty="Son")

    spectacle = Show.objects.create(
        project=project, title="Vertiges", venue=salle, event_type=Show.EVENT_PERFORMANCE,
        start_datetime=timezone.now(), end_datetime=timezone.now() + timezone.timedelta(hours=2),
    )
    montage = Show.objects.create(
        project=project, venue=salle, event_type=Show.EVENT_SETUP,
        start_datetime=timezone.now() - timezone.timedelta(hours=3),
        end_datetime=timezone.now() - timezone.timedelta(hours=1),
        parent_show=spectacle,
    )

    ShowMaterial.objects.create(show=spectacle, material=composant, quantity=2)
    ShowTechnician.objects.create(show=spectacle, technician=technicien)

    # Tournée à 2 arrêts (2026-08-04) — équivalent de l'ancien A→B, voir
    # `Transport`/`TransportStop` (models.py).
    transport = Transport.objects.create(
project=spectacle.project,
show=spectacle, scheduled_datetime=timezone.now() - timezone.timedelta(hours=4),
    )
    depart = TransportStop.objects.create(
        transport=transport, venue=entrepot, order=0, travel_minutes_from_previous=0,
    )
    arrivee = TransportStop.objects.create(
        transport=transport, venue=salle, order=1, travel_minutes_from_previous=30,
    )
    TransportTechnician.objects.create(transport=transport, technician=technicien)
    TransportMaterial.objects.create(
        transport=transport, material=composant, quantity=2,
        load_stop=depart, unload_stop=arrivee,
    )

    return project, {
        'venues': [entrepot, salle],
        'materials': [kit, composant],
        'shows': [spectacle, montage],
    }


class PortabilityRoundTripTests(TestCase):
    """`export_project_data`/`import_project_data` directement — pas d'API."""

    def test_round_trip_preserves_counts_and_hierarchy(self):
        project, refs = _build_full_project()
        data = export_project_data(project)

        new_project, counts = import_project_data(data)

        self.assertNotEqual(new_project.id, project.id)
        self.assertEqual(new_project.name, "Vertiges")
        self.assertEqual(new_project.client_name, "Compagnie X")
        self.assertEqual(str(new_project.start_date), "2026-09-01")

        self.assertEqual(counts, {
            'venues': 2,
            # 9 catégories par défaut (signal) + "Audio" déjà présente parmi
            # elles -> pas de doublon, `get_or_create` la retrouve.
            'material_categories': 9,
            'materials': 2,
            'technicians': 1,
            'shows': 2,
            'show_materials': 1,
            'show_technicians': 1,
            'transports': 1,
        })

        # Hiérarchie matériel remappée vers les nouvelles clés.
        new_kit = Material.objects.get(project=new_project, name="Kit Audio")
        new_composant = Material.objects.get(project=new_project, name="Micro sans fil")
        self.assertEqual(new_composant.parent_material_id, new_kit.id)
        self.assertNotEqual(new_kit.id, refs['materials'][0].id)

        # Bloc de spectacle rattaché remappé.
        new_spectacle = Show.objects.get(project=new_project, event_type=Show.EVENT_PERFORMANCE)
        new_montage = Show.objects.get(project=new_project, event_type=Show.EVENT_SETUP)
        self.assertEqual(new_montage.parent_show_id, new_spectacle.id)

        # Transport avec technicien ET matériel liés.
        new_transport = Transport.objects.get(show=new_spectacle)
        self.assertEqual(new_transport.transport_technicians.count(), 1)
        self.assertEqual(new_transport.transport_materials.count(), 1)
        self.assertEqual(new_transport.transport_materials.first().material_id, new_composant.id)

        # Le projet source n'est jamais modifié.
        self.assertEqual(Material.objects.filter(project=project).count(), 2)

    def test_round_trip_preserves_multi_stop_transport_material_portions(self):
        """Le remappage des `stops` se fait par POSITION (`order`), pas par
        id (les ids d'origine ne survivent pas à l'import) — le cas non
        trivial est une ligne de matériel qui charge/décharge NI au premier
        NI au dernier arrêt d'une tournée à 3 arrêts, le vrai scénario que
        les tournées multi-arrêts (2026-08-04) sont censées couvrir.
        `_build_full_project` ne teste qu'une tournée à 2 arrêts, où `order`
        et l'index de la liste coïncident déjà — ce test isole le
        remappage lui-même (suggéré en revue de code du 2026-08-04)."""
        project = Project.objects.create(name="Tournée 3 arrêts")
        venue_a = Venue.objects.create(project=project, name="Entrepôt", is_storage=True)
        venue_b = Venue.objects.create(project=project, name="Salle B")
        venue_c = Venue.objects.create(project=project, name="Salle C")
        categorie = MaterialCategory.objects.get(project=project, name="Audio")
        materiel = Material.objects.create(
            project=project, name="Enceinte", category=categorie, venue=venue_b, quantity=1,
        )
        spectacle = Show.objects.create(
            project=project, title="Filage", venue=venue_c, event_type=Show.EVENT_PERFORMANCE,
            start_datetime=timezone.now(), end_datetime=timezone.now() + timezone.timedelta(hours=1),
        )
        transport = Transport.objects.create(
project=spectacle.project,
show=spectacle, scheduled_datetime=timezone.now())
        TransportStop.objects.create(transport=transport, venue=venue_a, order=0, travel_minutes_from_previous=0)
        stop_b = TransportStop.objects.create(
            transport=transport, venue=venue_b, order=1, travel_minutes_from_previous=20,
        )
        stop_c = TransportStop.objects.create(
            transport=transport, venue=venue_c, order=2, travel_minutes_from_previous=30,
        )
        # Charge au 2e arrêt (B), décharge au 3e (C) — ni le premier ni le dernier.
        TransportMaterial.objects.create(
            transport=transport, material=materiel, quantity=1, load_stop=stop_b, unload_stop=stop_c,
        )

        data = export_project_data(project)
        new_project, _counts = import_project_data(data)

        new_transport = Transport.objects.get(show__project=new_project)
        new_tm = new_transport.transport_materials.get()
        self.assertEqual(new_tm.load_stop.venue.name, "Salle B")
        self.assertEqual(new_tm.load_stop.order, 1)
        self.assertEqual(new_tm.unload_stop.venue.name, "Salle C")
        self.assertEqual(new_tm.unload_stop.order, 2)
        self.assertEqual(
            [s.venue.name for s in new_transport.ordered_stops],
            ["Entrepôt", "Salle B", "Salle C"],
        )

    def test_name_override_replaces_file_name(self):
        project, _refs = _build_full_project()
        data = export_project_data(project)
        new_project, _counts = import_project_data(data, name="Vertiges — copie de secours")
        self.assertEqual(new_project.name, "Vertiges — copie de secours")

    def test_rejects_wrong_format_key(self):
        with self.assertRaises(PortabilityError):
            import_project_data({'format': 'autre-chose', 'format_version': '1.0', 'project': {'name': 'X'}})

    def test_rejects_unknown_major_version(self):
        with self.assertRaises(PortabilityError):
            import_project_data({
                'format': 'gear-management-project', 'format_version': '2.0',
                'project': {'name': 'X'},
            })

    def test_rejects_non_dict_payload(self):
        with self.assertRaises(PortabilityError):
            import_project_data(["pas un objet"])

    def test_rejects_missing_project_name(self):
        with self.assertRaises(PortabilityError):
            import_project_data({
                'format': 'gear-management-project', 'format_version': '1.0',
                'project': {},
            })

    def test_broken_reference_rolls_back_everything(self):
        """Un fichier corrompu (matériel référençant une catégorie absente du
        fichier n'est PAS une erreur — `category_id_map.get()` renvoie
        simplement `None` — mais une venue introuvable pour un spectacle doit
        annuler tout l'import (transaction atomique), pas laisser un projet à
        moitié importé."""
        project, _refs = _build_full_project()
        data = export_project_data(project)
        # Casse la référence de venue du premier spectacle.
        data['shows'][0]['venue'] = 999999
        projects_before = Project.objects.count()
        with self.assertRaises(PortabilityError):
            import_project_data(data)
        self.assertEqual(Project.objects.count(), projects_before)

    def test_export_is_json_serializable(self):
        """L'export doit pouvoir passer par `json.dumps` (types natifs
        uniquement une fois convertis) — même vérification que fait la vue
        (`DjangoJSONEncoder`)."""
        project, _refs = _build_full_project()
        data = export_project_data(project)
        from django.core.serializers.json import DjangoJSONEncoder
        body = json.dumps(data, cls=DjangoJSONEncoder)
        reparsed = json.loads(body)
        self.assertEqual(reparsed['format'], 'gear-management-project')
        self.assertEqual(reparsed['project']['name'], "Vertiges")


class ProjectExportImportAPITests(TestCase):
    """Les endpoints `GET /api/projects/{id}/export/` et
    `POST /api/projects/import/`."""

    def setUp(self):
        self.client = APIClient()
        self.django_user = DjangoUser.objects.create_superuser('admin', 'admin@example.com', 'pw')
        self.client.force_authenticate(user=self.django_user)

    def test_export_json_default(self):
        project, _refs = _build_full_project()
        response = self.client.get(f'/api/projects/{project.id}/export/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('application/json', response['Content-Type'])
        self.assertIn('attachment', response['Content-Disposition'])
        self.assertIn('.json', response['Content-Disposition'])
        body = json.loads(response.content)
        self.assertEqual(body['format'], 'gear-management-project')
        self.assertEqual(body['project']['name'], 'Vertiges')

    def test_export_xml(self):
        project, _refs = _build_full_project()
        response = self.client.get(f'/api/projects/{project.id}/export/', {'format': 'xml'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('xml', response['Content-Type'])
        self.assertIn('.xml', response['Content-Disposition'])
        self.assertIn(b'<project_export>', response.content)
        self.assertIn(b'<venue>', response.content)

    def test_export_requires_access(self):
        """Un compte sans membership ni statut staff ne peut pas exporter le
        projet d'un autre — même garde que le reste de l'API (HasProjectAccess)."""
        project, _refs = _build_full_project()
        other_django_user = DjangoUser.objects.create_user('viewer', 'viewer@example.com', 'pw')
        client = APIClient()
        client.force_authenticate(user=other_django_user)
        response = client.get(f'/api/projects/{project.id}/export/')
        self.assertIn(response.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND))

    def test_import_creates_new_project_via_api(self):
        project, _refs = _build_full_project()
        export_response = self.client.get(f'/api/projects/{project.id}/export/')
        exported = json.loads(export_response.content)

        import_response = self.client.post('/api/projects/import/', exported, format='json')
        self.assertEqual(import_response.status_code, status.HTTP_201_CREATED)
        self.assertNotEqual(import_response.data['project']['id'], project.id)
        self.assertEqual(import_response.data['imported']['materials'], 2)
        self.assertEqual(Project.objects.filter(name='Vertiges').count(), 2)

    def test_import_with_name_override_wrapper(self):
        project, _refs = _build_full_project()
        export_response = self.client.get(f'/api/projects/{project.id}/export/')
        exported = json.loads(export_response.content)

        import_response = self.client.post(
            '/api/projects/import/', {'data': exported, 'name': 'Vertiges (restauré)'}, format='json',
        )
        self.assertEqual(import_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(import_response.data['project']['name'], 'Vertiges (restauré)')

    def test_import_rejects_invalid_payload(self):
        response = self.client.post('/api/projects/import/', {'format': 'pas-le-bon-format'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('detail', response.data)


class SectionCsvExportTests(TestCase):
    """Exports CSV par section — `export-csv` sur `materials`/`venues`/
    `technicians`/`shows`."""

    def setUp(self):
        self.client = APIClient()
        self.django_user = DjangoUser.objects.create_superuser('admin', 'admin@example.com', 'pw')
        self.client.force_authenticate(user=self.django_user)
        self.project, self.refs = _build_full_project()

    def _assert_csv_response(self, response):
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('text/csv', response['Content-Type'])
        self.assertIn('attachment', response['Content-Disposition'])
        # 'utf-8-sig' retire le BOM en tête (voir csv_export.csv_response) —
        # sans ça, il resterait collé au premier caractère de l'en-tête.
        return response.content.decode('utf-8-sig')

    def test_materials_export_csv(self):
        response = self.client.get('/api/materials/export-csv/', {'project': self.project.id})
        content = self._assert_csv_response(response)
        self.assertIn('Nom;Catégorie;Quantité', content.splitlines()[0])
        self.assertIn('Kit Audio', content)
        self.assertIn('Micro sans fil', content)

    def test_materials_export_csv_can_exclude_inactive(self):
        inactive = Material.objects.create(
            project=self.project, name="Vieux rideau", venue=self.refs['venues'][0], is_active=False,
        )
        response = self.client.get(
            '/api/materials/export-csv/', {'project': self.project.id, 'include_inactive': 'false'},
        )
        content = self._assert_csv_response(response)
        self.assertNotIn(inactive.name, content)

    def test_venues_export_csv(self):
        response = self.client.get('/api/venues/export-csv/', {'project': self.project.id})
        content = self._assert_csv_response(response)
        self.assertIn('Entrepôt', content)
        self.assertIn('Salle principale', content)

    def test_technicians_export_csv(self):
        response = self.client.get('/api/technicians/export-csv/', {'project': self.project.id})
        content = self._assert_csv_response(response)
        self.assertIn('Sam', content)

    def test_shows_export_csv(self):
        response = self.client.get('/api/shows/export-csv/', {'project': self.project.id})
        content = self._assert_csv_response(response)
        self.assertIn('Vertiges', content)


class CsvExportPermissionTests(TestCase):
    """`can_access_project` (permissions.py, rôle viewer minimum en lecture)
    gate `export-csv` — même famille de contrôle que `CsvImportPermissionTests`
    (test_csv_import.py) pour `import-csv`, ajoutée en revue de code du
    2026-08-04 : `SectionCsvExportTests` ci-dessus n'utilisait qu'un
    superutilisateur, laissant la frontière de rôle non testée pour l'export."""

    def setUp(self):
        self.project, _refs = _build_full_project()
        self.client = APIClient()

    def test_viewer_can_export(self):
        django_user, _profile = _make_member('viewer2@example.com', self.project, ProjectMembership.ROLE_VIEWER)
        self.client.force_authenticate(user=django_user)
        response = self.client.get('/api/materials/export-csv/', {'project': self.project.id})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_non_member_cannot_export(self):
        django_user, _profile = _make_member('etranger2@example.com')
        self.client.force_authenticate(user=django_user)
        response = self.client.get('/api/materials/export-csv/', {'project': self.project.id})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class ImportSanitizationTests(TestCase):
    """Les notes importées passent aussi par `clean_notes` (2026-08-05).

    Trouvé en relecture : l'assainissement n'était branché que sur les
    serializers, alors que `portability.import_project_data` et
    `csv_import` créent les objets par `Model.objects.create()` (pour ne pas
    déclencher la validation de conflits) — ils écrivaient donc des notes
    brutes, ensuite rendues par `v-html` sur les fiches.

    Un fichier d'export ou un CSV échangé entre utilisateurs est exactement
    le vecteur que `rich_text.py` dit vouloir couvrir : ces deux chemins
    doivent nettoyer comme le fait l'API ordinaire.
    """

    def setUp(self):
        self.client = APIClient()
        self.django_user = DjangoUser.objects.create_superuser('admin', 'admin@example.com', 'pw')
        self.client.force_authenticate(user=self.django_user)

    def test_project_import_sanitizes_show_and_transport_notes(self):
        project, _refs = _build_full_project()
        exported = json.loads(self.client.get(f'/api/projects/{project.id}/export/').content)

        piege = '<p>ok</p><img src=x onerror="alert(1)"><script>alert(2)</script>'
        for show in exported['shows']:
            show['notes'] = piege
        for transport in exported['transports']:
            transport['notes'] = piege
        exported['project']['notes'] = piege

        response = self.client.post('/api/projects/import/', exported, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        importe = Project.objects.get(id=response.data['project']['id'])
        self.assertNotIn('script', importe.notes)
        self.assertNotIn('onerror', importe.notes)
        for show in importe.shows.all():
            self.assertNotIn('script', show.notes)
            self.assertNotIn('onerror', show.notes)
            # La mise en forme légitime, elle, survit.
            self.assertIn('<p>ok</p>', show.notes)
        for transport in Transport.objects.filter(show__project=importe):
            self.assertNotIn('script', transport.notes)
            self.assertNotIn('onerror', transport.notes)

    def test_csv_import_sanitizes_notes(self):
        # Le superutilisateur Django court-circuite le contrôle d'accès par
        # projet (voir permissions.py) — pas de membership à créer ici.
        project = Project.objects.create(name="Cible CSV")

        contenu = (
            'Nom;Code;Adresse;Contact;Coordonnées contact;'
            'Entrepôt;Latitude;Longitude;Notes\n'
            'Chapelle;CHAP;12 rue X;Alex;;Non;;;'
            '<p>Accès</p><img src=x onerror=alert(1)>\n'
        )
        response = self.client.post(
            '/api/venues/import-csv/',
            {'project': project.id, 'mode': 'append', 'csv': contenu},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)

        lieu = Venue.objects.get(project=project, name='Chapelle')
        self.assertNotIn('onerror', lieu.notes)
        self.assertIn('<p>Accès</p>', lieu.notes)
