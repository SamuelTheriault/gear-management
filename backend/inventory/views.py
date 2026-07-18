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
page de réglages du frontend.
"""

from rest_framework import generics, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .conflicts import (
    get_material_conflicts,
    get_technician_conflicts,
    get_transport_conflicts,
    serialize_material_conflict,
    serialize_technician_conflict,
)
from .models import (
    Department,
    Material,
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
    SettingsSerializer,
    ShowMaterialSerializer,
    ShowSerializer,
    ShowTechnicianSerializer,
    TechnicianSerializer,
    TransportSerializer,
    UserSerializer,
    VenueSerializer,
)


class UserViewSet(viewsets.ModelViewSet):
    """CRUD standard sur les comptes applicatifs."""

    queryset = User.objects.all()
    serializer_class = UserSerializer


class VenueViewSet(viewsets.ModelViewSet):
    """CRUD standard sur les lieux."""

    queryset = Venue.objects.all()
    serializer_class = VenueSerializer


class DepartmentViewSet(viewsets.ModelViewSet):
    """CRUD standard sur les départements."""

    queryset = Department.objects.all()
    serializer_class = DepartmentSerializer


class MaterialViewSet(viewsets.ModelViewSet):
    """CRUD standard sur l'inventaire de matériel."""

    queryset = Material.objects.select_related('parent_material', 'venue', 'department').all()
    serializer_class = MaterialSerializer


class ShowViewSet(viewsets.ModelViewSet):
    """CRUD standard sur les fiches spectacles, plus l'action `conflicts` en lecture seule."""

    queryset = Show.objects.select_related('venue').all()
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
            for conflict in get_material_conflicts(show, sm.material, exclude_id=sm.id):
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


class ShowMaterialViewSet(viewsets.ModelViewSet):
    """CRUD standard sur les assignations de matériel (validation de conflit dans le serializer)."""

    queryset = ShowMaterial.objects.select_related('show', 'material').all()
    serializer_class = ShowMaterialSerializer


class TechnicianViewSet(viewsets.ModelViewSet):
    """CRUD standard sur les techniciens."""

    queryset = Technician.objects.all()
    serializer_class = TechnicianSerializer


class ShowTechnicianViewSet(viewsets.ModelViewSet):
    """CRUD standard sur les assignations de techniciens (validation de conflit dans le serializer)."""

    queryset = ShowTechnician.objects.select_related('show', 'technician').all()
    serializer_class = ShowTechnicianSerializer


class TransportViewSet(viewsets.ModelViewSet):
    """CRUD standard sur les déplacements (livraison/ramassage), validation de conflit dans le serializer."""

    queryset = Transport.objects.select_related('show', 'origin_venue', 'destination_venue', 'technician').all()
    serializer_class = TransportSerializer


class SettingsView(generics.RetrieveUpdateAPIView):
    """Vue singleton pour les réglages globaux (`GET`/`PUT`/`PATCH` sur `/api/settings/`).

    Pas de liste ni de création : il n'existe toujours qu'une seule ligne de
    réglages, chargée (et créée si absente) via `Settings.load()`.
    """

    serializer_class = SettingsSerializer

    def get_object(self):
        return Settings.load()
