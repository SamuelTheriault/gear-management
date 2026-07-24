"""
Squelette API — ViewSets DRF pour les tables de schema.md (8 tables initiales
+ `transports` et `settings`, ajoutées le 2026-07-18).

CRUD standard sur chaque modèle. La logique de conflits vit dans les
serializers (ShowMaterialSerializer, ShowTechnicianSerializer,
TransportSerializer) et dans conflicts.py ; ShowViewSet expose en plus une
action `conflicts` en lecture seule pour lister les chevauchements
actuellement en place sur un spectacle — matériel, techniciens, ET
déplacements (utile pour repérer les assignations faites avec `force: true`).
`SettingsView` est une vue singleton (pas de liste/création) pour la future
page de réglages du frontend. `ProjectViewSet` expose en plus une action
`duplicate` pour copier un projet (lieux/matériel/techniciens, sans
assignations) vers un nouveau projet — voir `duplication.py`.
"""

from rest_framework import generics, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .conflicts import (
    get_material_conflicts,
    get_technician_conflicts,
    get_transport_conflicts,
    serialize_material_conflict,
    serialize_technician_conflict,
)
from .duplication import duplicate_project
from .transport_coherence import get_project_coherence_report, get_show_coherence_report
from .models import (
    Department,
    Material,
    Project,
    Settings,
    Show,
    ShowMaterial,
    ShowTechnician,
    Technician,
    Transport,
    User,
    Venue,
)
from .serializers import (
    DepartmentSerializer,
    MaterialSerializer,
    ProjectSerializer,
    SettingsSerializer,
    ShowMaterialSerializer,
    ShowSerializer,
    ShowTechnicianSerializer,
    TechnicianSerializer,
    TransportSerializer,
    UserSerializer,
    VenueSerializer,
)


class ProjectFilteredMixin:
    """Filtre optionnel `?project=<id>` sur les listes — voir `Project` (models.py).

    Isolation par projet : chaque production isolée (venues, matériel,
    techniciens, spectacles) n'apparaît que quand on précise son id. Optionnel
    plutôt qu'obligatoire pour ne pas casser l'accès admin/API brut ; le
    frontend (une fois branché) passera toujours ce paramètre pour refléter
    le projet actif sélectionné par Samuel.
    """

    def get_queryset(self):
        queryset = super().get_queryset()
        project_id = self.request.query_params.get('project')
        if project_id:
            queryset = queryset.filter(project_id=project_id)
        return queryset


class UserViewSet(viewsets.ModelViewSet):
    """CRUD standard sur les comptes applicatifs."""

    queryset = User.objects.all()
    serializer_class = UserSerializer


class ProjectViewSet(viewsets.ModelViewSet):
    """CRUD standard sur les productions — voir `Project` (models.py), plus
    l'action `duplicate` pour démarrer une nouvelle édition d'un mandat."""

    queryset = Project.objects.all()
    serializer_class = ProjectSerializer

    @action(detail=True, methods=['post'])
    def duplicate(self, request, pk=None):
        """Duplique ce projet vers un nouveau projet : lieux, matériel (hiérarchie
        préservée) et techniciens copiés, AUCUNE assignation/horaire (spectacles,
        déplacements) — voir `duplication.duplicate_project()`.

        Corps de requête : `name` (obligatoire) — nom du nouveau projet ;
        `client_name` (optionnel) — sinon repris du projet source (décision
        Samuel du 2026-07-19 : une nouvelle édition, c'est généralement le même
        client).
        """
        source_project = self.get_object()
        name = (request.data.get('name') or '').strip()
        if not name:
            return Response(
                {'name': "Le nom du nouveau projet est requis."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        client_name = request.data.get('client_name')
        if client_name is None:
            client_name = source_project.client_name

        new_project, counts = duplicate_project(source_project, name=name, client_name=client_name)
        return Response(
            {'project': ProjectSerializer(new_project).data, 'copied': counts},
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['get'], url_path='transport-coherence')
    def transport_coherence(self, request, pk=None):
        """Rapport de cohérence des emplacements de matériel pour toute la
        production (non bloquant — voir `transport_coherence.py`). Liste les
        incohérences spatiales : matériel requis à un lieu sans transport pour
        l'y amener (`materiel_non_livre`), transport partant d'un lieu où le
        matériel n'est pas présent (`origine_incoherente`), et matériel sans
        lieu d'entreposage donc non suivi (`origine_inconnue`)."""
        project = self.get_object()
        issues = get_project_coherence_report(project)
        return Response({'issues': issues, 'issue_count': len(issues)})


class VenueViewSet(ProjectFilteredMixin, viewsets.ModelViewSet):
    """CRUD standard sur les lieux, filtrable par projet (`?project=<id>`)."""

    queryset = Venue.objects.select_related('project').all()
    serializer_class = VenueSerializer


class DepartmentViewSet(viewsets.ModelViewSet):
    """CRUD standard sur les départements."""

    queryset = Department.objects.all()
    serializer_class = DepartmentSerializer


class MaterialViewSet(ProjectFilteredMixin, viewsets.ModelViewSet):
    """CRUD standard sur l'inventaire de matériel, filtrable par projet (`?project=<id>`).

    Le matériel désactivé (`is_active=False`, ex. un vieux rideau qu'on
    n'utilise plus) est masqué de la liste par défaut (`GET /api/materials/`)
    pour ne pas encombrer l'inventaire courant, sans jamais être supprimé —
    ajouter `?include_inactive=true` à la requête pour tout revoir (utile
    pour réactiver un item). La consultation par id (`GET /api/materials/{id}/`)
    reste toujours accessible peu importe le statut, pour ne pas casser
    l'affichage des assignations existantes (`show_materials`) qui
    référencent un matériel entretemps désactivé. Décision du 2026-07-19.
    """

    queryset = Material.objects.select_related('project', 'parent_material', 'venue', 'department').all()
    serializer_class = MaterialSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.action == 'list':
            include_inactive = self.request.query_params.get('include_inactive', '').lower() in (
                '1', 'true', 'yes',
            )
            if not include_inactive:
                queryset = queryset.filter(is_active=True)
        return queryset


class ShowViewSet(ProjectFilteredMixin, viewsets.ModelViewSet):
    """CRUD standard sur les fiches spectacles, filtrable par projet (`?project=<id>`),
    plus l'action `conflicts` en lecture seule."""

    queryset = Show.objects.select_related('project', 'venue').all()
    serializer_class = ShowSerializer

    @action(detail=True, methods=['get'])
    def conflicts(self, request, pk=None):
        """Liste les chevauchements actuellement en place pour ce spectacle
        (matériel, techniciens et déplacements), y compris les assignations
        créées avec `force: true` malgré un conflit signalé au moment de la
        création."""
        show = self.get_object()

        material_conflicts = []
        for sm in show.show_materials.select_related('material').all():
            for conflict in get_material_conflicts(show, sm.material, exclude_id=sm.id, quantity=sm.quantity):
                material_conflicts.append(serialize_material_conflict(conflict))

        technician_conflicts = []
        for st in show.show_technicians.select_related('technician').all():
            for conflict in get_technician_conflicts(show, st.technician, exclude_id=st.id):
                technician_conflicts.append(serialize_technician_conflict(conflict))

        for transport in show.transports.select_related('technician').all():
            if transport.technician_id is None:
                continue
            for conflict in get_transport_conflicts(
                transport.scheduled_datetime,
                transport.estimated_duration_minutes,
                transport.technician,
                exclude_id=transport.id,
            ):
                technician_conflicts.append(serialize_technician_conflict(conflict))

        return Response({
            'material_conflicts': material_conflicts,
            'technician_conflicts': technician_conflicts,
        })

    @action(detail=True, methods=['get'], url_path='transport-coherence')
    def transport_coherence(self, request, pk=None):
        """Rapport de cohérence des emplacements de matériel centré sur ce
        spectacle (non bloquant — voir `transport_coherence.py`) : matériel
        requis par ce spectacle mais non livré, transports de ce spectacle dont
        l'origine est incohérente, et matériel de ce spectacle sans lieu
        d'entreposage."""
        show = self.get_object()
        issues = get_show_coherence_report(show)
        return Response({'issues': issues, 'issue_count': len(issues)})


class ShowMaterialViewSet(viewsets.ModelViewSet):
    """CRUD standard sur les assignations de matériel (validation de conflit dans le serializer)."""

    queryset = ShowMaterial.objects.select_related('show', 'material').all()
    serializer_class = ShowMaterialSerializer


class TechnicianViewSet(ProjectFilteredMixin, viewsets.ModelViewSet):
    """CRUD standard sur les techniciens, filtrable par projet (`?project=<id>`)."""

    queryset = Technician.objects.select_related('project').all()
    serializer_class = TechnicianSerializer


class ShowTechnicianViewSet(viewsets.ModelViewSet):
    """CRUD standard sur les assignations de techniciens (validation de conflit dans le serializer)."""

    queryset = ShowTechnician.objects.select_related('show', 'technician').all()
    serializer_class = ShowTechnicianSerializer


class TransportViewSet(viewsets.ModelViewSet):
    """CRUD standard sur les déplacements (livraison/ramassage), validation de conflit dans le serializer.

    Filtres optionnels : `?status=to_approve` (ne renvoyer que les propositions
    auto à approuver — voir `transport_autogen.py`) ou `?status=confirmed` ;
    `?show=<id>` pour les déplacements d'un spectacle.
    """

    queryset = (
        Transport.objects
        .select_related('show', 'origin_venue', 'destination_venue', 'technician')
        .prefetch_related('transport_materials__material')
        .all()
    )
    serializer_class = TransportSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        status_param = self.request.query_params.get('status')
        if status_param:
            queryset = queryset.filter(status=status_param)
        show_id = self.request.query_params.get('show')
        if show_id:
            queryset = queryset.filter(show_id=show_id)
        return queryset


class SettingsView(generics.RetrieveUpdateAPIView):
    """Vue singleton pour les réglages globaux (`GET`/`PUT`/`PATCH` sur `/api/settings/`).

    Pas de liste ni de création : il n'existe toujours qu'une seule ligne de
    réglages, chargée (et créée si absente) via `Settings.load()`.
    """

    serializer_class = SettingsSerializer

    def get_object(self):
        return Settings.load()
